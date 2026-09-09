# Regenerates the README screenshots. Real widget rendering (offscreen
# Qt, no display needed) against invented data via FakeApplication —
# the same test double tests/test_ui_smoke.py uses — so there's no real
# playlist name, library path or SoulSeek username in these images, and
# anyone can reproduce them: `uv run python docs/screenshots/generate.py`.
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent

app = QApplication.instance() or QApplication([])

from seeker.ui import theme

from test_ui_smoke import FakeApplication  # noqa: E402
from seeker.models.playlist import Playlist  # noqa: E402
from seeker.models.track import Track  # noqa: E402
from seeker.models.library_location import LibraryLocation  # noqa: E402
from seeker.models.local_file import LocalFile  # noqa: E402
from seeker.models.soulseek_review_candidate import (  # noqa: E402
    SoulseekReviewCandidate,
)
from seeker.models.track_status import (  # noqa: E402
    TrackStatus, IN_LIBRARY, DOWNLOADING, NEEDS_REVIEW, NOT_FOUND,
)
from seeker.library.duplicate_service import (  # noqa: E402
    DuplicateFile, DuplicateGroup,
)
from seeker.soulseek.quality import LocalFileQuality  # noqa: E402


def pump(seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.02)


def make_track(i: int, artist: str, title: str) -> Track:
    return Track(
        id=f"track{i}", title=title, artist=artist,
        album=f"Album {i}", duration_ms=200000 + i * 1000,
        album_art_url=None,
    )


def make_local_file(i: int, filename: str, size_mb: float) -> LocalFile:
    return LocalFile(
        location_id=1, relative_path=filename, filename=filename,
        format=filename.rsplit(".", 1)[-1],
        size_bytes=int(size_mb * 1_000_000),
        mtime=1_700_000_000.0 + i, scanned_at="2026-08-01T00:00:00",
        id=i, tag_artist="Nova Reyes", tag_title="Voltage Drop",
        tag_album="Album 1", duration_ms=214000,
    )


playlists = [
    Playlist(id="p1", name="Peak Time Techno", track_count=4),
    Playlist(id="p2", name="Deep House Essentials", track_count=3),
    Playlist(id="p3", name="Warehouse Anthems", track_count=2),
]

statuses = [
    TrackStatus(
        track=make_track(1, "Nova Reyes", "Voltage Drop"), state=IN_LIBRARY,
    ),
    TrackStatus(
        track=make_track(2, "Kessler & Vane", "Concrete Bloom"),
        state=DOWNLOADING,
    ),
    TrackStatus(
        track=make_track(3, "Ilse Marchetti", "Afterimage"),
        state=NEEDS_REVIEW,
    ),
    TrackStatus(
        track=make_track(
            4, "Rutger Solheim", "Static Bloom (Original Mix)",
        ),
        state=NOT_FOUND,
    ),
]

review_candidates = [
    (
        make_track(5, "Odile Kessler", "Undertow (Club Mix)"),
        SoulseekReviewCandidate(
            track_id="track5", username="demo_peer_1",
            filename="Odile Kessler - Undertow (Club Mix).flac",
            score=0.91, quality_descriptor="FLAC, 1050kbps",
            found_at="2026-09-01T12:00:00", size=42_000_000,
            # Round 8 §12.10 — a real runner-up shown inline.
            runner_up_username="demo_peer_2",
            runner_up_filename="Odile Kessler - Undertow (Radio Edit).mp3",
            runner_up_score=0.76,
        ),
    ),
]

locations = [
    (
        LibraryLocation(
            id=1, name="Music", path="/Users/demo/Music",
            added_at="2026-01-01T00:00:00",
        ),
        True,
    ),
]

duplicate_groups = [
    DuplicateGroup(
        files=[
            DuplicateFile(
                local_file=make_local_file(
                    1, "Nova Reyes - Voltage Drop.flac", 38.2,
                ),
                quality=LocalFileQuality(
                    tier=0, bitrate_kbps=None, bit_depth=16,
                    sample_rate=44100, clipping_ratio=0.0,
                    integrated_loudness_lufs=-9.4,
                ),
            ),
            DuplicateFile(
                local_file=make_local_file(
                    2, "Nova Reyes - Voltage Drop (1).mp3", 8.1,
                ),
                quality=LocalFileQuality(
                    tier=2, bitrate_kbps=192, bit_depth=None,
                    sample_rate=44100, clipping_ratio=0.02,
                    integrated_loudness_lufs=-8.1,
                ),
            ),
        ],
        similarity=0.97,
    ),
]

application = FakeApplication(
    playlists=playlists, statuses=statuses, locations=locations,
    review_candidates=review_candidates, duplicate_groups=duplicate_groups,
)

from seeker.ui.main_window import MainWindow  # noqa: E402

out_dir = os.path.dirname(os.path.abspath(__file__))

theme.apply_theme(app, "dark")
window = MainWindow(application)
window.resize(1280, 820)
window.show()
pump(1.5)
window._dashboard_page.playlist_list.setCurrentRow(0)
pump(1.0)
window.grab().save(os.path.join(out_dir, "dashboard-dark.png"))

window._show_page("library")
pump(1.0)
# Round 8 §12.7 — show the results panel with a real result rendered
# and expanded, not just its empty placeholder state.
window._library_page._tagging_panel._render_tag_result({
    "tagged": 3, "tagged_without_art": 0,
    "tagged_art_rarely_supported_format": 0, "skipped_no_match": 0,
    "skipped_format_unsupported": 0, "skipped_already_tagged": 0,
    "skipped_already_analyzed": 0, "failed": 1,
    "details": [
        {
            "track_id": "t9", "reason": "failed",
            "message": "Rutger Solheim - Static Bloom: disk read error",
        },
    ],
})
window._library_page._tagging_panel.results_panel.details_toggle.setChecked(True)
pump(0.5)
window.grab().save(os.path.join(out_dir, "library-dark.png"))

window._show_page("review")
pump(1.0)
window.grab().save(os.path.join(out_dir, "review.png"))

window._show_page("duplicates")
pump(1.0)
window._duplicates_page._render_duplicate_groups(duplicate_groups)
pump(0.5)
window.grab().save(os.path.join(out_dir, "duplicates.png"))

window._show_page("dashboard")
pump(0.5)
theme.apply_theme(app, "light")
pump(0.5)
window.grab().save(os.path.join(out_dir, "dashboard-light.png"))

print("Screenshots written to", out_dir)
