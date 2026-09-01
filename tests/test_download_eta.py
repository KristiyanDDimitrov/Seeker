from datetime import datetime, timedelta, timezone

from seeker.ui.download_eta import (
    AggregateEta,
    DownloadEtaTracker,
    format_aggregate_header,
    format_eta_seconds,
)


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


def test_evict_drops_a_single_id_immediately():
    # Roadmap item 56 Phase 5.4 — the real fix for "a finished download
    # reads as Stalled": evict() removes one id the moment its row is
    # seen as terminal, without needing evict_except()'s once-per-poll
    # sweep over the whole active set.
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)
    tracker.record(1, 200, now - timedelta(seconds=1))
    tracker.record(1, 400, now)
    tracker.record(2, 100, now)

    tracker.evict(1)

    assert 1 not in tracker._history
    assert 2 in tracker._history
    assert tracker.describe(1, 1_000) == "Calculating…"


def test_evict_a_never_tracked_id_is_a_no_op():
    tracker = DownloadEtaTracker()

    tracker.evict(999)  # must not raise


def test_tracks_multiple_requests_independently():
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)

    tracker.record(1, 200, now - timedelta(seconds=1))
    tracker.record(1, 400, now)

    tracker.record(2, 500, now - timedelta(seconds=1))
    tracker.record(2, 500, now)

    assert tracker.describe(1, 1_000) == "3s"
    assert tracker.describe(2, 1_000) == "Calculating…"


# --- aggregate() / format_aggregate_header() (Task 9) -----------------------

def test_aggregate_sums_remaining_bytes_over_speed_for_contributors_only():
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)

    # Request 1: 200 bytes/s, 800 bytes remaining of 1_000 -> 4s.
    tracker.record(1, 200, now - timedelta(seconds=1))
    tracker.record(1, 400, now)

    # Request 2: 100 bytes/s, 900 bytes remaining of 1_000 -> 9s.
    tracker.record(2, 900, now - timedelta(seconds=1))
    tracker.record(2, 1_000, now)

    # Combined: (800 + 0) remaining ... actually sum(remaining)/sum(speed).
    # remaining_1 = 1_000 - 400 = 600, remaining_2 = 2_000 - 1_000 = 1_000.
    result = tracker.aggregate([(1, 1_000), (2, 2_000)])

    assert result.transferring_count == 2
    assert result.no_estimate_count == 0
    assert result.eta_seconds == (600 + 1_000) / (200 + 100)


def test_aggregate_excludes_queued_downloads_with_no_samples_yet():
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)

    tracker.record(1, 200, now - timedelta(seconds=1))
    tracker.record(1, 400, now)
    # Request 2 has never been sampled — a genuinely queued transfer.

    result = tracker.aggregate([(1, 1_000), (2, 5_000)])

    assert result.transferring_count == 1
    assert result.no_estimate_count == 1
    assert result.eta_seconds == (1_000 - 400) / 200
    assert result.all_non_contributors_stalled is False


def test_aggregate_excludes_downloads_with_unknown_total_bytes():
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)

    tracker.record(1, 200, now - timedelta(seconds=1))
    tracker.record(1, 400, now)

    # A download with total_bytes=None can't contribute regardless of
    # transfer state — it still counts toward no_estimate_count (it's
    # a real row shown on the Downloads page with no estimate), just
    # never toward all_non_contributors_stalled (an unknown size isn't
    # evidence the transfer has stopped).
    result = tracker.aggregate([(1, 1_000), (2, None)])

    assert result.transferring_count == 1
    assert result.no_estimate_count == 1


def test_aggregate_returns_none_eta_with_no_contributors():
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)

    # Only one sample each — still "Calculating…", not stalled.
    tracker.record(1, 100, now)
    tracker.record(2, 200, now)

    result = tracker.aggregate([(1, 1_000), (2, 2_000)])

    assert result.eta_seconds is None
    assert result.transferring_count == 0
    assert result.no_estimate_count == 2
    assert result.all_non_contributors_stalled is False


def test_aggregate_flags_all_non_contributors_stalled():
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)

    for offset in (2, 1, 0):
        tracker.record(1, 500, now - timedelta(seconds=offset))
        tracker.record(2, 800, now - timedelta(seconds=offset))

    result = tracker.aggregate([(1, 1_000), (2, 2_000)])

    assert result.eta_seconds is None
    assert result.no_estimate_count == 2
    assert result.all_non_contributors_stalled is True


def test_aggregate_not_all_stalled_when_mixed_with_still_calculating():
    tracker = DownloadEtaTracker()
    now = datetime.now(timezone.utc)

    for offset in (2, 1, 0):
        tracker.record(1, 500, now - timedelta(seconds=offset))
    tracker.record(2, 100, now)  # only one sample — calculating, not stalled

    result = tracker.aggregate([(1, 1_000), (2, 2_000)])

    assert result.no_estimate_count == 2
    assert result.all_non_contributors_stalled is False


def test_aggregate_with_no_downloads_at_all():
    tracker = DownloadEtaTracker()

    result = tracker.aggregate([])

    assert result.eta_seconds is None
    assert result.transferring_count == 0
    assert result.no_estimate_count == 0
    assert result.all_non_contributors_stalled is False


def test_format_aggregate_header_with_an_estimate():
    result = AggregateEta(
        eta_seconds=720, transferring_count=3,
        no_estimate_count=5, all_non_contributors_stalled=False,
    )

    assert format_aggregate_header(result) == (
        "About 12m 0s remaining · 3 transferring · 5 queued (no estimate)"
    )


def test_format_aggregate_header_waiting_for_transfers_to_start():
    result = AggregateEta(
        eta_seconds=None, transferring_count=0,
        no_estimate_count=4, all_non_contributors_stalled=False,
    )

    assert format_aggregate_header(result) == (
        "Waiting for transfers to start · 0 transferring · "
        "4 queued (no estimate)"
    )


def test_format_aggregate_header_all_stalled():
    result = AggregateEta(
        eta_seconds=None, transferring_count=0,
        no_estimate_count=2, all_non_contributors_stalled=True,
    )

    assert format_aggregate_header(result) == (
        "All active transfers stalled · 0 transferring · "
        "2 queued (no estimate)"
    )


def test_format_aggregate_header_omits_no_estimate_clause_when_zero():
    result = AggregateEta(
        eta_seconds=60, transferring_count=2,
        no_estimate_count=0, all_non_contributors_stalled=False,
    )

    assert format_aggregate_header(result) == (
        "About 1m 0s remaining · 2 transferring"
    )
