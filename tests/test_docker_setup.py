import os
import subprocess
from datetime import UTC, datetime, timedelta
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
    ensure_full_path_environment,
    generate_api_key,
    slskd_data_dir,
)

# A fixed reference point for "when this bring-up attempt started" —
# tests construct log entries before/after this to exercise the
# stale-entry filter.
SINCE = datetime(2026, 8, 28, 15, 0, 0, tzinfo=UTC)
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


def test_compose_file_path_copies_bundled_file_into_slskd_data_dir_when_frozen(
        tmp_path, monkeypatch,
):
    # Roadmap item 74 (P5.3) — real, live-confirmed problem: the OLD
    # behavior (returning sys._MEIPASS's own path directly) meant
    # SharingService.is_self_managed() compared a running container's
    # real recorded label against a path that changes on every rebuild
    # of the .app, so a relocated/rebuilt app could never recognize a
    # container it had itself created. Now copies the bundled resource
    # into the SAME stable per-user directory the DB/config already
    # live in, once, and always returns that canonical path afterward.
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "docker-compose.yml").write_text("services:\n  slskd:\n")

    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        "seeker.docker_setup.platformdirs.user_data_dir",
        lambda appname, **kwargs: str(data_dir),
    )
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys._MEIPASS", str(bundle_dir), raising=False)

    result = compose_file_path()

    assert result == data_dir / "slskd-data" / "docker-compose.yml"
    assert result.read_text() == "services:\n  slskd:\n"


def test_compose_file_path_does_not_overwrite_an_existing_canonical_copy(
        tmp_path, monkeypatch,
):
    # Guarded like every other one-time migration in this codebase
    # (item 18's DB move, item 19's env-config migration) — a later
    # Sharing-added volume line living in the canonical copy must
    # survive a subsequent app rebuild/relaunch untouched.
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "docker-compose.yml").write_text("services:\n  slskd:\n")

    data_dir = tmp_path / "data"
    canonical = data_dir / "slskd-data" / "docker-compose.yml"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("services:\n  slskd:\n  # a real edited line\n")

    monkeypatch.setattr(
        "seeker.docker_setup.platformdirs.user_data_dir",
        lambda appname, **kwargs: str(data_dir),
    )
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys._MEIPASS", str(bundle_dir), raising=False)

    result = compose_file_path()

    assert result == canonical
    assert result.read_text() == "services:\n  slskd:\n  # a real edited line\n"


# item 44's real bug: a GUI-launched .app gets launchd's minimal PATH
# (/usr/bin:/bin:/usr/sbin:/sbin — confirmed live via a real ephemeral
# LaunchAgent probe, a genuine launchd-spawned process with no shell in
# the chain), which excludes /usr/local/bin (Docker Desktop's own CLI
# symlink) and /opt/homebrew/bin (Apple Silicon Homebrew) — so `docker`
# genuinely can't be found even when installed and running.
_MINIMAL_LAUNCHD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def test_ensure_full_path_environment_merges_path_helper_output(
        monkeypatch,
):
    monkeypatch.setenv("PATH", _MINIMAL_LAUNCHD_PATH)

    def fake_run(args, **kwargs):
        assert args == ["/usr/libexec/path_helper", "-s"]
        return FakeCompletedProcess(
            returncode=0,
            stdout=(
                'PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:'
                '/bin:/usr/sbin:/sbin"; export PATH;\n'
            ),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    ensure_full_path_environment()

    entries = os.environ["PATH"].split(":")
    assert "/usr/local/bin" in entries
    assert "/opt/homebrew/bin" in entries
    assert "/usr/bin" in entries


def test_ensure_full_path_environment_falls_back_when_path_helper_unavailable(
        monkeypatch,
):
    # path_helper genuinely doesn't exist on every platform this code
    # might run on (only real on macOS) — must not raise, and must
    # still get the explicit fallback dirs onto PATH.
    monkeypatch.setenv("PATH", _MINIMAL_LAUNCHD_PATH)

    def fake_run(args, **kwargs):
        raise FileNotFoundError("/usr/libexec/path_helper: not found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    ensure_full_path_environment()

    entries = os.environ["PATH"].split(":")
    assert "/opt/homebrew/bin" in entries
    assert "/usr/local/bin" in entries
    # Original minimal PATH must survive, not be replaced.
    assert "/usr/bin" in entries
    assert "/bin" in entries


# Real gap, found via test_wizard.py's own blanket
# `monkeypatch.setattr("seeker.ui.wizard.subprocess.run", ...)` — since
# `subprocess` is a single shared module object, that patch replaces
# `subprocess.run` globally, not just for wizard.py's own calls. A
# fake that returns something with no `.stdout` attribute (a plain
# `None`, as that fixture's lambda does) crashed this function with an
# uncaught AttributeError, which is unacceptable for something that
# runs unconditionally at every `Application()` construction. This is
# also a stand-in for any real, unanticipated subprocess.run() failure
# mode on a target platform this code doesn't control.
def test_ensure_full_path_environment_never_raises_on_malformed_result(
        monkeypatch,
):
    monkeypatch.setenv("PATH", _MINIMAL_LAUNCHD_PATH)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)

    ensure_full_path_environment()

    entries = os.environ["PATH"].split(":")
    assert "/opt/homebrew/bin" in entries
    assert "/usr/local/bin" in entries


def test_ensure_full_path_environment_does_not_duplicate_existing_entries(
        monkeypatch,
):
    monkeypatch.setenv(
        "PATH", f"/opt/homebrew/bin:{_MINIMAL_LAUNCHD_PATH}",
    )

    def fake_run(args, **kwargs):
        return FakeCompletedProcess(
            returncode=0,
            stdout=(
                'PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:'
                '/bin:/usr/sbin:/sbin"; export PATH;\n'
            ),
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    ensure_full_path_environment()

    entries = os.environ["PATH"].split(":")
    assert entries.count("/opt/homebrew/bin") == 1


class FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout


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


def test_check_slskd_health_kicked_when_another_client_logs_in(monkeypatch):
    # Roadmap item 8 — real, confirmed-live text (two genuinely
    # disposable throwaway slskd containers, never the real production
    # one; see docs/HISTORY.md item 8): a "kicked, another client
    # already logged in with this username" disconnect lands at the
    # exact same "Disconnected" state as a bad-credentials rejection,
    # but is a real, distinct, confirmable log line — must classify as
    # its own KICKED status, not BAD_CREDENTIALS and not NOT_READY.
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

    assert result.status == SlskdHealthStatus.KICKED
    assert result.detail is not None
    assert "another client" in result.detail.lower()


def test_check_slskd_health_not_ready_for_a_genuinely_unrelated_error(
        monkeypatch,
):
    # A real error unrelated to either confirmed pattern set must not
    # be misclassified as BAD_CREDENTIALS or KICKED.
    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/api/v0/application"):
            return FakeResponse(200, {"server": {"state": "Disconnected"}})

        return FakeResponse(
            200,
            [
                {
                    "timestamp": AFTER_SINCE,
                    "level": "Error",
                    "message": "Error initializing shares: disk read error",
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

    def fake_run(command, env, capture_output, text, timeout, check):
        captured["command"] = command
        captured["env"] = env
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        captured["check"] = check

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
    # Explicit, not defaulted (PLW1510, round 8 §4.8.6) — the caller
    # inspects .returncode itself rather than wanting an exception.
    assert captured["check"] is False
