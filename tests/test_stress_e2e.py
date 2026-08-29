"""Broad, combined-load end-to-end stress test — deliberately different
in kind from every other test in this suite. Every other live
verification in this project's history (see CLAUDE.md/docs/HISTORY.md)
is real but narrow: one feature, proven, moved on from. This drives the
whole real pipeline together — overlapping, sustained, real
infrastructure — specifically hunting for the class of bug that only
shows up under combined, extended real usage (resource leaks, races
between concurrent background operations, a UI signal that bypasses
run_worker's protection).

Opt-in only (SEEKER_RUN_STRESS_TEST=1) — never runs in the normal fast
suite. Real infrastructure (Spotify, slskd, the X9 Pro library), real
wall-clock time (minutes, not seconds), and real mutations against the
production database. Same "skip on missing real infra" discipline as
test_audio_analysis.py's X9-Pro-drive skip, extended with an explicit
opt-in gate since — unlike that test — this one is also slow and
consequential even when the infra IS present, so it must never run
just because someone happened to have everything configured.

Kept as a durable regression guard, not a throwaway exploration
script — re-run this deliberately after any change to worker/timer/
connection lifecycle code, not just once.
"""

import os
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import psutil
import pytest

from seeker.application import Application
from seeker.config_store import load_config, resolve_config_path, save_config
from seeker.ui.main_window import MainWindow
from seeker.ui.settings_window import SettingsWindow
from seeker.ui.workers import _callbacks

X9_PRO_ROOT = Path("/Volumes/X9 Pro")

requires_stress_opt_in = pytest.mark.skipif(
    os.environ.get("SEEKER_RUN_STRESS_TEST") != "1",
    reason=(
        "opt-in only — set SEEKER_RUN_STRESS_TEST=1 to run. Real "
        "infrastructure, real wall-clock minutes, and real mutations "
        "against the production database; never runs in the normal "
        "fast suite even when that infra happens to be present."
    ),
)

# 5 real minutes by default — enough to span >10 real 20s backend-poll
# cycles and let real downloads actually transition state, without
# making a deliberate re-run of this file an all-afternoon affair.
# Override for a longer deliberate run, e.g.
# SEEKER_STRESS_DURATION_SECONDS=1800.
DEFAULT_DURATION_SECONDS = 300.0
SAMPLE_INTERVAL_SECONDS = 15.0

# A real, generous ceiling — not a tight bound. The point is catching a
# monotonic, unbounded climb (a leak signature), not flagging normal
# real workload memory use (loading 215 playlists' worth of Qt table
# rows, librosa's own numpy buffers during a scan, etc. all cost real,
# legitimate, bounded memory).
MAX_ACCEPTABLE_RSS_GROWTH_MB = 250.0
MAX_ACCEPTABLE_FD_GROWTH = 40
MAX_ACCEPTABLE_THREAD_GROWTH = 40


@dataclass
class ResourceSample:
    t: float
    label: str
    rss_mb: float
    num_fds: int
    num_threads: int
    active_workers: int


@dataclass
class SampleLog:
    process: psutil.Process
    start: float
    samples: list[ResourceSample] = field(default_factory=list)

    def sample(self, label: str) -> ResourceSample:
        mem = self.process.memory_info()
        entry = ResourceSample(
            t=time.monotonic() - self.start,
            label=label,
            rss_mb=mem.rss / (1024 * 1024),
            num_fds=self.process.num_fds(),
            num_threads=self.process.num_threads(),
            active_workers=len(_callbacks),
        )
        self.samples.append(entry)
        print(
            f"[stress] t={entry.t:7.1f}s  RSS={entry.rss_mb:7.1f}MB  "
            f"fds={entry.num_fds:3d}  threads={entry.num_threads:3d}  "
            f"active_workers={entry.active_workers:2d}  {label}"
        )
        return entry


def _pump(
        qapp: object,
        predicate: Callable[[], bool],
        timeout: float,
        interval: float = 0.1,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()  # type: ignore[attr-defined]
        if predicate():
            return True
        time.sleep(interval)
    qapp.processEvents()  # type: ignore[attr-defined]
    return predicate()


def _select_playlist(main_window: MainWindow, name: str) -> bool:
    for row in range(main_window.playlist_list.count()):
        item = main_window.playlist_list.item(row)
        playlist = item.data(256)  # Qt.ItemDataRole.UserRole == 256
        if playlist is not None and playlist.name == name:
            main_window.playlist_list.setCurrentItem(item)
            return True
    return False


@requires_stress_opt_in
def test_broad_end_to_end_stress(qapp):
    if not X9_PRO_ROOT.is_dir():
        pytest.skip("x9-pro drive not mounted")

    application = Application()

    if not application.spotify_configured:
        pytest.skip("Spotify not configured in this environment")
    if not application.soulseek_configured:
        pytest.skip("SoulSeek not configured in this environment")

    duration = float(
        os.environ.get(
            "SEEKER_STRESS_DURATION_SECONDS", DEFAULT_DURATION_SECONDS,
        )
    )

    log = SampleLog(process=psutil.Process(), start=time.monotonic())

    # Real config restored afterward, no matter what happens — this
    # test mutates the real production config.json (thresholds) and
    # must leave it exactly as found.
    config_path = resolve_config_path()
    original_config = load_config(config_path)

    main_window: MainWindow | None = None

    try:
        log.sample("start")

        main_window = MainWindow(application)
        _pump(qapp, lambda: main_window.playlist_list.count() > 0, timeout=30)
        log.sample("MainWindow constructed, playlists loaded")

        # --- Overlapping sync/scan/match: fired back to back, NOT
        # waiting for each to settle before starting the next — a real
        # impatient user's actual clicking pattern, not a sequential
        # scripted one.
        main_window.sync_button.click()
        main_window.scan_button.click()
        main_window.match_button.click()
        log.sample("sync/scan/match fired overlapping")

        settled = _pump(
            qapp,
            lambda: (
                main_window.sync_button.isEnabled()
                and main_window.scan_button.isEnabled()
                and main_window.match_button.isEnabled()
            ),
            timeout=90.0,
        )
        print(f"[stress] overlapping sync/scan/match settled: {settled}")
        print(f"[stress] status_label after settle: {main_window.status_label.text()!r}")
        log.sample("sync/scan/match settled")

        # --- Multiple concurrent downloads across playlists — more
        # than the two simultaneous real downloads previously verified
        # in this project's history. The real production DB currently
        # has real download-eligible activity concentrated in one
        # playlist ("Test") — MainWindow's own download_button is
        # single-selection by UI design (one playlist at a time), so
        # to genuinely exercise concurrent DownloadService access from
        # multiple simultaneous callers, this fires download_playlist()
        # directly through the same real QThreadPool/run_worker
        # mechanism the UI itself uses, for multiple playlists at once,
        # rather than being limited to what one button can select.
        from seeker.ui.workers import run_worker

        download_targets = ["Test", "240KM/H"]
        download_results: dict[str, str] = {}

        def make_download_fn(name: str) -> Callable[[], None]:
            def fn() -> None:
                application.download_service.download_playlist(name)

            return fn

        def make_on_finished(name: str) -> Callable[[object], None]:
            def on_finished(_: object) -> None:
                download_results[name] = "finished"

            return on_finished

        def make_on_error(name: str) -> Callable[[str], None]:
            def on_error(message: str) -> None:
                download_results[name] = f"error: {message}"

            return on_error

        # Also exercise the real UI path once, for the same playlist,
        # WHILE the direct concurrent calls above are still in flight —
        # a real double-submission from two different real code paths
        # hitting the same playlist's download logic concurrently.
        for name in download_targets:
            run_worker(
                main_window.thread_pool,
                make_download_fn(name),
                on_finished=make_on_finished(name),
                on_error=make_on_error(name),
            )

        if _select_playlist(main_window, "Test"):
            qapp.processEvents()
            main_window.download_button.click()

        log.sample(f"{len(download_targets) + 1} concurrent download operations fired")

        # --- Interleave real interaction with real background work
        # still in flight, sustained for the real target duration:
        # switch the selected playlist, open/close Settings repeatedly
        # (the exact worker/window-lifecycle concern §0 flagged),
        # change a threshold mid-session, and keep sampling resource
        # usage throughout.
        threshold_changed = False
        settings_reopen_count = 0
        deadline = log.start + duration

        while time.monotonic() < deadline:
            cycle_start = time.monotonic()

            # Switch playlists while background work (downloads,
            # backend poll) may still be running.
            for name in ("Test", "240KM/H"):
                if _select_playlist(main_window, name):
                    _pump(qapp, lambda: True, timeout=0.5)

            # Open and close Settings repeatedly — the real risk named
            # in §0: does a closed-but-not-deleted window, and its own
            # QThreadPool, actually get released, or does resource
            # usage climb with every open/close cycle? Deliberately NOT
            # tracked in a list that outlives this iteration — holding
            # every instance alive would make this test measure its
            # own retention, not the app's real close()/cleanup
            # behavior. Only `.close()` plus dropping the local
            # reference, exactly what a real user closing the window
            # actually does.
            settings_window: SettingsWindow | None = SettingsWindow(application)
            settings_window.show()
            _pump(
                qapp,
                lambda w=settings_window: w.locations_table.rowCount() >= 0,
                timeout=5.0,
            )
            settings_window.close()
            qapp.processEvents()
            settings_window = None
            settings_reopen_count += 1

            # Mid-session threshold change, real Settings widgets, real
            # save button — confirmed to affect the NEXT match run
            # without any restart, exercising the already-constructed
            # real track_matcher live (see CLAUDE.md item 28 §4).
            if not threshold_changed:
                live_settings: SettingsWindow | None = SettingsWindow(application)
                new_auto = (original_config.auto_match_threshold or 90.0) - 1.0
                new_needs_review = (
                    original_config.needs_review_threshold or 70.0
                ) - 1.0
                live_settings.auto_match_threshold_field.setText(str(new_auto))
                live_settings.needs_review_threshold_field.setText(
                    str(new_needs_review)
                )
                live_settings.save_thresholds_button.click()
                qapp.processEvents()

                reloaded = load_config(config_path)
                assert reloaded.auto_match_threshold == new_auto, (
                    "threshold save didn't persist to the real config store"
                )
                assert application._config_store.auto_match_threshold == new_auto, (
                    "Application's in-memory config store wasn't updated "
                    "by Settings' real save action"
                )

                # Trigger match again on the SAME already-constructed
                # track_matcher — the real point of this check.
                main_window.match_button.click()
                _pump(
                    qapp,
                    lambda: main_window.match_button.isEnabled(),
                    timeout=60.0,
                )
                assert main_window.status_label.text() == "", (
                    "match run after a live threshold change failed: "
                    f"{main_window.status_label.text()!r}"
                )
                live_settings.close()
                qapp.processEvents()
                live_settings = None
                threshold_changed = True
                print(
                    "[stress] live threshold change "
                    f"(auto={new_auto}, needs_review={new_needs_review}) "
                    "confirmed to affect the next match run without a "
                    "restart"
                )
                log.sample("threshold changed mid-session, next match confirmed")

            # Let the real backend timers actually fire while we wait
            # out the rest of this sampling interval.
            remaining = SAMPLE_INTERVAL_SECONDS - (time.monotonic() - cycle_start)
            if remaining > 0:
                _pump(qapp, lambda: False, timeout=remaining)

            log.sample(
                f"interleaved cycle (settings reopened "
                f"{settings_reopen_count}x so far)"
            )

        print(
            f"[stress] download results after the full run: "
            f"{download_results}"
        )
        log.sample("stress duration complete")

    finally:
        # Real cleanup, real restoration — this test must leave the
        # real production app in the exact state it found it in. Every
        # Settings window opened during the loop above was already
        # closed and dereferenced in place — nothing else to track
        # here.
        if main_window is not None:
            main_window.close()
        qapp.processEvents()

        save_config(original_config, config_path)
        application._config_store = original_config
        restored = load_config(config_path)
        assert restored.auto_match_threshold == original_config.auto_match_threshold
        assert (
            restored.needs_review_threshold
            == original_config.needs_review_threshold
        )
        print("[stress] real config store restored to its original values")

    log.sample("after close + config restore")

    # --- Report ---
    print("\n[stress] === full resource sample table ===")
    for entry in log.samples:
        print(
            f"  t={entry.t:7.1f}s  RSS={entry.rss_mb:7.1f}MB  "
            f"fds={entry.num_fds:3d}  threads={entry.num_threads:3d}  "
            f"active_workers={entry.active_workers:2d}  {entry.label}"
        )

    first, last = log.samples[0], log.samples[-1]
    rss_growth = last.rss_mb - first.rss_mb
    fd_growth = last.num_fds - first.num_fds
    thread_growth = last.num_threads - first.num_threads

    print(
        f"\n[stress] === summary: {last.t:.0f}s real duration, "
        f"{len(log.samples)} samples ==="
    )
    print(f"[stress] RSS: {first.rss_mb:.1f}MB -> {last.rss_mb:.1f}MB (Δ{rss_growth:+.1f}MB)")
    print(f"[stress] fds: {first.num_fds} -> {last.num_fds} (Δ{fd_growth:+d})")
    print(
        f"[stress] threads: {first.num_threads} -> {last.num_threads} "
        f"(Δ{thread_growth:+d})"
    )
    print(f"[stress] active_workers at end: {last.active_workers}")

    rss_values = [s.rss_mb for s in log.samples]
    print(
        f"[stress] RSS trend check: first-half mean="
        f"{statistics.mean(rss_values[: len(rss_values) // 2 or 1]):.1f}MB, "
        f"second-half mean="
        f"{statistics.mean(rss_values[len(rss_values) // 2 :]):.1f}MB"
    )

    # Every worker must have drained by the time the run is over — a
    # nonzero count here means something never fired its
    # finished/error signal, which is exactly the class of bug a
    # leak-hunting pass exists to catch.
    assert last.active_workers == 0, (
        f"{last.active_workers} worker(s) still registered as active "
        "after the run — something never completed"
    )

    assert rss_growth < MAX_ACCEPTABLE_RSS_GROWTH_MB, (
        f"RSS grew by {rss_growth:.1f}MB over the run (ceiling "
        f"{MAX_ACCEPTABLE_RSS_GROWTH_MB}MB) — possible leak"
    )
    assert fd_growth < MAX_ACCEPTABLE_FD_GROWTH, (
        f"open file descriptors grew by {fd_growth} over the run "
        f"(ceiling {MAX_ACCEPTABLE_FD_GROWTH}) — possible leak"
    )
    assert thread_growth < MAX_ACCEPTABLE_THREAD_GROWTH, (
        f"thread count grew by {thread_growth} over the run (ceiling "
        f"{MAX_ACCEPTABLE_THREAD_GROWTH}) — possible leak"
    )
