"""Renders every Seeker screen against one fixed, invented dataset.

    uv run python tools/screenshots.py              # all screens, both
                                                    # themes, two sizes
    uv run python tools/screenshots.py --page review --page settings
    uv run python tools/screenshots.py --readme     # the README images

The default run writes `<screen>-<theme>-<width>x<height>.png` into the
gitignored `tools/.screens/`, for reviewing the UI after a change.
`--readme` writes the committed images in `docs/screenshots/` instead.

Real widgets render offscreen (no display needed) over
`tests/fakes.py`'s `FakeApplication`, the double the UI tests use, so
no real playlist, library path or SoulSeek username reaches an image,
and nothing touches Seeker's database, config or slskd. Each screen is
reached the way a user reaches it: a sidebar click, a button press, a
tab. No private method is called.
"""
import argparse
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from PySide6.QtCore import QCoreApplication, QEvent, QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QPushButton,
    QWidget,
)

from fakes import (  # noqa: E402
    FakeApplication,
    FakeDownloadService,
    FakeDuplicateService,
    FakeMetadataService,
    FakeSharingService,
)
from seeker.audio.quality import LocalFileQuality  # noqa: E402
from seeker.library.duplicate_service import (  # noqa: E402
    DuplicateFile,
    DuplicateGroup,
)
from seeker.models.active_download import ActiveDownload  # noqa: E402
from seeker.models.download_request import (  # noqa: E402
    DownloadRequest,
    DownloadRole,
    DownloadStatus,
)
from seeker.models.history_event import (  # noqa: E402
    DOWNLOADED,
    TAGGED,
    HistoryEvent,
)
from seeker.models.library_location import LibraryLocation  # noqa: E402
from seeker.models.local_file import LocalFile  # noqa: E402
from seeker.models.needs_review_match import NeedsReviewMatch  # noqa: E402
from seeker.models.nested_location import NestedLocation  # noqa: E402
from seeker.models.playlist import Playlist  # noqa: E402
from seeker.models.soulseek_file import SoulseekFile  # noqa: E402
from seeker.models.soulseek_review_candidate import (  # noqa: E402
    SoulseekReviewCandidate,
)
from seeker.models.tag_result import TagResult  # noqa: E402
from seeker.models.track import Track  # noqa: E402
from seeker.models.track_status import (  # noqa: E402
    AWAITING_REVIEW,
    DOWNLOADING,
    IN_LIBRARY,
    NEEDS_REVIEW,
    NOT_FOUND,
    RETRYING,
    REVIEW_CANDIDATE,
    TrackStatus,
)
from seeker.models.upgrade_review import UpgradeReviewDetails  # noqa: E402
from seeker.soulseek.sharing_service import (  # noqa: E402
    LocationShareState,
    ShareEntry,
    ShareStatus,
    UploadStatus,
)
from seeker.ui import theme  # noqa: E402
from seeker.ui.main_window import MainWindow  # noqa: E402
from seeker.ui.pages.dashboard_page import DashboardPage  # noqa: E402
from seeker.ui.pages.duplicates_page import DuplicatesPage  # noqa: E402
from seeker.ui.pages.search_page import SearchPage  # noqa: E402
from seeker.ui.pages.tagging_panel import TaggingPanel  # noqa: E402
from seeker.ui.wizard import OnboardingWizard  # noqa: E402

SCREENS_DIR = REPO_ROOT / "tools" / ".screens"
README_DIR = REPO_ROOT / "docs" / "screenshots"
THEMES = ("dark", "light")
SIZES = ((1280, 820), (960, 640))

# --- The demo dataset -----------------------------------------------------

_FOUND_AT = "2026-09-01T12:00:00+00:00"


def _track(index: int, artist: str, title: str, album: str) -> Track:
    return Track(
        id=f"track{index}", title=title, artist=artist, album=album,
        duration_ms=180_000 + index * 7_000,
    )


TRACKS = [
    _track(1, "Nova Reyes", "Voltage Drop", "Night Shift"),
    _track(2, "Kessler & Vane", "Concrete Bloom", "Concrete Bloom EP"),
    _track(3, "Ilse Marchetti", "Afterimage", "Low Light"),
    _track(4, "Rutger Solheim", "Static Bloom (Original Mix)", "Static"),
    _track(5, "Odile Kessler", "Undertow (Club Mix)", "Undertow"),
    _track(6, "Mara Okafor", "Glasshouse", "Glasshouse"),
    _track(7, "Tomas Wren", "Signal Path", "Relay"),
    _track(8, "Ana Lindqvist", "Paper Moons (Extended)", "Paper Moons"),
    _track(9, "Juno Halvorsen", "Lowercase", "Lowercase"),
]


def _candidate(
        track: Track,
        score: float,
        quality: str,
        size_mb: int,
        runner_up_score: float | None = None,
) -> SoulseekReviewCandidate:
    """A SoulSeek candidate; `score` is on the matcher's 0-100 scale."""
    base = f"{track.artist} - {track.title}"
    return SoulseekReviewCandidate(
        track_id=track.id, username="demo_peer_1",
        filename=f"Music\\{track.artist}\\{base}.flac",
        score=score, quality_descriptor=quality, found_at=_FOUND_AT,
        size=size_mb * 1_000_000,
        runner_up_username=(
            "demo_peer_2" if runner_up_score is not None else None
        ),
        runner_up_filename=(
            f"{base} (Radio Edit).mp3" if runner_up_score is not None
            else None
        ),
        runner_up_score=runner_up_score,
    )


# One row per Dashboard state, in DashboardService's precedence order.
STATUSES = [
    TrackStatus(
        track=TRACKS[0], state=IN_LIBRARY,
        tagged_at="2026-09-02T09:30:00+00:00",
    ),
    TrackStatus(track=TRACKS[6], state=IN_LIBRARY),
    TrackStatus(
        track=TRACKS[1], state=DOWNLOADING,
        bytes_transferred=27_000_000, total_bytes=41_000_000,
    ),
    TrackStatus(track=TRACKS[7], state=AWAITING_REVIEW),
    TrackStatus(track=TRACKS[8], state=RETRYING),
    TrackStatus(
        track=TRACKS[2], state=NEEDS_REVIEW,
        soulseek_candidate=_candidate(TRACKS[2], 81.4, "FLAC", 38),
    ),
    TrackStatus(
        track=TRACKS[4], state=REVIEW_CANDIDATE,
        soulseek_candidate=_candidate(TRACKS[4], 72.6, "FLAC", 44, 64.0),
    ),
    TrackStatus(track=TRACKS[3], state=NOT_FOUND),
]

PLAYLISTS = [
    Playlist(
        id="p1", name="Peak Time Techno", track_count=len(STATUSES),
        snapshot_id="s1", tracks_snapshot_id="s1",
    ),
    Playlist(
        id="p2", name="Deep House Essentials", track_count=34,
        snapshot_id="s2", tracks_snapshot_id="s2",
    ),
    Playlist(
        id="p3", name="Warehouse Anthems", track_count=21,
        snapshot_id="s3",
    ),
    Playlist(
        id="p4", name="Sunrise Set", track_count=12,
        snapshot_id="s4b", tracks_snapshot_id="s4a",
    ),
]

LOCATIONS = [
    LibraryLocation(
        id=1, name="Music", path="/Users/demo/Music",
        added_at="2026-01-01T00:00:00+00:00",
    ),
    LibraryLocation(
        id=2, name="Archive", path="/Volumes/Archive/Music",
        added_at="2026-02-01T00:00:00+00:00",
    ),
    LibraryLocation(
        id=3, name="Edits", path="/Volumes/Archive/Music/Edits",
        added_at="2026-03-01T00:00:00+00:00",
    ),
]


def _request(
        track: Track,
        status: DownloadStatus,
        role: DownloadRole = DownloadRole.SETTLED,
        progress: tuple[int, int] | None = None,
        failure_reason: str | None = None,
) -> DownloadRequest:
    transferred, total = progress or (None, None)
    return DownloadRequest(
        track_id=track.id, username="demo_peer_1",
        filename=f"{track.artist} - {track.title}.flac", format="flac",
        requested_at="2026-09-03T18:00:00+00:00", role=role,
        status=status, quality_descriptor="FLAC",
        bytes_transferred=transferred, total_bytes=total,
        failure_reason=failure_reason,
    )


ACTIVE_DOWNLOADS = [
    ActiveDownload(
        request=_request(
            TRACKS[1], DownloadStatus.DOWNLOADING,
            progress=(27_000_000, 41_000_000),
        ),
        track=TRACKS[1], playlist_name="Peak Time Techno",
    ),
    ActiveDownload(
        request=_request(TRACKS[5], DownloadStatus.QUEUED),
        track=TRACKS[5], playlist_name="Deep House Essentials",
    ),
    ActiveDownload(
        request=_request(TRACKS[8], DownloadStatus.LOCKED),
        track=TRACKS[8], playlist_name="Peak Time Techno",
    ),
    ActiveDownload(
        request=_request(
            TRACKS[7], DownloadStatus.READY_FOR_REVIEW,
            role=DownloadRole.UPGRADE,
        ),
        track=TRACKS[7], playlist_name="Peak Time Techno",
    ),
    ActiveDownload(
        request=_request(
            TRACKS[6], DownloadStatus.COMPLETED,
            progress=(36_000_000, 36_000_000),
        ),
        track=TRACKS[6], playlist_name="Peak Time Techno",
    ),
    ActiveDownload(
        request=_request(
            TRACKS[3], DownloadStatus.FAILED,
            failure_reason="The peer went offline before the transfer.",
        ),
        track=TRACKS[3], playlist_name="Warehouse Anthems",
    ),
    ActiveDownload(
        request=_request(
            TRACKS[0], DownloadStatus.UNAVAILABLE,
            failure_reason="Every candidate was locked after 8 attempts.",
        ),
        track=TRACKS[0], playlist_name="Sunrise Set",
    ),
]

REVIEW_CANDIDATES = [
    (TRACKS[4], _candidate(TRACKS[4], 72.6, "FLAC, 1050kbps", 44, 64.0)),
    (TRACKS[3], _candidate(TRACKS[3], 58.9, "MP3, 320kbps", 11)),
]

NEEDS_REVIEW_MATCHES = [
    NeedsReviewMatch(
        track_id=TRACKS[2].id, track_artist=TRACKS[2].artist,
        track_title=TRACKS[2].title, local_file_id=11,
        local_file_path="House/Ilse Marchetti - Afterimage (Edit).mp3",
        location_name="Music", score=84.2,
        tag_artist="Ilse Marchetti", tag_title="Afterimage (Edit)",
    ),
]

PENDING_UPGRADES = [
    UpgradeReviewDetails(
        request_id=41, track=TRACKS[7], quality_descriptor="FLAC, 16/44.1",
        current_description="MP3, 192kbps",
        old_file_path="/Users/demo/Music/Ana Lindqvist - Paper Moons.mp3",
    ),
]

HISTORY_EVENTS = [
    HistoryEvent(
        occurred_at="2026-09-03T19:12:00+00:00", event_type=DOWNLOADED,
        track_artist=TRACKS[6].artist, track_title=TRACKS[6].title,
        playlist_name="Peak Time Techno", detail="FLAC from demo_peer_1",
    ),
    HistoryEvent(
        occurred_at="2026-09-03T18:40:00+00:00", event_type=TAGGED,
        track_artist=TRACKS[0].artist, track_title=TRACKS[0].title,
        playlist_name="Peak Time Techno", detail="Tags and cover art",
    ),
    HistoryEvent(
        occurred_at="2026-09-02T22:05:00+00:00", event_type=DOWNLOADED,
        track_artist=TRACKS[5].artist, track_title=TRACKS[5].title,
        playlist_name="Deep House Essentials",
        detail="MP3 320kbps from demo_peer_2",
    ),
    HistoryEvent(
        occurred_at="2026-08-30T11:00:00+00:00", event_type=TAGGED,
        track_artist=TRACKS[2].artist, track_title=TRACKS[2].title,
        playlist_name="Warehouse Anthems", detail="Tags; BPM 124, 8A",
    ),
]

SEARCH_RESULTS = [
    SoulseekFile(
        username="demo_peer_1",
        filename="Music\\Mara Okafor\\Glasshouse\\01 Glasshouse.flac",
        extension="flac", size=39_400_000, queue_length=0,
        upload_speed=2_400_000, has_free_upload_slot=True, length=301,
        bit_depth=16, sample_rate=44_100,
    ),
    SoulseekFile(
        username="demo_peer_2",
        filename="Mara Okafor - Glasshouse (Original Mix).aiff",
        extension="aiff", size=53_100_000, queue_length=3,
        upload_speed=900_000, has_free_upload_slot=False, length=301,
        bit_depth=24, sample_rate=48_000,
    ),
    SoulseekFile(
        username="demo_peer_3",
        filename="mara_okafor-glasshouse-320.mp3", extension="mp3",
        size=12_000_000, queue_length=0, upload_speed=600_000,
        has_free_upload_slot=True, length=300, bit_rate=320,
    ),
    SoulseekFile(
        username="demo_peer_4",
        filename="Glasshouse (Radio Edit).mp3", extension="mp3",
        size=7_100_000, queue_length=12, upload_speed=150_000,
        has_free_upload_slot=False, length=212, bit_rate=256,
        locked=True,
    ),
]


def _local_file(file_id: int, filename: str, size_mb: float) -> LocalFile:
    return LocalFile(
        id=file_id, location_id=1, relative_path=f"Techno/{filename}",
        filename=filename, format=filename.rsplit(".", 1)[-1],
        size_bytes=int(size_mb * 1_000_000), mtime=1_700_000_000.0,
        scanned_at="2026-08-01T00:00:00+00:00", tag_artist="Nova Reyes",
        tag_title="Voltage Drop", duration_ms=214_000,
    )


DUPLICATE_GROUPS = [
    DuplicateGroup(
        files=[
            DuplicateFile(
                local_file=_local_file(
                    1, "Nova Reyes - Voltage Drop.flac", 38.2,
                ),
                quality=LocalFileQuality(
                    tier=0, bitrate_kbps=None, bit_depth=16,
                    sample_rate=44_100, clipping_ratio=0.0,
                    integrated_loudness_lufs=-9.4,
                ),
            ),
            DuplicateFile(
                local_file=_local_file(
                    2, "Nova Reyes - Voltage Drop (1).mp3", 8.1,
                ),
                quality=LocalFileQuality(
                    tier=2, bitrate_kbps=192, bit_depth=None,
                    sample_rate=44_100, clipping_ratio=0.02,
                    integrated_loudness_lufs=-8.1,
                ),
            ),
        ],
        similarity=0.97,
    ),
]

TAG_RESULT = TagResult(
    tagged=6, tagged_without_art=1, skipped_no_match=1, failed=1,
    details=[
        {
            "track_id": TRACKS[3].id, "reason": "skipped_no_match",
            "message": "Rutger Solheim - Static Bloom: no local file",
        },
        {
            "track_id": TRACKS[8].id, "reason": "failed",
            "message": "Juno Halvorsen - Lowercase: disk read error",
        },
    ],
)

SHARE_ENTRY = ShareEntry(
    id="music", alias="Music", local_path="/shared/Music",
    is_excluded=False, directories=412, files=3_180,
)


def build_demo_application() -> FakeApplication:
    """A `FakeApplication` holding the whole demo dataset."""
    application = FakeApplication(
        playlists=list(PLAYLISTS),
        statuses=list(STATUSES),
        active_downloads=list(ACTIVE_DOWNLOADS),
        soulseek_configured=True,
        review_candidates=list(REVIEW_CANDIDATES),
        pending_upgrades=list(PENDING_UPGRADES),
        locations=[(location, True) for location in LOCATIONS],
        duplicate_groups=list(DUPLICATE_GROUPS),
        resolved_destination=(LOCATIONS[0], "Peak Time Techno"),
        history_events=list(HISTORY_EVENTS),
        needs_review_matches=list(NEEDS_REVIEW_MATCHES),
    )
    application.download_service = FakeDownloadService(
        resolved_destination=(LOCATIONS[0], "Peak Time Techno"),
        search_manual_results=list(SEARCH_RESULTS),
    )
    application.metadata_service = FakeMetadataService(tag_result=TAG_RESULT)
    application.duplicate_service = FakeDuplicateService(
        groups=list(DUPLICATE_GROUPS), cleanup_totals=(14, 182_000_000),
    )
    application.sharing_service = FakeSharingService(
        status=ShareStatus(
            ready=True, scanning=False, scan_pending=False, faulted=False,
            directories=412, files=3_180, shares=[SHARE_ENTRY],
        ),
        reconciliation=[
            LocationShareState(
                location=LOCATIONS[0], shared=True, share=SHARE_ENTRY,
            ),
            LocationShareState(
                location=LOCATIONS[1], shared=False, share=None,
            ),
        ],
        uploads=[
            UploadStatus(
                username="demo_listener",
                filename="Music\\Tomas Wren - Signal Path.flac",
                state="InProgress", bytes_transferred=12_000_000,
                size=31_000_000,
            ),
        ],
    )
    nested = [NestedLocation(inner=LOCATIONS[2], outer=LOCATIONS[1])]
    application.library_service.find_nested_locations = (
        lambda: nested
    )
    return application


# --- Driving the window -------------------------------------------------


def settle(app: QApplication, window: QWidget, seconds: float = 0.6) -> None:
    """Runs the event loop until the window's workers have delivered
    their results, then a moment longer for the repaint."""
    pool = getattr(window, "thread_pool", None)
    deadline = time.monotonic() + seconds
    while True:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        busy = pool is not None and pool.activeThreadCount() > 0
        if not busy and time.monotonic() >= deadline:
            break
        if time.monotonic() >= deadline + 5:
            break
        time.sleep(0.02)
    app.processEvents()


def close(app: QApplication, window: MainWindow | OnboardingWizard) -> None:
    """Stops the window's poll timers and lets every worker deliver
    before deleting it, so no result lands on a deleted widget."""
    for timer in window.findChildren(QTimer):
        timer.stop()
    window.thread_pool.waitForDone(5_000)
    settle(app, window, 0.1)
    window.hide()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def click_nav(window: MainWindow, label: str) -> None:
    """Clicks the sidebar button whose label (before any badge) is
    `label`, as a user would."""
    for button in window.findChildren(QPushButton):
        if button.isCheckable() and button.text().split("  (")[0] == label:
            button.click()
            return
    raise LookupError(f"No sidebar button labelled {label!r}")


def child(window: QWidget, kind: type[QWidget]) -> QWidget:
    found = window.findChild(kind)
    if found is None:
        raise LookupError(f"No {kind.__name__} in the window")
    return found


Step = Callable[[MainWindow], None]


def nav(label: str) -> Step:
    return lambda window: click_nav(window, label)


def _select_first_playlist(window: MainWindow) -> None:
    page = child(window, DashboardPage)
    assert isinstance(page, DashboardPage)
    page.playlist_list.setCurrentRow(0)


def _tag_playlist(window: MainWindow) -> None:
    panel = child(window, TaggingPanel)
    assert isinstance(panel, TaggingPanel)
    panel.tag_playlist_button.click()


def _search_for_a_track(window: MainWindow) -> None:
    page = child(window, SearchPage)
    assert isinstance(page, SearchPage)
    page.search_artist_edit.setText("Mara Okafor")
    page.search_title_edit.setText("Glasshouse")
    page.search_button.click()


def _find_duplicates(window: MainWindow) -> None:
    page = child(window, DuplicatesPage)
    assert isinstance(page, DuplicatesPage)
    page.find_duplicates_button.click()


def _settings_tab(index: int) -> Step:
    def show(window: MainWindow) -> None:
        window.settings_page.tabs.setCurrentIndex(index)

    return show


@dataclass(frozen=True)
class Screen:
    """A named screen, reached by `steps`; the event loop settles after
    each step, so a click lands on a page that has loaded."""
    name: str
    steps: tuple[Step, ...]


SCREENS = [
    Screen("dashboard", (nav("Dashboard"), _select_first_playlist)),
    # The Library page tags the playlist the Dashboard selects.
    Screen(
        "library",
        (
            nav("Dashboard"), _select_first_playlist, nav("Library"),
            _tag_playlist,
        ),
    ),
    Screen("search", (nav("Search"), _search_for_a_track)),
    Screen("downloads", (nav("Downloads"),)),
    Screen("review", (nav("Review"),)),
    Screen("duplicates", (nav("Duplicates"), _find_duplicates)),
    Screen("sharing", (nav("Sharing"),)),
    Screen("history", (nav("History"),)),
    Screen("help", (nav("Help"),)),
    Screen("support", (nav("Support"),)),
    Screen("settings-locations", (nav("Settings"), _settings_tab(0))),
    Screen("settings-downloads", (nav("Settings"), _settings_tab(1))),
    Screen("settings-connection", (nav("Settings"), _settings_tab(2))),
    Screen("settings-thresholds", (nav("Settings"), _settings_tab(3))),
]
WIZARD_STEPS = ("spotify", "library", "soulseek", "done")

# The committed README images: (file, screen, theme), all at 1280x820.
README_IMAGES = (
    ("dashboard-dark.png", "dashboard", "dark"),
    ("dashboard-light.png", "dashboard", "light"),
    ("library-dark.png", "library", "dark"),
    ("review.png", "review", "dark"),
    ("duplicates.png", "duplicates", "dark"),
)


def capture_window(
        app: QApplication,
        theme_name: str,
        screens: Sequence[Screen],
        sizes: Sequence[tuple[int, int]],
        name_for: Callable[[str, tuple[int, int]], Path],
) -> list[Path]:
    """Builds one `MainWindow` in `theme_name`, shows each screen and
    saves it at every size. Returns the written paths."""
    application = build_demo_application()
    application.set_theme_mode(theme_name)
    # As main_ui.py does: the theme is applied before the window exists.
    theme.apply_theme(app, theme_name)
    window = MainWindow(application)
    written: list[Path] = []
    try:
        window.resize(*sizes[0])
        window.show()
        settle(app, window, 1.0)
        for screen in screens:
            for step in screen.steps:
                step(window)
                settle(app, window)
            for size in sizes:
                window.resize(*size)
                settle(app, window, 0.3)
                path = name_for(screen.name, size)
                window.grab().save(str(path))
                written.append(path)
    finally:
        close(app, window)
    return written


def capture_wizard(
        app: QApplication,
        theme_name: str,
        sizes: Sequence[tuple[int, int]],
        name_for: Callable[[str, tuple[int, int]], Path],
) -> list[Path]:
    """Each onboarding step, shown by index. Step 3 renders before its
    Docker check runs: that check probes the real machine, which a
    screenshot must not depend on."""
    application = build_demo_application()
    application.spotify_configured = False
    application.set_theme_mode(theme_name)
    theme.apply_theme(app, theme_name)
    wizard = OnboardingWizard(application, on_complete=lambda: None)
    written: list[Path] = []
    try:
        wizard.show()
        for index, step in enumerate(WIZARD_STEPS):
            wizard.stack.setCurrentIndex(index)
            for size in sizes:
                wizard.resize(*size)
                settle(app, wizard, 0.3)
                path = name_for(f"wizard-{step}", size)
                wizard.grab().save(str(path))
                written.append(path)
    finally:
        close(app, wizard)
    return written


def render_all(
        app: QApplication,
        out_dir: Path,
        page_filter: Sequence[str] = (),
        themes: Sequence[str] = THEMES,
        sizes: Sequence[tuple[int, int]] = SIZES,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    screens = [
        screen for screen in SCREENS
        if not page_filter
        or any(screen.name.startswith(name) for name in page_filter)
    ]
    include_wizard = not page_filter or "wizard" in page_filter
    written: list[Path] = []
    for theme_name in themes:
        def name_for(
                screen: str,
                size: tuple[int, int],
                theme_name: str = theme_name,
        ) -> Path:
            return out_dir / f"{screen}-{theme_name}-{size[0]}x{size[1]}.png"

        if screens:
            written += capture_window(
                app, theme_name, screens, sizes, name_for,
            )
        if include_wizard:
            written += capture_wizard(app, theme_name, sizes, name_for)
    return written


def render_readme(app: QApplication, out_dir: Path) -> list[Path]:
    by_name = {screen.name: screen for screen in SCREENS}
    written: list[Path] = []
    for theme_name in THEMES:
        wanted = [
            (file_name, by_name[screen])
            for file_name, screen, image_theme in README_IMAGES
            if image_theme == theme_name
        ]
        files = {screen.name: file_name for file_name, screen in wanted}
        written += capture_window(
            app, theme_name, [screen for _, screen in wanted], SIZES[:1],
            lambda screen, _size, files=files: out_dir / files[screen],
        )
    return written


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--readme", action="store_true",
        help="write the committed README images to docs/screenshots/",
    )
    parser.add_argument(
        "--page", action="append", default=[], metavar="NAME",
        help="only screens whose name starts with NAME (repeatable; "
             "'wizard' selects the onboarding steps)",
    )
    parser.add_argument(
        "--theme", choices=THEMES, action="append",
        help="only this theme (repeatable)",
    )
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)

    if args.readme:
        written = render_readme(app, README_DIR)
    else:
        written = render_all(
            app, SCREENS_DIR, args.page, args.theme or THEMES,
        )
    print(f"{len(written)} images written to {written[0].parent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
