import socketserver
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from seeker.errors import SeekerError

# Single source of truth for the local callback port — the onboarding
# wizard displays DEFAULT_REDIRECT_URI (built from this) as the fixed,
# copy-pasteable value the user registers on Spotify's dashboard, so it
# must never drift from what create_callback_server() listens on.
CALLBACK_PORT = 8888
DEFAULT_REDIRECT_URI = f"http://127.0.0.1:{CALLBACK_PORT}/callback"

# Untuned — long enough for a human to read the real Spotify consent
# screen and click Allow, short enough that an abandoned/closed-tab
# authorization doesn't block a worker thread forever.
CALLBACK_TIMEOUT_SECONDS = 300.0


def _page(heading: str, body: str) -> bytes:
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        "<title>Seeker</title></head><body>"
        f"<h1>{heading}</h1><p>{body}</p></body></html>"
    ).encode()


# How often a wait re-checks its cancel event: the longest a Cancel
# click can take to free the port.
_CANCEL_POLL_SECONDS = 0.2

# Every response, the 404 included: the success page follows a URL
# that carried the one-time code, so nothing may cache it, embed it,
# run anything in it or leak it onward in a Referer.
_SECURITY_HEADERS = (
    ("Cache-Control", "no-store"),
    ("Content-Security-Policy", "default-src 'none'"),
    ("Referrer-Policy", "no-referrer"),
)

_SUCCESS_PAGE = _page(
    "Spotify authorization complete.",
    "You can close this window and return to Seeker.",
)
_CANCELLED_PAGE = _page(
    "Authorization was cancelled.",
    "Return to Seeker to try again.",
)
_FAILED_PAGE = _page(
    "Spotify authorization failed.",
    "Return to Seeker to see what went wrong and try again.",
)


class AuthorizationCancelledError(SeekerError):
    """The user cancelled a wait for the Spotify callback in Seeker."""

    def __init__(self) -> None:
        super().__init__("Authorization cancelled.")


@dataclass
class _CallbackResult:
    """Per-run state for one callback server — never a class
    attribute: state stored on a handler CLASS outlives its attempt, so
    a failed attempt's stale `error` would still be there for the next
    attempt in the same process to read first, raising "Spotify
    authorization failed" even after a real, successful second try.
    """
    authorization_code: str | None = None
    returned_state: str | None = None
    error: str | None = None
    received: bool = False


def _build_handler_class(
        result: _CallbackResult,
) -> type[BaseHTTPRequestHandler]:
    # A fresh handler class per call, closing over this call's own
    # _CallbackResult — so there is no class-level state: no shared
    # class left to leak between authorization attempts.
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed_url = urlparse(self.path)

            if parsed_url.path != "/callback":
                # A stray request (a browser's own /favicon.ico
                # fetch is the common real case) gets a 404 but does
                # NOT set `received`, so the caller's wait loop below
                # keeps waiting for the real callback instead of
                # returning empty-handed.
                self.send_error(404)
                return

            query = parse_qs(parsed_url.query)
            result.authorization_code = query.get("code", [None])[0]
            result.returned_state = query.get("state", [None])[0]
            result.error = query.get("error", [None])[0]
            result.received = True

            # access_denied is the user's own Cancel on Spotify's
            # consent screen; any other error is Spotify refusing.
            if result.error == "access_denied":
                page = _CANCELLED_PAGE
            elif result.error:
                page = _FAILED_PAGE
            else:
                page = _SUCCESS_PAGE

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def end_headers(self) -> None:
            for name, value in _SECURITY_HEADERS:
                self.send_header(name, value)
            super().end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            # Suppress BaseHTTPRequestHandler's default per-request
            # stderr logging — this is a short-lived local callback
            # server, not something that needs request logging.
            # `format` shadows the builtin only because this overrides
            # the stdlib base class's own parameter name exactly.
            return

    return _Handler


class _LoopbackHTTPServer(HTTPServer):
    """HTTPServer that skips the reverse-DNS lookup its own server_bind()
    would otherwise do. See HISTORY §136.

    Stdlib `http.server.HTTPServer.server_bind()` calls
    `socket.getfqdn(host)` to populate `server_name`, and
    `socketserver.TCPServer.__init__` runs that *before*
    `server_activate()` calls `listen()` — so on a machine with slow or
    absent reverse DNS, the socket sits bound-but-not-listening for the
    whole lookup. That widens the real race in `auth_manager._authorize()`
    (the browser can already be redirecting back before the callback
    server is accepting connections) from microseconds to potentially
    seconds. Skipping it is safe: nothing here ever reads `server_name`
    — the redirect URI's host is the literal `127.0.0.1` baked into
    `DEFAULT_REDIRECT_URI`, never anything `server_bind()` would derive.
    """

    def __init__(
            self,
            server_address: tuple[str, int],
            handler_class: type[BaseHTTPRequestHandler],
            callback_result: _CallbackResult,
    ) -> None:
        self.callback_result = callback_result
        super().__init__(server_address, handler_class)

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        # server_address[0] is typed str | bytes | bytearray upstream
        # (AF_UNIX sockets use bytes); this class only ever binds
        # "127.0.0.1", always a str.
        self.server_name = str(self.server_address[0])
        self.server_port = self.server_address[1]


def create_callback_server(port: int = CALLBACK_PORT) -> HTTPServer:
    """Binds (and starts listening on) the local callback socket and
    returns it, without serving any request yet — the caller decides
    when to start serving via `serve_until_callback()`. The split is
    what lets `auth_manager._authorize()` bind the socket *before*
    opening the browser, instead of after.
    """
    result = _CallbackResult()
    handler_class = _build_handler_class(result)
    return _LoopbackHTTPServer(("127.0.0.1", port), handler_class, result)


def serve_until_callback(
        server: HTTPServer,
        timeout_seconds: float = CALLBACK_TIMEOUT_SECONDS,
        cancel: threading.Event | None = None,
) -> tuple[str | None, str | None, str | None, bool]:
    """Blocks until the real /callback request lands on `server` or
    `timeout_seconds` elapses. Returns (code, state, error, timed_out) —
    `timed_out` is its own outcome, so a caller can tell "the user
    abandoned the consent screen" apart from every other failure shape
    and show something actionable instead of hanging forever.

    Setting `cancel` ends the wait within `_CANCEL_POLL_SECONDS` by
    raising AuthorizationCancelledError; either way `server` is closed
    before this returns, so the port is free for the next attempt.
    """
    assert isinstance(server, _LoopbackHTTPServer), (
        "serve_until_callback() only accepts a server built by "
        "create_callback_server()"
    )
    result = server.callback_result

    deadline = time.monotonic() + timeout_seconds
    try:
        while not result.received:
            if cancel is not None and cancel.is_set():
                raise AuthorizationCancelledError

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            # HTTPServer.timeout (via socketserver.BaseServer) bounds a
            # SINGLE handle_request() call, not the whole wait — reset
            # it each iteration from the real remaining budget, so a
            # stray non-callback request can't silently reset
            # the clock to a fresh full timeout_seconds.
            server.timeout = (
                remaining if cancel is None
                else min(remaining, _CANCEL_POLL_SECONDS)
            )
            server.handle_request()
    finally:
        server.server_close()

    if not result.received:
        return (None, None, None, True)

    return (
        result.authorization_code,
        result.returned_state,
        result.error,
        False,
    )
