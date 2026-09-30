import logging
import sys

import platformdirs
import pytest

from seeker import main
from seeker.soulseek import download_service


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
    poll_level = download_service.logger.level
    yield locked
    seeker_logger.handlers[:] = handlers
    seeker_logger.setLevel(level)
    download_service.logger.setLevel(poll_level)
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
def test_seeker_debug_poll_turns_on_the_download_service_trace(
        setting, level, unwritable_data_dir, monkeypatch,
):
    if setting is None:
        monkeypatch.delenv("SEEKER_DEBUG_POLL", raising=False)
    else:
        monkeypatch.setenv("SEEKER_DEBUG_POLL", setting)
    monkeypatch.setattr(sys, "argv", ["seeker", "--help"])

    with pytest.raises(SystemExit):
        main.main()

    assert download_service.logger.level == level
