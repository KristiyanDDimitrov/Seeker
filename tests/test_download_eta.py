from datetime import datetime, timedelta, timezone

from seeker.ui.download_eta import DownloadEtaTracker, format_eta_seconds


def test_format_eta_seconds_under_a_minute():
    assert format_eta_seconds(42) == "42s"


def test_format_eta_seconds_minutes_and_seconds():
    assert format_eta_seconds(125) == "2m 5s"


def test_format_eta_seconds_hours_and_minutes():
    assert format_eta_seconds(3725) == "1h 2m"


def test_format_eta_seconds_never_negative():
    assert format_eta_seconds(-5) == "0s"


def test_describe_with_no_samples_is_calculating():
    tracker = DownloadEtaTracker()

    assert tracker.describe(1, 1_000) == "Calculating…"


def test_describe_with_one_sample_is_calculating():
    tracker = DownloadEtaTracker()
    tracker.record(1, 100, datetime.now(timezone.utc))

    assert tracker.describe(1, 1_000) == "Calculating…"


def test_describe_computes_eta_from_last_two_samples():
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)

    # 200 bytes/second, 600 bytes remaining -> 3s.
    tracker.record(1, 200, now - timedelta(seconds=1))
    tracker.record(1, 400, now)

    assert tracker.describe(1, 1_000) == "3s"


def test_describe_ignores_a_stale_earlier_sample_pair():
    # Only the LAST two samples should drive the estimate — an older,
    # faster interval must not skew a since-slowed-down real transfer.
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)

    tracker.record(1, 0, now - timedelta(seconds=2))
    tracker.record(1, 900, now - timedelta(seconds=1))  # fast interval
    tracker.record(1, 950, now)  # much slower — 50 bytes/s, 50 remaining -> 1s

    assert tracker.describe(1, 1_000) == "1s"


def test_describe_reports_stalled_after_several_flat_samples():
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)

    for offset in (2, 1, 0):
        tracker.record(1, 500, now - timedelta(seconds=offset))

    assert tracker.describe(1, 1_000) == "Stalled"


def test_describe_not_yet_stalled_with_only_two_flat_samples():
    # The stall threshold requires several consecutive flat samples —
    # two alone (one poll interval of no progress) isn't proof of a
    # real stall yet, so this reports "Calculating…", not "Stalled".
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)

    tracker.record(1, 500, now - timedelta(seconds=1))
    tracker.record(1, 500, now)

    assert tracker.describe(1, 1_000) == "Calculating…"


def test_describe_recovers_from_stalled_once_progress_resumes():
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)

    for offset in (3, 2, 1):
        tracker.record(1, 500, now - timedelta(seconds=offset))
    tracker.record(1, 700, now)

    # The most recent samples are no longer all-flat (500, 500, 700),
    # so this must not report "Stalled" anymore.
    assert tracker.describe(1, 1_000) != "Stalled"


def test_record_bounds_history_size():
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)

    for i in range(10):
        tracker.record(1, i * 100, now + timedelta(seconds=i))

    assert len(tracker._history[1]) <= 3


def test_evict_except_drops_untracked_ids():
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)
    tracker.record(1, 100, now)
    tracker.record(2, 100, now)

    tracker.evict_except({2})

    assert tracker.describe(1, 1_000) == "Calculating…"
    assert 1 not in tracker._history
    assert 2 in tracker._history


def test_evict_except_keeps_ids_still_active():
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)
    tracker.record(1, 200, now - timedelta(seconds=1))
    tracker.record(1, 400, now)

    tracker.evict_except({1})

    assert tracker.describe(1, 1_000) == "3s"


def test_tracks_multiple_requests_independently():
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)

    tracker.record(1, 200, now - timedelta(seconds=1))
    tracker.record(1, 400, now)

    tracker.record(2, 500, now - timedelta(seconds=1))
    tracker.record(2, 500, now)

    assert tracker.describe(1, 1_000) == "3s"
    assert tracker.describe(2, 1_000) == "Calculating…"
