import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

# Single source of truth for the local callback port — the onboarding
# wizard displays DEFAULT_REDIRECT_URI (built from this) as the fixed,
# copy-pasteable value the user registers on Spotify's dashboard, so it
# must never drift from what wait_for_callback() actually listens on.
CALLBACK_PORT = 8888
DEFAULT_REDIRECT_URI = f"http://127.0.0.1:{CALLBACK_PORT}/callback"

# Untuned (round 8 §6.3.1) — long enough for a human to read the real
# Spotify consent screen and click Allow, short enough that an
# abandoned/closed-tab authorization doesn't block a worker thread
# forever.
CALLBACK_TIMEOUT_SECONDS = 300.0


@dataclass
class _CallbackResult:
    """Per-run state for one wait_for_callback() call — never a class
    attribute (round 8 §6.3.2): the old SpotifyCallbackHandler stored
    authorization_code/returned_state/error on the CLASS, so a failed
    attempt's stale `error` was still there for the next attempt in the
    same process to read first, raising "Spotify authorization failed"
    even after a real, successful second try.
    """
    authorization_code: str | None = None
    returned_state: str | None = None
    error: str | None = None
    received: bool = False


def _build_handler_class(
        result: _CallbackResult,
) -> type[BaseHTTPRequestHandler]:
    # A fresh handler class per call, closing over this call's own
    # _CallbackResult — this is what actually kills the class-level
    # state (§6.3.2): there is no shared class left to leak between
    # authorization attempts.
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed_url = urlparse(self.path)

            if parsed_url.path != "/callback":
                # §6.3.3 — a stray request (a browser's own /favicon.ico
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

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()

            self.wfile.write(
                b"""
                <html>
                    <body>
                        <h1>Spotify authorization complete.</h1>
                        <p>You can close this window and return to Seeker.</p>
                    </body>
                </html>
                """
            )

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            # Suppress BaseHTTPRequestHandler's default per-request
            # stderr logging — this is a short-lived local callback
            # server, not something that needs request logging.
            # `format` shadows the builtin only because this overrides
            # the stdlib base class's own parameter name exactly.
            return

    return _Handler


def wait_for_callback(
        port: int = CALLBACK_PORT,
        timeout_seconds: float = CALLBACK_TIMEOUT_SECONDS,
) -> tuple[str | None, str | None, str | None, bool]:
    """Blocks until the real /callback request lands or `timeout_seconds`
    elapses. Returns (code, state, error, timed_out) — `timed_out` is
    the "distinct outcome" §6.3.1 asks for, so a caller can tell "the
    user abandoned the consent screen" apart from every other failure
    shape and show something actionable instead of hanging forever.
    """
    result = _CallbackResult()
    handler_class = _build_handler_class(result)
    server = HTTPServer(("127.0.0.1", port), handler_class)

    deadline = time.monotonic() + timeout_seconds
    try:
        while not result.received:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            # HTTPServer.timeout (via socketserver.BaseServer) bounds a
            # SINGLE handle_request() call, not the whole wait — reset
            # it to the real remaining budget each iteration so a
            # stray non-callback request (§6.3.3) can't silently reset
            # the clock to a fresh full timeout_seconds.
            server.timeout = remaining
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
