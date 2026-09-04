import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from importlib.metadata import version
from pathlib import Path
from typing import Any

from PySide6.QtCore import QRectF, QSize, Qt, QThreadPool, QTimer
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPaintEvent,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker import _build_info
from seeker.application import Application
from seeker.audio_formats import AUDIO_EXTENSIONS
from seeker.filename_sanitize import sanitize_path_component
from seeker.library.duplicate_service import (
    BulkDuplicateResolutionResult,
    DuplicateGroup,
    GroupResolutionPlan,
)
from seeker.library.metadata_service import RenamePlan
from seeker.models.active_download import ActiveDownload
from seeker.models.download_request import DownloadRequest
from seeker.models.history_event import DOWNLOADED, TAGGED, HistoryEvent
from seeker.models.library_location import LibraryLocation
from seeker.models.needs_review_match import NeedsReviewMatch
from seeker.models.playlist import Playlist
from seeker.models.soulseek_file import SoulseekFile
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track
from seeker.models.track_status import (
    AWAITING_REVIEW,
    DOWNLOADING,
    IN_LIBRARY,
    NEEDS_REVIEW,
    NOT_FOUND,
    RETRYING,
    REVIEW_CANDIDATE,
    TrackStatus,
)
from seeker.models.upgrade_review import UpgradeReviewDetails
from seeker.sharing_service import (
    LocationShareState,
    ShareStatus,
    SharingApplyResult,
    UploadStatus,
)
from seeker.soulseek.download_service import (
    BulkUpgradeReplaceResult,
    NoDestinationConfiguredError,
)
from seeker.soulseek.quality import rank_candidates, score_candidate
from seeker.ui import help_text, theme
from seeker.ui.busy_actions import BusyActionRegistry
from seeker.update_check import UpdateCheckResult, UpdateStatus, check_for_update
from seeker.ui.download_eta import (
    AGGREGATE_ETA_TOOLTIP,
    DownloadEtaTracker,
    format_aggregate_header,
)
from seeker.ui.flow_layout import FlowLayout
from seeker.ui.formatting import format_file_size, format_timestamp
from seeker.ui.notice import InlineNotice
from seeker.ui.settings_window import (
    SETTINGS_TAB_CONNECTION,
    SETTINGS_TAB_LOCATIONS,
    SettingsPage,
)
from seeker.ui.upload_eta import UploadEtaTracker
from seeker.ui.workers import run_worker

NeedsReviewCandidates = list[tuple[Track, SoulseekReviewCandidate]]
PendingUpgrades = list[UpgradeReviewDetails]


# Untuned constant — matches the ~2s cadence already observed against
# real slskd elsewhere in this project (see CLAUDE.md); revisit once
# real usage data exists, same convention as every other threshold here.
POLL_INTERVAL_MS = 2_000

# Untuned constant — this timer makes real network calls to slskd (via
# poll_downloads()), so it deliberately runs far less often than the
# local-DB-only display refresh above. 15-30s starting range per the
# task brief; revisit once real usage data exists.
BACKEND_POLL_INTERVAL_MS = 20_000

# Roadmap item R7.5 — an unreachable slskd must not emit a tray
# notification on every 20s backend-poll error; untuned, same
# "reasonable starting guess" convention as every other threshold here.
ERROR_NOTIFICATION_COOLDOWN_SECONDS = 300.0

_STATE_LABELS = {
    IN_LIBRARY: "In library",
    DOWNLOADING: "Downloading",
    AWAITING_REVIEW: "Awaiting review",
    # Roadmap item 66 (Phase 4.1) — the file is locked or queued behind
    # a peer; Seeker is retrying in the background. Not waiting on a
    # human, unlike AWAITING_REVIEW above (the split this label exists
    # to make visible).
    RETRYING: "Retrying (locked/queued)",
    NEEDS_REVIEW: "Needs review",
    # A real SoulSeek candidate was found but wasn't auto-tier enough
    # to request — actionable from the Review page, hence the same
    # double-click affordance NEEDS_REVIEW/AWAITING_REVIEW get.
    REVIEW_CANDIDATE: "Candidate to review",
    NOT_FOUND: "Not found",
}

# Plain-language notes for statuses that aren't self-explanatory as raw
# text — a "locked" or "shortlisted" row is still actively being chased,
# just not in a way a non-technical status string conveys.
_DOWNLOAD_STATUS_LABELS = {
    "queued": "Queued",
    "downloading": "Downloading",
    "locked": "Retrying (locked)",
    "shortlisted": "Queued as backup",
    "ready_for_review": "Ready for review",
    "completed": "Completed",
    "failed": "Failed",
    # Roadmap item 66 (Phase 4.3) — exhausted its retry budget against
    # this specific peer; distinct from "Failed" so it reads as "we gave
    # up chasing this one," not "something errored."
    "unavailable": "Unavailable (gave up retrying)",
}

# Statuses where a progress bar means anything at all — a locked/
# shortlisted row has no real, current transfer to show progress for
# (see CLAUDE.md: a rejection leaves bytes_transferred/total_bytes
# unset by design, not zeroed). "failed" is deliberately absent too —
# it gets its own terminal branch below, not this one.
_PROGRESS_ELIGIBLE_STATUSES = {"queued", "downloading"}

# Roadmap item 56 Phase 5.4 — a row in any of these will never report
# new progress again. Branched on BEFORE ever consulting the ETA
# tracker, which is the actual fix for "a finished download reads as
# Stalled": the tracker has no concept of "this row is done," so
# feeding it more identical-bytes samples from a completed/failed/
# ready_for_review row eventually looks exactly like a genuinely stuck
# in-progress download (STALL_SAMPLE_COUNT identical samples) to it.
# 'unavailable' (item 66 Phase 4.3) is the same kind of terminal state
# as 'failed'.
_DOWNLOAD_TERMINAL_STATUSES = {
    "completed", "failed", "ready_for_review", "unavailable",
}

# Roadmap item 56 Phase 6.3 — a sentinel QButtonGroup id for the "Keep
# all" option, sharing the same group as the per-file keep radios so
# selecting one deselects the others (the exact behavior the user
# asked to keep). Real local_file ids are always positive
# (AUTOINCREMENT starts at 1), so 0 can never collide with one — and,
# confirmed live, -1 specifically CANNOT be used here: QButtonGroup.
# addButton(button, id=-1) doesn't set the id to -1 at all — Qt treats
# -1 as its own "auto-assign an id" sentinel and silently substitutes a
# different, Qt-generated negative id (checkedId() returned -2 in a
# real, direct repro), breaking any comparison against a real -1
# constant.
KEEP_ALL_DUPLICATES_ID = 0

# Roadmap item 68 (Phase 7.1) — named constants for the duplicates
# table's real column layout, replacing literal indices scattered
# across the render path. Three independent investigations (item 61
# Phase 6.2, and this block's own Phase 0.5 — both a real-service/
# real-libchromaprint repro and a 15-group/45-row real-scale repro at
# the real default window size) could NOT reproduce a genuine index-vs-
# header mismatch; this hardening exists so that bug CLASS becomes
# structurally impossible regardless, and so the regression test can
# resolve "Actions" by its real header text instead of sharing the same
# literal the render code uses (a test that shares the code's own
# mistake proves nothing).
class _DuplicatesColumn(IntEnum):
    GROUP = 0
    LOCATION = 1
    PATH = 2
    FORMAT = 3
    BITRATE = 4
    SIMILARITY = 5
    KEEP = 6
    ACTIONS = 7


_DUPLICATES_COLUMN_HEADERS = [
    "Group", "Location", "Path", "Format", "Bitrate", "Similarity",
    "Keep", "Actions",
]


# Roadmap item 82 (P13.5) — same "resolve by real header text, not a
# shared literal" precedent as _DuplicatesColumn above.
class _SearchColumn(IntEnum):
    USERNAME = 0
    FILENAME = 1
    FORMAT = 2
    BITRATE = 3
    SIZE = 4
    LOCKED = 5
    SCORE = 6
    ACTIONS = 7


_SEARCH_COLUMN_HEADERS = [
    "Username", "Filename", "Format", "Bitrate", "Size", "Locked",
    "Score", "Actions",
]

_HISTORY_EVENT_LABELS = {
    DOWNLOADED: "Downloaded",
    TAGGED: "Tagged",
}

# Untuned constant — a fixed sidebar width narrow enough to leave real
# room for content, wide enough that "Duplicates" (the longest nav
# label) never wraps or clips.
SIDEBAR_WIDTH = 200

# key -> (nav label, page title). One source of truth for both the
# sidebar button text (via _update_nav_badge, which appends a live
# count to the label half) and the page header's own title — a nav
# label and its page title only ever differ if a future page wants
# them to (none do yet).
_NAV_PAGES = (
    ("dashboard", "Dashboard"),
    ("search", "Search"),
    ("downloads", "Downloads"),
    ("review", "Review"),
    ("duplicates", "Duplicates"),
    ("sharing", "Sharing"),
    ("history", "History"),
)

# Roadmap item 65 (Phase 2.2) — human-readable label for each
# busy_actions key, shown on the global activity strip. Any key with no
# entry here falls back to a generic "Working…" rather than a raw key
# string leaking into the UI.
_BUSY_ACTION_LABELS: dict[str, str] = {
    "sync": "Refreshing playlists…",
    "scan": "Scanning library and matching tracks…",
    "match": "Re-matching library…",
    "download": "Requesting downloads…",
    "sync_tracks": "Loading tracks…",
    "tag_selected": "Tagging selected tracks…",
    "tag_playlist": "Tagging playlist…",
    "compute_fingerprints": "Computing fingerprints…",
    "find_duplicates": "Searching for duplicates…",
    "sharing_refresh": "Checking sharing status…",
    "history_refresh": "Loading history…",
    "search_manual": "Searching SoulSeek…",
    "download_manual": "Requesting download…",
}


def _build_subtitle_label(text: str) -> QLabel:
    # Persistent, not hover-dependent (Task 1) — a muted one-liner under
    # each tab's own header, aimed at someone who never reads the
    # README and goes straight into the app.
    label = QLabel(text)
    label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
    label.setWordWrap(True)
    return label


def _build_page(
        title: str,
        subtitle: str,
        content: QWidget,
        header_extra: QWidget | None = None,
) -> QWidget:
    # Every page in the shell gets the identical [title, subtitle,
    # content] shape and the identical page-level margins (Phase 3's
    # own documented layout convention) — this is the one place that
    # convention actually gets enforced, rather than each page copying
    # setContentsMargins/setSpacing by hand and drifting.
    #
    # header_extra (roadmap item 56 Phase 3) — an optional widget placed
    # to the LEFT of the title, in the same row. Only the Settings page
    # uses this today (its "← Back" button), but it's a real, reusable
    # extension point rather than a Settings-specific special case
    # bolted onto this shared helper.
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(
        theme.SPACING_XL, theme.SPACING_LG,
        theme.SPACING_XL, theme.SPACING_LG,
    )
    layout.setSpacing(theme.SPACING_MD)

    title_row = QHBoxLayout()
    title_row.setSpacing(theme.SPACING_SM)

    if header_extra is not None:
        title_row.addWidget(header_extra)

    title_label = QLabel(title)
    title_label.setStyleSheet(
        f"font-size: 18px; font-weight: 600; color: {theme.TEXT};"
    )
    title_row.addWidget(title_label)
    title_row.addStretch()

    layout.addLayout(title_row)
    layout.addWidget(_build_subtitle_label(subtitle))
    layout.addWidget(content, 1)

    return page


def _open_in_file_manager(path: Path) -> None:
    # Cross-platform "reveal in Finder/Explorer" — same
    # subprocess/best-effort spirit as docker_setup.py's own OS calls,
    # just for the desktop file manager instead of Docker. `path.mkdir`
    # first since a brand-new install's slskd-data subfolder in
    # particular may not exist yet (SoulSeek skipped in the wizard) —
    # opening a folder that doesn't exist would otherwise silently do
    # nothing on every platform.
    path.mkdir(parents=True, exist_ok=True)

    if sys.platform == "darwin":
        subprocess.run(["open", str(path)])
    elif sys.platform == "win32":
        subprocess.run(["explorer", str(path)])
    else:
        subprocess.run(["xdg-open", str(path)])


def _resolve_tray_icon_path() -> Path:
    """Roadmap item R7.2/98 (B9.1) — same sys.frozen/sys._MEIPASS branch
    as docker_setup.py's compose_file_path(): an ordinary `uv run
    seeker-ui` dev run resolves against this file's own real location
    in the source tree; a packaged build resolves against the
    icons/ directory seeker.spec bundles as a real PyInstaller `datas`
    entry (this file previously only fed EXE()/BUNDLE()'s own icon= at
    BUILD time — nothing made it available to the running process at
    runtime, which would have left a real packaged build's tray icon
    blank).

    Points at the real template asset (`seeker_menubar_Template.png` —
    Qt auto-picks up `...@2x.png` via its own high-DPI file
    convention), not the full-colour app `.icns` — see B9's own
    CLAUDE.md entry for why setIsMask(True) on the app icon produced a
    solid filled squircle instead of a legible glyph. The `.icns` stays
    the app/Dock icon (BUNDLE()'s own icon= in seeker.spec), unaffected
    by this."""
    if not getattr(sys, "frozen", False):
        return (
            Path(__file__).resolve().parent.parent.parent.parent
            / "packaging" / "icons" / "seeker_menubar_Template.png"
        )

    return Path(sys._MEIPASS) / "icons" / "seeker_menubar_Template.png"  # type: ignore[attr-defined]


def _resolve_wordmark_brows_path() -> Path:
    """Roadmap item C4 (round 5) — same `sys.frozen`/`sys._MEIPASS`
    branch as `_resolve_tray_icon_path` above; `packaging/icons/`
    already ships wholesale as a PyInstaller `datas` entry (item 90),
    so no `seeker.spec` change is needed for this new asset."""
    if not getattr(sys, "frozen", False):
        return (
            Path(__file__).resolve().parent.parent.parent.parent
            / "packaging" / "icons" / "seeker_brows.svg"
        )

    return Path(sys._MEIPASS) / "icons" / "seeker_brows.svg"  # type: ignore[attr-defined]


class _Wordmark(QWidget):
    """Roadmap item C4 (round 5) — the sidebar's "Seeker" label, with
    the logo's brow strokes composited above the real "ee". Draws its
    own text (rather than a QLabel + a separately-positioned QLabel for
    the brows) so the brow position can be derived from the SAME
    QFontMetrics call that lays out the text — `horizontalAdvance("S")`
    gives the left edge of "ee" and `horizontalAdvance("See") -
    horizontalAdvance("S")` its width, so this survives a font/size
    change with no hardcoded offset.

    `QSvgRenderer` has no `currentColor` support (C4.3) — the SVG is
    rendered to a `QPixmap` once at construction, then tinted with
    `QPainter` `CompositionMode_SourceIn`, the same template-image
    treatment `_resolve_tray_icon_path`'s asset gets from AppKit
    natively. One untinted asset then serves any palette (dark today;
    C5's light palette needs no second asset).

    Degrades to plain text with no brows (C4.5) if the SVG asset is
    missing or fails to parse — a packaged build must never show a
    blank label just because one resource didn't make it into the
    bundle.
    """

    _TEXT = "Seeker"
    _BROW_GAP = 3
    _BOTTOM_PADDING = theme.SPACING_MD  # matches the old label's own value

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._font = QFont()
        self._font.setBold(True)
        self._font.setPixelSize(20)
        self._brows_pixmap = self._load_tinted_brows()

    def _load_tinted_brows(self) -> QPixmap | None:
        path = _resolve_wordmark_brows_path()
        if not path.exists():
            return None
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return None

        dpr = self.devicePixelRatioF() if self.window() else 2.0
        size = renderer.defaultSize()
        if size.width() <= 0 or size.height() <= 0:
            return None

        pixmap = QPixmap(
            max(1, round(size.width() * dpr)),
            max(1, round(size.height() * dpr)),
        )
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceIn
        )
        painter.fillRect(
            0, 0, pixmap.width(), pixmap.height(), QColor(theme.ACCENT),
        )
        painter.end()
        return pixmap

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self._font)
        top = self._brow_reserve_height(metrics) if self._brows_pixmap else 0
        text_size = metrics.boundingRect(self._TEXT).size()
        return QSize(
            text_size.width(),
            text_size.height() + top + self._BOTTOM_PADDING,
        )

    def _brow_reserve_height(self, metrics: QFontMetrics) -> int:
        assert self._brows_pixmap is not None
        ee_width = self._ee_span(metrics)[1]
        aspect = self._brows_pixmap.height() / self._brows_pixmap.width()
        brow_height = ee_width * aspect
        # Room for the brows AND the tallest capital letter ("S"), which
        # rises higher above baseline than the "ee"'s own x-height.
        return round(max(
            brow_height + self._BROW_GAP,
            metrics.capHeight() - metrics.xHeight(),
        ))

    def _ee_span(self, metrics: QFontMetrics) -> tuple[int, int]:
        s_width = metrics.horizontalAdvance("S")
        ee_width = metrics.horizontalAdvance("See") - s_width
        return s_width, ee_width

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        metrics = QFontMetrics(self._font)
        top_reserve = (
            self._brow_reserve_height(metrics) if self._brows_pixmap else 0
        )
        baseline_y = top_reserve + metrics.ascent()

        painter.setFont(self._font)
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(0, baseline_y, self._TEXT)

        if self._brows_pixmap is not None:
            ee_left, ee_width = self._ee_span(metrics)
            aspect = self._brows_pixmap.height() / self._brows_pixmap.width()
            brow_height = ee_width * aspect
            top_of_ee = baseline_y - metrics.xHeight()
            brow_bottom = top_of_ee - self._BROW_GAP
            target = QRectF(
                ee_left, brow_bottom - brow_height, ee_width, brow_height,
            )
            painter.drawPixmap(target, self._brows_pixmap, QRectF(
                0, 0, self._brows_pixmap.width(), self._brows_pixmap.height(),
            ))
        painter.end()


def _build_support_links_row() -> QHBoxLayout:
    # Shared between AboutDialog and the Support page (roadmap item 64) —
    # both render the same real, filtered SUPPORT_LINKS set the same way,
    # so this lives once rather than as two copies of the identical loop.
    row = QHBoxLayout()
    for name, url in help_text.SUPPORT_LINKS.items():
        if not help_text.is_real_support_link(url):
            continue

        button = QPushButton(f"Support on {name}")
        button.setToolTip(help_text.TOOLTIP_SUPPORT_LINK)
        button.clicked.connect(
            lambda _=False, url=url: webbrowser.open(url)
        )
        row.addWidget(button)
    return row


def _build_nav_button(label: str) -> QPushButton:
    # A checkable, flat QPushButton rather than a bespoke widget —
    # QPushButton is already painted through Qt's style system (unlike
    # a plain QWidget, which needs WA_StyledBackground — see notice.py/
    # the sidebar's own comment), so its checked state can be styled
    # directly via the `[navItem="true"]:checked` QSS rule with no
    # extra plumbing. Text-only badge counts (via _update_nav_badge)
    # rather than a separate sibling widget, to keep one exclusive
    # QButtonGroup member per nav item instead of a composite row.
    button = QPushButton(label)
    button.setCheckable(True)
    button.setFlat(True)
    button.setProperty("navItem", True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


@dataclass
class _SharingSnapshot:
    """Everything the Sharing page (roadmap item 62, Phase 7) needs to
    render one background-thread fetch — bundled the same way
    _NextStepFacts bundles the Dashboard CTA's facts, so run_worker's
    single-callable contract only needs one round trip per refresh
    instead of four (status/self-managed/reconciliation/uploads)."""
    configured: bool
    status: ShareStatus | None
    self_managed: bool
    reconciliation: list[LocationShareState]
    uploads: list[UploadStatus]


@dataclass
class _NextStepFacts:
    """Every real fact roadmap item 7's Dashboard "next step" CTA needs
    to decide what to show — each field traces to one real service (or
    Application) method; nothing here is computed or guessed. Bundled
    into one dataclass purely so _fetch_next_step_facts() can gather
    them in a single background-thread call rather than one run_worker
    round trip per fact.
    """
    spotify_configured: bool
    has_library_location: bool
    has_cached_playlists: bool
    selected_playlist_name: str | None
    # None when no playlist is selected — deliberately distinct from an
    # empty list (a real playlist with zero synced tracks yet).
    track_statuses: list[TrackStatus] | None
    has_scanned_library: bool
    soulseek_configured: bool


@dataclass
class _NextStep:
    message: str
    kind: str
    action_text: str | None
    action: str | None


def _decide_next_step(facts: _NextStepFacts) -> _NextStep | None:
    """Pure presentation logic (roadmap item 7's own explicit
    instruction: "which CTA to render is presentation logic and stays
    in ui/") — every fact it reads was already resolved by a real
    service call in _fetch_next_step_facts(); this function only ever
    branches on values already computed elsewhere. Returns None when
    there's nothing to show at all (no playlist selected yet, with
    every global prerequisite already satisfied — the existing empty-
    state panel already covers "pick a playlist" there).
    """
    if not facts.spotify_configured:
        return _NextStep(
            "Connect Spotify to sync your playlists.",
            "info", "Connect Spotify", "settings_connection",
        )

    if not facts.has_library_location:
        return _NextStep(
            "Add your music folder so Seeker can match what you "
            "already have.",
            "info", "Add music folder", "settings_locations",
        )

    if not facts.has_cached_playlists:
        return _NextStep(
            "Refresh your playlists from Spotify to get started.",
            "info", "Refresh playlists", "sync",
        )

    if facts.selected_playlist_name is None or facts.track_statuses is None:
        return None

    playlist_name = facts.selected_playlist_name

    if not facts.track_statuses:
        return _NextStep(
            f"Load '{playlist_name}''s tracks to see what's missing.",
            "info", "Load tracks", "sync_tracks",
        )

    if not facts.has_scanned_library:
        return _NextStep(
            "Scan your library so Seeker knows what you already have.",
            "info", "Scan library", "scan",
        )

    # Roadmap item 66 (Phase 4.1) — counts both NOT_FOUND and
    # REVIEW_CANDIDATE: both have no active download_requests row at
    # all, so both are exactly what download_playlist() would actually
    # attempt something for on the next click (a fresh request, or a
    # needs-review candidate surfacing/staying surfaced — see Phase
    # 4.2). RETRYING/AWAITING_REVIEW are deliberately excluded — those
    # already have an active row, which get_requests_blocking_
    # redownload() would just skip as already-in-progress, so counting
    # them here would overstate what clicking Download actually does.
    missing_count = sum(
        1 for status in facts.track_statuses
        if status.state in (NOT_FOUND, REVIEW_CANDIDATE)
    )
    untagged_count = sum(
        1 for status in facts.track_statuses
        if status.state == IN_LIBRARY and status.tagged_at is None
    )

    if missing_count > 0:
        if not facts.soulseek_configured:
            return _NextStep(
                "Set up SoulSeek downloading to fetch what's missing.",
                "info", "Set up SoulSeek", "settings_connection",
            )

        plural = "s" if missing_count != 1 else ""
        return _NextStep(
            f"{missing_count} track{plural} missing from "
            f"'{playlist_name}'.",
            "info", f"Download {missing_count} missing track{plural}",
            "download",
        )

    if untagged_count > 0:
        plural = "s" if untagged_count != 1 else ""
        return _NextStep(
            f"{untagged_count} downloaded track{plural} still need "
            f"Spotify metadata.",
            "info", f"Tag {untagged_count} track{plural}", "tag_playlist",
        )

    return _NextStep(
        f"You're all set for '{playlist_name}'.", "success", None, None,
    )


def _wrap_progress_bar(bar: QProgressBar, label_text: str | None) -> QWidget:
    """Roadmap item 96 (B4.2) — the one place a progress bar gets put
    into a cell-ready container, used by every exit of both
    `_build_progress_widget` and `_build_terminal_progress_widget`. A
    bare bar returned directly from a `setCellWidget` call gets resized
    to the full cell rect by Qt, and the global stylesheet's `QProgress
    Bar { max-height: 14px; }` then clamps it to the TOP of that tall
    cell instead of centering it — exactly what a fourth branch could
    reintroduce by skipping this helper. `label_text=None` omits the
    label entirely (the indeterminate 'queued' branch — there's nothing
    determinate to show an ETA for)."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(bar, 1)
    if label_text is not None:
        layout.addWidget(QLabel(label_text))
    return container


def _build_terminal_progress_widget(request: DownloadRequest) -> QWidget:
    # Roadmap item 56 Phase 5.4 — a fixed label, never the ETA tracker,
    # for a row that will never report new progress again. 'unavailable'
    # (item 66 Phase 4.3) gets the same blank treatment as 'failed' — a
    # full bar would misleadingly read as "completed" for something that
    # never actually succeeded.
    if request.status in ("failed", "unavailable"):
        return QWidget()  # blank, not a misleading full/empty bar

    bar = QProgressBar()

    if request.total_bytes and request.bytes_transferred is not None:
        bar.setRange(0, request.total_bytes)
        bar.setValue(request.bytes_transferred)
    else:
        # A completed/ready_for_review row should always have real
        # bytes (item 20's standing rule), but render a full bar rather
        # than crash/guess if a real one somehow doesn't.
        bar.setRange(0, 1)
        bar.setValue(1)

    theme.style_determinate_progress_bar(bar)

    label_text = _DOWNLOAD_STATUS_LABELS.get(request.status, request.status)

    return _wrap_progress_bar(bar, label_text)


def _build_progress_widget(
        download: ActiveDownload,
        eta_text: str | None,
) -> QWidget:
    request = download.request

    if request.status in _DOWNLOAD_TERMINAL_STATUSES:
        return _build_terminal_progress_widget(request)

    if request.status not in _PROGRESS_ELIGIBLE_STATUSES:
        return QWidget()

    bar = QProgressBar()

    if not (request.total_bytes and request.bytes_transferred is not None):
        # No bytes reported yet — indeterminate ("busy") rather than a
        # 0%-forever bar that looks identical to actually being stuck.
        # No ETA either (Task 2): there's nothing determinate to
        # estimate against. Roadmap item 96 (B4.1) — wrapped in the
        # same container shape as the determinate branch below, not
        # returned bare: a bare bar gets clamped to the top of the cell
        # (see _wrap_progress_bar's own docstring for why).
        bar.setRange(0, 0)
        return _wrap_progress_bar(bar, None)

    bar.setRange(0, request.total_bytes)
    bar.setValue(request.bytes_transferred)
    theme.style_determinate_progress_bar(bar)

    # ETA only ever shown once the bar is determinate, per Task 2's own
    # scoping.
    return _wrap_progress_bar(bar, eta_text or "Calculating…")


class AboutDialog(QDialog):
    """The Help menu's "About Seeker" entry — app description, real
    installed version (read from package metadata rather than a second
    hardcoded literal that could drift from pyproject.toml), and
    support-the-creator links (Task 3; see settings_window.py-style
    placement precedent — Help/About is one of two deliberate spots for
    those, not the daily-use Dashboard/Downloads/Review screens).
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(help_text.ABOUT_DIALOG_TITLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING_XL, theme.SPACING_LG,
            theme.SPACING_XL, theme.SPACING_LG,
        )
        layout.setSpacing(theme.SPACING_MD)

        try:
            installed_version = version("seeker")
        except Exception:
            # Package metadata isn't always available (e.g. a frozen
            # PyInstaller build without an installed dist-info) — the
            # dialog should still open, just without a version line.
            installed_version = None

        body = help_text.ABOUT_DIALOG_BODY
        if installed_version is not None:
            body += f"<p>Version {installed_version}</p>"
        build_identity = help_text.format_build_identity(
            _build_info.GIT_SHA, _build_info.GIT_DESCRIBE,
            _build_info.BUILT_AT,
        )
        body += f"<p>{help_text.HELP_BUILD_IDENTITY_LABEL} {build_identity}</p>"

        text_label = QLabel(body)
        text_label.setTextFormat(Qt.TextFormat.RichText)
        text_label.setWordWrap(True)
        layout.addWidget(text_label)

        # setOpenExternalLinks(True) — Qt opens mailto:/https: links via
        # the OS default handler itself (QDesktopServices), no separate
        # webbrowser.open() wiring needed for a plain clickable label
        # (unlike the support buttons below, which need an explicit
        # click handler since they're QPushButtons, not link text).
        author_label = QLabel(help_text.ABOUT_DIALOG_AUTHOR_LINE)
        author_label.setTextFormat(Qt.TextFormat.RichText)
        author_label.setWordWrap(True)
        author_label.setOpenExternalLinks(True)
        layout.addWidget(author_label)

        license_label = QLabel(help_text.ABOUT_DIALOG_LICENSE_LINE)
        license_label.setTextFormat(Qt.TextFormat.RichText)
        license_label.setWordWrap(True)
        layout.addWidget(license_label)

        notices_label = QLabel(help_text.ABOUT_DIALOG_THIRD_PARTY_NOTICES)
        notices_label.setTextFormat(Qt.TextFormat.RichText)
        notices_label.setWordWrap(True)
        notices_label.setStyleSheet(f"color: {theme.TEXT_FAINT};")
        layout.addWidget(notices_label)

        # Real URLs aren't ready for every link yet — is_real_support_link()
        # filters out any still-TODO placeholder so a dead, non-URL button
        # never actually renders (see help_text.SUPPORT_LINKS's own note).
        # Same webbrowser.open() mechanism the Spotify OAuth flow already
        # uses; no SDK, no embedded payment UI. Shared with the Support
        # page (roadmap item 64) via _build_support_links_row().
        layout.addLayout(_build_support_links_row())

        close_row = QHBoxLayout()
        close_button = QPushButton("Close")
        close_button.setProperty("variant", "primary")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        close_row.addStretch()
        layout.addLayout(close_row)


class DestinationDialog(QDialog):
    """Roadmap item 6 §3 — "no dead end": shown instead of letting
    Download raise NoDestinationConfiguredError. Confirming it always
    persists a real destination somewhere (never a one-time,
    unpersisted choice — DownloadService._resolve_destination is
    re-evaluated later, on a separate poll cycle, when the file
    actually completes, so nothing durable would be left for it to
    find otherwise) and then the caller continues straight into the
    real download.

    Roadmap item 65 (Phase 3.2) — reused (not a second dialog) for a
    SECOND, more common trigger: a playlist with no destination of its
    own AND a configured default that WOULD resolve. `initial_subfolder`
    lets the caller pre-fill with the real current fallback (rather than
    always the raw playlist name) so the default stays one click away,
    and `location_path_preview`/`_update_preview` shows the exact
    absolute path that choice resolves to, live, as the user changes
    either field — including whether it already exists and how many
    audio files are already there, since that's what turns "it
    downloaded into a folder I didn't choose" into an informed choice.
    """

    def __init__(
            self,
            parent: QWidget,
            playlist_name: str,
            locations: list[LibraryLocation],
            default_location_id: int | None,
            initial_subfolder: str | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(help_text.DESTINATION_DIALOG_TITLE)
        self._locations = locations

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING_LG, theme.SPACING_LG,
            theme.SPACING_LG, theme.SPACING_LG,
        )
        layout.setSpacing(theme.SPACING_MD)

        intro = QLabel(
            help_text.DESTINATION_DIALOG_INTRO.format(playlist=playlist_name)
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()

        self.location_combo = QComboBox()
        for location in locations:
            self.location_combo.addItem(location.name, location.id)
        form.addRow("Location:", self.location_combo)

        # Prefill: the configured default, else the only location if
        # there's exactly one — never left on an arbitrary first entry
        # when there's a real, obvious choice.
        preselect_id = default_location_id
        if preselect_id is None and len(locations) == 1:
            preselect_id = locations[0].id
        if preselect_id is not None:
            index = self.location_combo.findData(preselect_id)
            if index >= 0:
                self.location_combo.setCurrentIndex(index)

        self.subfolder_field = QLineEdit(
            initial_subfolder if initial_subfolder is not None
            else playlist_name
        )
        form.addRow("Subfolder:", self.subfolder_field)

        layout.addLayout(form)

        # Roadmap item 65 (Phase 3.2) — a real, live-updating preview of
        # exactly where confirming would download to, and what's already
        # there. Recomputed on every relevant field change, not just once
        # at open, so it never goes stale while the user is still
        # deciding.
        self.location_path_preview = QLabel()
        self.location_path_preview.setWordWrap(True)
        self.location_path_preview.setStyleSheet(
            f"color: {theme.TEXT_MUTED};"
        )
        layout.addWidget(self.location_path_preview)

        self.location_combo.currentIndexChanged.connect(self._update_preview)
        self.subfolder_field.textChanged.connect(self._update_preview)
        self._update_preview()

        self.remember_checkbox = QCheckBox("Remember this for this playlist")
        self.remember_checkbox.setChecked(True)
        self.remember_checkbox.setToolTip(
            help_text.TOOLTIP_REMEMBER_DESTINATION_CHECKBOX.format(
                playlist=playlist_name,
            )
        )
        layout.addWidget(self.remember_checkbox)

        button_row = QHBoxLayout()
        self.confirm_button = QPushButton("Download")
        self.confirm_button.setProperty("variant", "primary")
        self.confirm_button.clicked.connect(self.accept)
        button_row.addWidget(self.confirm_button)
        button_row.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

    def _resolved_path(self) -> Path | None:
        location_id = self.selected_location_id()
        location = next(
            (loc for loc in self._locations if loc.id == location_id), None,
        )
        if location is None:
            return None

        subfolder = self.selected_subfolder()
        path = Path(location.path)
        return path / sanitize_path_component(subfolder) if subfolder else path

    def _update_preview(self) -> None:
        path = self._resolved_path()

        if path is None:
            self.location_path_preview.setText("")
            return

        exists = path.exists()
        audio_file_count: int | None = None

        if exists:
            try:
                audio_file_count = sum(
                    1 for entry in path.iterdir()
                    if entry.is_file()
                    and entry.suffix.lower() in AUDIO_EXTENSIONS
                )
            except OSError:
                # An unreadable folder shouldn't block the dialog — just
                # show the path itself without a file count (None).
                pass

        self.location_path_preview.setText(
            help_text.format_destination_preview(
                str(path), exists, audio_file_count,
            )
        )

    def selected_location_id(self) -> int | None:
        data = self.location_combo.currentData()
        return int(data) if data is not None else None

    def selected_subfolder(self) -> str | None:
        text = self.subfolder_field.text().strip()
        return text or None

    def remember_for_playlist(self) -> bool:
        return self.remember_checkbox.isChecked()


class RenamePreviewDialog(QDialog):
    """Roadmap item 67 (Phase 6.4) — every planned change, grouped by
    action, unchanged and refused tracks visible too. Nothing is
    written until the user explicitly clicks Rename — item 27's "no
    gate for tag-writing" precedent does NOT extend to this action,
    since renaming moves/replaces a file on disk and tag-writing never
    does.
    """

    def __init__(
            self,
            parent: QWidget,
            playlist_name: str,
            plans: list[RenamePlan],
    ):
        super().__init__(parent)
        self.setWindowTitle(help_text.RENAME_PREVIEW_DIALOG_TITLE)
        self.resize(640, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING_LG, theme.SPACING_LG,
            theme.SPACING_LG, theme.SPACING_LG,
        )
        layout.setSpacing(theme.SPACING_MD)

        intro = QLabel(
            f"'{playlist_name}': "
            + help_text.RENAME_PREVIEW_DIALOG_INTRO
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.renames = [p for p in plans if p.action == "rename"]
        self.collisions = [p for p in plans if p.action == "collision"]
        already_correct = [p for p in plans if p.action == "already_correct"]
        not_auto_matched = [
            p for p in plans if p.action == "not_auto_matched"
        ]
        refused = [
            p for p in plans if p.action in ("no_local_file", "error")
        ]

        list_widget = QListWidget()
        list_widget.setAlternatingRowColors(False)

        def add_section(heading: str, rows: list[RenamePlan]) -> None:
            if not rows:
                return

            header_item = QListWidgetItem(f"{heading} ({len(rows)})")
            font = header_item.font()
            font.setBold(True)
            header_item.setFont(font)
            header_item.setFlags(Qt.ItemFlag.NoItemFlags)
            list_widget.addItem(header_item)

            for plan in rows:
                # Roadmap item 93 (B3.2) — the location-relative path
                # (e.g. "Neuro/Audio, REEBZ - Tractor Beam.flac"), not
                # just the basename: a basename-only "Already correct"
                # row for a file elsewhere in the same library location
                # was indistinguishable from the file the user was
                # actually looking at (the real story behind B3's
                # "nothing was renamed" report). Absolute path stays
                # available as the tooltip for anyone who needs it.
                if plan.current_relative is not None and plan.proposed_relative is not None:
                    text = f"  {plan.current_relative}  →  {plan.proposed_relative}"
                elif plan.current_relative is not None:
                    text = f"  {plan.current_relative}"
                else:
                    text = f"  {plan.message or plan.track_id}"

                if plan.destination_note:
                    text = f"{text}\n    ⚠ {plan.destination_note}"

                item = QListWidgetItem(text)
                item.setFlags(Qt.ItemFlag.NoItemFlags)

                tooltip_parts = [
                    str(path) for path in (plan.current_path, plan.proposed_path)
                    if path is not None
                ]
                if tooltip_parts:
                    item.setToolTip("\n".join(tooltip_parts))

                list_widget.addItem(item)

        add_section(
            help_text.RENAME_PREVIEW_SECTION_RENAME, self.renames,
        )
        add_section(
            help_text.RENAME_PREVIEW_SECTION_COLLISION, self.collisions,
        )
        add_section(
            help_text.RENAME_PREVIEW_SECTION_ALREADY_CORRECT,
            already_correct,
        )
        add_section(
            help_text.RENAME_PREVIEW_SECTION_NOT_AUTO_MATCHED,
            not_auto_matched,
        )
        add_section(
            help_text.RENAME_PREVIEW_SECTION_REFUSED, refused,
        )

        if list_widget.count() == 0:
            list_widget.addItem(help_text.RENAME_PREVIEW_NO_CHANGES)

        layout.addWidget(theme.make_card(list_widget), 1)

        button_row = QHBoxLayout()
        total_to_rename = len(self.renames) + len(self.collisions)
        self.confirm_button = QPushButton(f"Rename {total_to_rename} file(s)")
        self.confirm_button.setProperty("variant", "primary")
        self.confirm_button.setEnabled(total_to_rename > 0)
        self.confirm_button.clicked.connect(self.accept)
        button_row.addWidget(self.confirm_button)
        button_row.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)


class BulkReplaceUpgradesDialog(QDialog):
    """Roadmap item R3.1 — "Replace all" pending upgrades. Same shape
    as RenamePreviewDialog: every row named plainly, nothing applied
    until the user explicitly confirms — this is one of the two most
    destructive actions in the app (it can delete real old files), so
    it inherits the project's standing "never modify/delete a real
    user file without explicit confirmation" rule in full, via the
    "Delete the old files" checkbox below (default OFF)."""

    def __init__(self, parent: QWidget, upgrades: PendingUpgrades):
        super().__init__(parent)
        self.setWindowTitle(help_text.BULK_REPLACE_UPGRADES_DIALOG_TITLE)
        self.resize(560, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING_LG, theme.SPACING_LG,
            theme.SPACING_LG, theme.SPACING_LG,
        )
        layout.setSpacing(theme.SPACING_MD)

        intro = QLabel(
            help_text.format_bulk_replace_upgrades_intro(len(upgrades))
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        list_widget = QListWidget()
        list_widget.setAlternatingRowColors(False)
        for details in upgrades:
            text = (
                f"{details.track.artist} - {details.track.title}  —  "
                f"{details.current_description} → "
                f"{details.quality_descriptor or 'unknown'}"
            )
            item = QListWidgetItem(text)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            list_widget.addItem(item)
        layout.addWidget(theme.make_card(list_widget), 1)

        self.delete_old_checkbox = QCheckBox("Delete the old files")
        self.delete_old_checkbox.setToolTip(
            help_text.TOOLTIP_BULK_DELETE_OLD_FILES_CHECKBOX
        )
        layout.addWidget(self.delete_old_checkbox)

        button_row = QHBoxLayout()
        self.confirm_button = QPushButton(f"Replace {len(upgrades)} upgrade(s)")
        self.confirm_button.setProperty("variant", "primary")
        self.confirm_button.setEnabled(len(upgrades) > 0)
        self.confirm_button.clicked.connect(self.accept)
        button_row.addWidget(self.confirm_button)
        button_row.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)


class BulkResolveDuplicatesDialog(QDialog):
    """Roadmap item R3.2 — "Resolve all groups." Lists REAL absolute
    paths of every file that would be deleted and every file that
    would be kept, since this deletes real user files — a bare count
    is not enough for this specific action, matching the brief's own
    instruction. Groups already set to "Keep all" are never passed in
    here at all (skipped by the caller before this dialog is even
    built) — this dialog only ever shows groups that would actually
    change something."""

    def __init__(
            self,
            parent: QWidget,
            plans_with_labels: list[tuple[GroupResolutionPlan, str, list[str]]],
    ):
        super().__init__(parent)
        self.setWindowTitle(help_text.BULK_RESOLVE_DUPLICATES_DIALOG_TITLE)
        self.resize(640, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING_LG, theme.SPACING_LG,
            theme.SPACING_LG, theme.SPACING_LG,
        )
        layout.setSpacing(theme.SPACING_MD)

        total_files_to_delete = sum(
            len(plan.delete_local_file_ids) for plan, _, _ in plans_with_labels
        )
        intro = QLabel(
            help_text.format_bulk_resolve_duplicates_intro(
                len(plans_with_labels), total_files_to_delete,
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        list_widget = QListWidget()
        list_widget.setAlternatingRowColors(False)

        def add_line(text: str) -> None:
            item = QListWidgetItem(text)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            list_widget.addItem(item)

        for index, (plan, keep_path, delete_paths) in enumerate(
                plans_with_labels, start=1,
        ):
            header_item = QListWidgetItem(f"Group {index}")
            font = header_item.font()
            font.setBold(True)
            header_item.setFont(font)
            header_item.setFlags(Qt.ItemFlag.NoItemFlags)
            list_widget.addItem(header_item)
            add_line(f"  Keep: {keep_path}")
            for delete_path in delete_paths:
                add_line(f"  Delete: {delete_path}")

        if list_widget.count() == 0:
            list_widget.addItem(help_text.BULK_RESOLVE_DUPLICATES_NO_GROUPS)

        layout.addWidget(theme.make_card(list_widget), 1)

        self.confirm_checkbox = QCheckBox(
            f"Permanently delete {total_files_to_delete} file(s)"
        )
        self.confirm_checkbox.setToolTip(
            help_text.TOOLTIP_BULK_DELETE_DUPLICATES_CHECKBOX
        )
        layout.addWidget(self.confirm_checkbox)

        button_row = QHBoxLayout()
        self.confirm_button = QPushButton(
            f"Resolve {len(plans_with_labels)} group(s)"
        )
        self.confirm_button.setProperty("variant", "danger")
        # Roadmap item R3.2 — same two-step gate as the single-group
        # Delete flow: the checkbox is required before the button can
        # do anything, not just informational text next to it.
        self.confirm_button.setEnabled(False)
        has_plans = len(plans_with_labels) > 0
        self.confirm_checkbox.toggled.connect(
            lambda checked: self.confirm_button.setEnabled(checked and has_plans)
        )
        self.confirm_button.clicked.connect(self.accept)
        button_row.addWidget(self.confirm_button)
        button_row.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)


class MainWindow(QMainWindow):
    def __init__(self, application: Application):
        super().__init__()
        # See SettingsWindow's identical fix (CLAUDE.md's broad
        # end-to-end stress test entry) — a parentless top-level
        # QMainWindow's close() only hides it by default, never
        # actually destroys it, unless this is set. MainWindow is
        # normally only closed once (app exit), but tests construct
        # and close it repeatedly — this matters there even if it's
        # rarely the operational hot path in real usage. Confirmed
        # this specific attribute was never the cause of a real,
        # separately-found segfault (see workers.py's own
        # SingleShotConnection fix) — isolated by temporarily removing
        # each of the two changes independently against the full test
        # suite before concluding which one was actually responsible.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.application = application
        self.thread_pool = QThreadPool()
        # Roadmap item 65 (Phase 2.1) — the single source of truth for
        # "is this named action currently running," consulted by every
        # poll-driven render method so it can skip a button whose own
        # action is still in flight instead of fighting run_worker's own
        # busy-disable (the proven mechanism behind Phase 0's 0.1 bug).
        self.busy_actions = BusyActionRegistry()
        # Roadmap item 65 (Phase 2.2/2.3) — keyed the same as
        # busy_actions; populated by a run_worker(on_progress=...)
        # callback (via _on_activity_progress), consulted by
        # _render_activity_strip. Empty for every action wired in Phase
        # 2 itself — Phase 7's fingerprinting/duplicate-search progress
        # is the first real producer.
        self._activity_progress: dict[str, tuple[str, int, int]] = {}
        self.selected_playlist: Playlist | None = None
        self._backend_poll_in_progress = False
        # Task 2 — speed/ETA estimation for the Downloads tab. Purely
        # in-memory, scoped to this window's lifetime — see
        # ui/download_eta.py's own docstring for the sampling contract.
        self._eta_tracker = DownloadEtaTracker()
        # Maps track_table row -> TrackStatus, rebuilt on every render —
        # needed to resolve a multi-selection back to real track ids for
        # "Tag selected" (Step 7).
        self._current_track_statuses: list[TrackStatus] = []
        # Set by a Dashboard double-click on a NEEDS_REVIEW/AWAITING_
        # REVIEW row (roadmap item 56 §2.4); consumed once by
        # _focus_pending_review_row the next time the Review page's data
        # actually loads.
        self._pending_review_focus_track_id: str | None = None
        # Roadmap item 71 (P3) — the "next step" notice is re-rendered
        # unconditionally on every 2s poll tick (see _render_next_step),
        # so dismissing it needs its own memory: the key of whatever
        # step was on screen when the user clicked X. Cleared the
        # moment the computed key changes, so a genuinely different
        # step (or the same step recurring later) still surfaces.
        self._dismissed_next_step_key: (
            tuple[str | None, str | None, str | None] | None
        ) = None
        self._current_next_step_key: (
            tuple[str | None, str | None, str | None] | None
        ) = None

        # Roadmap item R7 — menu-bar background operation.
        # Counts the tray menu's own status line and "Review (N)"/
        # "Upgrades (N)" items read — built from data the existing
        # poll methods already fetch, never a third source of truth
        # (R7.3's own explicit instruction).
        self._active_downloads_count = 0
        self._needs_review_count = 0
        self._pending_upgrades_count = 0
        # R7.1 — set once the window is genuinely hidden-to-tray
        # (closeEvent), not just "not the active window"; R7.6 reads
        # this to skip re-render work while nobody can see it.
        self._hidden_to_tray = False
        self._tray_icon: QSystemTrayIcon | None = None
        # R7.5 — de-duplicates "N item(s) need your decision" so it
        # only fires on a genuine INCREASE, never every poll tick the
        # count happens to still be positive.
        self._last_notified_review_count = 0
        # R7.5 — the newest HistoryEvent.occurred_at already accounted
        # for, seeded once (silently, no notification) right after
        # construction so pre-existing history never floods a first
        # notification the moment the tray icon appears.
        self._last_notified_download_at: str | None = None
        self._last_error_notification_at: float | None = None

        self._build_tray_icon()

        # Roadmap item 98 (B10) — reversed from item 81 (0.1): a commit
        # SHA in the one string a user reads most often looked like a
        # bug even when it wasn't one. Build identity already has its
        # correct home — Help -> About Seeker (below) already renders
        # GIT_SHA/GIT_DESCRIBE/BUILT_AT — so the title stays the plain
        # app name.
        self.setWindowTitle("Seeker")
        self.resize(1180, 760)
        self.setMinimumSize(960, 640)

        self._build_ui()
        self._render_no_playlist_selected()
        self._load_playlists()
        self._poll_active_downloads()
        self._poll_review_items()
        self._poll_next_step()
        self._seed_notification_cutoff()

        # DB-polling pattern for live status: rebuild the visible model
        # each tick rather than diffing for minimal repaints — an
        # acceptable v1 simplification, matching this project's habit
        # of shipping a working real version before optimizing.
        #
        # Roadmap item R2 — this tradeoff is now ONLY accepted for pure
        # DISPLAY state (table contents, labels, nav badges), never for
        # user INPUT: a rebuild used to destroy every checkbox/radio in
        # a polled table on every tick, not just "reset one mid-click"
        # as first assumed — a real reported bug, not a theoretical
        # edge case. The Review tab's "delete old file" checkbox and
        # the Duplicates "keep" radio selection now survive a rebuild
        # via a small state map keyed by stable identity (request_id /
        # the group's own member file ids — never row index), restored
        # on render and pruned when the underlying row is gone
        # (`_upgrade_delete_checked`, `_duplicates_keep_selection`). The
        # real long-term fix is diffing rows instead of rebuilding them
        # wholesale; the state map is the honest scoped fix on top of
        # the existing rebuild-every-tick pattern, not a claim that the
        # underlying pattern itself is now safe for any future
        # interactive control added to a polled table without the same
        # treatment.
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_INTERVAL_MS)
        self.poll_timer.timeout.connect(self._poll_selected_playlist)
        self.poll_timer.timeout.connect(self._poll_active_downloads)
        self.poll_timer.timeout.connect(self._poll_review_items)
        self.poll_timer.timeout.connect(self._poll_next_step)
        # Roadmap item 65 (Phase 2.2) — a periodic safety-net refresh on
        # top of the explicit begin()/end()-adjacent calls already made
        # at every busy-action call site; catches nothing new today (all
        # of those already call _render_activity_strip() synchronously)
        # but keeps the strip correct even if a future action forgets to.
        self.poll_timer.timeout.connect(self._render_activity_strip)
        # Roadmap item R7.3 — the tray menu's live status line/counts;
        # cheap (reads counts the other poll methods already set, no
        # new DB/network work of its own) so it stays on the fast 2s
        # tick like the rest of this timer's display refresh, not the
        # slow backend one.
        self.poll_timer.timeout.connect(self._render_tray_menu)
        self.poll_timer.start()

        # Separate, slower timer: the only thing in this app that causes
        # poll_downloads() (real slskd network calls) to run without an
        # explicit `seeker downloads status` invocation. poll_downloads()
        # was built with exactly this kind of unattended calling in mind
        # (no input() anywhere — see CLAUDE.md's guardrail tests), so
        # this is safe to fire on a bare timer with no user interaction.
        self.backend_poll_timer = QTimer(self)
        self.backend_poll_timer.setInterval(BACKEND_POLL_INTERVAL_MS)
        self.backend_poll_timer.timeout.connect(self._trigger_backend_poll)
        self.backend_poll_timer.timeout.connect(self._trigger_sharing_poll)
        self.backend_poll_timer.start()

    def _build_ui(self) -> None:
        self._build_help_menu()

        shell = QWidget()
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        shell_layout.addWidget(self._build_sidebar())

        # Roadmap item 65 (Phase 2.2) — a persistent activity strip
        # lives between the sidebar/header and the page content itself,
        # visible regardless of which page the user has navigated to
        # (button state alone is invisible once you've left the page a
        # long-running action was started from). A separate column
        # rather than widening shell_layout further, so the strip spans
        # only the content area, not the sidebar.
        content_column = QWidget()
        content_column_layout = QVBoxLayout(content_column)
        content_column_layout.setContentsMargins(0, 0, 0, 0)
        content_column_layout.setSpacing(0)

        self.activity_strip = self._build_activity_strip()
        content_column_layout.addWidget(self.activity_strip)

        self.stacked_widget = QStackedWidget()
        content_column_layout.addWidget(self.stacked_widget, 1)

        shell_layout.addWidget(content_column, 1)

        self._page_indices: dict[str, int] = {}
        self._register_page("dashboard", self._build_dashboard_page())
        self._register_page("search", self._build_search_page())
        self._register_page("downloads", self._build_downloads_page())
        self._register_page("review", _build_page(
            "Review", help_text.REVIEW_TAB_SUBTITLE,
            self._build_review_content(),
        ))
        self._register_page("duplicates", _build_page(
            "Duplicates", help_text.DUPLICATES_TAB_SUBTITLE,
            self._build_duplicates_content(),
        ))
        self._register_page("sharing", self._build_sharing_page())
        self._register_page("history", self._build_history_page())
        self._register_page("help", self._build_help_page())
        self._register_page("support", self._build_support_page())

        # Roadmap item 56 Phase 3 — Settings reversed from item 48's
        # separate-dialog decision into a real page, hosted the same
        # way as everything else here. header_extra is _build_page's
        # own extension point (see its docstring), used only by this
        # page today.
        self.settings_back_button = QPushButton("← Back")
        self.settings_back_button.setToolTip(help_text.TOOLTIP_SETTINGS_BACK)
        self.settings_back_button.clicked.connect(
            self._on_settings_back_clicked
        )
        self.settings_page = SettingsPage(
            self.application, on_about_requested=self._on_about_clicked,
        )
        self._register_page("settings", _build_page(
            "Settings", help_text.SETTINGS_WINDOW_SUBTITLE,
            self.settings_page, header_extra=self.settings_back_button,
        ))
        self._settings_page_index = self._page_indices["settings"]

        # Locations load lazily, on every real show of this page rather
        # than eagerly in _build_ui() — every MainWindow construction
        # runs _build_ui() once, and an eager worker here was confirmed
        # live to compound into a real, reproducible deadlock (Qt's
        # internal connection-list mutex vs. the GIL) under the rapid,
        # repeated MainWindow construction this project's own test
        # suite does — see CLAUDE.md/docs/HISTORY.md item 39. A real
        # page SHOW (unlike construction) is comparatively rare and
        # human-paced, so refreshing on every one (roadmap item 56
        # Phase 6.1 — a location added since the last visit must
        # actually appear) doesn't reintroduce that hazard; only the
        # original "fetch at construction time" trigger did.
        self._duplicates_page_index = self._page_indices["duplicates"]
        # Roadmap item 62 (Phase 7.6) — lazy-loaded like Duplicates
        # (first real page SHOW, never at construction — see item 39's
        # deadlock), but ALSO joins the standing 20s backend_poll_timer
        # once visited, same shape as Downloads' own real-slskd-call
        # poll — sharing status/uploads are live external state, not a
        # one-shot local read like Duplicates/History.
        self._sharing_page_index = self._page_indices["sharing"]
        self._sharing_page_visited = False
        self._sharing_poll_in_progress = False
        self._upload_eta_tracker = UploadEtaTracker()
        # Same lazy-load-on-first-real-visit reasoning as Duplicates
        # above — a plain, cheap local-DB read, but there's no reason
        # to pay it on every MainWindow construction when a real user
        # may never open this page in a given session.
        self._history_page_index = self._page_indices["history"]
        self._history_loaded = False
        # Tracks the currently-shown page key so the Settings back
        # button (roadmap item 56 Phase 3) knows where to return to,
        # and so _on_page_changed can detect "we just left Settings"
        # regardless of which navigation path was used (sidebar click,
        # back button, or a CTA/double-click action — every one of them
        # goes through _show_page).
        self._current_page_key = "dashboard"
        self._previous_page_key = "dashboard"
        self.stacked_widget.currentChanged.connect(self._on_page_changed)

        self.setCentralWidget(shell)
        self._show_page("dashboard")

    def _register_page(self, key: str, widget: QWidget) -> None:
        self._page_indices[key] = self.stacked_widget.addWidget(widget)

    def _show_page(self, key: str, focus_track_id: str | None = None) -> None:
        # Roadmap item 56 Phase 3 — every navigation path in this app
        # (sidebar click, the Settings back button, a Dashboard CTA
        # action, a double-click) already goes through this one method,
        # so it's the single place both the back button's "where to
        # return to" and the settings-exit invalidation (§3.3) can hook
        # into without needing a Settings-specific special case at each
        # call site.
        if key == "settings" and self._current_page_key != "settings":
            self._previous_page_key = self._current_page_key
        elif self._current_page_key == "settings" and key != "settings":
            self._invalidate_after_leaving_settings()

        self._current_page_key = key
        self.stacked_widget.setCurrentIndex(self._page_indices[key])

        button = self._nav_buttons.get(key)
        if button is not None:
            button.setChecked(True)

        if key == "review" and focus_track_id is not None:
            self._pending_review_focus_track_id = focus_track_id
            # The Review tables are already on the standing 2s
            # poll_timer regardless of which page is visible (item 48's
            # pattern) — this explicit call just avoids making the user
            # wait up to 2s to see the row get selected.
            self._poll_review_items()

    def _on_settings_back_clicked(self) -> None:
        self._show_page(self._previous_page_key)

    def _invalidate_after_leaving_settings(self) -> None:
        # Roadmap item 56 Phase 3 §3.3 — a Settings change can affect
        # the Duplicates page's location combo (a location added/
        # removed) and the Dashboard's own next-step CTA (Spotify/
        # library-location/threshold facts). Both already have a real
        # refresh method; this just calls them immediately on exit
        # rather than waiting for their own standing poll/lazy-load to
        # eventually catch up. Phase 6.1 (Duplicates combo refresh)
        # later reuses this exact same _refresh_duplicates_locations()
        # call, not a second one.
        self._refresh_duplicates_locations()
        self._poll_next_step()

    def _build_activity_strip(self) -> QWidget:
        # Roadmap item 65 (Phase 2.2) — hidden whenever nothing is
        # running (the common case); see _render_activity_strip for what
        # populates it.
        strip = QWidget()
        strip.setObjectName("activityStrip")
        # A plain QWidget subclass doesn't paint its own stylesheet
        # background by default in Qt (item 47's identical
        # WA_StyledBackground finding, same fix here).
        strip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        strip.setStyleSheet(
            f"#activityStrip {{ background-color: {theme.BG_SURFACE_2}; "
            f"border-bottom: 1px solid {theme.BORDER}; }}"
        )

        layout = QHBoxLayout(strip)
        layout.setContentsMargins(
            theme.SPACING_MD, theme.SPACING_XS,
            theme.SPACING_MD, theme.SPACING_XS,
        )
        layout.setSpacing(theme.SPACING_SM)

        self.activity_strip_label = QLabel("")
        layout.addWidget(self.activity_strip_label)

        # Untuned fixed width — wide enough to read a real percentage
        # without dominating the strip.
        self.activity_strip_bar = QProgressBar()
        self.activity_strip_bar.setFixedWidth(160)
        self.activity_strip_bar.setTextVisible(False)
        layout.addWidget(self.activity_strip_bar)

        layout.addStretch()

        strip.hide()
        return strip

    def _render_activity_strip(self) -> None:
        # Roadmap item R7.6 — a visual-only header strip; pure waste to
        # keep updating while nobody can see it.
        if self._hidden_to_tray:
            return

        running = sorted(self.busy_actions.running_keys())

        if not running:
            self.activity_strip.hide()
            return

        self.activity_strip.show()

        if len(running) > 1:
            # Multiple actions running at once — a real count, not an
            # invented merged progress number (roadmap item 65's own
            # explicit instruction: don't fold unrelated work into one
            # fake percentage).
            self.activity_strip_label.setText(
                f"{len(running)} actions running"
            )
            self.activity_strip_bar.setRange(0, 0)
            return

        key = running[0]
        label = _BUSY_ACTION_LABELS.get(key, "Working…")
        progress = self._activity_progress.get(key)

        if progress is not None:
            stage, current, total = progress
            self.activity_strip_label.setText(
                f"{label} {stage} ({current}/{total})" if stage else
                f"{label} ({current}/{total})"
            )
            self.activity_strip_bar.setRange(0, total)
            self.activity_strip_bar.setValue(current)
            theme.style_determinate_progress_bar(self.activity_strip_bar)
        else:
            self.activity_strip_label.setText(label)
            self.activity_strip_bar.setRange(0, 0)  # indeterminate

    def _on_activity_progress(
            self, key: str, stage: str, current: int, total: int,
    ) -> None:
        # Roadmap item 65 (Phase 2.3's real consumer) — populated by any
        # run_worker(..., on_progress=...) caller that also passes a
        # matching key through here (none yet in this phase; Phase 7's
        # fingerprinting/duplicate-search progress is the first real
        # producer). Cleared the moment the action itself ends, via
        # _run_busy_worker's own wrapped_finished/wrapped_error.
        self._activity_progress[key] = (stage, current, total)
        self._render_activity_strip()

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebarPanel")
        # A plain QWidget subclass doesn't paint its own stylesheet
        # background by default in Qt (see notice.py's identical
        # WA_StyledBackground fix, found live in Phase 3) — the
        # `#sidebarPanel` QSS rule below would otherwise silently do
        # nothing.
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        sidebar.setStyleSheet(
            f"#sidebarPanel {{ background-color: {theme.BG_SIDEBAR}; "
            f"border-right: 1px solid {theme.BORDER}; }}"
        )

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(
            theme.SPACING_MD, theme.SPACING_LG,
            theme.SPACING_MD, theme.SPACING_LG,
        )
        layout.setSpacing(theme.SPACING_XS)

        wordmark = _Wordmark()
        layout.addWidget(wordmark)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: dict[str, QPushButton] = {}

        for key, label in _NAV_PAGES:
            button = _build_nav_button(label)
            self._nav_group.addButton(button)
            self._nav_buttons[key] = button
            button.clicked.connect(
                lambda _checked=False, key=key: self._show_page(key)
            )
            layout.addWidget(button)

        layout.addStretch()

        help_button = _build_nav_button("Help")
        self._nav_group.addButton(help_button)
        self._nav_buttons["help"] = help_button
        help_button.clicked.connect(lambda: self._show_page("help"))
        layout.addWidget(help_button)

        # Roadmap item 64 — directly below Help, same individually-built
        # pattern (a simple _show_page(key) lambda, no initial-tab-aware
        # handler needed).
        support_button = _build_nav_button("Support")
        self._nav_group.addButton(support_button)
        self._nav_buttons["support"] = support_button
        support_button.clicked.connect(lambda: self._show_page("support"))
        layout.addWidget(support_button)

        # Roadmap item 56 Phase 3 — reversed from item 48's "Settings
        # deliberately stays a separate dialog" decision: in fullscreen,
        # a second window reads as a dead end with no way back to the
        # shell. Now a real, checkable, nav-group page like Help, just
        # built individually (like Help) rather than via the generic
        # _NAV_PAGES loop, since it needs the initial_tab-aware handler
        # below, not the loop's plain `_show_page(key)`.
        self.settings_button = _build_nav_button("Settings")
        self._nav_group.addButton(self.settings_button)
        self._nav_buttons["settings"] = self.settings_button
        self.settings_button.setToolTip(help_text.TOOLTIP_OPEN_SETTINGS)
        # clicked emits a bool (checked state) — never connect it
        # directly to _on_settings_clicked, whose first real parameter
        # is initial_tab, not a checked flag.
        self.settings_button.clicked.connect(
            lambda: self._on_settings_clicked()
        )
        layout.addWidget(self.settings_button)

        return sidebar

    def _update_nav_badge(self, key: str, count: int) -> None:
        label = dict(_NAV_PAGES).get(key) or key.capitalize()
        button = self._nav_buttons[key]
        button.setText(f"{label}  ({count})" if count > 0 else label)

    def _build_dashboard_action_row(self) -> QHBoxLayout:
        # Roadmap item 7 — relocated from the old global QToolBar
        # (visible on every page regardless of which one was showing)
        # onto the Dashboard page itself, right after the "next step"
        # CTA, as secondary buttons — matches the task's own explicit
        # placement. Sync/Scan/Match renamed from their old cryptic
        # labels; still global-scoped (all playlists/locations/tracks,
        # matching the CLI — item 22), unaffected by which playlist is
        # selected. Download is playlist-scoped (the one exception) but
        # lives in the same row since it's the other real action a user
        # takes from here.
        row = QHBoxLayout()

        self.download_button = QPushButton("Download selected playlist")
        self.download_button.setToolTip(
            help_text.TOOLTIP_DOWNLOAD_SELECTED_PLAYLIST
        )
        self.download_button.clicked.connect(self._on_download_clicked)
        row.addWidget(self.download_button)

        self.sync_button = QPushButton("Refresh playlists")
        self.sync_button.setToolTip(help_text.TOOLTIP_SYNC_ALL_PLAYLISTS)
        self.sync_button.clicked.connect(self._on_sync_clicked)
        row.addWidget(self.sync_button)

        # Roadmap item 79 (P12) — a bare "&" in QPushButton text is a
        # Qt keyboard-mnemonic marker, consumed and rendered as an
        # underline under the following character ("Rescan _match
        # library"), not a literal ampersand. "&Help" at this file's
        # menu-bar construction is a real, intentional mnemonic and is
        # the only place this should ever appear unescaped.
        self.scan_button = QPushButton("Rescan and match library")
        self.scan_button.setToolTip(help_text.TOOLTIP_SCAN_ALL_LOCATIONS)
        self.scan_button.clicked.connect(self._on_scan_clicked)
        row.addWidget(self.scan_button)

        self.match_button = QPushButton("Re-match library")
        self.match_button.setToolTip(help_text.TOOLTIP_MATCH_ALL_TRACKS)
        self.match_button.clicked.connect(self._on_match_clicked)
        row.addWidget(self.match_button)

        row.addStretch()
        return row

    def _build_dashboard_page(self) -> QWidget:
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(theme.SPACING_MD)

        # Roadmap item 7 — "next step" guidance, one primary CTA at a
        # time. Above dashboard_notice (errors/warnings), so guidance
        # and errors never overwrite each other.
        self.next_step_notice = InlineNotice()
        self.next_step_notice.dismissed.connect(self._on_next_step_dismissed)
        content_layout.addWidget(self.next_step_notice)

        content_layout.addLayout(self._build_dashboard_action_row())

        # Persistent, dismissible — outside the 2s poll's reach, unlike
        # status_label below (see notice.py's own docstring for why
        # that distinction is load-bearing, not cosmetic).
        self.dashboard_notice = InlineNotice()
        content_layout.addWidget(self.dashboard_notice)

        dashboard_content = QWidget()
        layout = QHBoxLayout(dashboard_content)
        layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(dashboard_content, 1)

        self.playlist_list = QListWidget()
        self.playlist_list.currentItemChanged.connect(
            self._on_playlist_selected
        )
        # Roadmap item 72 (P1) — a real floor, sized to fit a realistic
        # long playlist name rather than 0px: FlowLayout above removes
        # the tagging row's own floor, but without this the playlist
        # panel could still be squeezed to a sliver by a wide window
        # dominated by other content. PLAYLIST_NAME_WIDTH_SAMPLE is an
        # untuned stand-in for "a realistically long real playlist
        # name," not a measured real value.
        PLAYLIST_NAME_WIDTH_SAMPLE = "A pretty long playlist name (2026)"
        name_width = self.playlist_list.fontMetrics().horizontalAdvance(
            PLAYLIST_NAME_WIDTH_SAMPLE
        )
        self.playlist_list.setMinimumWidth(
            name_width + theme.SPACING_LG * 2
        )
        layout.addWidget(theme.make_card(self.playlist_list), 1)

        right = QVBoxLayout()

        self.track_table = QTableWidget(0, 4)
        self.track_table.setHorizontalHeaderLabels(
            ["Track", "Status", "Progress", "Actions"]
        )
        theme.apply_table_defaults(self.track_table)
        # Multi-select needed for "Tag selected" (Step 7) — rows, not
        # cells, and extended (ctrl/shift-click) rather than the Qt
        # default of single-row selection.
        self.track_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.track_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.track_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.track_table.customContextMenuRequested.connect(
            self._on_track_table_context_menu
        )
        # Roadmap item 56 §2.4 — double-clicking a NEEDS_REVIEW/
        # AWAITING_REVIEW row jumps straight to the Review page. Wired
        # on cellDoubleClicked (not itemDoubleClicked) since the target
        # column can hold plain text with no QTableWidgetItem guarantee
        # beyond what _render_track_statuses always sets.
        self.track_table.cellDoubleClicked.connect(
            self._on_track_table_cell_double_clicked
        )
        self.track_area_stack = QStackedWidget()
        # Roadmap item 80 (P10.1) — the CARD, not the bare table, is
        # the stack's real page; setCurrentWidget() calls below target
        # this card. self.track_table itself is untouched by this and
        # still the widget every other call site reads/writes rows on.
        self.track_table_card = theme.make_card(self.track_table)
        self.track_area_stack.addWidget(self.track_table_card)
        self._track_empty_panel = self._build_track_empty_panel()
        self.track_area_stack.addWidget(self._track_empty_panel)
        right.addWidget(self.track_area_stack)

        self.tagging_controls_layout = self._build_tagging_controls()
        right.addLayout(self.tagging_controls_layout)

        self.tagging_results = QPlainTextEdit()
        self.tagging_results.setReadOnly(True)
        self.tagging_results.setMaximumHeight(120)
        self.tagging_results.setPlaceholderText(
            "Tagging results will appear here."
        )
        right.addWidget(self.tagging_results)

        self.status_label = QLabel("")
        right.addWidget(self.status_label)

        layout.addLayout(right, 3)

        return _build_page(
            "Dashboard", help_text.DASHBOARD_TAB_SUBTITLE, content,
        )

    def _build_search_page(self) -> QWidget:
        # Roadmap item 82 (P13.4) — a dedicated page between Dashboard
        # (already the most crowded page — item 51) and Downloads (a
        # status view, not a search/results one). search_manual()/
        # download_manual() reuse the EXACT SAME search + quality-
        # ranking logic download_playlist uses; nothing new is ranked
        # or scored here.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING_MD)

        form = QFormLayout()

        self.search_artist_edit = QLineEdit()
        self.search_artist_edit.setToolTip(help_text.TOOLTIP_SEARCH_ARTIST)
        self.search_artist_edit.setPlaceholderText("Artist")
        form.addRow("Artist:", self.search_artist_edit)

        self.search_title_edit = QLineEdit()
        self.search_title_edit.setToolTip(help_text.TOOLTIP_SEARCH_TITLE)
        self.search_title_edit.setPlaceholderText("Title")
        form.addRow("Title:", self.search_title_edit)

        layout.addLayout(form)

        controls = QHBoxLayout()

        self.search_button = QPushButton("Search")
        self.search_button.setProperty("variant", "primary")
        self.search_button.setToolTip(help_text.TOOLTIP_SEARCH_BUTTON)
        self.search_button.clicked.connect(self._on_search_clicked)
        controls.addWidget(self.search_button)

        self.download_best_button = QPushButton("Download best")
        self.download_best_button.setToolTip(help_text.TOOLTIP_DOWNLOAD_BEST)
        self.download_best_button.setEnabled(False)
        self.download_best_button.clicked.connect(
            self._on_download_best_clicked
        )
        controls.addWidget(self.download_best_button)

        controls.addStretch()
        layout.addLayout(controls)

        self.search_status_label = QLabel("")
        layout.addWidget(self.search_status_label)

        self.search_results_table = QTableWidget(
            0, len(_SEARCH_COLUMN_HEADERS),
        )
        self.search_results_table.setHorizontalHeaderLabels(
            _SEARCH_COLUMN_HEADERS
        )
        theme.apply_table_defaults(self.search_results_table)
        layout.addWidget(theme.make_card(self.search_results_table))

        self._search_artist = ""
        self._search_title = ""
        self._search_files: list[SoulseekFile] = []

        return _build_page("Search", help_text.SEARCH_TAB_SUBTITLE, content)

    def _on_search_clicked(self) -> None:
        artist = self.search_artist_edit.text().strip()
        title = self.search_title_edit.text().strip()

        if not artist or not title:
            self.search_status_label.setText(
                help_text.SEARCH_EMPTY_FIELDS_MESSAGE
            )
            return

        self.download_best_button.setEnabled(False)
        self.search_status_label.setText(
            f"Searching for '{artist} - {title}'…"
        )

        self._run_busy_worker(
            "search_manual", self.search_button,
            lambda: (
                self.application.download_service
                .search_manual(artist, title)
            ),
            status_label=self.search_status_label,
            on_finished=lambda files: self._render_search_results(
                artist, title, files,
            ),
        )

    def _render_search_results(
            self,
            artist: str,
            title: str,
            files: list[SoulseekFile],
    ) -> None:
        self._search_artist = artist
        self._search_title = title
        self._search_files = files

        self.download_best_button.setEnabled(bool(files))
        self.search_status_label.setText(
            help_text.format_search_result_count(len(files))
            if files else help_text.SEARCH_NO_RESULTS_MESSAGE
        )

        ranked = rank_candidates(files)
        self.search_results_table.setRowCount(len(ranked))

        # Purely for the per-row score display — never persisted, never
        # passed to select_downloads (which scores against the SAME
        # inputs internally). See quality.score_candidate's own
        # docstring.
        scoring_track = Track(
            id="", title=title, artist=artist, album="", duration_ms=0,
        )
        action_widgets: list[QWidget] = []

        for row, file in enumerate(ranked):
            self.search_results_table.setItem(
                row, _SearchColumn.USERNAME, QTableWidgetItem(file.username),
            )
            self.search_results_table.setItem(
                row, _SearchColumn.FILENAME, QTableWidgetItem(file.filename),
            )
            self.search_results_table.setItem(
                row, _SearchColumn.FORMAT, QTableWidgetItem(file.extension),
            )
            bitrate_text = (
                f"{file.bit_rate} kbps" if file.bit_rate else "—"
            )
            self.search_results_table.setItem(
                row, _SearchColumn.BITRATE, QTableWidgetItem(bitrate_text),
            )
            self.search_results_table.setItem(
                row, _SearchColumn.SIZE,
                QTableWidgetItem(format_file_size(file.size)),
            )
            self.search_results_table.setItem(
                row, _SearchColumn.LOCKED,
                QTableWidgetItem("Yes" if file.locked else "No"),
            )
            score = score_candidate(scoring_track, file)
            score_text = f"{score:.1f}" if score is not None else "—"
            self.search_results_table.setItem(
                row, _SearchColumn.SCORE, QTableWidgetItem(score_text),
            )

            action_widget = self._build_search_result_actions(file)
            action_widgets.append(action_widget)
            self.search_results_table.setCellWidget(
                row, _SearchColumn.ACTIONS, action_widget,
            )

        self._size_search_columns(action_widgets)

    def _size_search_columns(self, action_widgets: list[QWidget]) -> None:
        # Roadmap item 82 (P13.5) — the exact P4/item 73 lesson applied
        # to a brand-new table from day one, rather than repeating the
        # "nothing ever sets a column width" mistake.
        header = self.search_results_table.horizontalHeader()
        header.setMinimumSectionSize(40)
        header.setStretchLastSection(False)

        content_fit_columns = (
            _SearchColumn.USERNAME, _SearchColumn.FORMAT,
            _SearchColumn.BITRATE, _SearchColumn.SIZE,
            _SearchColumn.LOCKED, _SearchColumn.SCORE,
        )
        for column in content_fit_columns:
            header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents,
            )

        header.setSectionResizeMode(
            _SearchColumn.FILENAME, QHeaderView.ResizeMode.Stretch,
        )

        theme.size_action_column(
            self.search_results_table, _SearchColumn.ACTIONS, action_widgets,
        )

    def _build_search_result_actions(self, file: SoulseekFile) -> QWidget:
        download_button = QPushButton("Download this one")
        download_button.setToolTip(help_text.TOOLTIP_DOWNLOAD_THIS_ONE)
        download_button.clicked.connect(
            lambda: self._on_download_this_one_clicked(file, download_button)
        )
        return theme.cell_widget(download_button)

    def _on_download_best_clicked(self) -> None:
        # Roadmap item 82 (P13.5) — the headline action, so it gets the
        # shared busy_actions/activity-strip treatment like every other
        # persistent-button action on this page (Search included).
        if not self._search_files:
            return

        artist, title, files = (
            self._search_artist, self._search_title, self._search_files,
        )
        self._run_busy_worker(
            "download_manual", self.download_best_button,
            lambda: self.application.download_service.download_manual(
                artist, title, files=files,
            ),
            status_label=self.search_status_label,
            on_finished=lambda result: self.search_status_label.setText(
                help_text.format_search_download_result(result)
            ),
            on_error=self._on_manual_download_error,
        )

    def _on_download_this_one_clicked(
            self, file: SoulseekFile, button: QPushButton,
    ) -> None:
        # A per-row action on an ephemeral, per-render button — managed
        # directly via run_worker's own button= disable/re-enable, the
        # same pattern _on_confirm_review_candidate uses, rather than
        # the shared "download_manual" busy_actions key (which
        # "Download best" above already owns, and which only tracks
        # ONE persistent button per key).
        artist, title = self._search_artist, self._search_title
        run_worker(
            self.thread_pool,
            lambda: self.application.download_service.download_manual(
                artist, title, chosen=file,
            ),
            button=button,
            status_label=self.search_status_label,
            on_finished=lambda result: self.search_status_label.setText(
                help_text.format_search_download_result(result)
            ),
            on_error=self._on_manual_download_error,
        )

    def _on_manual_download_error(self, message: str) -> None:
        if "destination" in message.lower():
            self.search_status_label.setText(
                f"{message} Set a default download location in Settings."
            )

    def _build_downloads_page(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)

        # Task 9's aggregate remaining-time header — text only, empty
        # (no reserved-but-blank strip) whenever there's nothing active
        # to summarize; see _render_aggregate_eta.
        self.downloads_eta_label = QLabel("")
        self.downloads_eta_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(self.downloads_eta_label)

        self.downloads_table = QTableWidget(0, 5)
        self.downloads_table.setHorizontalHeaderLabels(
            ["Track", "Playlist", "Role", "Status", "Progress"]
        )
        self.downloads_table.horizontalHeader().setStretchLastSection(True)
        theme.apply_table_defaults(self.downloads_table)
        layout.addWidget(theme.make_card(self.downloads_table))

        return _build_page(
            "Downloads", help_text.DOWNLOADS_TAB_SUBTITLE, content,
        )

    def _build_history_page(self) -> QWidget:
        # Derived entirely from existing download_requests/local_files
        # rows via Application.history_service — no new table, no new
        # poll timer (this is a "look back" view, not an active-
        # progress one like Downloads; a manual Refresh button is
        # enough). The honest "not a permanent log" limits live in
        # HISTORY_PAGE_SUBTITLE, not repeated here.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Show:"))

        self.history_filter_combo = QComboBox()
        self.history_filter_combo.setToolTip(
            help_text.TOOLTIP_HISTORY_FILTER_COMBO
        )
        self.history_filter_combo.addItem("All", None)
        self.history_filter_combo.addItem("Downloaded", DOWNLOADED)
        self.history_filter_combo.addItem("Tagged", TAGGED)
        self.history_filter_combo.currentIndexChanged.connect(
            self._render_history_table
        )
        controls.addWidget(self.history_filter_combo)

        controls.addStretch()

        self.history_refresh_button = QPushButton("Refresh")
        self.history_refresh_button.setToolTip(
            help_text.TOOLTIP_HISTORY_REFRESH_BUTTON
        )
        self.history_refresh_button.clicked.connect(self._refresh_history)
        controls.addWidget(self.history_refresh_button)

        layout.addLayout(controls)

        self.history_status_label = QLabel("")
        layout.addWidget(self.history_status_label)

        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(
            ["When", "What", "Track", "Detail"]
        )
        self.history_table.horizontalHeader().setStretchLastSection(True)
        theme.apply_table_defaults(self.history_table)
        layout.addWidget(theme.make_card(self.history_table))

        # Raw, unfiltered events from the last real fetch — the filter
        # combo re-renders from this in memory rather than re-querying,
        # since it's already a bounded, already-fetched list (DEFAULT_
        # LIMIT), not a live/paginated one.
        self._history_events: list[HistoryEvent] = []

        return _build_page(
            "History", help_text.HISTORY_PAGE_SUBTITLE, content,
        )

    def _refresh_history(self) -> None:
        self._run_busy_worker(
            "history_refresh", self.history_refresh_button,
            self.application.history_service.get_recent_events,
            status_label=self.history_status_label,
            on_finished=self._on_history_fetched,
        )

    def _on_history_fetched(self, events: list[HistoryEvent]) -> None:
        self._history_events = events
        self._render_history_table()

    def _render_history_table(self) -> None:
        selected_type = self.history_filter_combo.currentData()
        events = (
            self._history_events if selected_type is None
            else [
                event for event in self._history_events
                if event.event_type == selected_type
            ]
        )

        if not self._history_events:
            self.history_status_label.setText(
                "No downloaded or tagged tracks yet."
            )
        else:
            self.history_status_label.setText("")

        self.history_table.setRowCount(len(events))

        for row, event in enumerate(events):
            self.history_table.setItem(
                row, 0, QTableWidgetItem(format_timestamp(event.occurred_at)),
            )
            self.history_table.setItem(
                row, 1,
                QTableWidgetItem(_HISTORY_EVENT_LABELS[event.event_type]),
            )
            self.history_table.setItem(
                row, 2,
                QTableWidgetItem(
                    f"{event.track_artist} - {event.track_title} "
                    f"({event.playlist_name})"
                ),
            )
            self.history_table.setItem(
                row, 3, QTableWidgetItem(event.detail),
            )

    def _build_sharing_page(self) -> QWidget:
        # Roadmap item 62 (Phase 7) — what Seeker is giving back to the
        # SoulSeek network it downloads from. See help_text.py's
        # SHARING_FRAMING_BODY for why this page frames things honestly
        # rather than as a persuasive pitch.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING_LG)

        framing_label = QLabel(help_text.SHARING_FRAMING_BODY)
        framing_label.setTextFormat(Qt.TextFormat.RichText)
        framing_label.setWordWrap(True)
        layout.addWidget(framing_label)

        controls = QHBoxLayout()
        self.sharing_summary_label = QLabel("")
        controls.addWidget(self.sharing_summary_label, 1)

        self.sharing_refresh_button = QPushButton("Refresh")
        self.sharing_refresh_button.setToolTip(help_text.TOOLTIP_SHARING_REFRESH)
        self.sharing_refresh_button.clicked.connect(self._refresh_sharing)
        controls.addWidget(self.sharing_refresh_button)
        layout.addLayout(controls)

        self.sharing_status_label = QLabel("")
        layout.addWidget(self.sharing_status_label)

        self.sharing_locations_table = QTableWidget(0, 5)
        self.sharing_locations_table.setHorizontalHeaderLabels(
            ["Location", "Shared", "Container Path", "Files", "Action"]
        )
        theme.apply_table_defaults(self.sharing_locations_table)
        layout.addWidget(theme.make_card(self.sharing_locations_table))

        uploads_label = QLabel("Currently uploading")
        uploads_label.setStyleSheet(
            f"font-weight: 600; color: {theme.TEXT};"
        )
        layout.addWidget(uploads_label)

        self.sharing_uploads_table = QTableWidget(0, 4)
        self.sharing_uploads_table.setHorizontalHeaderLabels(
            ["Peer", "File", "State", "Progress"]
        )
        self.sharing_uploads_table.setToolTip(help_text.TOOLTIP_UPLOADS_TABLE)
        self.sharing_uploads_table.horizontalHeader().setStretchLastSection(True)
        theme.apply_table_defaults(self.sharing_uploads_table)
        layout.addWidget(theme.make_card(self.sharing_uploads_table))

        self._current_sharing_reconciliation: list[LocationShareState] = []
        self._current_sharing_self_managed = False

        return _build_page("Sharing", help_text.SHARING_TAB_SUBTITLE, content)

    def _gather_sharing_snapshot(self) -> _SharingSnapshot:
        if not self.application.soulseek_configured:
            return _SharingSnapshot(
                configured=False, status=None, self_managed=False,
                reconciliation=[], uploads=[],
            )

        service = self.application.sharing_service

        return _SharingSnapshot(
            configured=True,
            status=service.get_status(),
            self_managed=service.is_self_managed(),
            reconciliation=service.get_reconciliation(),
            uploads=service.get_uploads(),
        )

    def _refresh_sharing(self) -> None:
        self._run_busy_worker(
            "sharing_refresh", self.sharing_refresh_button,
            self._gather_sharing_snapshot,
            status_label=self.sharing_status_label,
            on_finished=self._render_sharing,
        )

    def _trigger_sharing_poll(self) -> None:
        if not self._sharing_page_visited:
            return

        if self._sharing_poll_in_progress:
            return

        if not self.application.soulseek_configured:
            return

        self._sharing_poll_in_progress = True

        def on_finished(snapshot: _SharingSnapshot) -> None:
            self._sharing_poll_in_progress = False
            self._render_sharing(snapshot)

        def on_error(_: str) -> None:
            self._sharing_poll_in_progress = False

        run_worker(
            self.thread_pool,
            self._gather_sharing_snapshot,
            on_finished=on_finished,
            on_error=on_error,
        )

    def _render_sharing(self, snapshot: _SharingSnapshot) -> None:
        self._current_sharing_reconciliation = snapshot.reconciliation
        self._current_sharing_self_managed = snapshot.self_managed

        if not snapshot.configured:
            self.sharing_summary_label.setText(
                help_text.SHARING_UNCONFIGURED_NOTICE
            )
            self.sharing_locations_table.setRowCount(0)
            self.sharing_uploads_table.setRowCount(0)
            return

        status = snapshot.status
        assert status is not None

        managed_note = (
            "Managed by Seeker." if snapshot.self_managed
            else "Not managed by Seeker — sharing changes need manual steps."
        )
        self.sharing_summary_label.setText(
            f"{status.directories} directories, {status.files} files "
            f"shared. {managed_note}"
        )

        self._render_sharing_locations_table(snapshot.reconciliation)
        self._render_sharing_uploads_table(snapshot.uploads)

    def _render_sharing_locations_table(
            self, reconciliation: list[LocationShareState],
    ) -> None:
        table = self.sharing_locations_table
        table.setRowCount(len(reconciliation))
        action_widgets: list[QWidget] = []

        for row, state in enumerate(reconciliation):
            table.setItem(row, 0, QTableWidgetItem(state.location.name))
            table.setItem(
                row, 1, QTableWidgetItem("Yes" if state.shared else "No"),
            )
            table.setItem(
                row, 2,
                QTableWidgetItem(
                    state.share.local_path if state.share else ""
                ),
            )
            table.setItem(
                row, 3,
                QTableWidgetItem(
                    str(state.share.files) if state.share
                    and state.share.files is not None else ""
                ),
            )

            if state.shared:
                shared_widget = theme.cell_widget(QLabel("Shared"))
                action_widgets.append(shared_widget)
                table.setCellWidget(row, 4, shared_widget)
                continue

            button = QPushButton("Add to my SoulSeek share")
            button.setToolTip(help_text.TOOLTIP_ADD_LOCATION_TO_SHARE)
            button.clicked.connect(
                lambda _checked=False, location=state.location:
                self._on_add_location_to_share_clicked(location)
            )
            # Roadmap item 80 (P10.3) — the brief's own named example:
            # a bare setCellWidget(button) gets literally resized to
            # fill the whole cell rect (setCellWidget positions its
            # widget directly, bypassing normal layout sizing), reading
            # as a filled cell rather than a button. cell_widget()'s
            # trailing stretch absorbs the leftover width instead.
            button_widget = theme.cell_widget(button)
            action_widgets.append(button_widget)
            table.setCellWidget(row, 4, button_widget)

        self._size_sharing_locations_columns(action_widgets)

    def _size_sharing_locations_columns(
            self, action_widgets: list[QWidget],
    ) -> None:
        # Roadmap item R5 (5b.1).
        header = self.sharing_locations_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        theme.size_action_column(self.sharing_locations_table, 4, action_widgets)

    def _render_sharing_uploads_table(
            self, uploads: list[UploadStatus],
    ) -> None:
        table = self.sharing_uploads_table
        # Roadmap item 73 (P4 audit) — the SAME stale-span bug class as
        # the duplicates table, found live during that fix's own
        # "audit every other table" step: this table's empty-state
        # branch below sets a 4-column span at row 0; setRowCount()
        # doesn't clear it, so a transition from empty -> a real upload
        # left that span active, visually swallowing the new row's
        # filename/state/progress cells into column 0 even though their
        # real QTableWidgetItem data was set correctly underneath.
        table.clearSpans()
        table.setRowCount(len(uploads))

        active_keys: set[tuple[str, str]] = set()
        now = datetime.now(timezone.utc)

        for row, upload in enumerate(uploads):
            table.setItem(
                row, 0, QTableWidgetItem(upload.username or "")
            )
            table.setItem(
                row, 1, QTableWidgetItem(upload.filename or "")
            )
            table.setItem(row, 2, QTableWidgetItem(upload.state or ""))

            progress_text = ""

            if (
                    upload.username is not None
                    and upload.filename is not None
                    and upload.bytes_transferred is not None
            ):
                key = (upload.username, upload.filename)
                active_keys.add(key)
                self._upload_eta_tracker.record(
                    key, upload.bytes_transferred, now,
                )
                progress_text = self._upload_eta_tracker.describe(
                    key, upload.size,
                )

            table.setItem(row, 3, QTableWidgetItem(progress_text))

        self._upload_eta_tracker.evict_except(active_keys)

        if not uploads:
            table.setRowCount(1)
            table.setSpan(0, 0, 1, 4)
            table.setItem(0, 0, QTableWidgetItem(help_text.NO_UPLOADS_LABEL))

    def _on_add_location_to_share_clicked(
            self, location: LibraryLocation,
    ) -> None:
        service = self.application.sharing_service
        plan = service.preview_add_location(location)

        if not self._current_sharing_self_managed:
            QMessageBox.information(
                self,
                help_text.SHARING_ADD_CONFIRM_TITLE,
                help_text.SHARING_NOT_SELF_MANAGED_NOTICE
                + "\n\n"
                + plan.compose_volume_line.strip()
                + "\n"
                + plan.slskd_share_directory_line.strip(),
            )
            return

        confirmed = QMessageBox.question(
            self,
            help_text.SHARING_ADD_CONFIRM_TITLE,
            help_text.format_add_to_share_confirm_body(
                location.name, location.path, plan.container_path,
            ),
        )

        if confirmed != QMessageBox.StandardButton.Yes:
            return

        run_worker(
            self.thread_pool,
            lambda: service.add_location_to_share(location, confirm=True),
            status_label=self.sharing_status_label,
            on_finished=self._on_add_location_to_share_finished,
        )

    def _on_add_location_to_share_finished(
            self, result: SharingApplyResult,
    ) -> None:
        ready_note = "" if result.became_ready else " Still finishing the scan."
        self.sharing_status_label.setText(
            f"'{result.location.name}' shared — "
            f"{result.directories_after} directories, "
            f"{result.files_after} files "
            f"(was {result.directories_before}/{result.files_before})."
            + ready_note
        )
        self._refresh_sharing()

    def _build_help_page(self) -> QWidget:
        # Real content (walkthrough/troubleshooting/data locations),
        # not a placeholder. Every data-location value below is a real,
        # already-resolved path (Application.data_locations) — cheap,
        # synchronous, purely local string formatting, so this builds
        # directly at page-construction time like AboutDialog's own
        # version() lookup, no lazy-load/run_worker needed (contrast
        # with Duplicates/History, which do a real DB read).
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(theme.SPACING_LG)

        walkthrough_label = QLabel(help_text.HELP_WALKTHROUGH_BODY)
        walkthrough_label.setTextFormat(Qt.TextFormat.RichText)
        walkthrough_label.setWordWrap(True)
        inner_layout.addWidget(walkthrough_label)

        troubleshooting_label = QLabel(help_text.HELP_TROUBLESHOOTING_BODY)
        troubleshooting_label.setTextFormat(Qt.TextFormat.RichText)
        troubleshooting_label.setWordWrap(True)
        inner_layout.addWidget(troubleshooting_label)

        locations = self.application.data_locations

        data_heading = QLabel(help_text.HELP_DATA_LOCATIONS_HEADING)
        data_heading.setTextFormat(Qt.TextFormat.RichText)
        inner_layout.addWidget(data_heading)

        intro_label = QLabel(help_text.HELP_DATA_LOCATIONS_INTRO)
        intro_label.setWordWrap(True)
        inner_layout.addWidget(intro_label)

        # Roadmap item 81 (0.2) — said explicitly, in the app, not just
        # in CLAUDE.md: a "fix didn't work on the other account" report
        # is very often a different-database report, not a
        # different-behavior one.
        per_account_label = QLabel(
            help_text.HELP_DATA_LOCATIONS_PER_ACCOUNT_NOTE
        )
        per_account_label.setWordWrap(True)
        inner_layout.addWidget(per_account_label)

        # Roadmap item 81 (0.1) — next to the data locations, not
        # buried in About, since this page is exactly where "which
        # build is this?" troubleshooting starts.
        build_identity = help_text.format_build_identity(
            _build_info.GIT_SHA, _build_info.GIT_DESCRIBE,
            _build_info.BUILT_AT,
        )
        build_label = QLabel(
            f"{help_text.HELP_BUILD_IDENTITY_LABEL} {build_identity}"
        )
        build_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        inner_layout.addWidget(build_label)

        locations_form = QFormLayout()
        for label_text, path in (
                (help_text.DATA_LOCATION_DATABASE_LABEL, locations.database_path),
                (help_text.DATA_LOCATION_CONFIG_LABEL, locations.config_path),
                (
                    help_text.DATA_LOCATION_SPOTIFY_TOKEN_LABEL,
                    locations.spotify_token_path,
                ),
                (help_text.DATA_LOCATION_SLSKD_LABEL, locations.slskd_data_dir),
        ):
            path_label = QLabel(str(path))
            path_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            path_label.setWordWrap(True)
            locations_form.addRow(label_text, path_label)
        inner_layout.addLayout(locations_form)

        open_folder_button = QPushButton(help_text.OPEN_DATA_FOLDER_BUTTON_TEXT)
        open_folder_button.setToolTip(help_text.TOOLTIP_OPEN_DATA_FOLDER)
        open_folder_button.clicked.connect(self._on_open_data_folder_clicked)
        inner_layout.addWidget(
            open_folder_button, alignment=Qt.AlignmentFlag.AlignLeft,
        )

        inner_layout.addStretch()

        # Scrollable — the walkthrough + troubleshooting + data-location
        # sections together are genuinely longer than this app's
        # 960x640 minimum window (item 48), unlike every other page.
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setWidget(inner)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(scroll_area)

        return _build_page("Help", help_text.HELP_PAGE_SUBTITLE, content)

    def _on_open_data_folder_clicked(self) -> None:
        _open_in_file_manager(self.application.data_locations.base_dir)

    def _build_support_page(self) -> QWidget:
        # Roadmap item 64 — a real sidebar page, directly below Help.
        # Every string here is entirely static copy (no service/DB call
        # at all, unlike Duplicates/History) — built directly at
        # construction time, the same "nothing to lazily load" reasoning
        # _build_help_page's own docstring already gives for its
        # Application.data_locations lookup, just with even less to
        # fetch here.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING_LG)

        framing_label = QLabel(help_text.SUPPORT_PAGE_FRAMING_BODY)
        framing_label.setTextFormat(Qt.TextFormat.RichText)
        framing_label.setWordWrap(True)
        layout.addWidget(framing_label)

        layout.addLayout(_build_support_links_row())

        non_financial_heading = QLabel(
            help_text.SUPPORT_PAGE_NON_FINANCIAL_HEADING
        )
        non_financial_heading.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(non_financial_heading)

        report_bug_label = QLabel(help_text.SUPPORT_PAGE_REPORT_BUG_BODY)
        report_bug_label.setTextFormat(Qt.TextFormat.RichText)
        report_bug_label.setWordWrap(True)
        report_bug_label.setOpenExternalLinks(True)
        layout.addWidget(report_bug_label)

        share_library_label = QLabel(help_text.SUPPORT_PAGE_SHARE_LIBRARY_BODY)
        share_library_label.setTextFormat(Qt.TextFormat.RichText)
        share_library_label.setWordWrap(True)
        layout.addWidget(share_library_label)

        go_to_sharing_button = QPushButton(
            help_text.SUPPORT_PAGE_GO_TO_SHARING_BUTTON_TEXT
        )
        go_to_sharing_button.clicked.connect(
            lambda: self._show_page("sharing")
        )
        layout.addWidget(
            go_to_sharing_button, alignment=Qt.AlignmentFlag.AlignLeft,
        )

        author_label = QLabel(help_text.ABOUT_DIALOG_AUTHOR_LINE)
        author_label.setTextFormat(Qt.TextFormat.RichText)
        author_label.setWordWrap(True)
        author_label.setOpenExternalLinks(True)
        layout.addWidget(author_label)

        layout.addStretch()

        return _build_page(
            "Support", help_text.SUPPORT_TAB_SUBTITLE, content,
        )

    def _build_help_menu(self) -> None:
        menu_bar = self.menuBar()
        help_menu = menu_bar.addMenu("&Help")

        about_action = QAction(help_text.ABOUT_MENU_TEXT, self)
        about_action.triggered.connect(self._on_about_clicked)
        help_menu.addAction(about_action)

        # Real, live GitHub call — user-triggered ONLY (this one menu
        # action), never on a timer or anywhere near startup/
        # construction. See update_check.py's own docstring for why.
        self.check_for_updates_action = QAction(
            help_text.CHECK_FOR_UPDATES_MENU_TEXT, self,
        )
        self.check_for_updates_action.triggered.connect(
            self._on_check_for_updates_clicked
        )
        help_menu.addAction(self.check_for_updates_action)

    def _on_about_clicked(self) -> None:
        dialog = AboutDialog(self)
        dialog.exec()

    def _on_check_for_updates_clicked(self) -> None:
        self.check_for_updates_action.setEnabled(False)
        run_worker(
            self.thread_pool,
            check_for_update,
            on_finished=self._show_update_check_result,
            on_error=self._on_update_check_error,
        )

    def _show_update_check_result(self, result: UpdateCheckResult) -> None:
        self.check_for_updates_action.setEnabled(True)

        box = QMessageBox(self)
        box.setWindowTitle(help_text.UPDATE_CHECK_DIALOG_TITLE)

        if result.status == UpdateStatus.UP_TO_DATE:
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(
                f"You're up to date (v{result.installed_version})."
            )
        elif result.status == UpdateStatus.UPDATE_AVAILABLE:
            box.setIcon(QMessageBox.Icon.Information)
            text = (
                f"A new version is available: {result.latest_version} "
                f"(you have v{result.installed_version})."
            )
            if result.release_url:
                text += f"<br><a href=\"{result.release_url}\">" \
                        f"View the release</a>"
                box.setTextFormat(Qt.TextFormat.RichText)
            box.setText(text)
        else:
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(f"Couldn't check for updates: {result.reason}")

        box.exec()

    def _on_update_check_error(self, message: str) -> None:
        # check_for_update() itself never raises (see its own
        # docstring) — this only exists as a defensive fallback for a
        # failure in run_worker's own dispatch, not an expected path.
        self.check_for_updates_action.setEnabled(True)
        QMessageBox.warning(
            self, help_text.UPDATE_CHECK_DIALOG_TITLE,
            f"Couldn't check for updates: {message}",
        )

    def _build_tagging_controls(self) -> FlowLayout:
        # Shared by all three triggers (per-track, "Tag selected",
        # "Tag playlist") — one set of options, not three independently
        # configurable copies. --bpm-range requiring --analyze-audio
        # (the CLI's own validation) is enforced structurally here by
        # hiding the range fields entirely while the checkbox is
        # unchecked, rather than validating the combination after the
        # fact the way the CLI has to.
        #
        # Roadmap item 72 (P1) — a plain QHBoxLayout's minimum width is
        # the SUM of its children's minimum widths, which made this
        # 9-widget row impose a ~900-1000px floor on the whole
        # dashboard page, squeezing the playlist panel next to it down
        # to almost nothing. FlowLayout fixes both halves at once: it
        # reflows 1-row -> 2-row -> 3-row purely from available width,
        # and its own minimumSize() is just the widest single item.
        # Roadmap item 79 (P11) — bare FlowLayout() leaves h_spacing/
        # v_spacing at -1, which falls through to _smart_spacing()'s
        # PM_LayoutHorizontalSpacing style query — approximately zero
        # under this app's Fusion styling, so the buttons touched.
        # These are deliberate, chosen values, not style-derived ones.
        controls = FlowLayout(
            h_spacing=theme.SPACING_SM, v_spacing=theme.SPACING_SM,
        )

        self.analyze_audio_checkbox = QCheckBox("Analyze audio (BPM/Key)")
        self.analyze_audio_checkbox.setToolTip(
            help_text.TOOLTIP_ANALYZE_AUDIO_CHECKBOX
        )
        self.analyze_audio_checkbox.toggled.connect(
            self._on_analyze_audio_toggled
        )
        controls.addWidget(self.analyze_audio_checkbox)

        self.bpm_min_edit = QLineEdit()
        self.bpm_min_edit.setPlaceholderText("Min BPM")
        self.bpm_min_edit.setToolTip(help_text.TOOLTIP_BPM_MIN)
        self.bpm_min_edit.hide()
        controls.addWidget(self.bpm_min_edit)

        self.bpm_max_edit = QLineEdit()
        self.bpm_max_edit.setPlaceholderText("Max BPM")
        self.bpm_max_edit.setToolTip(help_text.TOOLTIP_BPM_MAX)
        self.bpm_max_edit.hide()
        controls.addWidget(self.bpm_max_edit)

        self.force_retag_checkbox = QCheckBox("Re-tag already tagged files")
        self.force_retag_checkbox.setToolTip(
            help_text.TOOLTIP_FORCE_RETAG_CHECKBOX
        )
        controls.addWidget(self.force_retag_checkbox)

        self.tag_selected_button = QPushButton("Tag selected")
        self.tag_selected_button.setToolTip(help_text.TOOLTIP_TAG_SELECTED)
        self.tag_selected_button.clicked.connect(
            self._on_tag_selected_clicked
        )
        controls.addWidget(self.tag_selected_button)

        self.tag_playlist_button = QPushButton("Tag playlist")
        self.tag_playlist_button.setToolTip(help_text.TOOLTIP_TAG_PLAYLIST)
        self.tag_playlist_button.clicked.connect(
            self._on_tag_playlist_clicked
        )
        controls.addWidget(self.tag_playlist_button)

        # Roadmap item 66 (Phase 5.2) — a narrower, safer repair than
        # forcing a full re-tag: re-embeds art only, never text tags.
        self.fix_missing_art_button = QPushButton("Fix missing cover art")
        self.fix_missing_art_button.setToolTip(
            help_text.TOOLTIP_FIX_MISSING_ART
        )
        self.fix_missing_art_button.clicked.connect(
            self._on_fix_missing_art_clicked
        )
        controls.addWidget(self.fix_missing_art_button)

        # Roadmap item 66 (Phase 5.3) — the one-click fix for the
        # "no_url" case: a real sync-tracks call, honest about being a
        # real Spotify API call.
        self.fill_missing_art_urls_button = QPushButton(
            "Fill missing art URLs"
        )
        self.fill_missing_art_urls_button.setToolTip(
            help_text.TOOLTIP_FILL_MISSING_ART_URLS
        )
        self.fill_missing_art_urls_button.clicked.connect(
            self._on_fill_missing_art_urls_clicked
        )
        controls.addWidget(self.fill_missing_art_urls_button)

        # Roadmap item 67 (Phase 6.4) — always a preview first (item
        # 27's "no gate for tag-writing" precedent does NOT extend
        # here: this moves/replaces a real file).
        self.rename_files_button = QPushButton("Rename files to match metadata")
        self.rename_files_button.setToolTip(help_text.TOOLTIP_RENAME_FILES)
        self.rename_files_button.clicked.connect(
            self._on_rename_files_clicked
        )
        controls.addWidget(self.rename_files_button)

        return controls

    def _on_analyze_audio_toggled(self, checked: bool) -> None:
        self.bpm_min_edit.setVisible(checked)
        self.bpm_max_edit.setVisible(checked)

    def _resolve_tag_options(
            self,
    ) -> tuple[bool, tuple[float, float] | None, bool]:
        force = self.force_retag_checkbox.isChecked()
        analyze_audio = self.analyze_audio_checkbox.isChecked()

        if not analyze_audio:
            return False, None, force

        min_text = self.bpm_min_edit.text().strip()
        max_text = self.bpm_max_edit.text().strip()

        if not min_text and not max_text:
            # A range is optional even with analysis on — matches the
            # CLI, where --analyze-audio alone (no --bpm-range) is
            # perfectly valid.
            return True, None, force

        if not min_text or not max_text:
            raise ValueError(
                "Enter both a min and max BPM, or leave both blank."
            )

        try:
            return True, (float(min_text), float(max_text)), force
        except ValueError:
            raise ValueError("BPM range must be numeric.")

    def _render_tag_result(self, result: dict[str, Any]) -> None:
        self.status_label.setText("")

        lines = [
            f"Tagged: {result['tagged']} "
            f"({result['tagged_without_art']} without cover art, "
            f"{result['tagged_art_rarely_supported_format']} with art "
            f"in a rarely-supported format), "
            f"Skipped (no match): {result['skipped_no_match']}, "
            f"Skipped (unsupported format): "
            f"{result['skipped_format_unsupported']}, "
            f"Skipped (already tagged): "
            f"{result['skipped_already_tagged']}, "
            f"Skipped (already analyzed): "
            f"{result['skipped_already_analyzed']}, "
            f"Failed: {result['failed']}."
        ]

        for detail in result["details"]:
            lines.append(f"  [{detail['reason']}] {detail['message']}")

        self.tagging_results.setPlainText("\n".join(lines))

        # Roadmap item 56 Phase 4.2 — the UI must never show a bare
        # "success" when any part of it wasn't: routed through
        # InlineNotice (item 47), not status_label, so it survives the
        # next 2s poll tick; per-track detail is already reachable in
        # the persistent tagging_results panel above, itself unaffected
        # by that same clearing bug (a real QPlainTextEdit, never wired
        # into status_label's plumbing at all).
        self._show_tag_result_notice(result)

    def _show_tag_result_notice(self, result: dict[str, Any]) -> None:
        # Roadmap item 66 (Phase 5.1) — the real gap found in Phase 0.4:
        # this early return is still correct (nothing was even in
        # scope), but every real outcome AFTER it — including "every
        # selected track was already tagged" — now gets a message via
        # help_text.format_tag_result_notice, not just tagged/without_
        # art/failed.
        if result["tagged"] == 0 and not result["details"]:
            return

        message, kind = help_text.format_tag_result_notice(result)

        # Roadmap item 75 (P6, 6.2) — any track this run skipped as
        # already-tagged had its cover art never even looked at (see
        # format_tag_result_notice's own docstring); offer the real
        # next action right on the notice rather than leaving the user
        # to find "Fix missing cover art" on their own.
        if result.get("skipped_already_tagged", 0) > 0:
            self.dashboard_notice.show_message(
                message, kind=kind,
                action_text="Fix missing cover art",
                on_action=self._on_fix_missing_art_clicked,
            )
        else:
            self.dashboard_notice.show_message(message, kind=kind)

    def _selected_track_ids(self) -> list[str]:
        rows = sorted(
            {index.row() for index in self.track_table.selectionModel().selectedRows()}
        )
        return [self._current_track_statuses[row].track.id for row in rows]

    def _build_track_actions(self, status: TrackStatus) -> QWidget:
        # No button at all outside IN_LIBRARY — tag_tracks would just
        # report skipped_no_match for anything else, so there's nothing
        # real to offer here (same "blank cell, not a misleading
        # control" precedent as the Downloads tab's progress bars).
        if status.state != IN_LIBRARY:
            return QWidget()

        track_id = status.track.id

        if status.tagged_at is None:
            tag_button = QPushButton("Tag")
            tag_button.setToolTip(help_text.TOOLTIP_TAG_TRACK_ROW)
            tag_button.clicked.connect(
                lambda: self._on_tag_track_clicked(track_id, tag_button)
            )
            return theme.cell_widget(tag_button)

        tagged_label = QLabel("Tagged")
        tagged_label.setProperty("badge", "muted")
        tagged_label.setToolTip(f"Tagged {format_timestamp(status.tagged_at)}")
        return theme.cell_widget(tagged_label)

    def _on_track_table_context_menu(self, position: Any) -> None:
        row = self.track_table.rowAt(position.y())

        if row < 0 or row >= len(self._current_track_statuses):
            return

        status = self._current_track_statuses[row]

        if status.state != IN_LIBRARY or status.tagged_at is None:
            # Nothing this menu offers applies to an untagged or
            # not-in-library row — same "no control where there's
            # nothing real to do" precedent as the Actions column
            # itself, just via a context menu instead of a blank cell.
            return

        menu = QMenu(self)
        retag_action = QAction("Re-tag", self)
        retag_action.triggered.connect(
            lambda: self._on_retag_track_clicked(status.track.id)
        )
        menu.addAction(retag_action)
        menu.exec(self.track_table.viewport().mapToGlobal(position))

    def _on_tag_track_clicked(self, track_id: str, button: QPushButton) -> None:
        try:
            analyze_audio, bpm_range, force = self._resolve_tag_options()
        except ValueError as error:
            self.dashboard_notice.show_message(str(error), kind="error")
            return

        run_worker(
            self.thread_pool,
            lambda: self.application.metadata_service.tag_tracks(
                [track_id],
                analyze_audio=analyze_audio,
                expected_bpm_range=bpm_range,
                force=force,
            ),
            button=button,
            status_label=self.status_label,
            on_finished=self._render_tag_result,
        )

    def _on_retag_track_clicked(self, track_id: str) -> None:
        # The context menu's "Re-tag" always forces, independent of the
        # tagging panel's own checkbox — right-clicking a specific
        # already-tagged row and choosing "Re-tag" is an explicit,
        # unambiguous request to redo exactly this one file, the same
        # way the CLI's --force does for a whole playlist.
        try:
            analyze_audio, bpm_range, _ = self._resolve_tag_options()
        except ValueError as error:
            self.dashboard_notice.show_message(str(error), kind="error")
            return

        run_worker(
            self.thread_pool,
            lambda: self.application.metadata_service.tag_tracks(
                [track_id],
                analyze_audio=analyze_audio,
                expected_bpm_range=bpm_range,
                force=True,
            ),
            status_label=self.status_label,
            on_finished=self._render_tag_result,
        )

    def _on_tag_selected_clicked(self) -> None:
        track_ids = self._selected_track_ids()

        if not track_ids:
            self.dashboard_notice.show_message(
                "Select at least one track first.", kind="warning",
            )
            return

        try:
            analyze_audio, bpm_range, force = self._resolve_tag_options()
        except ValueError as error:
            self.dashboard_notice.show_message(str(error), kind="error")
            return

        self._run_busy_worker(
            "tag_selected", self.tag_selected_button,
            lambda: self.application.metadata_service.tag_tracks(
                track_ids,
                analyze_audio=analyze_audio,
                expected_bpm_range=bpm_range,
                force=force,
            ),
            status_label=self.status_label,
            on_finished=self._render_tag_result,
        )
        # Analysis in particular does real, potentially slow per-track
        # work — an in-progress note beyond just the disabled button,
        # for anything wider than a single track.
        self.status_label.setText(f"Tagging {len(track_ids)} selected track(s)...")

    def _on_tag_playlist_clicked(self) -> None:
        if self.selected_playlist is None:
            self.dashboard_notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        try:
            analyze_audio, bpm_range, force = self._resolve_tag_options()
        except ValueError as error:
            self.dashboard_notice.show_message(str(error), kind="error")
            return

        playlist_name = self.selected_playlist.name

        self._run_busy_worker(
            "tag_playlist", self.tag_playlist_button,
            lambda: self.application.metadata_service.tag_playlist(
                playlist_name,
                analyze_audio=analyze_audio,
                expected_bpm_range=bpm_range,
                force=force,
            ),
            status_label=self.status_label,
            on_finished=self._render_tag_result,
        )
        self.status_label.setText(f"Tagging playlist '{playlist_name}'...")

    def _on_fix_missing_art_clicked(self) -> None:
        if self.selected_playlist is None:
            self.dashboard_notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        playlist_name = self.selected_playlist.name

        self._run_busy_worker(
            "fix_missing_art", self.fix_missing_art_button,
            lambda: self.application.metadata_service
            .fix_missing_art_for_playlist(playlist_name),
            status_label=self.status_label,
            on_finished=self._render_fix_art_result,
        )
        self.status_label.setText(
            f"Fixing cover art for '{playlist_name}'..."
        )

    def _render_fix_art_result(self, result: dict[str, Any]) -> None:
        self.status_label.setText("")

        lines = [
            f"Fixed: {result['fixed']}, "
            f"Fixed (rarely-supported format): "
            f"{result['fixed_wav_rarely_supported']}, "
            f"Already correct: {result['already_correct']}, "
            f"No art URL: {result['no_url']}, "
            f"Download failed: {result['download_failed']}, "
            f"Embed failed: {result['embed_failed']}, "
            f"Unsupported format: {result['format_unsupported']}, "
            f"Skipped (no match): {result['skipped_no_match']}, "
            f"Failed: {result['failed']}."
        ]

        for detail in result["details"]:
            lines.append(f"  [{detail['reason']}] {detail['message']}")

        self.tagging_results.setPlainText("\n".join(lines))

        message, kind = help_text.format_fix_art_result_message(result)
        self.dashboard_notice.show_message(message, kind=kind)

    def _on_fill_missing_art_urls_clicked(self) -> None:
        if self.selected_playlist is None:
            self.dashboard_notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        playlist = self.selected_playlist

        self._run_busy_worker(
            "fill_missing_art_urls", self.fill_missing_art_urls_button,
            lambda: self.application.sync_service.sync_playlist_tracks(
                playlist
            ),
            status_label=self.status_label,
            on_finished=self._on_fill_missing_art_urls_finished,
        )
        self.status_label.setText(
            f"Refreshing '{playlist.name}' from Spotify..."
        )

    def _on_fill_missing_art_urls_finished(self, art_urls_filled: int) -> None:
        self._poll_selected_playlist()

        if art_urls_filled:
            plural = "s" if art_urls_filled != 1 else ""
            self.dashboard_notice.show_message(
                f"Filled in {art_urls_filled} missing album art "
                f"URL{plural}.",
                kind="success",
            )
        else:
            self.dashboard_notice.show_message(
                "No missing album art URLs found.", kind="info",
            )

    def _on_rename_files_clicked(self) -> None:
        if self.selected_playlist is None:
            self.dashboard_notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        playlist_name = self.selected_playlist.name

        self._run_busy_worker(
            "rename_files", self.rename_files_button,
            lambda: self.application.metadata_service.plan_renames(
                playlist_name=playlist_name,
            ),
            status_label=self.status_label,
            on_finished=lambda plans: self._open_rename_preview_dialog(
                playlist_name, plans,
            ),
        )

    def _open_rename_preview_dialog(
            self, playlist_name: str, plans: list[RenamePlan],
    ) -> None:
        dialog = RenamePreviewDialog(self, playlist_name, plans)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.busy_actions.begin(
            "rename_files", self.rename_files_button, "Renaming…",
        )
        self._render_activity_strip()

        run_worker(
            self.thread_pool,
            lambda: self.application.metadata_service.apply_renames(plans),
            status_label=self.status_label,
            on_finished=self._on_rename_files_finished,
            on_error=lambda _message: self._reset_rename_files_button(),
        )

    def _reset_rename_files_button(self) -> None:
        self.busy_actions.end("rename_files")
        self._render_activity_strip()

    def _on_rename_files_finished(self, result: Any) -> None:
        self._reset_rename_files_button()
        self._poll_selected_playlist()

        counts = {
            "renamed": result.renamed,
            "collisions": result.collisions,
            "failed": result.failed,
        }
        lines = [
            f"Renamed: {result.renamed} ({result.collisions} with a "
            f"numbered suffix), Already correct: {result.already_correct}, "
            f"Not auto-matched: {result.skipped_not_auto_matched}, "
            f"No local file: {result.skipped_no_local_file}, "
            f"Failed: {result.failed}."
        ]

        for detail in result.details:
            lines.append(f"  [{detail['reason']}] {detail['message']}")

        self.tagging_results.setPlainText("\n".join(lines))

        message, kind = help_text.format_rename_result_message(counts)
        self.dashboard_notice.show_message(message, kind=kind)

    def _build_review_content(self) -> QWidget:
        # Two independent sections, per item 26: SoulSeek needs-review
        # candidates (item 17's tier, gaining its first real
        # confirm/reject action here) and Phase 2 upgrade confirmations
        # (item 8's ready_for_review flow, previously CLI-only via
        # `seeker downloads review`). Both are driven by DownloadService
        # methods that were built explicit-decision and input()-free
        # specifically so a UI could call them directly — see CLAUDE.md
        # item 26 §0/§1.
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("SoulSeek candidates needing confirmation"))

        self.review_needs_table = QTableWidget(0, 4)
        self.review_needs_table.setHorizontalHeaderLabels(
            ["Track", "Score", "Candidate", "Actions"]
        )
        theme.apply_table_defaults(self.review_needs_table)
        layout.addWidget(theme.make_card(self.review_needs_table))

        upgrades_header_row = QHBoxLayout()
        upgrades_header_row.addWidget(
            QLabel("Downloaded upgrades ready for review")
        )
        upgrades_header_row.addStretch()
        # Roadmap item R3.1 — "Replace all". Real count set/refreshed
        # in _render_pending_upgrades, so it's never stale against
        # what's actually in the table.
        self.replace_all_upgrades_button = QPushButton("Replace all")
        self.replace_all_upgrades_button.setToolTip(
            help_text.TOOLTIP_REPLACE_ALL_UPGRADES
        )
        self.replace_all_upgrades_button.setEnabled(False)
        self.replace_all_upgrades_button.clicked.connect(
            self._on_replace_all_upgrades_clicked
        )
        upgrades_header_row.addWidget(self.replace_all_upgrades_button)
        layout.addLayout(upgrades_header_row)

        self.review_upgrades_table = QTableWidget(0, 4)
        self.review_upgrades_table.setHorizontalHeaderLabels(
            ["Track", "Current", "New quality", "Actions"]
        )
        theme.apply_table_defaults(self.review_upgrades_table)
        layout.addWidget(theme.make_card(self.review_upgrades_table))

        # Third section — roadmap item 56 Phase 2, closing item 7's
        # long-outstanding gap: needs_review LOCAL-FILE matches (distinct
        # from the SoulSeek candidates table above) never had a
        # confirm/reject UI at all before this.
        layout.addWidget(QLabel("Local library matches needing confirmation"))

        self.review_local_table = QTableWidget(0, 5)
        self.review_local_table.setHorizontalHeaderLabels(
            ["Track", "Matched file", "Location", "Score", "Actions"]
        )
        theme.apply_table_defaults(self.review_local_table)
        layout.addWidget(theme.make_card(self.review_local_table))

        # Roadmap item R2.1 — the 2s poll_timer rebuilds this table's
        # checkboxes from scratch every tick (see poll_timer's own
        # comment on why); nothing carried the checked state across
        # that rebuild before. Keyed by the stable
        # UpgradeReviewDetails.request_id, never row index — pruned to
        # only rows still present on every render (R2.3).
        self._upgrade_delete_checked: set[int] = set()
        self._current_pending_upgrades: PendingUpgrades = []

        return tab

    def _build_duplicates_content(self) -> QWidget:
        # Fingerprint computation + clustering/scoring were built and
        # live-verified first, read-only, per roadmap item 5's own
        # build order; the delete action below (item 40) is the later,
        # explicitly-scoped follow-up. Scoped to one library location
        # at a time (the location combo below), never merged across all
        # of them.
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)

        # Roadmap item 56 Phase 6.4 — persistent, cumulative, and
        # celebratory. Hidden entirely at zero — "an empty milestone is
        # worse than no milestone" (the brief's own framing, matching
        # this app's existing "blank, not a misleading control"
        # precedent for a genuinely-nothing-to-show state).
        self.duplicates_milestone_label = QLabel("")
        self.duplicates_milestone_label.hide()
        layout.addWidget(self.duplicates_milestone_label)

        controls = QHBoxLayout()

        self.duplicates_location_combo = QComboBox()
        self.duplicates_location_combo.setToolTip(
            help_text.TOOLTIP_DUPLICATES_LOCATION_COMBO
        )
        self.duplicates_location_combo.currentIndexChanged.connect(
            self._on_duplicates_location_changed
        )
        controls.addWidget(self.duplicates_location_combo)

        # Roadmap item 77 (P9) — the combo above used to be disabled in
        # folder-scope mode (reversed: see item 68 Phase 7.2's original
        # comment here, and CLAUDE.md item 77). It stays enabled now —
        # once resolve_folder_scopes() does most-specific-wins matching
        # (P8.2), the selected location is a genuinely useful tiebreak
        # preference for an ambiguous (nested-location) folder, not
        # dead weight the user had to uncheck-then-recheck around.
        self.duplicates_folders_checkbox = QCheckBox("Only these folders…")
        self.duplicates_folders_checkbox.setToolTip(
            help_text.TOOLTIP_DUPLICATES_FOLDERS_CHECKBOX
        )
        self.duplicates_folders_checkbox.toggled.connect(
            self._on_duplicates_folders_toggled
        )
        controls.addWidget(self.duplicates_folders_checkbox)

        self.compute_fingerprints_button = QPushButton("Compute fingerprints")
        self.compute_fingerprints_button.setToolTip(
            help_text.TOOLTIP_COMPUTE_FINGERPRINTS
        )
        self.compute_fingerprints_button.clicked.connect(
            self._on_compute_fingerprints_clicked
        )
        controls.addWidget(self.compute_fingerprints_button)

        self.find_duplicates_button = QPushButton("Find duplicates")
        self.find_duplicates_button.setToolTip(
            help_text.TOOLTIP_FIND_DUPLICATES
        )
        self.find_duplicates_button.clicked.connect(
            self._on_find_duplicates_clicked
        )
        controls.addWidget(self.find_duplicates_button)

        layout.addLayout(controls)

        # Roadmap item 68 (Phase 7.2) — hidden by default; shown only
        # when "Only these folders…" is checked. A plain QListWidget of
        # real absolute paths, resolved against registered locations
        # only at scope-count/run time (resolve_folder_scopes), not on
        # every add — an unregistered folder is a run-time error, not
        # something that blocks merely listing it.
        self.duplicates_folders_panel = QWidget()
        folders_panel_layout = QVBoxLayout(self.duplicates_folders_panel)
        folders_panel_layout.setContentsMargins(0, 0, 0, 0)

        self.duplicates_folders_list = QListWidget()
        folders_panel_layout.addWidget(
            theme.make_card(self.duplicates_folders_list)
        )

        folders_buttons_row = QHBoxLayout()

        self.duplicates_add_folder_button = QPushButton("Add folder…")
        self.duplicates_add_folder_button.setToolTip(
            help_text.TOOLTIP_DUPLICATES_ADD_FOLDER
        )
        self.duplicates_add_folder_button.clicked.connect(
            self._on_add_duplicates_folder_clicked
        )
        folders_buttons_row.addWidget(self.duplicates_add_folder_button)

        self.duplicates_remove_folder_button = QPushButton("Remove selected")
        self.duplicates_remove_folder_button.setToolTip(
            help_text.TOOLTIP_DUPLICATES_REMOVE_FOLDER
        )
        self.duplicates_remove_folder_button.clicked.connect(
            self._on_remove_duplicates_folder_clicked
        )
        folders_buttons_row.addWidget(self.duplicates_remove_folder_button)

        folders_panel_layout.addLayout(folders_buttons_row)

        # Shown BEFORE a real, potentially ~10-minute-at-real-scale run
        # (item 39's own real number) — see
        # help_text.format_duplicates_scope_count's own docstring.
        self.duplicates_scope_count_label = QLabel("")
        folders_panel_layout.addWidget(self.duplicates_scope_count_label)

        self.duplicates_folders_panel.setVisible(False)
        layout.addWidget(self.duplicates_folders_panel)

        duplicates_status_row = QHBoxLayout()
        self.duplicates_status_label = QLabel("")
        duplicates_status_row.addWidget(self.duplicates_status_label)
        duplicates_status_row.addStretch()
        # Roadmap item R3.2 — "Resolve all groups". Real count set in
        # _render_duplicate_groups, never stale against the table.
        self.resolve_all_duplicates_button = QPushButton("Resolve all groups")
        self.resolve_all_duplicates_button.setToolTip(
            help_text.TOOLTIP_RESOLVE_ALL_DUPLICATES
        )
        self.resolve_all_duplicates_button.setEnabled(False)
        self.resolve_all_duplicates_button.clicked.connect(
            self._on_resolve_all_duplicates_clicked
        )
        duplicates_status_row.addWidget(self.resolve_all_duplicates_button)
        layout.addLayout(duplicates_status_row)

        self.duplicates_table = QTableWidget(0, len(_DUPLICATES_COLUMN_HEADERS))
        self.duplicates_table.setHorizontalHeaderLabels(
            _DUPLICATES_COLUMN_HEADERS
        )
        theme.apply_table_defaults(self.duplicates_table)
        layout.addWidget(theme.make_card(self.duplicates_table))

        # QButtonGroup instances (one per duplicate group, so only one
        # radio per group can be selected) have no Qt parent-child
        # ownership tie to the table cells their radios live in -- kept
        # alive here for the same reason ui/workers.py's _callbacks
        # keeps a Worker reference until its own completion, and item
        # 22's docstring on that pattern more generally: a Qt object
        # with nothing else referencing it is a live GC/use-after-free
        # hazard, not just a style preference. Reset on every render.
        self._duplicate_button_groups: list[QButtonGroup] = []
        self._current_duplicate_groups: list[DuplicateGroup] = []
        # Roadmap item R2.2 — same rebuild-destroys-state bug as R2.1,
        # for the Duplicates "keep" radio selection: a group has no
        # stable id of its own (it's recomputed fresh by clustering, or
        # locally re-derived after a delete — see
        # _on_delete_duplicates_finished), so the group's OWN set of
        # member local_file ids is used as the key instead — stable
        # across the poll rebuild and across a local re-render, since
        # neither changes which files belong to a still-open group.
        # Value is the checked button's id — either a real
        # local_file.id or the KEEP_ALL_DUPLICATES_ID sentinel. Pruned
        # to only still-present groups on every render (R2.3).
        self._duplicates_keep_selection: dict[frozenset[int], int] = {}
        self._current_duplicates_location_name: str | None = None
        self._duplicates_locations_by_name: dict[str, LibraryLocation] = {}
        # Roadmap item 68 (Phase 7.2) — resolved by local_file.location_id
        # at render time so the LOCATION column (and the delete flow's
        # own path resolution below) reads correctly per-file even for a
        # pooled, cross-location folder-scope result — a single "current
        # location" no longer holds for those.
        self._duplicates_locations_by_id: dict[int, LibraryLocation] = {}
        # Persisted across page shows deliberately (never reset in
        # _on_page_changed) — same "don't lose it on every revisit"
        # precedent as the location combo's own selection.
        self._duplicates_folder_paths: list[str] = []

        return tab

    def _on_page_changed(self, index: int) -> None:
        # Roadmap item 56 Phase 6.1 — was gated by
        # _duplicates_locations_loaded to fire at most once ever (the
        # original fix for a real, confirmed Qt/GIL deadlock — item 39
        # — triggered by fetching at MainWindow *construction* time).
        # A page SHOW is a different, human-paced trigger — the same
        # distinction item 39's own addendum already draws — so
        # refreshing on every show (a location added since the last
        # visit must actually appear) doesn't reintroduce that
        # construction-time hazard. Settings' own exit (§3.3) already
        # calls this same method directly; both paths now land on it.
        if index == self._duplicates_page_index:
            self._refresh_duplicates_locations()
            self._refresh_duplicates_milestone()

        if index == self._sharing_page_index:
            self._sharing_page_visited = True
            self._refresh_sharing()

        if index == self._history_page_index and not self._history_loaded:
            self._history_loaded = True
            self._refresh_history()

    def _refresh_duplicates_locations(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.library_service.list_locations,
            on_finished=self._render_duplicates_locations,
        )

    def _refresh_duplicates_milestone(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.duplicate_service.get_cleanup_totals,
            on_finished=self._render_duplicates_milestone,
        )

    def _render_duplicates_milestone(self, totals: tuple[int, int]) -> None:
        files_deleted, bytes_freed = totals

        if bytes_freed == 0 and files_deleted == 0:
            self.duplicates_milestone_label.hide()
            return

        self.duplicates_milestone_label.setText(
            f"You've reclaimed {format_file_size(bytes_freed)} across "
            f"{files_deleted} file{'s' if files_deleted != 1 else ''}."
        )
        self.duplicates_milestone_label.show()

    def _render_duplicates_locations(
            self,
            locations: list[tuple[Any, bool]],
    ) -> None:
        # Preserve the current selection across a refresh (Phase 6.1)
        # when that location still exists — losing it on every page
        # revisit would be a real regression of its own.
        previously_selected = self._selected_duplicates_location()

        self.duplicates_location_combo.clear()
        # Roadmap item 56 Phase 6.3/6.4 — the real LibraryLocation
        # (path for the delete-confirmation dialog's exact full paths
        # and the table's own Location column; id for the reclaimed-
        # space milestone's cleanup record). Neither is carried on
        # LocalFile/DuplicateFile at all (only location_id, and not
        # even that on the milestone side), and find_duplicate_groups()
        # is already scoped to one location per call, so this is
        # resolved once here rather than plumbed through the service
        # layer.
        self._duplicates_locations_by_name = {
            location.name: location for location, _ in locations
        }
        self._duplicates_locations_by_id = {
            location.id: location
            for location, _ in locations
            if location.id is not None
        }

        for location, _ in locations:
            self.duplicates_location_combo.addItem(
                location.name, location.name
            )

        if previously_selected is not None:
            index = self.duplicates_location_combo.findData(
                previously_selected
            )
            if index >= 0:
                self.duplicates_location_combo.setCurrentIndex(index)

    def _selected_duplicates_location(self) -> str | None:
        name = self.duplicates_location_combo.currentData()
        return str(name) if name is not None else None

    def _selected_duplicates_location_id(self) -> int | None:
        # Roadmap item 77 (P9) — the combo stays enabled in folder-scope
        # mode now, and its selection is passed through as
        # resolve_folder_scopes()'s tiebreak preference (P8.2) rather
        # than being dead weight while checked.
        name = self._selected_duplicates_location()
        if name is None:
            return None
        location = self._duplicates_locations_by_name.get(name)
        return location.id if location else None

    def _selected_duplicates_folders(self) -> list[str]:
        if not self.duplicates_folders_checkbox.isChecked():
            return []
        return list(self._duplicates_folder_paths)

    def _on_duplicates_folders_toggled(self, checked: bool) -> None:
        self.duplicates_folders_panel.setVisible(checked)
        self._refresh_duplicates_folder_scope_count()

    def _on_duplicates_location_changed(self) -> None:
        # Roadmap item 77 (P9) — a location-combo change can change
        # which real location a tied folder scope resolves to (P8.2's
        # tiebreak), so the scope count must reflect it live, not just
        # sit stale until the next folder is added/removed.
        self._refresh_duplicates_folder_scope_count()

    def _on_add_duplicates_folder_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose a folder to add to the scope"
        )

        if not path or path in self._duplicates_folder_paths:
            return

        self._duplicates_folder_paths.append(path)
        self.duplicates_folders_list.addItem(path)
        self._refresh_duplicates_folder_scope_count()

    def _on_remove_duplicates_folder_clicked(self) -> None:
        for item in self.duplicates_folders_list.selectedItems():
            path = item.text()
            self.duplicates_folders_list.takeItem(
                self.duplicates_folders_list.row(item)
            )
            if path in self._duplicates_folder_paths:
                self._duplicates_folder_paths.remove(path)

        self._refresh_duplicates_folder_scope_count()

    def _refresh_duplicates_folder_scope_count(self) -> None:
        if (
                not self.duplicates_folders_checkbox.isChecked()
                or not self._duplicates_folder_paths
        ):
            self.duplicates_scope_count_label.setText("")
            return

        folders = list(self._duplicates_folder_paths)
        preferred_location_id = self._selected_duplicates_location_id()

        def compute_summary() -> Any:
            service = self.application.duplicate_service
            scopes = service.resolve_folder_scopes(
                folders, preferred_location_id=preferred_location_id,
            )
            return service.summarize_scopes(scopes)

        run_worker(
            self.thread_pool, compute_summary,
            on_finished=lambda summary: self.duplicates_scope_count_label.setText(
                help_text.format_duplicates_scope_count(summary)
            ),
            on_error=self.duplicates_scope_count_label.setText,
        )

    def _on_compute_fingerprints_clicked(self) -> None:
        folders = self._selected_duplicates_folders()

        if folders:
            preferred_location_id = self._selected_duplicates_location_id()
            self._run_busy_worker(
                "compute_fingerprints", self.compute_fingerprints_button,
                lambda progress: self._compute_fingerprints_for_folders(
                    folders, progress, preferred_location_id,
                ),
                status_label=self.duplicates_status_label,
                on_finished=self._render_fingerprint_result,
                reports_progress=True,
            )
            self.duplicates_status_label.setText(
                f"Computing fingerprints for {len(folders)} folder(s)..."
            )
            return

        location_name = self._selected_duplicates_location()

        if location_name is None:
            self.duplicates_status_label.setText(
                "Select a library location first."
            )
            return

        self._run_busy_worker(
            "compute_fingerprints", self.compute_fingerprints_button,
            lambda progress: (
                self.application.duplicate_service.compute_fingerprints(
                    location_name, progress=progress,
                )
            ),
            status_label=self.duplicates_status_label,
            on_finished=self._render_fingerprint_result,
            reports_progress=True,
        )
        self.duplicates_status_label.setText(
            f"Computing fingerprints for '{location_name}'..."
        )

    def _compute_fingerprints_for_folders(
            self,
            folders: list[str],
            progress: Callable[[str, int, int], None],
            preferred_location_id: int | None = None,
    ) -> dict[str, Any]:
        # Roadmap item 68 (Phase 7.2/7.3) — compute_fingerprints() is
        # itself scoped to one library location per call; folder mode
        # can span more than one (find_duplicate_groups_across_scopes'
        # own cross-location pooling), so this groups the resolved
        # scopes by location, calls it once per location, and translates
        # each call's own 1..N progress into a running offset against
        # the real combined total — so the activity strip still reads
        # 1..total once, not resetting partway through.
        service = self.application.duplicate_service
        scopes = service.resolve_folder_scopes(
            folders, preferred_location_id=preferred_location_id,
        )
        total = service.count_files_for_scopes(scopes)

        folders_by_location: dict[str, list[str]] = {}
        for scope in scopes:
            folders_by_location.setdefault(
                scope.location.name, [],
            ).append(scope.folder_relative_path)

        combined: dict[str, Any] = {
            "computed": 0,
            "skipped_already_computed": 0,
            "failed": 0,
            "details": [],
        }
        completed_before = 0

        for location_name, relative_folders in folders_by_location.items():
            def report(
                    stage: str, current: int, _total: int,
                    offset: int = completed_before,
            ) -> None:
                progress(stage, offset + current, total)

            result = service.compute_fingerprints(
                location_name, folders=relative_folders, progress=report,
            )
            combined["computed"] += result["computed"]
            combined["skipped_already_computed"] += (
                result["skipped_already_computed"]
            )
            combined["failed"] += result["failed"]
            combined["details"].extend(result["details"])
            completed_before += (
                result["computed"]
                + result["skipped_already_computed"]
                + result["failed"]
            )

        return combined

    def _render_fingerprint_result(self, result: dict[str, Any]) -> None:
        self.duplicates_status_label.setText(
            help_text.format_fingerprint_result_message(result)
        )

    def _on_find_duplicates_clicked(self) -> None:
        folders = self._selected_duplicates_folders()

        if folders:
            # No single location applies to a pooled, possibly
            # cross-location result — _render_duplicate_groups resolves
            # each row's location individually via
            # _duplicates_locations_by_id instead.
            self._current_duplicates_location_name = None
            preferred_location_id = self._selected_duplicates_location_id()

            self._run_busy_worker(
                "find_duplicates", self.find_duplicates_button,
                lambda progress: (
                    self.application.duplicate_service
                    .find_duplicate_groups_across_scopes(
                        self.application.duplicate_service
                        .resolve_folder_scopes(
                            folders,
                            preferred_location_id=preferred_location_id,
                        ),
                        progress=progress,
                    )
                ),
                status_label=self.duplicates_status_label,
                on_finished=self._render_duplicate_groups,
                reports_progress=True,
            )
            self.duplicates_status_label.setText(
                f"Searching for duplicates in {len(folders)} folder(s)..."
            )
            return

        location_name = self._selected_duplicates_location()

        if location_name is None:
            self.duplicates_status_label.setText(
                "Select a library location first."
            )
            return

        # Roadmap item 56 Phase 6.3 — the delete-confirmation dialog's
        # full paths need a real location; captured here rather than
        # re-read from the combo later, so a combo selection change
        # while this search is still running can't attach the wrong
        # location name to the results it eventually renders. (The
        # LOCATION column itself resolves per-file, not from this — see
        # item 68.)
        self._current_duplicates_location_name = location_name

        self._run_busy_worker(
            "find_duplicates", self.find_duplicates_button,
            lambda progress: (
                self.application.duplicate_service.find_duplicate_groups(
                    location_name, progress=progress,
                )
            ),
            status_label=self.duplicates_status_label,
            on_finished=self._render_duplicate_groups,
            reports_progress=True,
        )
        self.duplicates_status_label.setText(
            f"Searching for duplicates in '{location_name}'..."
        )

    def _on_duplicates_keep_toggled(
            self, group_key: frozenset[int], button_id: int, checked: bool,
    ) -> None:
        if checked:
            self._duplicates_keep_selection[group_key] = button_id

    def _render_duplicate_groups(self, groups: list[DuplicateGroup]) -> None:
        self._duplicate_button_groups = []
        # Kept so a single-group resolution can drop just that group and
        # re-render locally afterward — see _on_delete_duplicates_finished's
        # own docstring for why re-fetching via find_duplicate_groups()
        # after every resolution is not an option at real scale.
        self._current_duplicate_groups = groups

        # Roadmap item 73 (P4) — setRowCount() does NOT clear spans, so
        # a stale span from a PREVIOUS render (different group shapes)
        # could silently hide a real Actions widget under a new row that
        # happens to land inside an old span's coverage. Confirmed via
        # grep: this was never called anywhere in this file before.
        self.duplicates_table.clearSpans()

        # Roadmap item R2.3 — prune selection state for groups no
        # longer present (resolved, or no longer clustered together).
        # Runs even for an empty `groups` list (the early-return branch
        # right below) — a "no duplicates found" render must not leave
        # stale selections sitting in the map forever either.
        live_group_keys = {
            frozenset(f.local_file.id for f in group.files)
            for group in groups
        }
        self._duplicates_keep_selection = {
            key: value
            for key, value in self._duplicates_keep_selection.items()
            if key in live_group_keys
        }

        self.resolve_all_duplicates_button.setEnabled(len(groups) > 0)
        self.resolve_all_duplicates_button.setText(
            f"Resolve all groups ({len(groups)})" if groups
            else "Resolve all groups"
        )

        if not groups:
            self.duplicates_table.setRowCount(0)
            self.duplicates_status_label.setText(
                "No duplicates found. Run Compute fingerprints first if "
                "you haven't yet."
            )
            return

        self.duplicates_status_label.setText(
            f"Found {len(groups)} duplicate group(s)."
        )

        total_rows = sum(len(group.files) for group in groups)
        self.duplicates_table.setRowCount(total_rows)

        # Roadmap item 73 (P4) — every real Actions widget built this
        # render, so its true widest sizeHint() can size the ACTIONS
        # column for real below (a per-group extra button — see
        # _build_duplicate_group_actions — means this isn't always the
        # same width for every group).
        action_widgets: list[QWidget] = []

        row = 0
        for group_index, group in enumerate(groups, start=1):
            # group.files is already ranked best-quality-first (see
            # DuplicateGroup's own docstring) -- files[0] is this
            # group's own recommendation for which copy to keep,
            # pre-selected below but never auto-applied: the radio can
            # still be moved to any other file in the group before
            # Delete is ever clicked.
            button_group = QButtonGroup(self.duplicates_table)
            self._duplicate_button_groups.append(button_group)
            group_first_row = row

            # Roadmap item R2.2 — this group's stable key (its own
            # member file ids) and whatever was selected for it before
            # the last rebuild, if anything. Recorded back into the map
            # on every real toggle, not just read once here — the user
            # can change their mind more than once before Delete.
            group_key = frozenset(
                f.local_file.id for f in group.files
                if f.local_file.id is not None
            )
            previously_selected_id = self._duplicates_keep_selection.get(
                group_key
            )
            button_group.idToggled.connect(
                lambda button_id, checked, group_key=group_key: (
                    self._on_duplicates_keep_toggled(
                        group_key, button_id, checked,
                    )
                )
            )

            for file_index, duplicate_file in enumerate(group.files):
                local_file = duplicate_file.local_file
                quality = duplicate_file.quality
                assert local_file.id is not None

                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.GROUP,
                    QTableWidgetItem(str(group_index)),
                )
                # Location + full relative path (roadmap item 56 Phase
                # 6.3) — "the same file in two folders" is a judgement
                # the user needs the real path to make, not just a
                # bare filename. Resolved PER FILE (roadmap item 68,
                # Phase 7.2) rather than from one outer variable — a
                # pooled, cross-location folder-scope result can put
                # files from two different real locations in the same
                # group.
                file_location = self._duplicates_locations_by_id.get(
                    local_file.location_id
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.LOCATION,
                    QTableWidgetItem(
                        file_location.name if file_location else "—"
                    ),
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.PATH,
                    QTableWidgetItem(local_file.relative_path),
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.FORMAT,
                    QTableWidgetItem(local_file.format),
                )
                bitrate_text = (
                    f"{quality.bitrate_kbps} kbps"
                    if quality.bitrate_kbps
                    else "—"
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.BITRATE,
                    QTableWidgetItem(bitrate_text),
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.SIMILARITY,
                    QTableWidgetItem(f"{group.similarity:.1%}"),
                )

                keep_radio = QRadioButton()
                keep_radio.setToolTip(help_text.TOOLTIP_KEEP_FILE_RADIO)
                # Roadmap item R2.2 — restore the user's own prior
                # selection for this group when there is one; only fall
                # back to the "best quality first" default when nothing
                # was ever chosen for it.
                keep_radio.setChecked(
                    local_file.id == previously_selected_id
                    if previously_selected_id is not None
                    else file_index == 0
                )
                # The button's own id IS the local_file_id -- checkedId()
                # below reads it back directly, no separate id-to-file
                # mapping needed.
                button_group.addButton(keep_radio, id=local_file.id)
                self.duplicates_table.setCellWidget(
                    row, _DuplicatesColumn.KEEP, keep_radio,
                )

                row += 1

            # Roadmap item 77 (P7, 5th report) -- setSpan() BEFORE
            # setCellWidget() for the group's first row, so the real
            # widget's geometry is computed against the final spanned
            # rect, not a single-cell rect that a later setSpan() call
            # then silently changes underneath it. And no widget of any
            # kind (blank or otherwise) goes on the covered rows: a
            # blank QWidget() there used to get resolved by Qt's own
            # span geometry to the EXACT SAME rect as the real widget
            # (visualRect() resolves every cell inside a span to the
            # whole span's rect) and, being added to the viewport
            # later, painted over it -- confirmed live via
            # childAt(center of the Actions cell) returning the blank
            # widget, not the real one, before this fix. The span
            # itself is what makes the covered rows read as blank; no
            # cell widget is needed there at all.
            self.duplicates_table.setSpan(
                group_first_row, _DuplicatesColumn.ACTIONS,
                len(group.files), 1,
            )
            group_actions_widget = self._build_duplicate_group_actions(
                group, button_group, previously_selected_id,
            )
            action_widgets.append(group_actions_widget)
            self.duplicates_table.setCellWidget(
                group_first_row, _DuplicatesColumn.ACTIONS,
                group_actions_widget,
            )

        self._size_duplicates_columns(action_widgets)

    def _size_duplicates_columns(
            self, action_widgets: list[QWidget],
    ) -> None:
        """Roadmap item 73 (P4) — a real, live-measured floor for the
        Actions column, closing the actual reported bug: at the app's
        real 960x640 minimum window size, against real production
        duplicate groups, this widget's own visibleRegion() was
        confirmed (0,0,0,0) — fully invisible, not merely clipped —
        because NOTHING in this app ever set a column width, so
        Actions (column 7 of 8) got whatever tiny sliver
        setStretchLastSection's leftover-space math happened to leave
        it. Fixed mode + an explicit width DERIVED from the real
        widget's own sizeHint() (never a magic number) makes this
        column immune to that squeeze regardless of window width.
        """
        header = self.duplicates_table.horizontalHeader()
        # A floor no column can be silently squeezed below (item 4.3) —
        # untuned, a reasonable "still shows something" minimum.
        header.setMinimumSectionSize(40)
        # Roadmap item 73 (P4) — stretching the LAST section (whichever
        # column that happens to be) is exactly the mechanism that let
        # Actions collapse to a sliver in the first place; every column
        # now gets its own explicit, derived resize mode instead.
        header.setStretchLastSection(False)

        content_fit_columns = (
            _DuplicatesColumn.GROUP, _DuplicatesColumn.LOCATION,
            _DuplicatesColumn.FORMAT, _DuplicatesColumn.BITRATE,
            _DuplicatesColumn.SIMILARITY, _DuplicatesColumn.KEEP,
        )
        for column in content_fit_columns:
            header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents,
            )

        # PATH holds a full relative path (item 4.2's own "own
        # usability problem" callout) — stretches to hold the long
        # value rather than sitting at Qt's 100px column default.
        header.setSectionResizeMode(
            _DuplicatesColumn.PATH, QHeaderView.ResizeMode.Stretch,
        )

        # Roadmap item R5 (5b.1) — extracted into the shared
        # theme.size_action_column, now also used by Search/Track/
        # Sharing/Review's Actions columns instead of a tenth copy.
        theme.size_action_column(
            self.duplicates_table, _DuplicatesColumn.ACTIONS, action_widgets,
        )

    def _build_duplicate_group_actions(
            self,
            group: DuplicateGroup,
            button_group: QButtonGroup,
            previously_selected_id: int | None,
    ) -> QWidget:
        # Roadmap item 56 Phase 6.3 — "the same file living in several
        # folders is sometimes deliberate." An additional button in the
        # group's EXISTING QButtonGroup (a sentinel id, not a separate
        # control/group) so the "selecting one deselects the others"
        # behavior is preserved and simply extended, not reimplemented.
        keep_all_radio = QRadioButton("Keep all")
        keep_all_radio.setToolTip(help_text.TOOLTIP_KEEP_ALL_DUPLICATES_RADIO)
        # Roadmap item R2.2 — same preserved-selection treatment as the
        # per-file keep radios above.
        keep_all_radio.setChecked(
            previously_selected_id == KEEP_ALL_DUPLICATES_ID
        )
        button_group.addButton(keep_all_radio, id=KEEP_ALL_DUPLICATES_ID)

        confirm_checkbox = QCheckBox("Confirm delete")
        confirm_checkbox.setToolTip(
            help_text.TOOLTIP_DELETE_DUPLICATES_CHECKBOX
        )

        delete_button = QPushButton("Delete")
        delete_button.setToolTip(help_text.TOOLTIP_DELETE_DUPLICATES_BUTTON)
        delete_button.clicked.connect(
            lambda: self._on_delete_duplicates_clicked(
                group, button_group, confirm_checkbox, delete_button,
            )
        )

        def _update_delete_enabled() -> None:
            # "Keep all" selected means there is nothing to delete.
            delete_button.setEnabled(
                button_group.checkedId() != KEEP_ALL_DUPLICATES_ID
            )

        button_group.buttonToggled.connect(
            lambda _button, _checked: _update_delete_enabled()
        )
        _update_delete_enabled()

        return theme.cell_widget(keep_all_radio, confirm_checkbox, delete_button)

    def _on_delete_duplicates_clicked(
            self,
            group: DuplicateGroup,
            button_group: QButtonGroup,
            confirm_checkbox: QCheckBox,
            button: QPushButton,
    ) -> None:
        if not confirm_checkbox.isChecked():
            # The standing rule against touching a file without
            # confirmation applies in full here: a click alone is only
            # the FIRST signal (which file to keep); the checkbox is
            # the second, explicit one, mirroring the Review tab's own
            # Replace + "Delete old file" checkbox pair. Neither one
            # alone deletes anything.
            self.duplicates_status_label.setText(
                "Check \"Confirm delete\" before deleting duplicate "
                "files."
            )
            return

        keep_id = button_group.checkedId()

        if keep_id == KEEP_ALL_DUPLICATES_ID:
            # Defense in depth — the Delete button is already disabled
            # in this state, but nothing structurally prevents this
            # method being reached some other way.
            return

        delete_ids = [
            duplicate_file.local_file.id
            for duplicate_file in group.files
            if duplicate_file.local_file.id is not None
            and duplicate_file.local_file.id != keep_id
        ]

        # Roadmap item 68 (Phase 7.2) — resolved PER FILE via
        # local_file.location_id rather than one "current location":
        # a pooled, cross-location folder-scope group can hold files
        # from more than one real registered location.
        # Roadmap item 56 Phase 6.3 — deleting real user files warrants
        # naming them: the exact full paths about to be deleted, not
        # just a bare count, in a second, explicit confirmation.
        paths_to_delete = [
            str(
                Path(
                    self._duplicates_locations_by_id[
                        duplicate_file.local_file.location_id
                    ].path
                ) / duplicate_file.local_file.relative_path
            )
            for duplicate_file in group.files
            if duplicate_file.local_file.id in delete_ids
            and duplicate_file.local_file.location_id
            in self._duplicates_locations_by_id
        ]

        # Purely informational provenance on the resulting
        # duplicate_cleanups row (DuplicateService.delete_local_files'
        # own docstring) — the KEPT file's location is the most
        # meaningful single answer to "where did this cleanup happen"
        # for a pooled, possibly cross-location group.
        keep_duplicate_file = next(
            (
                duplicate_file for duplicate_file in group.files
                if duplicate_file.local_file.id == keep_id
            ),
            None,
        )
        location_id = (
            keep_duplicate_file.local_file.location_id
            if keep_duplicate_file is not None else None
        )

        confirmed = QMessageBox.question(
            self,
            help_text.DELETE_DUPLICATES_CONFIRM_TITLE,
            help_text.format_delete_duplicates_confirm_body(paths_to_delete),
        )

        if confirmed != QMessageBox.StandardButton.Yes:
            return

        run_worker(
            self.thread_pool,
            lambda: self.application.duplicate_service.delete_local_files(
                delete_ids, keep_id, location_id,
            ),
            button=button,
            status_label=self.duplicates_status_label,
            on_finished=lambda result: self._on_delete_duplicates_finished(
                result, group,
            ),
        )

    def _on_delete_duplicates_finished(
            self,
            result: dict[str, Any],
            group: DuplicateGroup,
    ) -> None:
        # Deliberately NOT a find_duplicate_groups() re-fetch after every
        # single-group resolution. That call recomputes the ENTIRE
        # location's clustering from scratch every time, by design (item
        # 39 — never persisted, so a moved/rescanned file can't leave a
        # stale group behind) — real, live-verified cost against a real
        # ~3,100-file/344-group library was ~10 minutes (see
        # docs/HISTORY.md item 39). Re-running that after every single
        # group would make resolving a real library's worth of
        # duplicates one at a time completely impractical (344 groups x
        # ~10 minutes each). Instead, drop just the resolved group from
        # the in-memory list this tab already holds and re-render from
        # that — no backend call at all.
        message = f"Deleted: {result['deleted']}, Failed: {result['failed']}."

        if result["failed"] > 0:
            # A partial failure means the DB/disk state for this group
            # may not actually match "fully resolved" (see
            # DuplicateService.delete_local_files' own per-item
            # semantics) — leave it visible rather than assuming it's
            # gone, so the user can see it's still there and retry.
            self.duplicates_status_label.setText(message)
            return

        self._current_duplicate_groups = [
            g for g in self._current_duplicate_groups if g is not group
        ]
        # _render_duplicate_groups sets its own "Found N group(s)"/"No
        # duplicates found" status text -- overwritten here afterward so
        # the deletion result is what the user actually sees.
        self._render_duplicate_groups(self._current_duplicate_groups)
        self.duplicates_status_label.setText(
            f"{message} {self.duplicates_status_label.text()}"
        )
        # A real deletion just happened (delete_local_files already
        # recorded it) — refresh the milestone total immediately rather
        # than waiting for the next page revisit.
        self._refresh_duplicates_milestone()

    def _build_group_resolution_plan(
            self, group: DuplicateGroup, keep_id: int,
    ) -> tuple[GroupResolutionPlan, str, list[str]] | None:
        """Roadmap item R3.2 — the same per-group plan (real per-file
        location resolution, real absolute paths) `_on_delete_
        duplicates_clicked` builds for a single group, factored out so
        "Resolve all groups" can build the identical plan for every
        group without a second, drifting copy. `None` when there's
        nothing to delete or the keep selection doesn't resolve to a
        real file in this group (shouldn't happen for a real render,
        but never trusted blindly for a batch that deletes real files).
        """
        delete_ids = [
            duplicate_file.local_file.id
            for duplicate_file in group.files
            if duplicate_file.local_file.id is not None
            and duplicate_file.local_file.id != keep_id
        ]

        if not delete_ids:
            return None

        keep_duplicate_file = next(
            (
                duplicate_file for duplicate_file in group.files
                if duplicate_file.local_file.id == keep_id
            ),
            None,
        )

        if keep_duplicate_file is None:
            return None

        location_id = keep_duplicate_file.local_file.location_id
        keep_location = self._duplicates_locations_by_id.get(location_id)
        keep_path = (
            str(
                Path(keep_location.path)
                / keep_duplicate_file.local_file.relative_path
            )
            if keep_location is not None
            else keep_duplicate_file.local_file.relative_path
        )

        delete_paths = [
            str(
                Path(
                    self._duplicates_locations_by_id[
                        duplicate_file.local_file.location_id
                    ].path
                ) / duplicate_file.local_file.relative_path
            )
            for duplicate_file in group.files
            if duplicate_file.local_file.id in delete_ids
            and duplicate_file.local_file.location_id
            in self._duplicates_locations_by_id
        ]

        plan = GroupResolutionPlan(
            delete_local_file_ids=delete_ids,
            keep_local_file_id=keep_id,
            location_id=location_id,
        )

        return plan, keep_path, delete_paths

    def _on_resolve_all_duplicates_clicked(self) -> None:
        # Roadmap item R3.2/R3.3 — built fresh from what's actually on
        # screen right now (the current groups AND the current keep
        # selections), never a stale plan from an earlier click.
        groups = self._current_duplicate_groups

        plans_with_labels: list[tuple[GroupResolutionPlan, str, list[str]]] = []
        resolved_groups: list[DuplicateGroup] = []

        for group in groups:
            group_key = frozenset(
                f.local_file.id for f in group.files
                if f.local_file.id is not None
            )
            default_keep_id = (
                group.files[0].local_file.id if group.files else None
            )
            keep_id = self._duplicates_keep_selection.get(
                group_key, default_keep_id,
            )

            if keep_id is None or keep_id == KEEP_ALL_DUPLICATES_ID:
                # "Keep all" (or no resolvable keep target at all) is
                # never turned into a plan — skipped, not overridden.
                continue

            built = self._build_group_resolution_plan(group, keep_id)

            if built is None:
                continue

            plans_with_labels.append(built)
            resolved_groups.append(group)

        dialog = BulkResolveDuplicatesDialog(self, plans_with_labels)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if not plans_with_labels or not dialog.confirm_checkbox.isChecked():
            # Defense in depth — the confirm button is already disabled
            # in either state, but nothing structurally prevents this
            # method being reached some other way.
            return

        plans = [plan for plan, _, _ in plans_with_labels]

        run_worker(
            self.thread_pool,
            lambda: self.application.duplicate_service.resolve_groups(plans),
            button=self.resolve_all_duplicates_button,
            status_label=self.duplicates_status_label,
            on_finished=lambda result: self._on_bulk_resolve_duplicates_finished(
                result, resolved_groups,
            ),
        )

    def _on_bulk_resolve_duplicates_finished(
            self,
            result: BulkDuplicateResolutionResult,
            attempted_groups: list[DuplicateGroup],
    ) -> None:
        QMessageBox.information(
            self,
            help_text.BULK_RESOLVE_DUPLICATES_DIALOG_TITLE,
            help_text.format_bulk_resolve_duplicates_result(result),
        )

        # Same "drop resolved groups locally, never a full
        # find_duplicate_groups() re-fetch" discipline as the
        # single-group flow (_on_delete_duplicates_finished's own
        # docstring) — a group that partially failed stays visible,
        # per plan_outcomes, so the user can see it's still there and
        # retry rather than assuming it's gone.
        succeeded_groups = {
            id(group)
            for group, succeeded in zip(attempted_groups, result.plan_outcomes)
            if succeeded
        }
        self._current_duplicate_groups = [
            group for group in self._current_duplicate_groups
            if id(group) not in succeeded_groups
        ]
        self._render_duplicate_groups(self._current_duplicate_groups)

        if result.files_deleted > 0:
            self._refresh_duplicates_milestone()

    def _load_playlists(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.sync_service.list_playlists,
            status_label=self.status_label,
            on_finished=self._populate_playlists,
        )

    def _populate_playlists(self, playlists: list[Playlist]) -> None:
        self.playlist_list.clear()

        for playlist in playlists:
            item = QListWidgetItem(
                f"{playlist.name} ({playlist.track_count} tracks)"
            )
            item.setData(Qt.ItemDataRole.UserRole, playlist)
            self.playlist_list.addItem(item)

    def _build_track_empty_panel(self) -> QWidget:
        # Roadmap item 7 — "No playlist selected, or an empty table,
        # renders a small centred panel with one line of copy and the
        # relevant button — not a bare grid." One panel, two real
        # states (see _render_no_playlist_selected/_render_track_
        # statuses): no playlist picked yet (no button — there's
        # nothing to click but the list on the left), and a real
        # playlist whose tracks haven't been loaded yet (a real "Load
        # tracks" action).
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addStretch()

        self.track_empty_label = QLabel("")
        self.track_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.track_empty_label.setWordWrap(True)
        self.track_empty_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        layout.addWidget(self.track_empty_label)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.sync_tracks_button = QPushButton("Load tracks")
        self.sync_tracks_button.setToolTip(help_text.TOOLTIP_SYNC_TRACKS)
        self.sync_tracks_button.clicked.connect(
            self._on_sync_tracks_clicked
        )
        button_row.addWidget(self.sync_tracks_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        layout.addStretch()
        return panel

    def _on_playlist_selected(
            self,
            current: QListWidgetItem | None,
            previous: QListWidgetItem | None,
    ) -> None:
        self.selected_playlist = (
            current.data(Qt.ItemDataRole.UserRole)
            if current is not None
            else None
        )
        self._poll_selected_playlist()
        self._poll_next_step()

    def _poll_selected_playlist(self) -> None:
        # Roadmap item R7.6 — the Dashboard's own track table has no
        # tray-menu relevance at all; skip entirely while hidden rather
        # than just gating the render half, since the fetch itself has
        # no other consumer either.
        if self._hidden_to_tray:
            return

        if self.selected_playlist is None:
            self._render_no_playlist_selected()
            return

        playlist_name = self.selected_playlist.name

        run_worker(
            self.thread_pool,
            lambda: self.application.dashboard_service
            .get_playlist_track_status(playlist_name),
            status_label=self.status_label,
            on_finished=self._render_track_statuses,
        )

    def _render_no_playlist_selected(self) -> None:
        self._current_track_statuses = []
        self.track_table.setRowCount(0)
        self.track_empty_label.setText(
            "Pick a playlist on the left to see its tracks."
        )
        self.sync_tracks_button.hide()
        self.track_area_stack.setCurrentWidget(self._track_empty_panel)

    def _render_track_statuses(self, statuses: list[TrackStatus]) -> None:
        self._current_track_statuses = statuses

        if not statuses:
            self.track_table.setRowCount(0)
            playlist_name = (
                self.selected_playlist.name
                if self.selected_playlist is not None
                else ""
            )
            self.track_empty_label.setText(
                f"'{playlist_name}''s tracks haven't been loaded yet."
            )
            # Explicit, user-triggered sync only — never auto-fetched on
            # selection, since track syncing was deliberately split out
            # from playlist syncing to keep Spotify API calls scoped
            # and intentional (roadmap item 1).
            self.sync_tracks_button.show()
            self.track_area_stack.setCurrentWidget(self._track_empty_panel)
            return

        self.track_area_stack.setCurrentWidget(self.track_table_card)

        self.track_table.setRowCount(len(statuses))
        action_widgets: list[QWidget] = []

        for row, status in enumerate(statuses):
            label = f"{status.track.artist} - {status.track.title}"
            self.track_table.setItem(row, 0, QTableWidgetItem(label))

            state_text = _STATE_LABELS[status.state]
            # Roadmap item 66 (Phase 4.1) — only meaningful for
            # NEEDS_REVIEW now: REVIEW_CANDIDATE's own label already
            # says "Candidate to review," so appending this here would
            # just repeat itself (dashboard_service.py's own
            # _compute_status never sets soulseek_candidate on any other
            # state — see its docstring).
            if status.state == NEEDS_REVIEW and status.soulseek_candidate is not None:
                state_text += " (SoulSeek candidate found)"
            status_item = QTableWidgetItem(state_text)

            # Roadmap item 56 §2.4 (extended by item 66 Phase 4.1) —
            # only these states have anything to jump to on the Review
            # page; every other status is a genuine no-op on
            # double-click, so only these get the affordance rather than
            # a misleading cue on every row.
            if status.state in (NEEDS_REVIEW, AWAITING_REVIEW, REVIEW_CANDIDATE):
                status_item.setToolTip(
                    help_text.TOOLTIP_DOUBLE_CLICK_TO_REVIEW
                )
                font = status_item.font()
                font.setUnderline(True)
                status_item.setFont(font)
                status_item.setForeground(QColor(theme.ACCENT))

            self.track_table.setItem(row, 1, status_item)

            if (
                    status.state == DOWNLOADING
                    and status.total_bytes
                    and status.bytes_transferred is not None
            ):
                progress = QProgressBar()
                progress.setMaximum(status.total_bytes)
                progress.setValue(status.bytes_transferred)
                theme.style_determinate_progress_bar(progress)
                # Roadmap item C3 (round 5) — a bare QProgressBar handed
                # to setCellWidget gets resized to the whole (tall) cell
                # rect, then the global `QProgressBar { max-height:
                # 14px; }` rule clamps it to the TOP instead of
                # centering it — the identical bug B4/item 96 fixed on
                # the Downloads page, in this Dashboard-only builder B4
                # never touched. `_wrap_progress_bar` is the one shared
                # container both pages now go through; the Dashboard
                # deliberately passes no label (`None`) — no ETA is
                # tracked per-track here, unlike Downloads.
                self.track_table.setCellWidget(
                    row, 2, _wrap_progress_bar(progress, None),
                )
            else:
                self.track_table.setCellWidget(row, 2, QWidget())

            track_actions = self._build_track_actions(status)
            action_widgets.append(track_actions)
            self.track_table.setCellWidget(row, 3, track_actions)

        self._size_track_columns(action_widgets)

    def _size_track_columns(self, action_widgets: list[QWidget]) -> None:
        # Roadmap item R5 (5b.1) — same shape as
        # _size_duplicates_columns/_size_search_columns, via the new
        # shared theme.size_action_column.
        header = self.track_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        theme.size_action_column(self.track_table, 3, action_widgets)

    def _on_track_table_cell_double_clicked(
            self, row: int, _column: int,
    ) -> None:
        if row < 0 or row >= len(self._current_track_statuses):
            return

        status = self._current_track_statuses[row]

        if status.state not in (NEEDS_REVIEW, AWAITING_REVIEW, REVIEW_CANDIDATE):
            # A genuine no-op — every other status has nothing to jump
            # to, so double-clicking those rows must not navigate at all.
            return

        self._show_page("review", focus_track_id=status.track.id)

    def _fetch_next_step_facts(self) -> _NextStepFacts:
        # Bundled into one background-thread call rather than one
        # run_worker round trip per fact — each field still traces to
        # exactly one real service/Application call, this just avoids
        # a chain of sequential worker hops to gather them.
        playlist_name = (
            self.selected_playlist.name
            if self.selected_playlist is not None
            else None
        )
        track_statuses = (
            self.application.dashboard_service
            .get_playlist_track_status(playlist_name)
            if playlist_name is not None
            else None
        )

        return _NextStepFacts(
            spotify_configured=self.application.spotify_configured,
            has_library_location=bool(
                self.application.library_service.list_locations()
            ),
            has_cached_playlists=bool(
                self.application.sync_service.list_playlists()
            ),
            selected_playlist_name=playlist_name,
            track_statuses=track_statuses,
            has_scanned_library=(
                self.application.library_service.has_scanned_library()
            ),
            soulseek_configured=self.application.soulseek_configured,
        )

    def _poll_next_step(self) -> None:
        # Roadmap item R7.6 — the Dashboard's own CTA banner has no
        # tray-menu relevance; skip entirely while hidden.
        if self._hidden_to_tray:
            return

        run_worker(
            self.thread_pool,
            self._fetch_next_step_facts,
            on_finished=self._render_next_step,
        )

    def _on_next_step_dismissed(self) -> None:
        self._dismissed_next_step_key = self._current_next_step_key

    def _render_next_step(self, facts: _NextStepFacts) -> None:
        step = _decide_next_step(facts)

        # Roadmap item 71 (P3) — identity of "the step currently being
        # offered," so a dismissal can be remembered per-step rather
        # than globally: a real fact change (playlist switched, or the
        # underlying next-step reason changed) always surfaces again.
        key = (
            facts.selected_playlist_name,
            step.message if step is not None else None,
            step.action if step is not None else None,
        )
        already_dismissed = key == self._dismissed_next_step_key
        self._current_next_step_key = key

        if not already_dismissed:
            # Either never dismissed, or dismissed a DIFFERENT step —
            # that dismissal no longer applies to what's showing now.
            self._dismissed_next_step_key = None

        if step is None:
            self.next_step_notice.dismiss()
        elif already_dismissed:
            pass
        else:
            action = step.action
            self.next_step_notice.show_message(
                step.message,
                kind=step.kind,
                action_text=step.action_text,
                on_action=(
                    (lambda: self._on_next_step_action(action))
                    if action is not None else None
                ),
            )

        # The action row's own Download button offers the exact same
        # download_playlist() call, against the exact same unmatched-
        # tracks set, as the CTA's own "download" action (confirmed:
        # get_unmatched_for_playlist filters match_method IS NULL,
        # which already excludes needs-review tracks either way — so
        # there is no genuine scope difference to preserve between
        # them today). Showing both at once is a real duplicate
        # action, not two different things that happen to look
        # similar — hide the row's copy while the CTA is already
        # offering it, rather than inventing a second, artificially
        # different scope. Re-shown once anything else is the current
        # CTA (or once the CTA has nothing to show at all), so it
        # stays available as an ordinary manual action.
        #
        # Roadmap item 65 (Phase 2.1/2.2 fix) — every setVisible/
        # setEnabled call below now first checks busy_actions.is_running
        # for that same button's own key, and skips touching it entirely
        # if so. This poll tick has no idea a background action might
        # still be mid-flight; without this guard, Phase 0's own 0.1
        # investigation proved this exact method re-enables a button
        # within 2s of a click regardless of whether its real work was
        # still running — and, for Download specifically, a real
        # reported bug: this setVisible call could hide the button out
        # from under an in-progress download the instant the CTA's own
        # action was still "download" (which it usually still is, since
        # the missing-track count hasn't changed yet).
        if not self.busy_actions.is_running("download"):
            self.download_button.setVisible(
                step is None or step.action != "download"
            )
            # Disabled, not hidden, for every other action-row button —
            # matches the CTA strip's own point (don't present an action
            # that genuinely can't do anything yet) without the row's
            # width jumping around on every fact change.
            self.download_button.setEnabled(
                facts.selected_playlist_name is not None
            )

        if not self.busy_actions.is_running("sync"):
            self.sync_button.setEnabled(facts.spotify_configured)

        if not self.busy_actions.is_running("scan"):
            self.scan_button.setEnabled(facts.has_library_location)

        if not self.busy_actions.is_running("match"):
            self.match_button.setEnabled(
                facts.has_cached_playlists and facts.has_library_location
            )

    def _on_next_step_action(self, action: str) -> None:
        if action == "settings_connection":
            self._on_settings_clicked(SETTINGS_TAB_CONNECTION)
        elif action == "settings_locations":
            self._on_settings_clicked(SETTINGS_TAB_LOCATIONS)
        elif action == "sync":
            self._on_sync_clicked()
        elif action == "sync_tracks":
            self._on_sync_tracks_clicked()
        elif action == "scan":
            self._on_scan_clicked()
        elif action == "download":
            self._on_download_clicked()
        elif action == "tag_playlist":
            self._on_tag_playlist_clicked()

    def _poll_active_downloads(self) -> None:
        # Purely observational — a cheap local DB read via
        # DashboardService.get_active_downloads(), GLOBAL across every
        # playlist (unlike _poll_selected_playlist above). No
        # confirm/reject action lives here; that's a separate future
        # Review screen.
        run_worker(
            self.thread_pool,
            self.application.dashboard_service.get_active_downloads,
            on_finished=self._render_active_downloads,
        )

    def _render_active_downloads(self, downloads: list[ActiveDownload]) -> None:
        # Roadmap item R7.3 — the tray menu's own status line, built
        # from this same fetch. Counted here (not deferred behind the
        # R7.6 hidden-window gate below) since the whole point of the
        # tray is a live status while nothing else is visible.
        self._active_downloads_count = sum(
            1 for download in downloads
            if download.request.status == "downloading"
        )

        # Roadmap item R7.6 — re-rendering the table (and the nav
        # badge/ETA header, both visual-only) is pure waste while
        # nobody can see the window; the real backend poll that feeds
        # this data keeps running regardless (see _trigger_backend_poll,
        # untouched by this check — it lives on a separate timer).
        if self._hidden_to_tray:
            return

        self._update_nav_badge("downloads", len(downloads))
        self.downloads_table.setRowCount(len(downloads))
        self._render_aggregate_eta(downloads)

        for row, download in enumerate(downloads):
            track = download.track
            label = f"{track.artist} - {track.title}"
            self.downloads_table.setItem(row, 0, QTableWidgetItem(label))
            self.downloads_table.setItem(
                row, 1, QTableWidgetItem(download.playlist_name),
            )
            self.downloads_table.setItem(
                row, 2, QTableWidgetItem(download.request.role.capitalize()),
            )

            status = download.request.status
            status_text = _DOWNLOAD_STATUS_LABELS.get(status, status)
            self.downloads_table.setItem(row, 3, QTableWidgetItem(status_text))

            request = download.request
            is_terminal = status in _DOWNLOAD_TERMINAL_STATUSES

            if is_terminal:
                # Roadmap item 56 Phase 5.4 — evicted the moment a
                # terminal status is seen, not left to evict_except()'s
                # once-per-poll sweep; the ETA tracker is never
                # consulted for this row at all below.
                if request.id is not None:
                    self._eta_tracker.evict(request.id)
                eta_text = None
            else:
                eta_text = (
                    self._eta_tracker.describe(
                        request.id, request.total_bytes,
                    )
                    if request.id is not None and request.total_bytes
                    else None
                )

            self.downloads_table.setCellWidget(
                row, 4, _build_progress_widget(download, eta_text),
            )

        # Roadmap item R5 (5b.2) — this table's progress-bar cell
        # widgets are real per-row content, same treatment as every
        # table with an Actions column even though this one has none
        # (item 80's own deliberate scoping — see _build_progress_widget/
        # _build_terminal_progress_widget's bespoke stretch factor).
        self.downloads_table.resizeRowsToContents()

    def _render_aggregate_eta(self, downloads: list[ActiveDownload]) -> None:
        # No reserved-but-blank strip when there's nothing active — the
        # empty string collapses the label to zero height, matching
        # this project's "blank, not a misleading control" precedent
        # (item 27) rather than showing "0 transferring" forever.
        if not downloads:
            self.downloads_eta_label.setText("")
            self.downloads_eta_label.setToolTip("")
            return

        # Roadmap item 56 Phase 5.4 — a terminal row (completed/failed/
        # ready_for_review, still visible for
        # RECENTLY_FINISHED_WINDOW_SECONDS) has nothing left to
        # estimate; counting it here previously folded it into the
        # header's "queued (no estimate)" figure, which reads as
        # actively waiting rather than already finished.
        pairs = [
            (download.request.id, download.request.total_bytes)
            for download in downloads
            if download.request.id is not None
            and download.request.status not in _DOWNLOAD_TERMINAL_STATUSES
        ]
        result = self._eta_tracker.aggregate(pairs)
        self.downloads_eta_label.setText(format_aggregate_header(result))
        self.downloads_eta_label.setToolTip(AGGREGATE_ETA_TOOLTIP)

    def _poll_review_items(self) -> None:
        # All three halves are cheap, local-DB-only reads (like
        # get_active_downloads above) — no real slskd network calls, so
        # this belongs on the 2s display-refresh timer, not the 20s
        # backend-poll one. Bundled into one worker call rather than
        # three so every table updates from the same consistent DB
        # snapshot.
        def fetch() -> tuple[
                NeedsReviewCandidates, PendingUpgrades,
                list[NeedsReviewMatch],
        ]:
            service = self.application.download_service
            return (
                service.get_review_candidates(),
                service.get_pending_upgrade_reviews(),
                self.application.library_service.get_needs_review_matches(),
            )

        run_worker(
            self.thread_pool,
            fetch,
            on_finished=self._render_review_items,
        )

    def _render_review_items(
            self,
            data: tuple[
                NeedsReviewCandidates, PendingUpgrades,
                list[NeedsReviewMatch],
            ],
    ) -> None:
        candidates, upgrades, local_matches = data
        total = len(candidates) + len(upgrades) + len(local_matches)
        self._update_nav_badge("review", total)
        # Roadmap item R7.3 — the tray menu's own "Review (N)"/
        # "Upgrades (N)" counts, built from this same fetch (never a
        # third source of truth). "Review" covers everything needing a
        # confirm/reject decision; "Upgrades" is its own real Phase 2
        # concept (replace/decline), kept distinct in the menu the same
        # way the two are already distinct sections on this page.
        self._needs_review_count = len(candidates) + len(local_matches)
        self._pending_upgrades_count = len(upgrades)
        self._check_for_needs_decision_notification(total)
        self._render_needs_review_candidates(candidates)
        self._render_pending_upgrades(upgrades)
        self._render_local_needs_review_matches(local_matches)
        self._focus_pending_review_row(candidates, upgrades, local_matches)

    def _render_needs_review_candidates(
            self,
            candidates: NeedsReviewCandidates,
    ) -> None:
        # Roadmap item R7.6 — counts/notifications are already computed
        # by the caller (_render_review_items) before this runs; the
        # table rebuild itself is pure waste while hidden.
        if self._hidden_to_tray:
            return

        self.review_needs_table.setRowCount(len(candidates))
        action_widgets: list[QWidget] = []

        for row, (track, candidate) in enumerate(candidates):
            label = f"{track.artist} - {track.title}"
            self.review_needs_table.setItem(row, 0, QTableWidgetItem(label))
            self.review_needs_table.setItem(
                row, 1, QTableWidgetItem(f"{candidate.score:.1f}"),
            )

            candidate_text = f"{candidate.quality_descriptor} — {candidate.username}"
            self.review_needs_table.setItem(
                row, 2, QTableWidgetItem(candidate_text),
            )

            needs_review_actions = self._build_needs_review_actions(track.id)
            action_widgets.append(needs_review_actions)
            self.review_needs_table.setCellWidget(row, 3, needs_review_actions)

        self._size_review_needs_columns(action_widgets)

    def _size_review_needs_columns(self, action_widgets: list[QWidget]) -> None:
        # Roadmap item R5 (5b.1).
        header = self.review_needs_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        theme.size_action_column(self.review_needs_table, 3, action_widgets)

    def _build_needs_review_actions(self, track_id: str) -> QWidget:
        confirm_button = QPushButton("Confirm")
        confirm_button.setToolTip(help_text.TOOLTIP_CONFIRM_REVIEW_CANDIDATE)
        reject_button = QPushButton("Reject")
        reject_button.setToolTip(help_text.TOOLTIP_REJECT_REVIEW_CANDIDATE)

        confirm_button.clicked.connect(
            lambda: self._on_confirm_review_candidate(track_id, confirm_button)
        )
        reject_button.clicked.connect(
            lambda: self._on_reject_review_candidate(track_id, reject_button)
        )

        return theme.cell_widget(confirm_button, reject_button)

    def _on_confirm_review_candidate(
            self,
            track_id: str,
            button: QPushButton,
    ) -> None:
        # confirm_review_candidate makes a real request_download() call
        # (network) — routed through the worker pool like every other
        # long-running action, never called directly on the main thread.
        run_worker(
            self.thread_pool,
            lambda: self.application.download_service.confirm_review_candidate(
                track_id
            ),
            button=button,
            status_label=self.status_label,
            on_finished=lambda _: self._poll_review_items(),
        )

    def _on_reject_review_candidate(
            self,
            track_id: str,
            button: QPushButton,
    ) -> None:
        run_worker(
            self.thread_pool,
            lambda: self.application.download_service.reject_review_candidate(
                track_id
            ),
            button=button,
            status_label=self.status_label,
            on_finished=lambda _: self._poll_review_items(),
        )

    def _render_pending_upgrades(self, upgrades: PendingUpgrades) -> None:
        # Roadmap item R3.1 — the real list "Replace all" acts on,
        # recomputed fresh every render so a click always sees exactly
        # what's on screen right now (item 76's own "recompute at click
        # time" lesson, R3.3). Kept unconditional (not behind the R7.6
        # hidden-window gate below) — the underlying poll keeps
        # fetching fresh data while hidden, so this stays correct the
        # instant the window is shown again.
        self._current_pending_upgrades = upgrades

        # Roadmap item R7.6 — the table rebuild itself is pure waste
        # while hidden.
        if self._hidden_to_tray:
            return

        self.review_upgrades_table.setRowCount(len(upgrades))
        self.replace_all_upgrades_button.setEnabled(len(upgrades) > 0)
        self.replace_all_upgrades_button.setText(
            f"Replace all ({len(upgrades)})" if upgrades else "Replace all"
        )

        # Roadmap item R2.3 — prune keys for rows that no longer exist,
        # so this can't grow unbounded across a long session.
        live_request_ids = {details.request_id for details in upgrades}
        self._upgrade_delete_checked &= live_request_ids

        action_widgets: list[QWidget] = []

        for row, details in enumerate(upgrades):
            label = f"{details.track.artist} - {details.track.title}"
            self.review_upgrades_table.setItem(row, 0, QTableWidgetItem(label))
            self.review_upgrades_table.setItem(
                row, 1, QTableWidgetItem(details.current_description),
            )
            self.review_upgrades_table.setItem(
                row, 2, QTableWidgetItem(details.quality_descriptor or "—"),
            )
            upgrade_actions = self._build_upgrade_actions(details)
            action_widgets.append(upgrade_actions)
            self.review_upgrades_table.setCellWidget(row, 3, upgrade_actions)

        self._size_review_upgrades_columns(action_widgets)

    def _size_review_upgrades_columns(self, action_widgets: list[QWidget]) -> None:
        # Roadmap item R5 (5b.1).
        header = self.review_upgrades_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        theme.size_action_column(self.review_upgrades_table, 3, action_widgets)

    def _on_upgrade_delete_checkbox_toggled(
            self, request_id: int, checked: bool,
    ) -> None:
        if checked:
            self._upgrade_delete_checked.add(request_id)
        else:
            self._upgrade_delete_checked.discard(request_id)

    def _build_upgrade_actions(self, details: UpgradeReviewDetails) -> QWidget:
        replace_button = QPushButton("Replace")
        replace_button.setToolTip(help_text.TOOLTIP_REPLACE_UPGRADE)
        decline_button = QPushButton("Decline")
        decline_button.setToolTip(help_text.TOOLTIP_DECLINE_UPGRADE)

        # The "delete old file?" control only ever appears when there's
        # a real old file to delete — mirrors the CLI's own guard around
        # its second input() prompt (get_upgrade_review_details leaves
        # old_file_path unset when there's nothing to replace).
        widgets: list[QWidget] = []
        delete_checkbox: QCheckBox | None = None
        if details.old_file_path is not None:
            delete_checkbox = QCheckBox("Delete old file")
            delete_checkbox.setToolTip(
                help_text.TOOLTIP_DELETE_OLD_FILE_CHECKBOX
            )
            # Roadmap item R2.1 — restore whatever this row's checkbox
            # was set to before the last rebuild, and keep the state
            # map updated as the user toggles it, keyed by the stable
            # request_id (never row index, which shifts as rows are
            # added/removed).
            request_id = details.request_id
            delete_checkbox.setChecked(
                request_id in self._upgrade_delete_checked
            )
            delete_checkbox.toggled.connect(
                lambda checked, request_id=request_id: (
                    self._on_upgrade_delete_checkbox_toggled(
                        request_id, checked,
                    )
                )
            )
            widgets.append(delete_checkbox)

        def on_replace() -> None:
            delete_old = delete_checkbox is not None and delete_checkbox.isChecked()
            self._on_apply_upgrade_decision(
                details.request_id, True, delete_old, replace_button,
            )

        def on_decline() -> None:
            # A true no-op per apply_upgrade_decision's own contract —
            # the row stays ready_for_review and is offered again next
            # poll, identical to declining the CLI's prompt.
            self._on_apply_upgrade_decision(
                details.request_id, False, False, decline_button,
            )

        replace_button.clicked.connect(on_replace)
        decline_button.clicked.connect(on_decline)

        widgets.extend((replace_button, decline_button))
        return theme.cell_widget(*widgets)

    def _on_apply_upgrade_decision(
            self,
            request_id: int,
            replace: bool,
            delete_old: bool,
            button: QPushButton,
    ) -> None:
        run_worker(
            self.thread_pool,
            lambda: self.application.download_service.apply_upgrade_decision(
                request_id, replace, delete_old,
            ),
            button=button,
            on_finished=self._on_upgrade_decision_finished,
        )

    def _on_upgrade_decision_finished(self, message: str | None) -> None:
        # apply_upgrade_decision returns None for a decline (no-op, no
        # message needed) and a short status string for a real replace —
        # run_worker's own status_label wiring only fires on error, so
        # the success message is surfaced here instead.
        if message is not None:
            self.status_label.setText(message)

        self._poll_review_items()

    def _on_replace_all_upgrades_clicked(self) -> None:
        # Roadmap item R3.1/R3.3 — built fresh from what's actually on
        # screen right now, never a stale plan from an earlier click.
        upgrades = self._current_pending_upgrades

        if not upgrades:
            return

        dialog = BulkReplaceUpgradesDialog(self, upgrades)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        delete_old = dialog.delete_old_checkbox.isChecked()
        request_ids = [details.request_id for details in upgrades]

        run_worker(
            self.thread_pool,
            lambda: self.application.download_service
            .apply_upgrade_decisions_batch(request_ids, delete_old),
            button=self.replace_all_upgrades_button,
            status_label=self.status_label,
            on_finished=self._on_bulk_replace_upgrades_finished,
        )

    def _on_bulk_replace_upgrades_finished(
            self, result: BulkUpgradeReplaceResult,
    ) -> None:
        QMessageBox.information(
            self,
            help_text.BULK_REPLACE_UPGRADES_DIALOG_TITLE,
            help_text.format_bulk_replace_upgrades_result(result),
        )
        # A partial failure's rows stay ready_for_review (apply_upgrade_
        # decision's own contract — see apply_upgrade_decisions_batch's
        # docstring) and are simply offered again by this same refresh,
        # never dropped.
        self._poll_review_items()

    def _render_local_needs_review_matches(
            self,
            matches: list[NeedsReviewMatch],
    ) -> None:
        # Roadmap item R7.6 — the table rebuild itself is pure waste
        # while hidden.
        if self._hidden_to_tray:
            return

        self.review_local_table.setRowCount(len(matches))
        action_widgets: list[QWidget] = []

        for row, match in enumerate(matches):
            label = f"{match.track_artist} - {match.track_title}"
            self.review_local_table.setItem(row, 0, QTableWidgetItem(label))
            self.review_local_table.setItem(
                row, 1, QTableWidgetItem(match.local_file_path),
            )
            self.review_local_table.setItem(
                row, 2, QTableWidgetItem(match.location_name),
            )
            self.review_local_table.setItem(
                row, 3, QTableWidgetItem(f"{match.score:.1f}"),
            )
            local_review_actions = self._build_local_review_actions(
                match.track_id,
            )
            action_widgets.append(local_review_actions)
            self.review_local_table.setCellWidget(row, 4, local_review_actions)

        self._size_review_local_columns(action_widgets)

    def _size_review_local_columns(self, action_widgets: list[QWidget]) -> None:
        # Roadmap item R5 (5b.1).
        header = self.review_local_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        theme.size_action_column(self.review_local_table, 4, action_widgets)

    def _build_local_review_actions(self, track_id: str) -> QWidget:
        confirm_button = QPushButton("Confirm")
        confirm_button.setToolTip(help_text.TOOLTIP_CONFIRM_LOCAL_MATCH)
        reject_button = QPushButton("Reject")
        reject_button.setToolTip(help_text.TOOLTIP_REJECT_LOCAL_MATCH)

        confirm_button.clicked.connect(
            lambda: self._on_confirm_local_match(track_id, confirm_button)
        )
        reject_button.clicked.connect(
            lambda: self._on_reject_local_match(track_id, reject_button)
        )

        return theme.cell_widget(confirm_button, reject_button)

    def _on_confirm_local_match(
            self,
            track_id: str,
            button: QPushButton,
    ) -> None:
        # No file on disk is touched by confirm_match() — no double-
        # confirm gate, matching item 27's precedent that this project's
        # confirmation gate is for file replacement, not DB state.
        run_worker(
            self.thread_pool,
            lambda: self.application.library_service.confirm_match(
                track_id
            ),
            button=button,
            status_label=self.status_label,
            on_finished=self._on_local_review_decision_finished,
        )

    def _on_reject_local_match(
            self,
            track_id: str,
            button: QPushButton,
    ) -> None:
        run_worker(
            self.thread_pool,
            lambda: self.application.library_service.reject_match(
                track_id
            ),
            button=button,
            status_label=self.status_label,
            on_finished=self._on_local_review_decision_finished,
        )

    def _on_local_review_decision_finished(self, _result: None) -> None:
        self._poll_review_items()
        self._poll_selected_playlist()

    def _focus_pending_review_row(
            self,
            candidates: NeedsReviewCandidates,
            upgrades: PendingUpgrades,
            local_matches: list[NeedsReviewMatch],
    ) -> None:
        # Double-clicking a NEEDS_REVIEW/AWAITING_REVIEW/REVIEW_CANDIDATE
        # Dashboard cell (roadmap item 56 Phase 2 §2.4, extended by item
        # 66 Phase 4.1 to cover REVIEW_CANDIDATE too) sets
        # _pending_review_focus_track_id and switches to this page; once
        # the real data has actually loaded, this scrolls to and selects
        # the matching row — a track that turns out to have nothing here
        # yet (e.g. a locked/shortlisted RETRYING row, not yet
        # ready_for_review) just lands on the page with nothing
        # selected, rather than erroring.
        track_id = self._pending_review_focus_track_id

        if track_id is None:
            return

        self._pending_review_focus_track_id = None

        for row, (track, _candidate) in enumerate(candidates):
            if track.id == track_id:
                self.review_needs_table.selectRow(row)
                needs_item = self.review_needs_table.item(row, 0)
                if needs_item is not None:
                    self.review_needs_table.scrollToItem(needs_item)
                return

        for row, details in enumerate(upgrades):
            if details.track.id == track_id:
                self.review_upgrades_table.selectRow(row)
                item = self.review_upgrades_table.item(row, 0)
                if item is not None:
                    self.review_upgrades_table.scrollToItem(item)
                return

        for row, match in enumerate(local_matches):
            if match.track_id == track_id:
                self.review_local_table.selectRow(row)
                local_item = self.review_local_table.item(row, 0)
                if local_item is not None:
                    self.review_local_table.scrollToItem(local_item)
                return

    def _trigger_backend_poll(self) -> None:
        if self._backend_poll_in_progress:
            # A previous poll_downloads() call (real slskd network
            # calls) is still running — a slow or hanging response must
            # not cause a second, overlapping writer to start on top of
            # it. Skip this tick; the next one will try again.
            return

        if not self.application.soulseek_configured:
            return

        self._backend_poll_in_progress = True

        def on_poll_finished(_: object) -> None:
            self._backend_poll_in_progress = False
            self._sample_download_progress()
            # A settled download completing during this real poll (Phase
            # 1's indexing fix) flips a track straight to IN_LIBRARY —
            # refresh the selected playlist's own track table right now
            # rather than waiting up to POLL_INTERVAL_MS for the next
            # 2s display tick to happen to catch it.
            self._poll_selected_playlist()
            # Roadmap item R7.5 — checked on the same real 20s cycle
            # that can actually produce a newly-completed download, not
            # a new timer of its own.
            self._check_for_download_notifications()

        def on_poll_error(_: str) -> None:
            self._backend_poll_in_progress = False
            self._notify_error(
                "Seeker couldn't reach slskd — check that it's running."
            )

        run_worker(
            self.thread_pool,
            self.application.download_service.poll_downloads,
            on_finished=on_poll_finished,
            on_error=on_poll_error,
        )

    def _sample_download_progress(self) -> None:
        # Task 2 — feeds DownloadEtaTracker exactly once per real
        # poll_downloads() cycle (this method is only ever called from
        # _trigger_backend_poll's on_finished above), never from the 2s
        # display-refresh tick — sampling there would just re-diff
        # against the same DB row poll_downloads() hasn't touched yet.
        run_worker(
            self.thread_pool,
            self.application.dashboard_service.get_active_downloads,
            on_finished=self._record_eta_samples,
        )

    def _record_eta_samples(self, downloads: list[ActiveDownload]) -> None:
        active_request_ids = {
            download.request.id
            for download in downloads
            if download.request.id is not None
        }
        self._eta_tracker.evict_except(active_request_ids)

        now = datetime.now(timezone.utc)
        for download in downloads:
            request = download.request
            if request.id is not None and request.bytes_transferred is not None:
                self._eta_tracker.record(request.id, request.bytes_transferred, now)

    def _run_busy_worker(
            self,
            key: str,
            button: QPushButton,
            fn: Callable[[], Any] | Callable[[Callable[[str, int, int], None]], Any],
            *,
            busy_text: str | None = None,
            status_label: QLabel | None = None,
            on_finished: Callable[[Any], None] | None = None,
            on_error: Callable[[str], None] | None = None,
            reports_progress: bool = False,
    ) -> None:
        # Roadmap item 65 (Phase 2.1) — the shared shape for a long-
        # running action that should register in busy_actions/the
        # activity strip: begin() before submitting, end() on every real
        # completion path (success or error) so it's never left marked
        # running past its own task. Replaces passing button= directly to
        # run_worker() for every call site converted to use this — the
        # registry, not run_worker itself, now owns that button's
        # enable/disable + text for the duration.
        self.busy_actions.begin(key, button, busy_text)
        self._render_activity_strip()

        def wrapped_finished(result: Any) -> None:
            self.busy_actions.end(key)
            self._activity_progress.pop(key, None)
            self._render_activity_strip()
            if on_finished is not None:
                on_finished(result)

        def wrapped_error(message: str) -> None:
            self.busy_actions.end(key)
            self._activity_progress.pop(key, None)
            self._render_activity_strip()
            if on_error is not None:
                on_error(message)

        run_worker(
            self.thread_pool, fn, status_label=status_label,
            on_finished=wrapped_finished, on_error=wrapped_error,
            on_progress=(
                (lambda stage, current, total:
                 self._on_activity_progress(key, stage, current, total))
                if reports_progress else None
            ),
        )

    def _on_sync_clicked(self) -> None:
        self._run_busy_worker(
            "sync", self.sync_button,
            self.application.sync_service.sync_playlists,
            status_label=self.status_label,
            on_finished=lambda _: self._load_playlists(),
        )

    def _on_scan_clicked(self) -> None:
        # scan_and_match() chains scan_all() + match_all() into one
        # background call (roadmap item 56) — a plain scan used to leave
        # newly-found files with no track_matches row at all until a
        # separate, non-obvious "Re-match library" click. run_worker()'s
        # single dispatcher gives no safe way to push a genuine live
        # "now matching..." update partway through one background call
        # (see ui/workers.py's own docstring on why a per-task signal was
        # deliberately removed) — this sets an immediate placeholder
        # instead, replaced by the real combined result once the whole
        # call finishes.
        self._run_busy_worker(
            "scan", self.scan_button,
            self.application.library_service.scan_and_match,
            busy_text="Scanning…",
            status_label=self.status_label,
            on_finished=self._on_scan_and_match_finished,
        )
        self.status_label.setText("Scanning library, then matching tracks…")

    def _on_scan_and_match_finished(self, result: dict[str, int]) -> None:
        self.status_label.setText(
            f"Scanned: {result['added']} added, {result['updated']} "
            f"updated, {result['removed']} removed. "
            f"Matched: {result['auto']} auto, "
            f"{result['needs_review']} needs review, "
            f"{result['unmatched']} unmatched."
        )
        self._poll_selected_playlist()

    def _on_match_clicked(self) -> None:
        self._run_busy_worker(
            "match", self.match_button,
            self.application.track_matcher.match_all,
            status_label=self.status_label,
            on_finished=lambda _: self._poll_selected_playlist(),
        )

    def _set_download_button_busy(self) -> None:
        # Idempotent (BusyActionRegistry.begin() no-ops if already
        # running) — safe to call again at every hop of the download
        # chain below, matching this method's own pre-registry behavior.
        self.busy_actions.begin(
            "download", self.download_button, "Starting download…",
        )
        self._render_activity_strip()

    def _reset_download_button(self) -> None:
        self.busy_actions.end("download")
        self._render_activity_strip()

    def _on_download_clicked(self) -> None:
        if self.selected_playlist is None:
            self.dashboard_notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        playlist = self.selected_playlist
        playlist_name = playlist.name

        # Roadmap item 56 Phase 5.1 — the button previously gave no
        # feedback at all that anything had started, across this
        # entire multi-step chain (resolvability check, maybe a
        # destination dialog, then the real download). Disabled +
        # relabeled here and re-asserted at the top of every
        # continuation below (run_worker's own success-path
        # `button.setEnabled(True)` would otherwise flip it back on
        # between hops) so it never reads "enabled but says Starting
        # download…" at any point in the chain; reset on every real
        # exit path (cancelled dialog, no locations, real completion,
        # or a genuine error via on_error).
        self._set_download_button_busy()

        # Roadmap item 65 (Phase 3.2) — a playlist with its OWN
        # destination already set (`playlist.download_location_id`,
        # already loaded on the Playlist itself — no extra query needed)
        # always skips straight to the real download; the prompt below
        # is only for a playlist that would otherwise silently fall
        # through to the configured default (roadmap item 6 §3's own
        # earlier fallback), so the user gets to see and confirm — or
        # change — where it's actually going, once per playlist.
        if playlist.download_location_id is not None:
            self._start_download(playlist_name)
            return

        # Fetches both the real current fallback (to pre-fill the
        # dialog with the exact path it would already use — shares
        # DownloadService._resolve_destination with the real move step
        # via get_resolved_destination, so this can never drift into a
        # second, different notion of "resolvable") and every registered
        # location (for the picker), in one round trip.
        run_worker(
            self.thread_pool,
            lambda: (
                self.application.download_service
                .get_resolved_destination(playlist_name),
                self.application.library_service.list_locations(),
            ),
            on_finished=lambda result: self._open_destination_dialog(
                playlist_name, result[1], result[0],
            ),
            on_error=lambda _message: self._reset_download_button(),
        )

    def _open_destination_dialog(
            self,
            playlist_name: str,
            locations: list[tuple[LibraryLocation, bool]],
            resolved: tuple[LibraryLocation, str | None] | None = None,
    ) -> None:
        if not locations:
            self._reset_download_button()
            self.dashboard_notice.show_message(
                help_text.NO_LOCATIONS_FOR_DESTINATION_DIALOG,
                kind="warning",
            )
            return

        location_objects = [location for location, _ in locations]

        # Roadmap item 65 (Phase 3.2) — when the real fallback already
        # resolves (`resolved` given), pre-fill with exactly what it
        # would use: that location, and its real subfolder (already
        # sanitized by _resolve_destination — never re-sanitized here).
        # Falls back to the app-wide configured default (item 6 §3's
        # original behavior) only when nothing resolved at all.
        if resolved is not None:
            prefill_location, prefill_subfolder = resolved
            default_location_id: int | None = prefill_location.id
        else:
            prefill_subfolder = None
            default_location_id = (
                self.application._config_store.default_download_location_id
            )

        dialog = DestinationDialog(
            self, playlist_name, location_objects, default_location_id,
            initial_subfolder=prefill_subfolder,
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._reset_download_button()
            return

        location_id = dialog.selected_location_id()

        if location_id is None:
            self._reset_download_button()
            return

        subfolder = dialog.selected_subfolder()
        remember_for_playlist = dialog.remember_for_playlist()

        def do_persist() -> None:
            if remember_for_playlist:
                location = next(
                    loc for loc in location_objects if loc.id == location_id
                )
                self.application.download_service.set_destination(
                    playlist_name, location.name, subfolder,
                )
            else:
                # Not remembered specifically for this playlist — the
                # only other real destination concept is the app-wide
                # default (roadmap item 6 §1), so this becomes that.
                # Deliberately always True for the subfolder-per-
                # playlist toggle here: the field was prefilled with
                # the playlist's own name, so treating this choice as
                # "per playlist" matches what was actually shown,
                # even if the text was hand-edited to something else
                # for this one confirmation.
                self.application.persist_default_destination(
                    location_id, True,
                )

        self._set_download_button_busy()

        run_worker(
            self.thread_pool,
            do_persist,
            on_finished=lambda _: self._start_download(playlist_name),
            on_error=lambda _message: self._reset_download_button(),
        )

    def _start_download(self, playlist_name: str) -> None:
        self._set_download_button_busy()

        run_worker(
            self.thread_pool,
            lambda: self.application.download_service.download_playlist(
                playlist_name
            ),
            status_label=self.status_label,
            on_finished=self._on_download_finished,
            on_error=lambda _message: self._reset_download_button(),
        )

    def _on_download_finished(self, result: dict[str, Any]) -> None:
        self._reset_download_button()
        self._poll_selected_playlist()

        # Roadmap item 66 (Phase 4.2) — the real fix for "Requested 16,
        # skipped 12 (no candidates found)" when several of those 12 had
        # in fact become real Review candidates: help_text.py's own
        # formatter names each outcome separately rather than folding
        # them into one generic figure.
        message = help_text.format_download_result_message(result)
        kind = "success" if result["requested"] else "info"
        self.dashboard_notice.show_message(message, kind=kind)

    def _on_sync_tracks_clicked(self) -> None:
        if self.selected_playlist is None:
            return

        playlist = self.selected_playlist

        def do_sync() -> Any:
            self.application.sync_service.sync_playlist_tracks(playlist)

        self._run_busy_worker(
            "sync_tracks", self.sync_tracks_button, do_sync,
            status_label=self.status_label,
            on_finished=lambda _: self._poll_selected_playlist(),
        )

    def _on_settings_clicked(self, initial_tab: str | None = None) -> None:
        # Roadmap item 56 Phase 3 — self.settings_page is a single,
        # long-lived page built once in _build_ui() (item 22's "held
        # reference" concern that used to apply to a per-open
        # SettingsWindow no longer applies at all: this widget is never
        # constructed-and-discarded).
        if initial_tab is not None:
            self.settings_page.select_tab(initial_tab)

        self._show_page("settings")

    # --- Roadmap item R7: run in the background from the macOS menu bar ----

    def _build_tray_icon(self) -> None:
        # R7.2 — guarded on real availability; a platform/session with
        # no tray (this app's own offscreen test environment included —
        # confirmed live, not assumed: QSystemTrayIcon.
        # isSystemTrayAvailable() reports False under QT_QPA_PLATFORM=
        # offscreen) falls back to today's ordinary quit-on-close
        # behavior untouched — closeEvent below checks self._tray_icon
        # is not None before doing anything different.
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon = None
            return

        icon_path = _resolve_tray_icon_path()
        icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
        # macOS "template image" convention — a monochrome glyph whose
        # alpha channel Qt/AppKit recolor automatically for the current
        # menu bar appearance (light/dark), instead of showing a fixed-
        # color icon that can read wrong against either.
        #
        # Roadmap item 98 (B9) — setIsMask(True) against the full-colour
        # app `.icns` (the original approach here) produced a solid
        # filled squircle: setIsMask discards colour and stamps only the
        # ALPHA channel, and the app icon's alpha is one opaque rounded
        # square. `seeker_menubar_Template.png`/`...@2x.png` is a real,
        # derived-not-redrawn template asset instead — reproducible if
        # the app icon ever changes: the 1024px `seeker_icon.icns`
        # artwork was thresholded on luminance (a flat background at
        # 13.6 vs. artwork consistently > 30 gave a clean split), the
        # faint background circle dropped, the result cropped to the
        # artwork's own bounding box, the two brow strokes dilated
        # slightly (thin strokes otherwise don't survive an 18px
        # downscale), and the whole thing re-emitted as solid black
        # pixels with the glyph carried entirely in the alpha channel —
        # exactly what a template image is. Checked at real menu-bar
        # size composited against both a light and a dark background
        # before adopting it.
        icon.setIsMask(True)

        self._tray_icon = QSystemTrayIcon(icon, self)
        self._tray_icon.setToolTip("Seeker")

        menu = QMenu()

        self._tray_status_action = menu.addAction("Idle")
        self._tray_status_action.setEnabled(False)
        menu.addSeparator()

        self._tray_pause_action = menu.addAction("Pause downloads")
        self._tray_pause_action.setCheckable(True)
        self._tray_pause_action.setChecked(self.application.downloads_paused)
        self._tray_pause_action.toggled.connect(self._on_tray_pause_toggled)

        self._tray_review_action = menu.addAction("Review")
        self._tray_review_action.triggered.connect(
            lambda: self._on_tray_open_page("review")
        )
        self._tray_upgrades_action = menu.addAction("Upgrades")
        self._tray_upgrades_action.triggered.connect(
            lambda: self._on_tray_open_page("review")
        )
        menu.addSeparator()

        # Roadmap item 98 (B9.5) — "Check now" was ambiguous with Help
        # menu's "Check for updates…" (a completely different action —
        # this one triggers an immediate slskd download/upload status
        # poll, not an app-update check). Renamed plainly, with a
        # tooltip, so the two "check"s can't be confused.
        check_now_action = menu.addAction("Check downloads now")
        check_now_action.setToolTip(
            "Refresh download/upload status immediately, instead of "
            "waiting for the next automatic check."
        )
        check_now_action.triggered.connect(self._on_tray_check_now)
        open_action = menu.addAction("Open Seeker")
        open_action.triggered.connect(self._on_tray_open_seeker)
        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._on_tray_quit)

        self._tray_icon.setContextMenu(menu)
        self._tray_icon.activated.connect(self._on_tray_icon_activated)
        self._tray_icon.show()

    def _on_tray_icon_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # macOS routes a left-click on a QSystemTrayIcon straight to its
        # context menu already (Trigger never fires there the way it
        # does on Windows/Linux) — this exists for those other
        # platforms, where a left-click should behave like "Open
        # Seeker" rather than doing nothing.
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._on_tray_open_seeker()

    def _on_tray_pause_toggled(self, checked: bool) -> None:
        self.application.set_downloads_paused(checked)
        self._render_tray_menu()

    def _on_tray_open_page(self, key: str) -> None:
        self._on_tray_open_seeker()
        self._show_page(key)

    def _on_tray_check_now(self) -> None:
        self._trigger_backend_poll()

    def _on_tray_open_seeker(self) -> None:
        self._hidden_to_tray = False
        self.showNormal()
        self.raise_()
        self.activateWindow()
        # Roadmap item R7.6 — the poll methods skip their own work
        # while hidden; catch up immediately on reopen rather than
        # waiting up to POLL_INTERVAL_MS for the next tick to notice
        # the window is visible again.
        self._poll_selected_playlist()
        self._poll_active_downloads()
        self._poll_review_items()
        self._poll_next_step()
        self._render_activity_strip()

    def _on_tray_quit(self) -> None:
        # Roadmap item R7.7 — a real quit request, same as ⌘Q/dock
        # "Quit Seeker". Goes straight to QApplication.quit() (posts a
        # real quit event) rather than self.close() — close() would
        # re-enter this window's own closeEvent, which hides to the
        # tray instead of quitting, exactly the behavior a Quit click
        # must bypass. The actual cleanup lives in
        # cleanup_before_quit(), connected once to QApplication.
        # aboutToQuit in main_ui.py, so it fires for every real quit
        # route uniformly, not just this one.
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def cleanup_before_quit(self) -> None:
        # Roadmap item R7.7 — the one real cleanup path for every quit
        # route (tray Quit, real ⌘Q/dock-quit — both reach here via
        # QApplication.aboutToQuit, connected once in main_ui.py).
        # Deliberately NOT an attempt at roadmap item 70's own open,
        # unresolved stress-test hang — this stops timers/hides the
        # tray icon so a real quit doesn't leave anything running past
        # the window closing, but does not change poll_downloads/
        # fingerprinting internals at all.
        self.poll_timer.stop()
        self.backend_poll_timer.stop()

        if self._tray_icon is not None:
            self._tray_icon.hide()

    def _render_tray_menu(self) -> None:
        if self._tray_icon is None:
            return

        parts = []
        if self._active_downloads_count > 0:
            plural = "s" if self._active_downloads_count != 1 else ""
            parts.append(f"{self._active_downloads_count} downloading{plural}")

        status_text = ", ".join(parts) if parts else "Idle"

        if self.application.downloads_paused:
            status_text += " (paused)"

        self._tray_status_action.setText(status_text)
        self._tray_review_action.setText(
            f"Review ({self._needs_review_count})"
            if self._needs_review_count else "Review"
        )
        self._tray_upgrades_action.setText(
            f"Upgrades ({self._pending_upgrades_count})"
            if self._pending_upgrades_count else "Upgrades"
        )

        # Mirrors the config store, not local UI state — a pause
        # toggled from elsewhere (a future Settings/Dashboard control)
        # must still show correctly here without this menu having
        # caused it. blockSignals so re-syncing the checked state
        # can't itself re-trigger _on_tray_pause_toggled's own save.
        self._tray_pause_action.blockSignals(True)
        self._tray_pause_action.setChecked(self.application.downloads_paused)
        self._tray_pause_action.blockSignals(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        # Roadmap item R7.1/R7.2 — hides to the menu bar instead of
        # quitting, but ONLY when there's a real tray icon to hide to;
        # with none available (or not actually shown), this falls
        # through to Qt's ordinary close behavior unchanged — the
        # explicit fallback the brief itself asks for.
        if self._tray_icon is None or not self._tray_icon.isVisible():
            super().closeEvent(event)
            return

        event.ignore()
        self.hide()
        self._hidden_to_tray = True

        if not self.application._config_store.tray_hide_notice_shown:
            self._tray_icon.showMessage(
                "Seeker",
                "Seeker is still running in the menu bar. Use the menu "
                "bar icon to reopen it, or Quit from there to exit.",
                QSystemTrayIcon.MessageIcon.Information,
            )
            self.application.mark_tray_hide_notice_shown()

    def _seed_notification_cutoff(self) -> None:
        # Roadmap item R7.5 — silently records the newest existing
        # HistoryEvent so pre-existing download history never floods a
        # notification the instant the tray icon appears; only a
        # DOWNLOADED event with a NEWER occurred_at than this counts as
        # "new" from here on (get_recent_events sorts newest-first).
        run_worker(
            self.thread_pool,
            lambda: self.application.history_service.get_recent_events(limit=1),
            on_finished=self._on_notification_cutoff_seeded,
        )

    def _on_notification_cutoff_seeded(self, events: list[HistoryEvent]) -> None:
        if events:
            self._last_notified_download_at = events[0].occurred_at

    def _check_for_download_notifications(self) -> None:
        # Roadmap item R7.5 — batched per playlist, built from
        # HistoryService's own existing derived DOWNLOADED events (item
        # 54), not a new source of truth; runs on the real 20s backend-
        # poll cycle (the only cycle that can actually produce a newly-
        # completed download), never its own timer.
        if self._tray_icon is None:
            return

        if not self.application._config_store.notify_downloads_finished:
            return

        if self._last_notified_download_at is None:
            # Seeding hasn't completed yet (or found nothing) — skip
            # this cycle rather than risk treating all of history as
            # "new" the moment it does land.
            return

        run_worker(
            self.thread_pool,
            lambda: self.application.history_service.get_recent_events(limit=50),
            on_finished=self._on_download_notification_events,
        )

    def _on_download_notification_events(self, events: list[HistoryEvent]) -> None:
        cutoff = self._last_notified_download_at
        assert cutoff is not None

        new_events = [
            event for event in events
            if event.occurred_at > cutoff and event.event_type == DOWNLOADED
        ]

        if new_events and self._tray_icon is not None:
            counts_by_playlist: dict[str, int] = {}
            for event in new_events:
                counts_by_playlist[event.playlist_name] = (
                    counts_by_playlist.get(event.playlist_name, 0) + 1
                )

            message = "\n".join(
                f"{playlist}: {count} track{'s' if count != 1 else ''} "
                f"downloaded"
                for playlist, count in counts_by_playlist.items()
            )
            self._tray_icon.showMessage(
                "Seeker", message, QSystemTrayIcon.MessageIcon.Information,
            )

        if events:
            self._last_notified_download_at = events[0].occurred_at

    def _check_for_needs_decision_notification(self, total: int) -> None:
        # Roadmap item R7.5 — fires only on a genuine INCREASE from the
        # last-seen total, never on every poll tick the count happens
        # to still be positive (that would notify every 2s for as long
        # as anything sits unreviewed).
        if (
                self._tray_icon is not None
                and self.application._config_store.notify_needs_decision
                and total > self._last_notified_review_count
        ):
            plural = "s" if total != 1 else ""
            self._tray_icon.showMessage(
                "Seeker",
                f"{total} item{plural} need your decision on the Review "
                f"page.",
                QSystemTrayIcon.MessageIcon.Information,
            )

        self._last_notified_review_count = total

    def _notify_error(self, message: str) -> None:
        # Roadmap item R7.5 — rate-limited so an unreachable slskd
        # can't emit a notification every single 20s backend-poll tick.
        if self._tray_icon is None:
            return

        if not self.application._config_store.notify_errors:
            return

        now = time.monotonic()

        if (
                self._last_error_notification_at is not None
                and now - self._last_error_notification_at
                < ERROR_NOTIFICATION_COOLDOWN_SECONDS
        ):
            return

        self._last_error_notification_at = now
        self._tray_icon.showMessage(
            "Seeker", message, QSystemTrayIcon.MessageIcon.Warning,
        )
