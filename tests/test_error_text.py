import sqlite3

import httpx
import pytest

from seeker.error_text import DETAILS_HINT, describe_error
from seeker.soulseek.download_service import NoDestinationConfiguredError

SLSKD_URL = "http://127.0.0.1:5030/api/v0/searches"


def _request(url: str) -> httpx.Request:
    return httpx.Request("GET", url)


def _status_error(url: str, status: int) -> httpx.HTTPStatusError:
    request = _request(url)
    return httpx.HTTPStatusError(
        f"Server error '{status}' for url '{url}'",
        request=request,
        response=httpx.Response(status, request=request),
    )


def test_seekers_own_error_keeps_its_message():
    error = NoDestinationConfiguredError("Choose a destination first.")

    assert describe_error(error) == "Choose a destination first."


def test_a_domain_message_on_a_builtin_error_is_kept():
    assert describe_error(ValueError("Pick a playlist.")) == "Pick a playlist."


def test_connect_error_to_slskd_names_it_and_asks_about_docker():
    error = httpx.ConnectError(
        "[Errno 61] Connection refused", request=_request(SLSKD_URL),
    )

    text = describe_error(error)

    assert "slskd" in text
    assert "127.0.0.1:5030" in text
    assert "Docker" in text
    assert "Errno" not in text


@pytest.mark.parametrize(
    "url",
    [
        "https://api.spotify.com/v1/me/playlists",
        "https://accounts.spotify.com/api/token",
        "https://i.scdn.co/image/abc",
    ],
)
def test_connect_error_to_spotify_says_check_your_connection(url):
    error = httpx.ConnectError("nodename nor servname", request=_request(url))

    text = describe_error(error)

    assert "Spotify" in text
    assert "connection" in text


def test_connect_error_to_github_says_try_later():
    error = httpx.ConnectError(
        "boom",
        request=_request("https://api.github.com/repos/x/y/releases/latest"),
    )

    text = describe_error(error)

    assert "GitHub" in text
    assert "later" in text


def test_timeout_says_the_service_did_not_respond():
    error = httpx.ReadTimeout("timed out", request=_request(SLSKD_URL))

    text = describe_error(error)

    assert "slskd" in text
    assert "respond" in text


def test_transport_error_without_a_request_is_still_readable():
    text = describe_error(httpx.ConnectError("[Errno 61] Connection refused"))

    assert "Errno" not in text
    assert "connect" in text.lower()


def test_server_error_names_the_service_and_status():
    text = describe_error(_status_error(SLSKD_URL, 503))

    assert "slskd" in text
    assert "503" in text
    assert "server error" in text


def test_client_error_names_the_service_and_status():
    text = describe_error(
        _status_error("https://api.spotify.com/v1/playlists/x", 404),
    )

    assert "Spotify" in text
    assert "404" in text
    assert "developer.mozilla.org" not in text


def test_locked_database_asks_to_try_again():
    text = describe_error(sqlite3.OperationalError("database is locked"))

    assert "busy" in text
    assert "try again" in text.lower()


def test_other_database_errors_point_at_the_log():
    text = describe_error(
        sqlite3.IntegrityError("FOREIGN KEY constraint failed"),
    )

    assert "FOREIGN KEY" not in text
    assert "database" in text
    assert text.endswith(DETAILS_HINT)


def test_bare_assertion_error_names_its_class_and_the_log():
    text = describe_error(AssertionError())

    assert "AssertionError" in text
    assert text.endswith(DETAILS_HINT)


def test_empty_message_falls_back_to_class_name_and_the_log():
    text = describe_error(RuntimeError("   "))

    assert "RuntimeError" in text
    assert text.endswith(DETAILS_HINT)


def test_programming_error_hides_its_raw_message():
    text = describe_error(KeyError("track_id"))

    assert "KeyError" in text
    assert "track_id" not in text
    assert text.endswith(DETAILS_HINT)


def test_os_error_reads_as_reason_and_path():
    error = FileNotFoundError(2, "No such file or directory", "/music/a.mp3")

    assert describe_error(error) == (
        "No such file or directory: /music/a.mp3"
    )


def test_os_error_without_a_path_reads_as_its_reason():
    assert describe_error(PermissionError(13, "Permission denied")) == (
        "Permission denied"
    )


def test_details_hint_can_be_replaced_for_the_cli():
    text = describe_error(AssertionError(), details_hint="")

    assert "Open log folder" not in text
    assert "AssertionError" in text
