import logging
import sys

from seeker import config
from seeker.application import Application
from seeker.cli import dispatch, parse_args
from seeker.soulseek import download_service


def _configure_logging() -> None:
    # The CLI's own output channel (§7.2.1) — a bare "%(message)s"
    # formatter so a service's logger.info() reads identically to the
    # print() it replaced. WARNING/ERROR always show; DEBUG is opt-in
    # per logger (SEEKER_DEBUG_POLL, in main()).
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("seeker")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def main() -> None:
    _configure_logging()
    config.load_env_file()
    if config.debug_poll():
        download_service.logger.setLevel(logging.DEBUG)

    # Before Application: constructing it opens the database and
    # migrates config, which `--help` or a mistyped command must not.
    parsed = parse_args()

    # Spotify config is resolved lazily now (config store, falling back
    # to .env) — see Application.auth_manager. A command that doesn't
    # need Spotify auth at all (e.g. `library scan`) must still work
    # without it configured, matching how SLSKD_* has always worked.
    dispatch(Application(), parsed)
