from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse


# Single source of truth for the local callback port — the onboarding
# wizard displays DEFAULT_REDIRECT_URI (built from this) as the fixed,
# copy-pasteable value the user registers on Spotify's dashboard, so it
# must never drift from what wait_for_callback() actually listens on.
CALLBACK_PORT = 8888
DEFAULT_REDIRECT_URI = f"http://127.0.0.1:{CALLBACK_PORT}/callback"


class SpotifyCallbackHandler(BaseHTTPRequestHandler):
    authorization_code = None
    returned_state = None
    error = None

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)

        if parsed_url.path != "/callback":
            self.send_error(404)
            return

        query = parse_qs(parsed_url.query)

        SpotifyCallbackHandler.authorization_code = query.get(
            "code", [None]
        )[0]

        SpotifyCallbackHandler.returned_state = query.get(
            "state", [None]
        )[0]

        SpotifyCallbackHandler.error = query.get(
            "error", [None]
        )[0]

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

    def log_message(self, format: str, *args: object) -> None:
        # Suppress BaseHTTPRequestHandler's default per-request stderr
        # logging — this is a short-lived local callback server, not
        # something that needs request logging.
        return


def wait_for_callback(
        port: int = CALLBACK_PORT,
) -> tuple[str | None, str | None, str | None]:
    server = HTTPServer(("127.0.0.1", port), SpotifyCallbackHandler)

    server.handle_request()
    server.server_close()

    return (
        SpotifyCallbackHandler.authorization_code,
        SpotifyCallbackHandler.returned_state,
        SpotifyCallbackHandler.error,
    )