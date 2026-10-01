from datetime import UTC, datetime, timedelta

from seeker.ui.upload_eta import UploadEtaTracker

KEY = ("peer", "Music/Artist - Title.flac")
START = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def _record(tracker, key, *byte_counts, every_seconds=2):
    for index, byte_count in enumerate(byte_counts):
        tracker.record(
            key, byte_count, START + timedelta(seconds=every_seconds * index),
        )


def test_an_upload_needs_two_samples_before_an_estimate():
    tracker = UploadEtaTracker()
    assert tracker.describe(KEY, 1_000_000) == "Calculating…"

    _record(tracker, KEY, 0)

    assert tracker.describe(KEY, 1_000_000) == "Calculating…"


def test_the_estimate_comes_from_the_latest_speed():
    tracker = UploadEtaTracker()
    # Earlier pace 50 KB/s, latest 150 KB/s (300 KB in 2 s); 600 KB
    # left at the latest pace is 4 s.
    _record(tracker, KEY, 0, 100_000, 400_000)

    assert tracker.describe(KEY, 1_000_000) == "4s"


def test_three_samples_without_progress_read_as_stalled():
    tracker = UploadEtaTracker()
    _record(tracker, KEY, 0, 50_000, 50_000, 50_000)

    assert tracker.describe(KEY, 1_000_000) == "Stalled"


def test_progress_after_a_stall_estimates_again():
    tracker = UploadEtaTracker()
    _record(tracker, KEY, 50_000, 50_000, 50_000, 150_000)

    assert tracker.describe(KEY, 1_000_000) == "17s"


def test_no_progress_or_an_unknown_size_keeps_calculating():
    tracker = UploadEtaTracker()
    _record(tracker, KEY, 100_000, 100_000)
    assert tracker.describe(KEY, 1_000_000) == "Calculating…"

    other = ("peer", "other.mp3")
    _record(tracker, other, 0, 100_000)
    assert tracker.describe(other, None) == "Calculating…"


def test_evict_except_forgets_finished_uploads_only():
    tracker = UploadEtaTracker()
    finished = ("peer", "done.mp3")
    _record(tracker, KEY, 0, 100_000)
    _record(tracker, finished, 0, 100_000)

    tracker.evict_except({KEY})

    assert tracker.describe(finished, 1_000_000) == "Calculating…"
    assert tracker.describe(KEY, 1_000_000) == "18s"
