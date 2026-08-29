import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from seeker.docker_setup import (
    SLSKD_NETWORK_PASSWORD_ENV_VAR,
    SLSKD_NETWORK_USERNAME_ENV_VAR,
    DockerState,
    SlskdHealthStatus,
    bring_up_slskd,
    check_slskd_health,
    compose_file_path,
    detect_docker_state,
    generate_api_key,
    slskd_data_dir,
)

# A fixed reference point for "when this bring-up attempt started" —
# tests construct log entries before/after this to exercise the
# stale-entry filter.
SINCE = datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)
BEFORE_SINCE = (SINCE - timedelta(minutes=5)).isoformat()
AFTER_SINCE = (SINCE + timedelta(seconds=1)).isoformat()


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


def test_slskd_data_dir_uses_platformdirs_and_slskd_data_subdir(
        tmp_path, monkeypatch,
):
    # Moved here from ui/wizard.py (Step 8 §3) so Settings' "Update
    # SoulSeek credentials" action can resolve the identical path
    # without importing a UI module — same platformdirs directory the
    # DB/config store already live in.
    monkeypatch.setattr(
        "seeker.docker_setup.platformdirs.user_data_dir",
        lambda appname, **kwargs: str(tmp_path),
    )

    assert slskd_data_dir() == tmp_path / "slskd-data"


# Packaging task's resource-path fix (see docs/HISTORY.md packaging
# entry): dev-mode behavior must stay byte-identical to what shipped
# before — CWD-relative, matching the CLI's own documented "run
# `docker compose up` from the project root" convention. Only a frozen
# build (sys.frozen set by PyInstaller's bootloader) should switch to
# resolving against sys._MEIPASS instead.
def test_compose_file_path_is_cwd_relative_outside_a_frozen_build(monkeypatch):
    monkeypatch.delattr("sys.frozen", raising=False)

    assert compose_file_path() == Path("docker-compose.yml")


def test_compose_file_path_resolves_against_meipass_when_frozen(monkeypatch):
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys._MEIPASS", "/fake/bundle/root", raising=False)

    assert compose_file_path() == Path("/fake/bundle/root/docker-compose.yml")


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

    result = check_slskd_health("http://localhost:5030", "key", SINCE)

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

    result = check_slskd_health("http://localhost:5030", "key", SINCE)

    assert result.status == SlskdHealthStatus.NOT_READY


def test_check_slskd_health_not_ready_when_application_unreachable(
        monkeypatch,
):
    def fake_get(url, headers=None, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_slskd_health("http://localhost:5030", "key", SINCE)

    assert result.status == SlskdHealthStatus.NOT_READY


def test_check_slskd_health_detects_real_bad_credentials_log_pattern(
        monkeypatch,
):
    # Real, confirmed-live log entries (2026-08-28) for a deliberately
    # wrong SoulSeek password against a real container — timestamped
    # after `since`, so this is a real, current-attempt rejection.
    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/api/v0/application"):
            return FakeResponse(200, {"server": {"state": "Disconnected"}})

        return FakeResponse(
            200,
            [
                {
                    "timestamp": AFTER_SINCE,
                    "level": "Information",
                    "message": "Connected to the Soulseek server",
                },
                {
                    "timestamp": AFTER_SINCE,
                    "level": "Error",
                    "message": (
                        "Disconnected from the Soulseek server: invalid "
                        "username or password"
                    ),
                },
                {
                    "timestamp": AFTER_SINCE,
                    "level": "Error",
                    "message": (
                        'Failed to reconnect: "The server rejected login '
                        'attempt: INVALIDPASS'
                    ),
                },
            ],
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_slskd_health("http://localhost:5030", "key", SINCE)

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
                    "timestamp": AFTER_SINCE,
                    "level": "Error",
                    "message": "Disconnected from the Soulseek server: "
                                "another client logged in using the same "
                                "username",
                },
            ],
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_slskd_health("http://localhost:5030", "key", SINCE)

    assert result.status == SlskdHealthStatus.NOT_READY


def test_check_slskd_health_ignores_stale_bad_credentials_entry_before_since(
        monkeypatch,
):
    # The real gap this test guards: /api/v0/logs returns the whole
    # recent log buffer, not just what happened after this call. A
    # stale Error entry from an earlier attempt (e.g. a mistyped
    # password the user already corrected) must not false-positive a
    # later, genuinely still-negotiating poll as BAD_CREDENTIALS.
    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/api/v0/application"):
            return FakeResponse(200, {"server": {"state": "Disconnected"}})

        return FakeResponse(
            200,
            [
                {
                    "timestamp": BEFORE_SINCE,
                    "level": "Error",
                    "message": (
                        "Disconnected from the Soulseek server: invalid "
                        "username or password"
                    ),
                },
            ],
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_slskd_health("http://localhost:5030", "key", SINCE)

    assert result.status == SlskdHealthStatus.NOT_READY


def test_check_slskd_health_ignores_error_entry_with_unparseable_timestamp(
        monkeypatch,
):
    # Defensive: an entry that can't be proven recent must not be
    # trusted either way — skipped, not treated as a false positive.
    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/api/v0/application"):
            return FakeResponse(200, {"server": {"state": "Disconnected"}})

        return FakeResponse(
            200,
            [
                {
                    "timestamp": "not-a-real-timestamp",
                    "level": "Error",
                    "message": (
                        "Disconnected from the Soulseek server: invalid "
                        "username or password"
                    ),
                },
            ],
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_slskd_health("http://localhost:5030", "key", SINCE)

    assert result.status == SlskdHealthStatus.NOT_READY


def test_bring_up_slskd_builds_correct_env_and_command(monkeypatch):
    # No caller in this codebase ever exercises bring_up_slskd's real
    # body — every wizard/Settings test mocks it out entirely (there's
    # no reasonable way to unit test a real `docker compose up`). This
    # is the one direct test of what it actually constructs — a real
    # regression risk given item 13's own history of getting the
    # SoulSeek-network-vs-web-UI env var names wrong once already.
    captured = {}

    def fake_run(command, env, capture_output, text, timeout):
        captured["command"] = command
        captured["env"] = env
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout

        class FakeResult:
            returncode = 0
            stderr = ""

        return FakeResult()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("UNRELATED_VAR", "should-be-preserved")

    bring_up_slskd(
        compose_file="docker-compose.yml",
        soulseek_username="realuser",
        soulseek_password="realpass",
        api_key="real-api-key",
        slskd_data_dir="/data/slskd-data",
        library_location_path="/music",
    )

    assert captured["command"] == [
        "docker", "compose", "-f", "docker-compose.yml", "up", "-d",
    ]
    env = captured["env"]
    assert env[SLSKD_NETWORK_USERNAME_ENV_VAR] == "realuser"
    assert env[SLSKD_NETWORK_PASSWORD_ENV_VAR] == "realpass"
    assert env["SLSKD_API_KEY"] == "real-api-key"
    assert env["SLSKD_DATA_DIR"] == "/data/slskd-data"
    assert env["SLSKD_SHARE_PATH"] == "/music"
    # The real process environment is passed through, not replaced —
    # confirms **os.environ is actually spread in, not just assumed.
    assert env["UNRELATED_VAR"] == "should-be-preserved"
    assert captured["capture_output"] is True
    assert captured["text"] is True
