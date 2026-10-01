import logging
import sys
from types import SimpleNamespace

import platformdirs
import pytest

from seeker import main
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
