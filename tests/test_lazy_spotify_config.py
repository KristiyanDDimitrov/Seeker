import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC_PATH = str(Path(__file__).resolve().parents[1] / "src")


def _run_fresh_environment_script(tmp_path: Path, script: str) -> str:
    # A real subprocess with a genuinely clean environment — python-dotenv's
    # load_dotenv() walks up from config.py's own file location looking
    # for a .env file, not from the subprocess's cwd, so it would still
    # find *this* project's real .env regardless of cwd. Setting the
    # SPOTIFY_*/SLSKD_* keys to an empty string (not absent) beforehand
    # is what actually prevents that — load_dotenv()'s default
    # override=False treats "already present, even empty" as already
    # set and leaves it alone (confirmed empirically, not assumed).
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
