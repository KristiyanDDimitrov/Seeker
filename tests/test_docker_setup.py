import subprocess

import httpx
import pytest

from seeker.docker_setup import (
    SLSKD_NETWORK_PASSWORD_ENV_VAR,
    SLSKD_NETWORK_USERNAME_ENV_VAR,
    DockerState,
    SlskdHealthStatus,
    check_slskd_health,
    detect_docker_state,
    generate_api_key,
)


# Regression test locking in the real, confirmed-live env var mapping
# (2026-08-28) — this is exactly the kind of assumption this project
# has been burned by before. Confirmed empirically against a real
# running container: SLSKD_SLSK_USERNAME/SLSKD_SLSK_PASSWORD produced a
# real "Logged in to the Soulseek server as seekerapp"; both
# SLSKD_SOULSEEK_USERNAME/PASSWORD (a plausible-looking wrong guess)
# and bare SLSKD_USERNAME/PASSWORD (which is actually the web UI login,
# per slskd's own --help/--envars output) produced "username and/or
# password invalid" instead.
def test_credential_env_var_names_match_the_confirmed_live_mapping():
    assert SLSKD_NETWORK_USERNAME_ENV_VAR == "SLSKD_SLSK_USERNAME"
    assert SLSKD_NETWORK_PASSWORD_ENV_VAR == "SLSKD_SLSK_PASSWORD"


def test_generate_api_key_is_within_slskd_documented_length_range():
    key = generate_api_key()

    # slskd.yml's own example comment documents API keys as 16-255
    # characters.
    assert 16 <= len(key) <= 255


def test_generate_api_key_produces_distinct_values():
    assert generate_api_key() != generate_api_key()


class FakeCompletedProcess:
    def __init__(self, returncode: int):
        self.returncode = returncode


def test_detect_docker_state_not_installed_when_docker_missing(monkeypatch):
    def fake_run(args, **kwargs):
        raise FileNotFoundError("docker: command not found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert detect_docker_state() == DockerState.NOT_INSTALLED


def test_detect_docker_state_not_installed_when_version_check_errors(
        monkeypatch,
):
    def fake_run(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert detect_docker_state() == DockerState.NOT_INSTALLED


def test_detect_docker_state_installed_not_running_when_info_fails(
        monkeypatch,
):
    def fake_run(args, **kwargs):
        if args[1] == "--version":
            return FakeCompletedProcess(returncode=0)

        return FakeCompletedProcess(returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert detect_docker_state() == DockerState.INSTALLED_NOT_RUNNING


def test_detect_docker_state_installed_not_running_when_info_times_out(
        monkeypatch,
):
    def fake_run(args, **kwargs):
        if args[1] == "--version":
            return FakeCompletedProcess(returncode=0)

        raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 10))

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert detect_docker_state() == DockerState.INSTALLED_NOT_RUNNING


def test_detect_docker_state_running_when_both_succeed(monkeypatch):
    def fake_run(args, **kwargs):
        return FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert detect_docker_state() == DockerState.RUNNING


class FakeResponse:
    def __init__(self, status_code: int, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=httpx.Request("GET", "http://localhost:5030"),
                response=self,  # type: ignore[arg-type]
            )


def test_check_slskd_health_healthy_when_state_matches(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(200, {"server": {"state": "Connected, LoggedIn"}})

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_slskd_health("http://localhost:5030", "key")

    assert result.status == SlskdHealthStatus.HEALTHY


def test_check_slskd_health_not_ready_while_still_negotiating(monkeypatch):
    # Real, confirmed-live finding: /api/v0/server's state field alone
    # doesn't distinguish "still connecting" from anything else — a
    # plausible mid-negotiation state (or a plain connection refused)
    # must classify as NOT_READY, not error out or misreport health.
    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/api/v0/application"):
            return FakeResponse(200, {"server": {"state": "Connecting"}})

        return FakeResponse(200, [])

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_slskd_health("http://localhost:5030", "key")

    assert result.status == SlskdHealthStatus.NOT_READY


def test_check_slskd_health_not_ready_when_application_unreachable(
        monkeypatch,
):
    def fake_get(url, headers=None, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_slskd_health("http://localhost:5030", "key")

    assert result.status == SlskdHealthStatus.NOT_READY


def test_check_slskd_health_detects_real_bad_credentials_log_pattern(
        monkeypatch,
):
    # Real, confirmed-live log entries (2026-08-28) for a deliberately
    # wrong SoulSeek password against a real container.
    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/api/v0/application"):
            return FakeResponse(200, {"server": {"state": "Disconnected"}})

        return FakeResponse(
            200,
            [
                {
                    "level": "Information",
                    "message": "Connected to the Soulseek server",
                },
                {
                    "level": "Error",
                    "message": (
                        "Disconnected from the Soulseek server: invalid "
                        "username or password"
                    ),
                },
                {
                    "level": "Error",
                    "message": (
                        'Failed to reconnect: "The server rejected login '
                        'attempt: INVALIDPASS'
                    ),
                },
            ],
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_slskd_health("http://localhost:5030", "key")

    assert result.status == SlskdHealthStatus.BAD_CREDENTIALS
    assert result.detail is not None
    assert "invalid username or password" in result.detail.lower()


def test_check_slskd_health_not_ready_when_disconnected_for_unrelated_reason(
        monkeypatch,
):
    # Real, confirmed-live finding: a "kicked, another client already
    # logged in" disconnect lands at the exact same "Disconnected"
    # state as a bad-credentials rejection — only a log entry matching
    # the confirmed bad-credential pattern should classify as
    # BAD_CREDENTIALS; anything else must not be misclassified.
    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/api/v0/application"):
            return FakeResponse(200, {"server": {"state": "Disconnected"}})

        return FakeResponse(
            200,
            [
                {
                    "level": "Error",
                    "message": "Disconnected from the Soulseek server: "
                                "another client logged in using the same "
                                "username",
                },
            ],
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_slskd_health("http://localhost:5030", "key")

    assert result.status == SlskdHealthStatus.NOT_READY
