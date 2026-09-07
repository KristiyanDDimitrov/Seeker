"""Standalone repro script for the real stress-test hang found live on
2026-09-02 while closing out roadmap items 68-69 (Duplicates folder
scoping + progress, fingerprint fallback): a real `SEEKER_RUN_STRESS_
TEST=1` run of `tests/test_stress_e2e.py` hung for 1h37m+ at essentially
0% CPU immediately after firing sync/scan/match + Compute Fingerprints
concurrently and waiting for them to settle — the exact scenario this
script isolates. Not a test module itself (leading underscore, matching
tests/_workers_*_repro.py and tests/_stress_step3/4_*_repro.py's own
convention).

Isolated from production: monkeypatches platformdirs so Application()
resolves to a fresh throwaway data dir (same pattern as
_stress_step3_no_locked_repro.py), never touches the real production DB.
A fake cached Spotify token avoids a real OAuth popup (same reason as
step3's own repro) — the resulting Spotify sync will fail fast with a
real, harmless 401 in a background worker, which is fine: what this
script needs is the CONCURRENT WORKER TRAFFIC, not real playlist data.

Bounded via `faulthandler.dump_traceback` fired from a background
`threading.Timer` if the main pump loop hasn't finished within
HANG_TIMEOUT_SECONDS — dumps every thread's real Python stack to stderr
so a genuine hang produces a definitive trace instead of another silent
1.5-hour wait.
"""
import faulthandler
import json
import os
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HANG_TIMEOUT_SECONDS = 150.0

import tempfile  # noqa: E402

_THROWAWAY_DIR = Path(tempfile.mkdtemp(prefix="seeker_hang_repro_"))

import platformdirs  # noqa: E402


def _fake_user_data_dir(appname: str, **kwargs: object) -> str:
    return str(_THROWAWAY_DIR)


platformdirs.user_data_dir = _fake_user_data_dir  # type: ignore[assignment]

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from seeker.application import Application  # noqa: E402
from seeker.models.library_location import LibraryLocation  # noqa: E402

LOCATION_NAME = "HangReproLocation"
SCALE_LOCATION_NAME = "HangReproScaleLocation"
# Roadmap item 68/69 hang investigation — the real stress-test run that
# hung had a REAL library scan (thousands of files) and a REAL Spotify
# sync running concurrently with compute_fingerprints' tiny 2-file
# worker; this script's first pass (2-file scan, fake-token sync that
# fails fast) completed cleanly, unlike the real run. Symlinking a real
# sample of the real X9 Pro library into a second, separate throwaway
# location gives scan/match a much more realistic real duration to
# overlap with, without touching the real production DB or copying
# multiple GB of real audio.
X9_PRO_ROOT = Path("/Volumes/X9 Pro")
SAMPLE_PATHS_FILE = Path(
    "/private/tmp/claude-501/-Users-sinthesis-PycharmProjects-Seeker/"
    "fa32cc6e-0861-4be6-a0e7-545e4a5eabd6/scratchpad/sample_paths.txt"
)


def _seed_fake_spotify_token() -> None:
    token_path = _THROWAWAY_DIR / "spotify_token.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "fake-hang-repro-token",
                "refresh_token": "fake-hang-repro-refresh",
                "expires_at": time.time() + 3600,
            }
        )
    )


def _write_tone(
        path: Path,
        frequency: float,
        duration_seconds: float = 2.0,
) -> None:
    sample_rate = 44_100
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds))
    samples = (np.sin(2 * np.pi * frequency * t) * 0.3).astype(np.float32)
    sf.write(str(path), samples, sample_rate)


def _seed_location(application: Application) -> None:
    music_dir = _THROWAWAY_DIR / "music"
    music_dir.mkdir(parents=True, exist_ok=True)
    _write_tone(music_dir / "a.wav", 440.0)
    _write_tone(
            music_dir / "b.wav",
            440.0,
    )  # a real duplicate pair, same as the stress test

    from datetime import datetime, timezone

    with application.database.transaction() as connection:
        application.library_service.locations.add(
            LibraryLocation(
                id=None, name=LOCATION_NAME, path=str(music_dir),
                added_at=datetime.now(timezone.utc).isoformat(),
            ),
            connection,
        )


def _seed_scale_location(application: Application) -> int:
    if not X9_PRO_ROOT.is_dir() or not SAMPLE_PATHS_FILE.is_file():
        print(
            "[hang-repro] no real X9 Pro sample available -- skipping "
            "the scale location, scan/match will be near-instant",
            flush=True,
        )
        return 0

    scale_dir = _THROWAWAY_DIR / "scale"
    scale_dir.mkdir(parents=True, exist_ok=True)

    relative_paths = [
        line.strip() for line in SAMPLE_PATHS_FILE.read_text().splitlines()
        if line.strip()
    ]

    count = 0
    for index, relative_path in enumerate(relative_paths):
        real_path = X9_PRO_ROOT / relative_path
        if not real_path.is_file():
            continue
        link_path = scale_dir / f"{index}{real_path.suffix}"
        try:
            link_path.symlink_to(real_path)
            count += 1
        except OSError:
            continue

    from datetime import datetime, timezone

    with application.database.transaction() as connection:
        application.library_service.locations.add(
            LibraryLocation(
                id=None, name=SCALE_LOCATION_NAME, path=str(scale_dir),
                added_at=datetime.now(timezone.utc).isoformat(),
            ),
            connection,
        )

    print(
            f"[hang-repro] scale location: {count} real files symlinked",
            flush=True,
    )
    return count


def _dump_and_exit() -> None:
    print(
        f"\n[hang-repro] HANG DETECTED after {HANG_TIMEOUT_SECONDS}s — "
        f"dumping all thread stacks:\n",
        file=sys.stderr, flush=True,
    )
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
    sys.stderr.flush()
    os._exit(
            1
    )  # hard exit -- don't wait on anything else that might also be stuck


def main() -> None:
    watchdog = threading.Timer(HANG_TIMEOUT_SECONDS, _dump_and_exit)
    watchdog.daemon = True
    watchdog.start()

    qapp = QApplication.instance() or QApplication([])

    _seed_fake_spotify_token()

    application = Application()
    print(f"[hang-repro] throwaway data dir: {_THROWAWAY_DIR}", flush=True)

    _seed_location(application)
    _seed_scale_location(application)

    from seeker.ui.main_window import MainWindow

    main_window = MainWindow(application)
    print("[hang-repro] MainWindow constructed", flush=True)

    qapp.processEvents()

    def _select_location(name: str) -> bool:
        combo = main_window.duplicates_location_combo
        for index in range(combo.count()):
            if combo.itemText(index) == name:
                combo.setCurrentIndex(index)
                return True
        return False

    def _pump(predicate, timeout: float, interval: float = 0.1) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            qapp.processEvents()
            if predicate():
                return True
            time.sleep(interval)
        qapp.processEvents()
        return predicate()

    # Exact same overlapping pattern as test_stress_e2e.py: sync/scan/
    # match fired back to back, THEN immediately (not waiting) show the
    # Duplicates page and fire Compute Fingerprints.
    print("[hang-repro] firing sync/scan/match...", flush=True)
    main_window.sync_button.click()
    main_window.scan_button.click()
    main_window.match_button.click()

    main_window._show_page("duplicates")
    _pump(lambda: _select_location(LOCATION_NAME), timeout=15.0)
    print("[hang-repro] firing compute_fingerprints...", flush=True)
    main_window.compute_fingerprints_button.click()
    print(
        "[hang-repro] all four fired, waiting for sync/scan/match to "
        "settle...",
        flush=True,
    )

    settled = _pump(
        lambda: (
            main_window.sync_button.isEnabled()
            and main_window.scan_button.isEnabled()
            and main_window.match_button.isEnabled()
        ),
        timeout=90.0,
    )
    print(f"[hang-repro] sync/scan/match settled: {settled}", flush=True)

    fingerprints_done = _pump(
        lambda: main_window.compute_fingerprints_button.isEnabled(),
        timeout=30.0,
    )
    print(
        f"[hang-repro] fingerprinting settled: {fingerprints_done}, "
        f"status={main_window.duplicates_status_label.text()!r}",
        flush=True,
    )

    watchdog.cancel()
    print("[hang-repro] DONE — did not hang", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
