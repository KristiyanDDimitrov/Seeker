from seeker.application import Application
from seeker.cli import run


def main() -> None:
    # Spotify config is resolved lazily now (config store, falling back
    # to .env) — see Application.auth_manager. A command that doesn't
    # need Spotify auth at all (e.g. `library scan`) must still work
    # without it configured, matching how SLSKD_* has always worked.
    application = Application()

    run(application)