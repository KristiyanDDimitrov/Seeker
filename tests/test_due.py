"""is_due: when a periodic job (the daily sweep, the update check) is
due again."""
from datetime import UTC, datetime, timedelta

import pytest

from seeker.due import is_due

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
DAY = timedelta(hours=24)


@pytest.mark.parametrize(("last", "due"), [
    (None, True),
    ((NOW - timedelta(days=3)).isoformat(), True),
    ((NOW - DAY).isoformat(), True),
    ((NOW - DAY + timedelta(seconds=1)).isoformat(), False),
    (NOW.isoformat(), False),
    # The clock went back past the last run: waiting for it to catch
    # up could mean days with no run.
    ((NOW + timedelta(hours=1)).isoformat(), True),
    # A hand-edited value: run, and the stamp repairs it.
    ("yesterday", True),
    ("2026-10-09T08:00:00", True),
])
def test_is_due(last, due):
    assert is_due(NOW, last, DAY) is due


def test_is_due_measures_the_interval_it_is_given():
    last = (NOW - timedelta(hours=2)).isoformat()

    assert is_due(NOW, last, timedelta(hours=1)) is True
    assert is_due(NOW, last, timedelta(hours=3)) is False
