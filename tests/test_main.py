import codecs
import io
import locale
import logging
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import platformdirs
import pytest

from seeker import main
from seeker.errors import TextFileNotUtf8Error
from seeker.soulseek import poller


@pytest.fixture
def unwritable_data_dir(tmp_path, monkeypatch):
    """Point every platformdirs lookup into a directory nothing can be
    created in, so any attempt to open the database, migrate config or
    write a token fails loudly."""
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    monkeypatch.setattr(
        platformdirs, "user_data_dir",
        lambda *args, **kwargs: str(locked / "Seeker"),
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    seeker_logger = logging.getLogger("seeker")
    handlers, level = list(seeker_logger.handlers), seeker_logger.level
    poll_level = poller.logger.level
    yield locked
    seeker_logger.handlers[:] = handlers
    seeker_logger.setLevel(level)
    poller.logger.setLevel(poll_level)
    locked.chmod(0o700)


@pytest.mark.parametrize(
    "argv",
    [["--help"], ["library", "--help"], ["no-such-command"], []],
)
def test_help_and_usage_errors_never_touch_user_data(
        argv, unwritable_data_dir, monkeypatch, capsys,
):
    monkeypatch.setattr(sys, "argv", ["seeker", *argv])

    with pytest.raises(SystemExit) as exit_info:
        main.main()

    assert exit_info.value.code in (0, 2)
    captured = capsys.readouterr()
    assert "usage: seeker" in captured.out + captured.err
    assert list(unwritable_data_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("setting", "level"),
    [("1", logging.DEBUG), ("0", logging.NOTSET), (None, logging.NOTSET)],
)
def test_seeker_debug_poll_turns_on_the_poll_trace(
        setting, level, unwritable_data_dir, monkeypatch,
):
    if setting is None:
        monkeypatch.delenv("SEEKER_DEBUG_POLL", raising=False)
    else:
        monkeypatch.setenv("SEEKER_DEBUG_POLL", setting)
    monkeypatch.setattr(sys, "argv", ["seeker", "--help"])

    with pytest.raises(SystemExit):
        main.main()

    assert poller.logger.level == level


def test_a_command_runs_against_a_real_application_instance(
        unwritable_data_dir, monkeypatch,
):
    # Application itself is replaced: constructing the real one opens
    # the database, which the locked data directory forbids.
    class RecordingMatcher:
        match_all_calls = 0

        def match_all(self):
            self.match_all_calls += 1

    application = SimpleNamespace(track_matcher=RecordingMatcher())
    monkeypatch.setattr(main, "Application", lambda: application)
    monkeypatch.setattr(sys, "argv", ["seeker", "library", "match"])

    main.main()

    assert application.track_matcher.match_all_calls == 1


# A name that cp1252, the ANSI code page of a Western Windows install,
# cannot encode, in escapes so no command line or source encoding
# stands between it and the bytes.
_NAME = "Nova Reyes \u2014 \u6771\u4eac"


def _code_page_stream() -> io.TextIOWrapper:
    """A stream in cp1252, as Windows gives a redirected stdout or
    stderr (AUDIT PF-12); `newline` keeps `\\n` as written."""
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\n")


def test_the_cli_prints_a_name_outside_the_code_page_as_utf8(
        unwritable_data_dir, monkeypatch,
):
    """Through a cp1252 stream, `print()` of a name outside it raised
    UnicodeEncodeError and ended the command. `main()` writes stdout and
    stderr as UTF-8 before anything prints, and a character UTF-8
    cannot encode (a lone surrogate, as `os.fsdecode` makes of a
    filename's undecodable byte) prints as `?`."""
    stdout, stderr = _code_page_stream(), _code_page_stream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(main, "Application", lambda: None)

    def dispatch(application, parsed):
        print(_NAME)
        print(f"{_NAME} \udce9", file=sys.stderr)

    monkeypatch.setattr(main, "dispatch", dispatch)
    monkeypatch.setattr(sys, "argv", ["seeker", "sync"])

    main.main()

    stdout.flush()
    stderr.flush()
    assert stdout.buffer.getvalue() == f"{_NAME}\n".encode()
    assert stderr.buffer.getvalue() == f"{_NAME} ?\n".encode()


# The CLI in a child of its own, its output piped as a redirect is:
# the program prints `_NAME` from where a command's output comes.
_PIPED_CLI = (
    "import sys\n"
    "from seeker import main\n"
    "main.Application = lambda: None\n"
    f"main.dispatch = lambda application, parsed: print({_NAME!a})\n"
    "sys.argv = ['seeker', 'sync']\n"
    "main.main()\n"
)


def test_the_cli_writes_utf8_to_a_pipe(tmp_path):
    """Where the platform's pipe is not UTF-8 (Windows: the ANSI code
    page), the child would fail on `_NAME`; on macOS it shows the same
    output a person's redirect gets."""
    result = subprocess.run(  # noqa: S603 — this interpreter, a fixed script
        [sys.executable, "-c", _PIPED_CLI],
        cwd=tmp_path, capture_output=True, timeout=60, check=False,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.decode("utf-8").splitlines() == [_NAME]


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="a pipe is UTF-8 on macOS already; Windows gives it the code page",
)
def test_on_windows_a_pipe_takes_the_ansi_code_page():
    """The control for the test above: on Windows a child's piped
    stdout is in the ANSI code page (`locale.getencoding()`), never
    UTF-8, unless the program says otherwise, so the CLI's UTF-8 there
    is `main()`'s doing (PF-11 and PF-12's premise)."""
    result = subprocess.run(
        [sys.executable, "-c", "import sys; print(sys.stdout.encoding)"],
        capture_output=True, text=True, timeout=60, check=True,
    )

    piped = codecs.lookup(result.stdout.strip()).name
    assert piped == codecs.lookup(locale.getencoding()).name
    assert piped != "utf-8"


def test_settings_seeker_cannot_read_stop_the_cli_with_their_sentence(
        unwritable_data_dir, monkeypatch, capsys,
):
    """Building the Application reads config.json, and one that is not
    UTF-8 raises TextFileNotUtf8Error. The CLI prints its sentence, as
    it prints a command's error, and exits 1: no traceback."""
    def refuse():
        raise TextFileNotUtf8Error(Path("config.json"))

    monkeypatch.setattr(main, "Application", refuse)
    monkeypatch.setattr(sys, "argv", ["seeker", "sync"])

    with pytest.raises(SystemExit) as exit_info:
        main.main()

    assert exit_info.value.code == 1
    assert capsys.readouterr().out == (
        "config.json is not UTF-8 text, so Seeker has left it as it is. "
        "Save it as UTF-8 in a text editor, then try again.\n"
    )
