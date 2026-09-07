"""Standalone repro script for roadmap item 63, Step 3 (2026-09-02): does
over-frequent poll_downloads() cadence still happen with ZERO locked
rows in the table? Not a test module itself (leading underscore,
matching tests/_workers_*_repro.py's convention) — run directly as a
subprocess, watched live.

Isolated from production: monkeypatches platformdirs so Application()
resolves to a fresh throwaway data dir (same pattern as
test_application.py's _fake_user_data_dir), so this never touches the
real production DB or config.json. Seeds the throwaway DB with REAL
track data copied from Kris's real "Under Pressure (Deluxe)" playlist
(15 real Logic tracks, synced via `seeker sync-tracks` earlier in this
investigation) so download_playlist() searches real, plausible titles
against real local slskd — just via a disposable destination location,
never the real X9 Pro library.

Zero locked rows by construction: nothing pre-seeds download_requests
at all. Whatever poll_downloads() finds is only what a single real
download_playlist() call itself produces.
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DURATION_SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 300.0
TRACKS_JSON = Path(sys.argv[2]) if len(sys.argv) > 2 else None

import tempfile

_THROWAWAY_DIR = Path(tempfile.mkdtemp(prefix="seeker_step3_repro_"))

import platformdirs


def _fake_user_data_dir(appname: str, **kwargs: object) -> str:
    return str(_THROWAWAY_DIR)


platformdirs.user_data_dir = _fake_user_data_dir  # type: ignore[assignment]

from datetime import UTC

from PySide6.QtWidgets import QApplication

from seeker.application import Application
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.models.track import Track
from seeker.ui.main_window import MainWindow

PLAYLIST_ID = "step3-under-pressure-repro"
PLAYLIST_NAME = "Under Pressure (Deluxe)"


def _seed(application: Application, tracks_path: Path) -> None:
    tracks_data = json.loads(tracks_path.read_text())

    location_dir = _THROWAWAY_DIR / "destination"
    location_dir.mkdir(parents=True, exist_ok=True)

    with application.database.transaction() as connection:
        application.download_service.playlists.save(
            Playlist(
                id=PLAYLIST_ID,
                name=PLAYLIST_NAME,
                track_count=len(tracks_data),
            ),
            connection,
        )

        for row in tracks_data:
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
            PLAYLIST_ID,
            [row["id"] for row in tracks_data],
            connection,
        )

        from datetime import datetime

        application.download_service.locations.add(
            LibraryLocation(
                id=None,
                name="Step3ReproDestination",
                path=str(location_dir),
                added_at=datetime.now(UTC).isoformat(),
            ),
            connection,
        )

    application.download_service.set_destination(
        PLAYLIST_NAME, "Step3ReproDestination",
    )


def _seed_fake_spotify_token() -> None:
    # MainWindow._load_playlists() eagerly evaluates
    # application.sync_service on construction, which eagerly evaluates
    # application.spotify, which calls auth_manager.get_valid_token() —
    # with no cached token in this throwaway data dir, that opens a
    # REAL Spotify OAuth browser tab (confirmed live, 2026-09-02: it
    # did exactly this on the first run of this script). A
    # non-expired-looking fake token file short-circuits
    # get_valid_token() to just return it directly — no network call,
    # no browser. The one real consequence is list_playlists() later
    # failing its Spotify API call in a background worker thread with
    # this fake access_token (a harmless, caught 401 surfaced via
    # status_label, not a crash) — acceptable since this repro never
    # needs real playlist data anyway.
    token_path = _THROWAWAY_DIR / "spotify_token.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "fake-step3-repro-token",
                "refresh_token": "fake-step3-repro-refresh",
                "expires_at": time.time() + 3600,
            }
        )
    )


def main() -> None:
    assert TRACKS_JSON is not None, (
        "usage: _stress_step3_no_locked_repro.py <duration_s> <tracks.json>"
    )

    qapp = QApplication.instance() or QApplication([])

    _seed_fake_spotify_token()

    application = Application()
    print(f"[step3] throwaway data dir: {_THROWAWAY_DIR}", flush=True)

    _seed(application, TRACKS_JSON)

    with application.database.transaction() as connection:
        locked_before = (
            application.download_service.download_requests.get_locked(
                connection,
            )
        )
    print(
        f"[step3] locked rows before download_playlist(): "
        f"{len(locked_before)}",
        flush=True,
    )

    result = application.download_service.download_playlist(PLAYLIST_NAME)
    print(f"[step3] download_playlist() result: {result}", flush=True)

    main_window = MainWindow(application)
    print("[step3] MainWindow constructed, pumping event loop", flush=True)

    deadline = time.monotonic() + DURATION_SECONDS
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.05)

    print("[step3] duration complete, closing", flush=True)
    main_window.close()
    qapp.processEvents()
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
