"""GitHub-releases-based update check.

A real, unauthenticated external dependency — one GET against
api.github.com's `/releases/latest` endpoint, subject to GitHub's own
per-source-IP unauthenticated rate limit (60 requests/hour, confirmed
live 2026-09-01, see CLAUDE.md item 55). Treated with the same caution
as this project's other live-dependency checks (Docker/slskd health,
items 23/44): never called automatically, never on a timer or at
startup — only from an explicit user action (Help -> "Check for
updates...", see ui/main_window.py). `check_for_update()` itself never
raises — every real failure mode (network error, timeout, an
unexpected/malformed response, an unparseable version tag) is caught
and reported as UNAVAILABLE with a reason, the same "swallow into a
status enum, don't raise" discipline `docker_setup.py::
check_slskd_health`/`detect_docker_state` already established.
"""

from dataclasses import dataclass
from enum import Enum, auto
from importlib.metadata import PackageNotFoundError, version

import httpx
from packaging.version import InvalidVersion, Version

REPO = "KristiyanDDimitrov/Seeker"
RELEASES_LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

# Untuned, same convention as every other threshold in this codebase —
# long enough for a slow real connection, short enough that a hung
# request doesn't leave a user-triggered check spinning indefinitely.
REQUEST_TIMEOUT_SECONDS = 10.0


class UpdateStatus(Enum):
    UP_TO_DATE = auto()
    UPDATE_AVAILABLE = auto()
    UNAVAILABLE = auto()
    # Round 9 §4.2a — split out of UNAVAILABLE. A repo with no
    # published releases (confirmed live 2026-09-09: this repo has
    # none) has nothing wrong with it; GitHub's own 404 for that case is
    # identical to every OTHER 404 shape this module treats as a real
    # failure. UNAVAILABLE's caller (main_window.py) renders a Warning
    # icon and a "Couldn't check for updates:" prefix — both imply a
    # fault. A repo with nothing to report yet isn't one.
    NO_RELEASES_PUBLISHED = auto()


@dataclass
class UpdateCheckResult:
    status: UpdateStatus
    # Populated for UP_TO_DATE/UPDATE_AVAILABLE only.
    latest_version: str | None = None
    release_url: str | None = None
    # Populated whenever the installed version was resolved at all
    # (i.e. every branch past _installed_version() succeeding) — lets a
    # caller show "you have X, latest is Y" without re-querying package
    # metadata itself.
    installed_version: str | None = None
    # Populated for UNAVAILABLE only — a short, human-readable reason,
    # never a raw exception/traceback (this is shown directly in a
    # dialog).
    reason: str | None = None


def _installed_version() -> str | None:
    # Same mechanism AboutDialog already uses (item 34) — real installed
    # package metadata, never a second hardcoded literal that could
    # drift from pyproject.toml. None only when running from source
    # with no installed dist-info (e.g. `uv run` without `uv sync`
    # having registered the project — not expected in normal use, but
    # not fatal either: it just means there's nothing to compare
    # against).
    try:
        return version("seeker")
    except PackageNotFoundError:
        return None


def check_for_update() -> UpdateCheckResult:
    # Thin wrapper enforcing the "never raises" contract unconditionally
    # — every real, anticipated failure mode is already handled with a
    # specific, useful reason inside _check_for_update(); this final
    # catch-all exists only so a genuinely unforeseen exception (a bug,
    # an httpx internal we didn't anticipate) still reports UNAVAILABLE
    # instead of crashing the caller — this runs from a manual Help
    # menu click, so it must never take the app down with it. Same
    # "swallow into a status enum, don't raise" discipline this
    # project's other live-dependency checks already use (docker_setup
    # .py's check_slskd_health/detect_docker_state).
    try:
        return _check_for_update()
    except Exception as error:
        return UpdateCheckResult(
            UpdateStatus.UNAVAILABLE,
            reason=f"Unexpected error while checking for updates: {error}",
        )


def _check_for_update() -> UpdateCheckResult:
    installed = _installed_version()

    if installed is None:
        return UpdateCheckResult(
            UpdateStatus.UNAVAILABLE,
            reason="Seeker's installed version couldn't be determined.",
        )

    try:
        installed_version = Version(installed)
    except InvalidVersion:
        return UpdateCheckResult(
            UpdateStatus.UNAVAILABLE,
            reason=f"Installed version '{installed}' isn't a version "
                   f"Seeker knows how to compare.",
        )

    try:
        response = httpx.get(
            RELEASES_LATEST_URL, timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        return UpdateCheckResult(
            UpdateStatus.UNAVAILABLE,
            reason="Timed out reaching GitHub.",
            installed_version=installed,
        )
    except httpx.HTTPError as error:
        return UpdateCheckResult(
            UpdateStatus.UNAVAILABLE,
            reason=f"Couldn't reach GitHub: {error}",
            installed_version=installed,
        )

    if response.status_code == 404:
        # The real, confirmed shape for this repo today (no release has
        # ever been published) — GitHub returns the identical 404 for
        # "repo doesn't exist" too, but that's not a real scenario for
        # a hardcoded, known-good REPO constant. NO_RELEASES_PUBLISHED,
        # not UNAVAILABLE — see that status's own docstring for why.
        return UpdateCheckResult(
            UpdateStatus.NO_RELEASES_PUBLISHED,
            reason="No releases have been published yet.",
            installed_version=installed,
        )

    if response.status_code == 403:
        # GitHub's real unauthenticated rate limit (60/hour, shared per
        # source IP) — a real, reachable state, not hypothetical.
        return UpdateCheckResult(
            UpdateStatus.UNAVAILABLE,
            reason="GitHub rate-limited this check — try again later.",
            installed_version=installed,
        )

    if response.status_code != 200:
        return UpdateCheckResult(
            UpdateStatus.UNAVAILABLE,
            reason=f"GitHub returned an unexpected response "
                   f"(status {response.status_code}).",
            installed_version=installed,
        )

    try:
        payload = response.json()
        tag_name = payload["tag_name"]
        release_url = payload.get("html_url")
    except ValueError:
        return UpdateCheckResult(
            UpdateStatus.UNAVAILABLE,
            reason="GitHub's response wasn't valid JSON.",
            installed_version=installed,
        )
    except KeyError:
        return UpdateCheckResult(
            UpdateStatus.UNAVAILABLE,
            reason="GitHub's response was missing the expected fields.",
            installed_version=installed,
        )

    try:
        latest_version = Version(tag_name)
    except InvalidVersion:
        return UpdateCheckResult(
            UpdateStatus.UNAVAILABLE,
            reason=f"Couldn't parse the latest release tag "
                   f"('{tag_name}').",
            installed_version=installed,
        )

    if latest_version > installed_version:
        return UpdateCheckResult(
            UpdateStatus.UPDATE_AVAILABLE,
            latest_version=tag_name, release_url=release_url,
            installed_version=installed,
        )

    return UpdateCheckResult(
        UpdateStatus.UP_TO_DATE,
        latest_version=tag_name, release_url=release_url,
        installed_version=installed,
    )
