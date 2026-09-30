import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC_PATH = str(Path(__file__).resolve().parents[1] / "src")


def _run_fresh_environment_script(tmp_path: Path, script: str) -> str:
    # A real subprocess with a genuinely clean environment: the
    # SPOTIFY_*/SLSKD_* keys are set empty, which reads as unconfigured
    # (and which load_dotenv's override=False would leave alone).
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("SPOTIFY_") and not key.startswith("SLSKD_")
    }
    env["SPOTIFY_CLIENT_ID"] = ""
    env["SPOTIFY_REDIRECT_URI"] = ""
    env["SLSKD_BASE_URL"] = ""
    env["SLSKD_API_KEY"] = ""
    env["SLSKD_DOWNLOAD_DIR"] = ""
    # Isolate platformdirs' app-data location too, so this never reads
    # or writes this machine's real config store/database.
    env["HOME"] = str(tmp_path)
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg-data")

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,  # asserts on result.returncode itself below
    )

    assert result.returncode == 0, (
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    return result.stdout


def test_fresh_environment_imports_every_wizard_module_without_crashing(
        tmp_path,
):
    # The core of the prerequisite fix (§0): a completely fresh
    # environment (no .env, no config store) must be able to import
    # every module the onboarding wizard needs without crashing.
    # Constructing Application() must not raise either — only actually
    # triggering Spotify auth may.
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {SRC_PATH!r})

        import seeker.config
        import seeker.config_store
        import seeker.spotify.auth_manager
        import seeker.spotify.callback_server
        import seeker.application
        import seeker.cli
        import seeker.main
        import seeker.main_ui

        from seeker.application import Application

        application = Application()
        assert application.spotify_configured is False

        try:
            application.auth_manager
        except RuntimeError as error:
            print("RAISED_CLEANLY:", error)
        else:
            raise AssertionError(
                "auth_manager should have raised with nothing configured"
            )

        print("IMPORTS_OK")
    """)

    output = _run_fresh_environment_script(tmp_path, script)

    assert "IMPORTS_OK" in output
    assert "RAISED_CLEANLY: SPOTIFY_CLIENT_ID is not configured." in output


def test_fresh_environment_other_commands_still_work_without_spotify(
        tmp_path,
):
    # Matches the SLSKD_* precedent exactly: a command that never
    # touches Spotify auth at all must keep working with nothing
    # configured — library_service/dashboard_service construction must
    # never force auth_manager into existence.
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {SRC_PATH!r})

        from seeker.application import Application

        application = Application()

        # None of these touch Spotify auth.
        application.library_service
        application.track_matcher
        application.dashboard_service
        application.onboarding_complete

        print("OTHER_SERVICES_OK")
    """)

    output = _run_fresh_environment_script(tmp_path, script)

    assert "OTHER_SERVICES_OK" in output


def _run_without_seeker_env(tmp_path: Path, script: str) -> str:
    # Unlike _run_fresh_environment_script, the keys are absent (not
    # empty), so any .env load is visible in os.environ.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("SPOTIFY_", "SLSKD_"))
    }
    env["HOME"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(tmp_path), env=env, capture_output=True, text=True,
        timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_importing_config_reads_no_env_file(tmp_path):
    # load_dotenv() at import walked up from the installed module's own
    # directory: this checkout's .env, or a frozen bundle's parents.
    (tmp_path / ".env").write_text("SPOTIFY_CLIENT_ID=from-working-dir\n")
    script = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {SRC_PATH!r})
        import seeker.application
        print(sorted(
            key for key in os.environ
            if key.startswith(("SPOTIFY_", "SLSKD_"))
        ))
    """)

    assert _run_without_seeker_env(tmp_path, script).strip() == "[]"


def test_load_env_file_reads_the_working_directorys_env(tmp_path):
    (tmp_path / ".env").write_text("SPOTIFY_CLIENT_ID=from-working-dir\n")
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {SRC_PATH!r})
        from seeker import config
        config.load_env_file()
        print(config.spotify_client_id())
    """)

    assert _run_without_seeker_env(tmp_path, script).strip() == (
        "from-working-dir"
    )


def test_a_frozen_app_never_reads_an_env_file(tmp_path):
    (tmp_path / ".env").write_text("SPOTIFY_CLIENT_ID=from-working-dir\n")
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {SRC_PATH!r})
        sys.frozen = True
        from seeker import config
        config.load_env_file()
        print(config.spotify_client_id())
    """)

    assert _run_without_seeker_env(tmp_path, script).strip() == "None"
