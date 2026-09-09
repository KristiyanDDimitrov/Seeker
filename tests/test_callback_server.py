import threading
from http.server import HTTPServer
from queue import Queue

import httpx

from seeker.spotify.callback_server import (
    create_callback_server,
    serve_until_callback,
    wait_for_callback,
)


def _serve_in_background(
        server: HTTPServer, result_queue: Queue, timeout_seconds: float = 5.0,
) -> None:
    result_queue.put(serve_until_callback(server, timeout_seconds))


def test_wait_for_callback_parses_code_and_state_from_real_request():
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


def test_wait_for_callback_captures_error_param():
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
    # WITHOUT consuming wait_for_callback()'s one chance to see the real
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
        "a stray non-callback request must not make wait_for_callback "
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


def test_wait_for_callback_times_out_when_nothing_ever_arrives():
    # Round 8 §6.3.1: the old code called handle_request() with no
    # timeout at all and blocked forever on an abandoned/closed
    # authorization tab. A real (short, test-scoped) timeout must
    # return a distinct outcome rather than hang. No client ever
    # connects, so the thin wait_for_callback() wrapper is fine here.
    code, state, error, timed_out = wait_for_callback(
        port=0, timeout_seconds=0.2,
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
