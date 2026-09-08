import logging
import sys

from seeker.application import Application
from seeker.cli import run


def _configure_logging() -> None:
    # The CLI's own output channel (§7.2.1) — a bare "%(message)s"
    # formatter so a service's logger.info() reads identically to the
    # print() it replaced. WARNING/ERROR always show; DEBUG stays
    # opt-in via each call site's own gate (e.g. download_service.py's
    # SEEKER_DEBUG_POLL), unaffected by this handler's INFO level.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("seeker")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def main() -> None:
    _configure_logging()

    # Spotify config is resolved lazily now (config store, falling back
    # to .env) — see Application.auth_manager. A command that doesn't
    # need Spotify auth at all (e.g. `library scan`) must still work
    # without it configured, matching how SLSKD_* has always worked.
    application = Application()

    run(application)
