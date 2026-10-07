"""One sentence a person can act on, for any exception a task raised.

Shared by the UI's worker error path and the CLI, so it imports no Qt.
Seeker's own errors, and builtin errors Seeker raises with a message
(`ValueError("Pick a playlist.")`), already read as sentences and keep
their text. What gets translated is the text nobody wrote for a person:
`[Errno 61] Connection refused`, `FOREIGN KEY constraint failed`, a
bare `AssertionError()` that stringifies to nothing.
"""

import sqlite3
from dataclasses import dataclass

import httpx

DETAILS_HINT = "Details are in the log (Help → Open log folder)."

# Builtin exception types Seeker never raises on purpose — none appears
# in a `raise` anywhere under src/. Reaching the user, one is always a
# bug, and its own text (`'track_id'`, `'NoneType' object has no
# attribute …`) means nothing to them.
_PROGRAMMING_ERRORS: tuple[type[BaseException], ...] = (
    ArithmeticError,
    AssertionError,
    AttributeError,
    LookupError,
    NameError,
    TypeError,
)


@dataclass(frozen=True)
class _Service:
    name: str
    next_step: str


_SPOTIFY = _Service("Spotify", "Check your internet connection and try again.")
_GITHUB = _Service("GitHub", "Try again later.")
# slskd is the only HTTP peer that is neither Spotify nor GitHub, and
# the one whose base URL the user configures, so it is the default.
_SLSKD = _Service("slskd", "Is Docker running? slskd runs inside it.")

_SPOTIFY_DOMAINS = ("spotify.com", "scdn.co", "spotifycdn.com")
_GITHUB_DOMAINS = ("github.com", "githubusercontent.com")


def describe_error(
        error: BaseException,
        *,
        details_hint: str = DETAILS_HINT,
) -> str:
    """Returns readable text for `error`. `details_hint` ends the text
    wherever the specifics were left in the log; the CLI, which has no
    log folder, passes its own or `""`."""
    if isinstance(error, httpx.TransportError):
        return _describe_transport_error(error, details_hint)

    if isinstance(error, httpx.HTTPStatusError):
        return _describe_status_error(error, details_hint)

    if isinstance(error, sqlite3.Error):
        return _describe_database_error(error, details_hint)

    if isinstance(error, OSError) and error.strerror:
        if error.filename:
            return f"{error.strerror}: {error.filename}"

        return error.strerror

    message = str(error).strip()

    if message and not isinstance(error, _PROGRAMMING_ERRORS):
        return message

    return _join(
        f"Something went wrong inside Seeker ({type(error).__name__}).",
        details_hint,
    )


def _describe_transport_error(
        error: httpx.TransportError,
        details_hint: str,
) -> str:
    url = _request_url(error)

    if url is None:
        return _join("Couldn't connect to the network.", details_hint)

    service = _service_for(url.host)
    where = f"{service.name} ({_address(url)})"

    if isinstance(error, httpx.TimeoutException):
        return _join(f"{where} didn't respond in time.", service.next_step)

    return _join(f"Couldn't reach {where}.", service.next_step)


def _describe_status_error(
        error: httpx.HTTPStatusError,
        details_hint: str,
) -> str:
    service = _service_for(error.request.url.host)
    status = error.response.status_code

    if status >= 500:
        return _join(
            f"{service.name} returned a server error (HTTP {status}).",
            "Try again in a moment.",
            details_hint,
        )

    return _join(
        f"{service.name} rejected the request (HTTP {status}).",
        details_hint,
    )


def _describe_database_error(error: sqlite3.Error, details_hint: str) -> str:
    if "database is locked" in str(error):
        return (
            "Seeker's database is busy with another task. "
            "Try again in a moment."
        )

    return _join("Seeker's database reported an error.", details_hint)


def _request_url(error: httpx.TransportError) -> httpx.URL | None:
    # `.request` is a property that raises RuntimeError when the error
    # was built without one (httpx's own contract, not an edge case of
    # ours).
    try:
        return error.request.url
    except RuntimeError:
        return None


def _service_for(host: str) -> _Service:
    if _in_domains(host, _SPOTIFY_DOMAINS):
        return _SPOTIFY

    if _in_domains(host, _GITHUB_DOMAINS):
        return _GITHUB

    return _SLSKD


def _in_domains(host: str, domains: tuple[str, ...]) -> bool:
    return any(
        host == domain or host.endswith(f".{domain}") for domain in domains
    )


def _address(url: httpx.URL) -> str:
    return f"{url.host}:{url.port}" if url.port is not None else url.host


def _join(*sentences: str) -> str:
    return " ".join(sentence for sentence in sentences if sentence)
