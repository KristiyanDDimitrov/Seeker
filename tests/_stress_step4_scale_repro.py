"""Standalone repro script for roadmap item 63, Step 4 (2026-09-02): do
the two remaining untested candidates from the original investigation —
real production DB SCALE (a large `pending`/`locked` backlog) and the
FULL concurrent-traffic combination (multiple simultaneous
download_playlist() calls + real fingerprinting + the poll timer, all
at once) — only reproduce the storm TOGETHER? Not a test module itself
(leading underscore, matching tests/_workers_*_repro.py and
tests/_stress_step3_no_locked_repro.py's convention).

Fully isolated from production (monkeypatched platformdirs, throwaway
data dir, fake cached Spotify token seeded up front — see Step 3's
HISTORY.md write-up for why that last part matters). DB scale is
synthetic: ~50 filler download_requests rows (mixed queued/downloading/
locked, not uniform — the original incident specifically involved
locked-row retries) against filler tracks never touched by any real
download flow. Concurrent traffic is real and uses the SAME mechanism
test_stress_e2e.py already proved out (run_worker/main_window.
thread_pool, real button clicks) rather than a different threading
model: 3 synthetic playlists built by splitting Kris's real 15-track
"Under Pressure (Deluxe)" list three ways, each downloaded via a real
download_playlist() call fired concurrently, plus real fingerprinting
via the same disposable scratch-WAV duplicate location
test_stress_e2e.py uses (imported directly, not duplicated).
"""
import json
import os
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DURATION_SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 300.0
TRACKS_JSON = Path(sys.argv[2]) if len(sys.argv) > 2 else None
FILLER_ROW_COUNT = int(sys.argv[3]) if len(sys.argv) > 3 else 50

import tempfile

_THROWAWAY_DIR = Path(tempfile.mkdtemp(prefix="seeker_step4_repro_"))

import platformdirs


def _fake_user_data_dir(appname: str, **kwargs: object) -> str:
    return str(_THROWAWAY_DIR)


platformdirs.user_data_dir = _fake_user_data_dir  # type: ignore[assignment]

from PySide6.QtWidgets import QApplication

from seeker.application import Application
from seeker.models.download_request import DownloadRequest
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.models.track import Track
from seeker.ui.main_window import MainWindow
from seeker.ui.workers import run_worker

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_stress_e2e import (
    STRESS_DUPLICATES_LOCATION_NAME,
    _cleanup_stress_duplicate_location,
    _create_stress_duplicate_location,
    _pump,
    _select_duplicates_location,
)

PLAYLIST_NAMES = [
    "Step4Repro-Split-A",
    "Step4Repro-Split-B",
    "Step4Repro-Split-C",
]


def _seed_fake_spotify_token() -> None:
    token_path = _THROWAWAY_DIR / "spotify_token.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "fake-step4-repro-token",
                "refresh_token": "fake-step4-repro-refresh",
                "expires_at": time.time() + 3600,
            }
        )
    )


def _seed_filler_backlog(application: Application, count: int) -> None:
    """~count synthetic download_requests rows, mixed status, against
    filler tracks no real download flow ever touches — simulates DB
    scale without needing count real Spotify tracks."""
    now = datetime.now(UTC).isoformat()

    with application.database.transaction() as connection:
        for i in range(count):
            track_id = f"step4-filler-track-{i}"
            application.download_service.tracks.save(
                Track(
                    id=track_id,
                    title=f"Filler Track {i}",
                    artist="Filler Artist",
                    album="Filler Album",
                    duration_ms=200_000,
                    album_art_url=None,
                ),
                connection,
            )

            # Not uniform: ~40% locked (the original incident's own
            # shape), ~60% queued/downloading pending.
            status = "locked" if i % 5 < 2 else random.choice(
                ["queued", "downloading"]
            )

            application.download_service.download_requests.add(
                DownloadRequest(
                    track_id=track_id,
                    username=f"step4-fake-peer-{i}",
                    filename=f"fake/path/filler-{i}.mp3",
                    format="mp3",
                    requested_at=now,
                    role="upgrade" if status == "locked" else "settled",
                    status=status,
                    transfer_id=f"step4-fake-transfer-{i}",
                    size=5_000_000,
                    rank=1,
                ),
                connection,
            )

    print(f"[step4] seeded {count} filler download_requests rows", flush=True)


def _seed_split_playlists(application: Application, tracks_path: Path) -> None:
    tracks_data = json.loads(tracks_path.read_text())
    thirds = [tracks_data[0::3], tracks_data[1::3], tracks_data[2::3]]

    with application.database.transaction() as connection:
        for name, rows in zip(PLAYLIST_NAMES, thirds):
            playlist_id = f"step4-{name}"

            application.download_service.playlists.save(
                Playlist(id=playlist_id, name=name, track_count=len(rows)),
                connection,
            )

            for row in rows:
                application.download_service.tracks.save(
                    Track(
                        id=row["id"],
                        title=row["title"],
                        artist=row["artist"],
                        album=row["album"],
                        duration_ms=row["duration_ms"],
                        album_art_url=row["album_art_url"],
                    ),
                    connection,
                )

            application.download_service.tracks.replace_playlist_tracks(
                playlist_id, [row["id"] for row in rows], connection,
            )

            location_dir = _THROWAWAY_DIR / f"destination-{name}"
            location_dir.mkdir(parents=True, exist_ok=True)

            application.download_service.locations.add(
                LibraryLocation(
                    id=None,
                    name=f"Step4Dest-{name}",
                    path=str(location_dir),
                    added_at=datetime.now(UTC).isoformat(),
                ),
                connection,
            )

    for name in PLAYLIST_NAMES:
        application.download_service.set_destination(name, f"Step4Dest-{name}")


def main() -> None:
    assert TRACKS_JSON is not None, (
        "usage: _stress_step4_scale_repro.py <duration_s> <tracks.json> "
        "[filler_row_count]"
    )

    qapp = QApplication.instance() or QApplication([])

    _seed_fake_spotify_token()

    application = Application()
    print(f"[step4] throwaway data dir: {_THROWAWAY_DIR}", flush=True)

    _seed_filler_backlog(application, FILLER_ROW_COUNT)
    _seed_split_playlists(application, TRACKS_JSON)

    scratch_dir = _create_stress_duplicate_location(application)
    print(
            f"[step4] duplicate scratch location ready: {scratch_dir}",
            flush=True,
    )

    main_window = MainWindow(application)
    print("[step4] MainWindow constructed", flush=True)

    try:
        # Real fingerprinting, via the real UI path — same mechanism
        # test_stress_e2e.py already proved out, not a direct
        # duplicate_service call.
        main_window._show_page("duplicates")
        _pump(
            qapp,
            lambda: _select_duplicates_location(
                main_window, STRESS_DUPLICATES_LOCATION_NAME,
            ),
            timeout=15.0,
        )
        main_window.compute_fingerprints_button.click()
        print("[step4] fingerprinting fired", flush=True)

        # 3 real concurrent download_playlist() calls, via the same
        # run_worker/QThreadPool mechanism the real UI uses — fired
        # while fingerprinting above is still in flight, matching
        # test_stress_e2e.py's own overlapping-traffic shape.
        results: dict[str, str] = {}

        def make_download_fn(name: str):  # type: ignore[no-untyped-def]
            def fn() -> None:
                application.download_service.download_playlist(name)

            return fn

        def make_on_finished(name: str):  # type: ignore[no-untyped-def]
            def on_finished(_: object) -> None:
                results[name] = "finished"

            return on_finished

        def make_on_error(name: str):  # type: ignore[no-untyped-def]
            def on_error(message: str) -> None:
                results[name] = f"error: {message}"

            return on_error

        for name in PLAYLIST_NAMES:
            run_worker(
                main_window.thread_pool,
                make_download_fn(name),
                on_finished=make_on_finished(name),
                on_error=make_on_error(name),
            )

        print(
            f"[step4] {len(PLAYLIST_NAMES)} concurrent download_playlist() "
            f"calls fired, pumping event loop",
            flush=True,
        )

        deadline = time.monotonic() + DURATION_SECONDS
        while time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.05)

        print(
                f"[step4] duration complete, download results: {results}",
                flush=True,
        )
        main_window.close()
        qapp.processEvents()
    finally:
        _cleanup_stress_duplicate_location(application, scratch_dir)

    print("DONE", flush=True)


if __name__ == "__main__":
    main()
