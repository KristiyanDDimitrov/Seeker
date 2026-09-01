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

**Duplicates tab (roadmap items 5/40) added to the mix (2026-08-30).**
This test predates the whole duplicate detector — it never exercised
fingerprinting/clustering/delete worker traffic running concurrently
with Sync/Scan/Match/Download. Deliberately scoped to a small,
disposable library location with two synthetic, byte-identical WAV
files (`_create_stress_duplicate_location`/`_cleanup_stress_duplicate_
location` below), never the real X9 Pro library: `find_duplicate_
groups()` recomputes an entire location's clustering from scratch on
every call and is documented (CLAUDE.md item 39) to take ~10 real
minutes over the real ~3,100-file production library — running that
inside this test's ~5-minute default duration, or deleting a real file
from the user's real library as part of an automated test, would defeat
the point of a fast, safe, repeatable regression guard. The scratch
location and its files are registered/scanned/fingerprinted/clustered/
resolved (a real Delete click, real confirm checkbox, real worker path)
through the exact same code every real user's Duplicates tab goes
through — only the input data is disposable, not the mechanism.
"""

import os
import shutil
import statistics
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import psutil
import pytest
import soundfile as sf
from PySide6.QtWidgets import QCheckBox, QPushButton

from seeker.application import Application
from seeker.audio_fingerprint import is_available as fingerprinting_is_available
from seeker.config_store import load_config, resolve_config_path, save_config
from seeker.library.duplicate_service import DuplicateGroup
from seeker.ui.main_window import MainWindow
from seeker.ui.workers import _callbacks

X9_PRO_ROOT = Path("/Volumes/X9 Pro")

# A fixed, recognizable name rather than something timestamped — makes a
# leftover from a crashed prior run trivially discoverable and lets
# _create_stress_duplicate_location clean one up defensively before
# registering its own, rather than accumulating "SeekerStressTest..."
# locations in the real production DB run after run.
STRESS_DUPLICATES_LOCATION_NAME = "SeekerStressTestDuplicates"

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
#
# Raised from 250.0 (roadmap item 56 Phase 3, re-verified 2026-09-01
# against this branch's Settings-page conversion): two real, consecutive
# runs measured 263.2MB/266.3MB total growth, both real re-runs from a
# genuinely clean baseline, not one-off noise. Investigated properly
# before touching this number, not just relaxed to make the failure go
# away — the full per-sample table showed WHY: the interleaved loop's
# RSS climbed from 480MB (t=15.5s) to ~527MB and then genuinely
# PLATEAUED for the run's entire last ~120s (9 consecutive samples, all
# within a 2MB band) — the exact "not a leak" shape this comment already
# described, not the "monotonic, unbounded climb" this ceiling exists to
# catch. Root cause of the real, legitimate increase: §3.3's settings-
# exit invalidation (_refresh_duplicates_locations()/_poll_next_step())
# now fires two extra real run_worker round-trips per Settings
# navigation cycle, work this test's interleaved loop didn't exercise at
# this frequency before Settings became a persistent page. See the new
# tail-plateau assertion below for the check that actually targets the
# leak signature this ceiling alone couldn't distinguish from legitimate
# extra steady-state work.
MAX_ACCEPTABLE_RSS_GROWTH_MB = 300.0
MAX_ACCEPTABLE_FD_GROWTH = 40
MAX_ACCEPTABLE_THREAD_GROWTH = 40
# A genuine leak keeps climbing even in the run's own tail; legitimate
# one-time warm-up cost (allocator arenas reaching a working-set size,
# Qt object pools stabilizing) does not. Checked over the last quarter
# of samples (>= 3) — tight enough to catch real continued growth,
# generous enough to absorb ordinary sample-to-sample jitter.
MAX_ACCEPTABLE_TAIL_RSS_RANGE_MB = 20.0


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


def _select_duplicates_location(main_window: MainWindow, name: str) -> bool:
    combo = main_window.duplicates_location_combo
    for index in range(combo.count()):
        if combo.itemText(index) == name:
            combo.setCurrentIndex(index)
            return True
    return False


def _create_stress_duplicate_location(application: Application) -> Path:
    """Registers a small, disposable library location with two
    byte-identical synthetic WAV files — real audio, decoded and
    fingerprinted through the real libchromaprint binding, but not a
    single byte of the real production library. Returns the scratch
    directory; the caller is responsible for calling
    _cleanup_stress_duplicate_location in a finally block regardless of
    how the test exits.
    """
    scratch_dir = Path(
        tempfile.mkdtemp(prefix="seeker_stress_duplicates_")
    )

    sample_rate = 44100
    duration_seconds = 3
    t = np.linspace(
        0, duration_seconds, sample_rate * duration_seconds, endpoint=False,
    )
    tone = (0.2 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)

    sf.write(str(scratch_dir / "track_a.wav"), tone, sample_rate)
    sf.write(str(scratch_dir / "track_a_copy.wav"), tone, sample_rate)

    try:
        # Best-effort cleanup of a same-named location left behind by a
        # crashed prior run — remove_location() is a silent no-op if
        # none exists (see LibraryService.remove_location).
        application.library_service.remove_location(
            STRESS_DUPLICATES_LOCATION_NAME
        )

        location = application.library_service.add_location(
            STRESS_DUPLICATES_LOCATION_NAME, str(scratch_dir),
        )
        # Scoped to just this one location (LibraryScanner.scan), not
        # LibraryService.scan_all() — scanning the real, huge X9 Pro
        # location synchronously here, before the real overlapping
        # sync/scan/match click flurry even starts, would both block
        # test setup for real minutes and duplicate work the test's own
        # Scan button click already does for every registered location,
        # including this one.
        application.library_service.scanner.scan(location)
    except Exception:
        shutil.rmtree(scratch_dir, ignore_errors=True)
        raise

    return scratch_dir


def _cleanup_stress_duplicate_location(
        application: Application, scratch_dir: Path,
) -> None:
    try:
        application.library_service.remove_location(
            STRESS_DUPLICATES_LOCATION_NAME
        )
    except Exception as error:
        print(
            f"[stress] failed to remove stress duplicates location from "
            f"the real DB: {error}"
        )
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


@requires_stress_opt_in
def test_broad_end_to_end_stress(qapp):
    if not X9_PRO_ROOT.is_dir():
        pytest.skip("x9-pro drive not mounted")

    application = Application()

    if not application.spotify_configured:
        pytest.skip("Spotify not configured in this environment")
    if not application.soulseek_configured:
        pytest.skip("SoulSeek not configured in this environment")
    if not fingerprinting_is_available():
        pytest.skip("libchromaprint not available in this environment")

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
    duplicates_scratch_dir: Path | None = None

    try:
        duplicates_scratch_dir = _create_stress_duplicate_location(application)
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

        # --- Duplicates page: switch to it for real (the same real
        # QStackedWidget.currentChanged path a user clicking the sidebar
        # nav item takes, including the lazy-load fix from CLAUDE.md's
        # Known Issues entry) and fire Compute fingerprints on the
        # disposable scratch location right alongside the sync/scan/
        # match flurry above — genuine overlapping worker/QThreadPool
        # traffic, not run sequentially after everything else settles.
        main_window._show_page("duplicates")
        _pump(
            qapp,
            lambda: _select_duplicates_location(
                main_window, STRESS_DUPLICATES_LOCATION_NAME,
            ),
            timeout=15.0,
        )
        main_window.compute_fingerprints_button.click()
        log.sample("sync/scan/match + duplicates fingerprinting fired overlapping")

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

        # Compute fingerprints on 2 tiny synthetic WAVs finishes in well
        # under a second in practice, but wait for real rather than
        # assume it — then fire Find duplicates so ITS clustering work
        # genuinely overlaps with the concurrent downloads fired next,
        # not just with sync/scan/match above.
        fingerprints_done = _pump(
            qapp,
            lambda: main_window.compute_fingerprints_button.isEnabled(),
            timeout=30.0,
        )
        print(
            f"[stress] duplicates fingerprinting settled: "
            f"{fingerprints_done}, status="
            f"{main_window.duplicates_status_label.text()!r}"
        )
        main_window.find_duplicates_button.click()
        log.sample("duplicates: find fired, overlapping with downloads next")

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
        duplicates_delete_done = False
        settings_reopen_count = 0
        deadline = log.start + duration

        while time.monotonic() < deadline:
            cycle_start = time.monotonic()

            # Switch playlists while background work (downloads,
            # backend poll) may still be running.
            for name in ("Test", "240KM/H"):
                if _select_playlist(main_window, name):
                    _pump(qapp, lambda: True, timeout=0.5)

            # Navigate to and away from the Settings PAGE repeatedly —
            # roadmap item 56 Phase 3 turned Settings from a separate,
            # per-open QMainWindow (the original real leak this section
            # was built to catch, item 32) into a single, persistent
            # page hosted in main_window's own QStackedWidget. The real
            # risk this section now needs to catch is different:
            # main_window.settings_page is never reconstructed, so
            # there's no per-cycle window-lifecycle leak left in THIS
            # path any more — but repeated _show_page() navigation while
            # other background work (downloads, backend poll) is still
            # in flight is itself a real, not-yet-exercised interaction,
            # and settings-exit now fires real background work of its
            # own (_invalidate_after_leaving_settings, §3.3).
            main_window._show_page("settings")
            _pump(
                qapp,
                lambda: main_window.settings_page
                .locations_table.rowCount() >= 0,
                timeout=5.0,
            )
            main_window._show_page("dashboard")
            qapp.processEvents()
            settings_reopen_count += 1

            # Sharing page (roadmap item 62, Phase 7) — real, live
            # get_status/is_self_managed/get_reconciliation/get_uploads
            # calls against the real production slskd, overlapping with
            # every other real worker traffic this loop already fires.
            # Deliberately READ-ONLY: unlike Duplicates' delete action
            # (exercised against a disposable synthetic scratch
            # location above), Sharing's write path
            # (add_location_to_share) recreates the real production
            # slskd container and rewrites real docker-compose.yml/
            # slskd.yml — there's no disposable analog for that, so it
            # stays unexercised here rather than silently mutating real
            # infrastructure as a side effect of an automated test.
            main_window._show_page("sharing")
            _pump(
                qapp,
                lambda: bool(main_window.sharing_summary_label.text()),
                timeout=15.0,
            )
            main_window._show_page("dashboard")
            qapp.processEvents()

            # Duplicates delete lifecycle (item 40) — the deferred-
            # delete action this stress test never exercised before.
            # Waits (across cycles, up to SAMPLE_INTERVAL_SECONDS each)
            # for the Find duplicates click fired above to land, then
            # runs the real double-confirm flow (checkbox + button) a
            # real user takes, through the real run_worker path, while
            # downloads/backend-poll traffic from the sections above may
            # still be in flight.
            if not duplicates_delete_done and main_window._current_duplicate_groups:
                group: DuplicateGroup = main_window._current_duplicate_groups[0]
                # Column 7 ("Actions") — the table gained a "Keep" radio
                # column (index 6) in roadmap item 56 Phase 6.3, pushing
                # Actions from 6 to 7; this stress test (opt-in, so it
                # wasn't caught by that phase's own test-suite sweep)
                # still referenced the pre-Phase-6.3 index.
                actions = main_window.duplicates_table.cellWidget(0, 7)
                assert actions is not None
                checkbox = actions.findChildren(QCheckBox)[0]
                delete_button = actions.findChildren(QPushButton)[0]
                checkbox.setChecked(True)
                delete_button.click()

                deleted = _pump(
                    qapp,
                    lambda: group not in main_window._current_duplicate_groups,
                    timeout=30.0,
                )
                print(
                    f"[stress] duplicates: group delete completed="
                    f"{deleted}, status="
                    f"{main_window.duplicates_status_label.text()!r}"
                )
                duplicates_delete_done = True
                log.sample("duplicates: group delete lifecycle exercised")

            # Mid-session threshold change, real Settings widgets, real
            # save button — confirmed to affect the NEXT match run
            # without any restart, exercising the already-constructed
            # real track_matcher live (see CLAUDE.md item 28 §4).
            if not threshold_changed:
                # Real Settings widgets, real save button, on the SAME
                # persistent main_window.settings_page — no separate
                # window to construct/close any more (item 56 Phase 3).
                live_settings = main_window.settings_page
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
        print(
            f"[stress] duplicates delete lifecycle exercised: "
            f"{duplicates_delete_done}"
        )
        print(
            f"[stress] sharing page summary after final visit: "
            f"{main_window.sharing_summary_label.text()!r}"
        )
        log.sample("stress duration complete")

    finally:
        # Give any still-genuinely-in-flight worker (a real slskd HTTP
        # round trip from the 20s backend-poll timer, up to ~15s each,
        # possibly several in sequence for poll_downloads()' locked/
        # queued/downloading rows) a real chance to finish before
        # closing the window and asserting active_workers == 0 below.
        # Found live (CLAUDE.md item 41): without this wait, a
        # backend-poll worker that started near the interleaved loop's
        # own deadline could still be waiting on a real slskd response
        # (in one real run, a 500 from slskd's own batches endpoint)
        # when main_window.close() ran — not a leak, just this test's
        # own fixed-duration loop not giving real, legitimately slow
        # network I/O enough time to land before checking. A worker
        # that genuinely never completes still fails the assertion
        # below after this bounded wait — this only removes false
        # failures from normal real-world network latency.
        drained = _pump(qapp, lambda: len(_callbacks) == 0, timeout=60.0)
        print(
            f"[stress] outstanding workers drained before close: "
            f"{drained} (active_workers={len(_callbacks)})"
        )

        # Real cleanup, real restoration — this test must leave the
        # real production app in the exact state it found it in. Every
        # Settings window opened during the loop above was already
        # closed and dereferenced in place — nothing else to track
        # here.
        if main_window is not None:
            main_window.close()
        qapp.processEvents()

        if duplicates_scratch_dir is not None:
            _cleanup_stress_duplicate_location(application, duplicates_scratch_dir)
            print("[stress] disposable duplicates location + scratch files removed")

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

    tail_size = max(len(rss_values) // 4, 3)
    tail_values = rss_values[-tail_size:]
    tail_range = max(tail_values) - min(tail_values)
    print(
        f"[stress] RSS tail plateau check: last {tail_size} samples "
        f"range={tail_range:.1f}MB (min={min(tail_values):.1f}MB, "
        f"max={max(tail_values):.1f}MB)"
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
    # The actual leak signature this whole test hunts for: a genuine
    # leak keeps climbing all the way to the end, even after any
    # legitimate one-time warm-up cost has already happened earlier in
    # the run. A flat tail is real evidence of "grew once, then
    # stabilized" — the raw total-growth ceiling above can't tell that
    # apart from "still climbing," but this can.
    assert tail_range < MAX_ACCEPTABLE_TAIL_RSS_RANGE_MB, (
        f"RSS was still moving by {tail_range:.1f}MB across the run's "
        f"last {tail_size} samples (ceiling "
        f"{MAX_ACCEPTABLE_TAIL_RSS_RANGE_MB}MB) — real evidence of "
        "continued growth, not just a one-time warm-up cost"
    )
    assert fd_growth < MAX_ACCEPTABLE_FD_GROWTH, (
        f"open file descriptors grew by {fd_growth} over the run "
        f"(ceiling {MAX_ACCEPTABLE_FD_GROWTH}) — possible leak"
    )
    assert thread_growth < MAX_ACCEPTABLE_THREAD_GROWTH, (
        f"thread count grew by {thread_growth} over the run (ceiling "
        f"{MAX_ACCEPTABLE_THREAD_GROWTH}) — possible leak"
    )
