import threading
import time
from http.server import HTTPServer
from queue import Queue

import httpx
import pytest

from seeker.spotify.callback_server import (
    AuthorizationCancelledError,
    create_callback_server,
    serve_until_callback,
)


def _serve_in_background(
        server: HTTPServer, result_queue: Queue, timeout_seconds: float = 5.0,
) -> None:
    result_queue.put(serve_until_callback(server, timeout_seconds))


def test_serve_until_callback_parses_code_and_state_from_real_request():
    # Round 9 §1.2: the server is created (bound + listening) on this
    # thread, so it is provably ready before any client connects —
    # only serve_until_callback() itself runs in the background. Port 0
    # picks a real ephemeral port, read back from server_address.
    server = create_callback_server(port=0)
    port = server.server_address[1]
    result_queue: Queue = Queue()
    thread = threading.Thread(
        target=_serve_in_background, args=(server, result_queue)
    )
    thread.start()

    response = httpx.get(
        f"http://127.0.0.1:{port}/callback",
        params={"code": "auth-code-1", "state": "state-1"},
        timeout=5.0,
    )
    thread.join(timeout=5.0)

    assert response.status_code == 200
    assert b"authorization complete" in response.content

    code, state, error, timed_out = result_queue.get(timeout=1.0)
    assert code == "auth-code-1"
    assert state == "state-1"
    assert error is None
    assert timed_out is False


def test_serve_until_callback_captures_error_param():
    server = create_callback_server(port=0)
    port = server.server_address[1]
    result_queue: Queue = Queue()
    thread = threading.Thread(
        target=_serve_in_background, args=(server, result_queue)
    )
    thread.start()

    httpx.get(
        f"http://127.0.0.1:{port}/callback",
        params={"error": "access_denied", "state": "state-1"},
        timeout=5.0,
    )
    thread.join(timeout=5.0)

    code, _state, error, timed_out = result_queue.get(timeout=1.0)
    assert code is None
    assert error == "access_denied"
    assert timed_out is False


def test_callback_handler_returns_404_but_keeps_waiting_for_the_real_callback():
    # Round 8 §6.3.3: a stray non-/callback request (a browser's own
    # /favicon.ico fetch is the real-world case) must get its own 404
    # WITHOUT consuming serve_until_callback()'s one chance to see the real
    # authorization — the old behavior treated any request as "the"
    # request and returned empty-handed from here on.
    server = create_callback_server(port=0)
    port = server.server_address[1]
    result_queue: Queue = Queue()
    thread = threading.Thread(
        target=_serve_in_background, args=(server, result_queue)
    )
    thread.start()

    stray_response = httpx.get(
        f"http://127.0.0.1:{port}/not-callback", timeout=5.0
    )
    assert stray_response.status_code == 404
    assert result_queue.empty(), (
        "a stray non-callback request must not make serve_until_callback "
        "return early"
    )

    real_response = httpx.get(
        f"http://127.0.0.1:{port}/callback",
        params={"code": "auth-code-2", "state": "state-2"},
        timeout=5.0,
    )
    thread.join(timeout=5.0)

    assert real_response.status_code == 200
    code, state, error, timed_out = result_queue.get(timeout=1.0)
    assert code == "auth-code-2"
    assert state == "state-2"
    assert error is None
    assert timed_out is False


def test_serve_until_callback_times_out_when_nothing_ever_arrives():
    # Round 8 §6.3.1: the old code called handle_request() with no
    # timeout at all and blocked forever on an abandoned/closed
    # authorization tab. A real (short, test-scoped) timeout must
    # return a distinct outcome rather than hang.
    code, state, error, timed_out = serve_until_callback(
        create_callback_server(port=0), timeout_seconds=0.2,
    )

    assert code is None
    assert state is None
    assert error is None
    assert timed_out is True


def test_two_consecutive_runs_do_not_leak_state_between_them():
    # Round 8 §6.3.2: the old SpotifyCallbackHandler stored
    # authorization_code/returned_state/error on the CLASS, so a failed
    # attempt's stale `error` was still visible to the very next
    # attempt in the same process. Each create_callback_server() call
    # must get genuinely fresh state — two separate ephemeral-port
    # servers stand in for two separate real authorize attempts.
    first_server = create_callback_server(port=0)
    first_port = first_server.server_address[1]
    result_queue: Queue = Queue()
    thread = threading.Thread(
        target=_serve_in_background, args=(first_server, result_queue)
    )
    thread.start()
    httpx.get(
        f"http://127.0.0.1:{first_port}/callback",
        params={"error": "access_denied"},
        timeout=5.0,
    )
    thread.join(timeout=5.0)
    first_error = result_queue.get(timeout=1.0)[2]
    assert first_error == "access_denied"

    second_server = create_callback_server(port=0)
    second_port = second_server.server_address[1]
    result_queue = Queue()
    thread = threading.Thread(
        target=_serve_in_background, args=(second_server, result_queue)
    )
    thread.start()
    httpx.get(
        f"http://127.0.0.1:{second_port}/callback",
        params={"code": "auth-code-3", "state": "state-3"},
        timeout=5.0,
    )
    thread.join(timeout=5.0)
    second_code, second_state, second_error, _timed_out = result_queue.get(
        timeout=1.0
    )

    assert second_code == "auth-code-3"
    assert second_state == "state-3"
    assert second_error is None, (
        "the first run's stale error must not leak into the second run"
    )


def _get_in_background(server: HTTPServer, **params: str) -> httpx.Response:
    port = server.server_address[1]
    result_queue: Queue = Queue()
    thread = threading.Thread(
        target=_serve_in_background, args=(server, result_queue)
    )
    thread.start()
    response = httpx.get(
        f"http://127.0.0.1:{port}/callback", params=params, timeout=5.0,
    )
    thread.join(timeout=5.0)
    return response


def test_error_callback_page_says_authorization_was_cancelled():
    # Spotify redirects with error=access_denied when the user clicks
    # Cancel on its consent screen; the page must not claim success.
    response = _get_in_background(
        create_callback_server(port=0),
        error="access_denied", state="state-1",
    )

    assert response.status_code == 200
    assert b"authorization complete" not in response.content
    assert b"Authorization was cancelled" in response.content
    assert b"Return to Seeker to try again" in response.content


def test_callback_responses_are_not_cached_framed_or_referred():
    response = _get_in_background(
        create_callback_server(port=0), code="auth-code", state="state-1",
    )

    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Security-Policy"] == "default-src 'none'"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_stray_request_404_carries_the_same_security_headers():
    server = create_callback_server(port=0)
    port = server.server_address[1]
    result_queue: Queue = Queue()
    thread = threading.Thread(
        target=_serve_in_background, args=(server, result_queue, 0.5)
    )
    thread.start()

    response = httpx.get(f"http://127.0.0.1:{port}/favicon.ico", timeout=5.0)
    thread.join(timeout=5.0)

    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Security-Policy"] == "default-src 'none'"


def test_cancel_returns_promptly_and_frees_the_port():
    # A mistyped Client ID leaves Spotify on its own INVALID_CLIENT
    # page, which never redirects: without a cancel the wait holds the
    # port for the full CALLBACK_TIMEOUT_SECONDS.
    server = create_callback_server(port=0)
    port = server.server_address[1]
    cancel = threading.Event()
    raised: Queue = Queue()

    def serve() -> None:
        try:
            serve_until_callback(server, timeout_seconds=60.0, cancel=cancel)
        except AuthorizationCancelledError as error:
            raised.put(error)

    thread = threading.Thread(target=serve)
    thread.start()

    started = time.monotonic()
    cancel.set()
    thread.join(timeout=5.0)

    assert not thread.is_alive()
    assert time.monotonic() - started < 2.0
    assert isinstance(raised.get(timeout=1.0), AuthorizationCancelledError)

    # A second attempt after the cancel binds the same port.
    second = create_callback_server(port=port)
    second.server_close()


def test_already_cancelled_wait_serves_nothing_and_closes_the_socket():
    server = create_callback_server(port=0)
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(AuthorizationCancelledError):
        serve_until_callback(server, timeout_seconds=60.0, cancel=cancel)

    assert server.socket.fileno() == -1
