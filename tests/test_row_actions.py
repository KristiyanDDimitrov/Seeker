"""Tests for seeker.ui.row_actions.RunningRows."""

import shiboken6
from PySide6.QtWidgets import QPushButton

from seeker.ui.row_actions import RunningRows


def test_bind_leaves_a_row_that_is_not_running_alone(qtbot):
    rows: RunningRows[str] = RunningRows()
    button = QPushButton()
    qtbot.addWidget(button)

    rows.bind("t1", button)

    assert button.isEnabled()
    assert "t1" not in rows


def test_settle_reenables_the_rebuilt_row_and_skips_the_deleted_one(qtbot):
    rows: RunningRows[str] = RunningRows()
    started_from = QPushButton()
    rebuilt = QPushButton()
    qtbot.addWidget(rebuilt)
    rows.start("t1", started_from)
    shiboken6.Shiboken.delete(started_from)

    rows.bind("t1", rebuilt)
    assert not rebuilt.isEnabled()

    rows.settle("t1")

    assert rebuilt.isEnabled()
    assert "t1" not in rows
