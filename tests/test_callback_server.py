import threading
from queue import Queue

import httpx

from seeker.spotify.callback_server import (
    SpotifyCallbackHandler,
    wait_for_callback,
)


def _run_server_in_background(port: int, result_queue: Queue) -> None:
    result_queue.put(wait_for_callback(port=port))


def _reset_handler_state() -> None:
    # Class-level attributes shared across requests/instances — reset
    # between tests so one test's captured code/state/error can't leak
    # into the next.
    SpotifyCallbackHandler.authorization_code = None
    SpotifyCallbackHandler.returned_state = None
    SpotifyCallbackHandler.error = None


def test_wait_for_callback_parses_code_and_state_from_real_request():
    _reset_handler_state()
    port = 18881
    result_queue: Queue = Queue()
    thread = threading.Thread(
        target=_run_server_in_background, args=(port, result_queue)
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

    code, state, error = result_queue.get(timeout=1.0)
    assert code == "auth-code-1"
    assert state == "state-1"
    assert error is None


def test_wait_for_callback_captures_error_param():
    _reset_handler_state()
    port = 18882
    result_queue: Queue = Queue()
    thread = threading.Thread(
        target=_run_server_in_background, args=(port, result_queue)
    )
    thread.start()

    httpx.get(
        f"http://127.0.0.1:{port}/callback",
        params={"error": "access_denied", "state": "state-1"},
        timeout=5.0,
    )
    thread.join(timeout=5.0)

    code, state, error = result_queue.get(timeout=1.0)
    assert code is None
    assert error == "access_denied"


def test_callback_handler_returns_404_for_unrecognized_path():
    _reset_handler_state()
    port = 18883
    result_queue: Queue = Queue()
    thread = threading.Thread(
        target=_run_server_in_background, args=(port, result_queue)
    )
    thread.start()

    response = httpx.get(
        f"http://127.0.0.1:{port}/not-callback", timeout=5.0
    )
    thread.join(timeout=5.0)

    assert response.status_code == 404

    code, state, error = result_queue.get(timeout=1.0)
    assert code is None
    assert state is None
    assert error is None
