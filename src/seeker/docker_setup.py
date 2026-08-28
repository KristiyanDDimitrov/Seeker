import os
import secrets
import subprocess
from dataclasses import dataclass
from enum import Enum

import httpx


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
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return DockerState.INSTALLED_NOT_RUNNING

    if result.returncode == 0:
        return DockerState.RUNNING

    return DockerState.INSTALLED_NOT_RUNNING


def generate_api_key() -> str:
    # slskd documents API keys as 16-255 characters (see slskd.yml's own
    # example comment) — token_urlsafe(32) produces a 43-character
    # string, comfortably inside that range.
    return secrets.token_urlsafe(32)


# Real, confirmed-live env var names (2026-08-28) — read straight from
# the slskd binary's own `--envars` output against the actual running
# container, not assumed from docs. Two real, distinguishable
# credential pairs exist and are easy to conflate:
#   SLSKD_USERNAME / SLSKD_PASSWORD       -> the WEB UI login
#     (--help: "username/password for web UI", default "slskd"/"slskd")
#   SLSKD_SLSK_USERNAME / SLSKD_SLSK_PASSWORD -> the SOULSEEK NETWORK
#     login (--help: "username/password for the Soulseek network").
# Confirmed empirically which is which by starting a throwaway
# container with each candidate pair and reading its own logs: setting
# SLSKD_SOULSEEK_USERNAME/PASSWORD (a plausible-looking but WRONG
# guess) and bare SLSKD_USERNAME/PASSWORD both produced "Not connecting
# to the Soulseek server; username and/or password invalid"; only
# SLSKD_SLSK_USERNAME/SLSKD_SLSK_PASSWORD produced a real
# "Logged in to the Soulseek server as <username>" — this wizard's
# credential fields map to these two, and only these two.
SLSKD_NETWORK_USERNAME_ENV_VAR = "SLSKD_SLSK_USERNAME"
SLSKD_NETWORK_PASSWORD_ENV_VAR = "SLSKD_SLSK_PASSWORD"


SLSKD_HEALTHY_STATE = "Connected, LoggedIn"

# Real, confirmed-live finding (2026-08-28): slskd's /api/v0/server (and
# /api/v0/application's "server" block) never distinguishes "still
# negotiating" from "rejected — bad credentials" — its ServerState
# schema (confirmed via the live swagger spec) carries only
# state/isConnected/isLoggedIn/isTransitioning, no error/reason field
# at all. Both a genuine bad-password rejection and an unrelated
# "kicked, another client already logged in with this username" case
# were observed live to converge on the exact same terminal
# state: "Disconnected". The real reason only ever appears via
# /api/v0/logs' Error-level entries — confirmed live for a deliberately
# wrong password: "Disconnected from the Soulseek server: invalid
# username or password" / "Failed to reconnect: ...INVALIDPASS".
# Matched case-insensitively by substring, same discipline as
# RECOGNIZED_REJECTION_PATTERNS elsewhere in this codebase — not
# broadened past what's actually been confirmed.
BAD_CREDENTIALS_LOG_PATTERNS = ("invalid username or password", "invalidpass")


class SlskdHealthStatus(Enum):
    HEALTHY = "healthy"
    BAD_CREDENTIALS = "bad_credentials"
    NOT_READY = "not_ready"


@dataclass
class SlskdHealthCheckResult:
    status: SlskdHealthStatus
    detail: str | None = None


def check_slskd_health(base_url: str, api_key: str) -> SlskdHealthCheckResult:
    # A single check, not a blocking poll loop — the wizard's own QTimer
    # calls this repeatedly (same pattern as the dashboard's live-status
    # poll), tracking overall elapsed time itself for the timeout. Keeps
    # this directly, deterministically testable per call.
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

            message = str(entry.get("message", "")).lower()

            if any(
                    pattern in message
                    for pattern in BAD_CREDENTIALS_LOG_PATTERNS
            ):
                return SlskdHealthCheckResult(
                    SlskdHealthStatus.BAD_CREDENTIALS,
                    detail=str(entry.get("message")),
                )
    except httpx.HTTPError:
        pass

    return SlskdHealthCheckResult(SlskdHealthStatus.NOT_READY)


def bring_up_slskd(
        compose_file: str,
        soulseek_username: str,
        soulseek_password: str,
        api_key: str,
        slskd_data_dir: str,
        library_location_path: str,
) -> subprocess.CompletedProcess[str]:
    # Passes the collected credentials/API key/paths directly as
    # environment variables to `docker compose up`, which Compose
    # substitutes into docker-compose.yml's ${VAR} placeholders — no
    # second, compose-specific env file (matches how Task 1 already
    # rejected a second .env-editing mechanism for this exact reason).
    env = {
        **os.environ,
        SLSKD_NETWORK_USERNAME_ENV_VAR: soulseek_username,
        SLSKD_NETWORK_PASSWORD_ENV_VAR: soulseek_password,
        "SLSKD_API_KEY": api_key,
        "SLSKD_DATA_DIR": slskd_data_dir,
        "SLSKD_SHARE_PATH": library_location_path,
    }

    return subprocess.run(
        ["docker", "compose", "-f", compose_file, "up", "-d"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
