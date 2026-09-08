import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

import httpx
import platformdirs

logger = logging.getLogger(__name__)

# /opt/homebrew/bin (Apple Silicon Homebrew) isn't guaranteed to reach
# PATH via path_helper below — it depends on a /etc/paths.d/homebrew
# file that isn't present on every install. Listed explicitly rather
# than relying on that file happening to exist. HISTORY §44.
_FALLBACK_BIN_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")


def ensure_full_path_environment() -> None:
    """Extend os.environ["PATH"] to match what a real login/interactive
    shell would have, not the minimal PATH a GUI-launched macOS app
    actually gets (launchd's bare `/usr/bin:/bin:/usr/sbin:/sbin`,
    missing /usr/local/bin and /opt/homebrew/bin — confirmed live via
    a real ephemeral LaunchAgent probe, HISTORY §44). Called once at
    Application startup, before anything Docker-related runs — every
    docker_setup.py subprocess call inherits os.environ already, so
    mutating it here fixes every call site at once.
    """
    try:
        result = subprocess.run(
            ["/usr/libexec/path_helper", "-s"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        match = re.search(r'PATH="([^"]*)"', result.stdout)
        resolved_path = match.group(1) if match else ""
    except Exception:
        # Best-effort only — this runs unconditionally at Application
        # startup (see the call site), so it must never be able to
        # crash startup itself, on any platform, for any reason
        # (path_helper doesn't exist at all outside macOS, and its
        # output shape isn't a contract this code controls). The
        # explicit _FALLBACK_BIN_DIRS below still get applied even
        # when this fails entirely.
        resolved_path = ""

    entries = resolved_path.split(":") if resolved_path else []
    entries += os.environ.get("PATH", "").split(":")
    entries += list(_FALLBACK_BIN_DIRS)

    merged = [entry for entry in dict.fromkeys(entries) if entry]
    os.environ["PATH"] = os.pathsep.join(merged)


def compose_file_path() -> Path:
    # Same home as slskd_data_dir() just below — both wizard.py and
    # settings_window.py need the identical path.
    #
    # docker-compose.yml is real *resource data*: a packaged build
    # bundles it as a PyInstaller `datas` entry (packaging/seeker.spec).
    # In dev, `sys.frozen` is never set, so this stays CWD-relative
    # (`docker compose up` is documented, README, to run from the
    # project root) — deliberately not source-tree-relative, which
    # would be a real behavior change from what's shipped and tested.
    if not getattr(sys, "frozen", False):
        return Path("docker-compose.yml")

    # A frozen build must NOT resolve this to sys._MEIPASS directly —
    # PyInstaller regenerates that path on every build, so a rebuilt or
    # relocated .app could never again recognize a container it had
    # itself previously created as self-managed (SharingService.
    # is_self_managed() compares against the running container's
    # recorded config-files label). Copy the bundled resource, once,
    # into the stable per-user slskd_data_dir() and always return that
    # canonical path afterward — guarded so a later Sharing-added
    # volume line is never clobbered by a subsequent app update.
    # HISTORY §74 (P5.3).
    canonical_path = slskd_data_dir() / "docker-compose.yml"

    if not canonical_path.exists():
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        bundled_path = (
            Path(sys._MEIPASS)  # type: ignore[attr-defined]
            / "docker-compose.yml"
        )
        shutil.copy2(bundled_path, canonical_path)

    return canonical_path


def slskd_data_dir() -> Path:
    # Shared by both wizard.py and settings_window.py, hence living in
    # a service-layer module rather than either UI one. Same per-user
    # app-data directory the DB/config store live in.
    return Path(
        platformdirs.user_data_dir("Seeker", appauthor=False)
    ) / "slskd-data"


class DockerState(Enum):
    NOT_INSTALLED = "not_installed"
    INSTALLED_NOT_RUNNING = "installed_not_running"
    RUNNING = "running"


def detect_docker_state() -> DockerState:
    try:
        subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            timeout=5,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return DockerState.NOT_INSTALLED
    except subprocess.TimeoutExpired:
        return DockerState.INSTALLED_NOT_RUNNING

    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            check=False,  # caller inspects result.returncode itself
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return DockerState.INSTALLED_NOT_RUNNING

    if result.returncode == 0:
        return DockerState.RUNNING

    return DockerState.INSTALLED_NOT_RUNNING


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def is_non_loopback_http_url(url: str) -> bool:
    """True when `url` is plain (unencrypted) HTTP pointed somewhere
    other than this machine.

    `SoulseekClient` sends `X-API-Key` as a plain header on every
    request; over loopback that's fine, but a `SLSKD_BASE_URL` pointed
    at a remote host over `http://` would put the key on the wire in
    clear. Used to warn in Settings, not to block anything — this
    project has no remote-slskd flow of its own, but `.env`'s
    `SLSKD_BASE_URL` is still user-editable outside the app.
    """
    parsed = urlparse(url)
    return parsed.scheme == "http" and parsed.hostname not in _LOOPBACK_HOSTS


def generate_api_key() -> str:
    # slskd documents API keys as 16-255 characters (see slskd.yml's own
    # example comment) — token_urlsafe(32) produces a 43-character
    # string, comfortably inside that range.
    return secrets.token_urlsafe(32)


# Two real, distinguishable credential pairs, confirmed live against
# slskd's own `--envars` output — easy to conflate, do not merge them:
# SLSKD_USERNAME/PASSWORD is the WEB UI login; SLSKD_SLSK_USERNAME/
# PASSWORD is the SOULSEEK NETWORK login. HISTORY §23.
SLSKD_NETWORK_USERNAME_ENV_VAR = "SLSKD_SLSK_USERNAME"
SLSKD_NETWORK_PASSWORD_ENV_VAR = "SLSKD_SLSK_PASSWORD"

SLSKD_WEB_USERNAME_ENV_VAR = "SLSKD_USERNAME"
SLSKD_WEB_PASSWORD_ENV_VAR = "SLSKD_PASSWORD"


SLSKD_HEALTHY_STATE = "Connected, LoggedIn"

# slskd's /api/v0/application carries no error/reason field at all
# (confirmed via its live swagger spec) — a bad-password rejection and
# an unrelated "kicked, another client already logged in" case both
# converge on the same terminal state, "Disconnected". The real reason
# only ever appears via /api/v0/logs' Error-level entries, matched by
# message substring — no structured error-code field exists to pin to
# instead, confirmed by inspecting a real captured entry's shape
# ({timestamp, context, level, message}). Matched case-insensitively.
# Worth re-checking against a real container after any slskd upgrade,
# since a future version could reword these messages. HISTORY §23, §52.
BAD_CREDENTIALS_LOG_PATTERNS = ("invalid username or password", "invalidpass")

# Disjoint from BAD_CREDENTIALS_LOG_PATTERNS (no shared words) — real,
# distinct Error-level text confirmed live against two disposable
# throwaway containers. HISTORY §52.
KICKED_LOG_PATTERNS = ("another client logged in using the same username",)


class SlskdHealthStatus(Enum):
    HEALTHY = "healthy"
    BAD_CREDENTIALS = "bad_credentials"
    KICKED = "kicked"
    NOT_READY = "not_ready"


@dataclass
class SlskdHealthCheckResult:
    status: SlskdHealthStatus
    detail: str | None = None


def _parse_log_timestamp(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None

    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def check_slskd_health(
        base_url: str,
        api_key: str,
        since: datetime,
) -> SlskdHealthCheckResult:
    """A single check, not a blocking poll loop — the caller (the
    wizard's own QTimer) calls this repeatedly, tracking overall
    elapsed time itself for the timeout.

    `since` filters /api/v0/logs' Error entries to this specific
    bring-up attempt: that endpoint returns the whole recent log
    buffer, so without filtering, a stale entry from an earlier,
    already-corrected attempt would false-positive every later poll as
    BAD_CREDENTIALS forever. HISTORY §23.
    """
    headers = {"X-API-Key": api_key}

    try:
        response = httpx.get(
            f"{base_url}/api/v0/application", headers=headers, timeout=10.0,
        )
        response.raise_for_status()
        state = response.json().get("server", {}).get("state")

        if state == SLSKD_HEALTHY_STATE:
            return SlskdHealthCheckResult(SlskdHealthStatus.HEALTHY)
    except httpx.HTTPError:
        return SlskdHealthCheckResult(SlskdHealthStatus.NOT_READY)

    try:
        logs_response = httpx.get(
            f"{base_url}/api/v0/logs", headers=headers, timeout=10.0,
        )
        logs_response.raise_for_status()

        for entry in logs_response.json():
            if entry.get("level") != "Error":
                continue

            entry_timestamp = _parse_log_timestamp(entry.get("timestamp"))

            # An entry with no parseable timestamp can't be proven
            # recent — skip rather than risk a false positive from
            # something stale.
            if entry_timestamp is None or entry_timestamp < since:
                continue

            message = str(entry.get("message", "")).lower()

            if any(
                    pattern in message
                    for pattern in BAD_CREDENTIALS_LOG_PATTERNS
            ):
                return SlskdHealthCheckResult(
                    SlskdHealthStatus.BAD_CREDENTIALS,
                    detail=str(entry.get("message")),
                )

            if any(
                    pattern in message
                    for pattern in KICKED_LOG_PATTERNS
            ):
                return SlskdHealthCheckResult(
                    SlskdHealthStatus.KICKED,
                    detail=str(entry.get("message")),
                )
    except httpx.HTTPError:
        logger.debug("Failed to read slskd logs for health check", exc_info=True)

    return SlskdHealthCheckResult(SlskdHealthStatus.NOT_READY)


class SlskdWebLoginStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


def check_slskd_web_login(
        base_url: str,
        username: str,
        password: str,
) -> SlskdWebLoginStatus:
    """Confirm a WEB UI login (distinct from the API-key-authenticated
    calls everywhere else in this codebase) actually works against the
    real running container, by attempting the same
    `POST /api/v0/session` slskd's own login page uses.

    `ensure_slskd_web_credentials()` generates and persists a login,
    but slskd will not let `SLSKD_USERNAME`/`SLSKD_PASSWORD` override a
    web UI login already customised before Seeker set the env var — the
    persisted value can silently stop matching what the container will
    actually accept. Live-confirmed: a generated credential that didn't
    take produces a real `401`, not an error. `UNKNOWN` covers slskd
    being unreachable at all (caller should not claim a login is broken
    when it simply couldn't be checked). HISTORY §116, §117.
    """
    try:
        response = httpx.post(
            f"{base_url}/api/v0/session",
            json={"username": username, "password": password},
            timeout=10.0,
        )
    except httpx.HTTPError:
        return SlskdWebLoginStatus.UNKNOWN

    if response.status_code == 200:
        return SlskdWebLoginStatus.ACTIVE

    if response.status_code == 401:
        return SlskdWebLoginStatus.INACTIVE

    return SlskdWebLoginStatus.UNKNOWN


def bring_up_slskd(
        compose_file: str,
        soulseek_username: str,
        soulseek_password: str,
        api_key: str,
        slskd_data_dir: str,
        web_username: str,
        web_password: str,
        library_location_path: str | None = None,
) -> subprocess.CompletedProcess[str]:
    # Passes the collected credentials/API key/paths directly as
    # environment variables to `docker compose up`, which Compose
    # substitutes into docker-compose.yml's ${VAR} placeholders — no
    # second, compose-specific env file.
    #
    # `library_location_path` is optional: a recreate triggered by
    # SharingService.add_location_to_share may not know the current
    # live-mounted share path and must not clobber it with a blank —
    # omitting the key lets Compose fall through to docker-compose.yml's
    # own `${SLSKD_SHARE_PATH:-...}` default instead of substituting an
    # explicit empty string. HISTORY §84 (R6).
    env = {
        **os.environ,
        SLSKD_NETWORK_USERNAME_ENV_VAR: soulseek_username,
        SLSKD_NETWORK_PASSWORD_ENV_VAR: soulseek_password,
        "SLSKD_API_KEY": api_key,
        "SLSKD_DATA_DIR": slskd_data_dir,
        SLSKD_WEB_USERNAME_ENV_VAR: web_username,
        SLSKD_WEB_PASSWORD_ENV_VAR: web_password,
    }

    if library_location_path is not None:
        env["SLSKD_SHARE_PATH"] = library_location_path

    return subprocess.run(
        ["docker", "compose", "-f", compose_file, "up", "-d"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,  # caller inspects .returncode itself
    )
