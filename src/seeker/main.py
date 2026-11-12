import io
import logging
import sys

from seeker import config
from seeker.application import Application
from seeker.cli import dispatch, parse_args, printable
from seeker.error_text import describe_error
from seeker.errors import SeekerError
from seeker.soulseek import poller


def _write_utf8() -> None:
    # Redirected to a file or a pipe on Windows, stdout and stderr take
    # the ANSI code page (cp1252 on a Western install, UNVERIFIED on
    # hardware), and print() of a track or peer name outside it raises
    # UnicodeEncodeError, ending the command. macOS writes UTF-8
    # already (tests/test_main.py's pipe test passed there without
    # this). What UTF-8 cannot encode, a lone surrogate from an
    # undecodable filename byte, prints as `?` on stdout; stderr keeps
    # Python's own escape, so a traceback keeps its detail. A stream
    # that is not a TextIOWrapper (None, with no console) is left alone.
    for stream, errors in ((sys.stdout, "replace"), (sys.stderr, "backslashreplace")):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors=errors)


def _configure_logging() -> None:
    # The CLI's own output channel — a bare "%(message)s" formatter so a
    # service's logger.info() reads like a plain print(). WARNING/ERROR
    # always show; DEBUG is opt-in per logger (SEEKER_DEBUG_POLL, in
    # main()).
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("seeker")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def main() -> None:
    _write_utf8()
    _configure_logging()
    config.load_env_file()
    if config.debug_poll():
        poller.logger.setLevel(logging.DEBUG)

    # Before Application: constructing it opens the database and
    # migrates config, which `--help` or a mistyped command must not.
    parsed = parse_args()

    # Spotify config is resolved lazily now (config store, falling back
    # to .env) — see Application.auth_manager. A command that doesn't
    # need Spotify auth at all (e.g. `library scan`) must still work
    # without it configured, matching how SLSKD_* has always worked.
    try:
        application = Application()
    except SeekerError as error:
        # Building it reads config.json, which can refuse to load (one
        # that is not UTF-8): its sentence, as dispatch prints a
        # command's error.
        print(printable(describe_error(error, details_hint="")))
        sys.exit(1)

    dispatch(application, parsed)
