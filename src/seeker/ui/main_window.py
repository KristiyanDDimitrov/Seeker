import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.application import Application
from seeker.library.duplicate_service import DuplicateGroup
from seeker.models.active_download import ActiveDownload
from seeker.models.history_event import DOWNLOADED, TAGGED, HistoryEvent
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track
from seeker.models.track_status import (
    AWAITING_REVIEW,
    DOWNLOADING,
    IN_LIBRARY,
    NEEDS_REVIEW,
    NOT_FOUND,
    TrackStatus,
)
from seeker.models.upgrade_review import UpgradeReviewDetails
from seeker.ui import help_text, theme
from seeker.update_check import UpdateCheckResult, UpdateStatus, check_for_update
from seeker.ui.download_eta import (
    AGGREGATE_ETA_TOOLTIP,
    DownloadEtaTracker,
    format_aggregate_header,
)
from seeker.ui.formatting import format_timestamp
from seeker.ui.notice import InlineNotice
from seeker.ui.settings_window import (
    SETTINGS_TAB_CONNECTION,
    SETTINGS_TAB_LOCATIONS,
    SettingsWindow,
)
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

_STATE_LABELS = {
    IN_LIBRARY: "In library",
    DOWNLOADING: "Downloading",
    AWAITING_REVIEW: "Awaiting review",
    NEEDS_REVIEW: "Needs review",
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
}

# Statuses where a progress bar means anything at all — a locked/
# shortlisted/failed row has no real, current transfer to show progress
# for (see CLAUDE.md: a rejection leaves bytes_transferred/total_bytes
# unset by design, not zeroed).
_PROGRESS_ELIGIBLE_STATUSES = {"queued", "downloading", "ready_for_review", "completed"}

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
    ("downloads", "Downloads"),
    ("review", "Review"),
    ("duplicates", "Duplicates"),
    ("history", "History"),
)


def _build_subtitle_label(text: str) -> QLabel:
    # Persistent, not hover-dependent (Task 1) — a muted one-liner under
    # each tab's own header, aimed at someone who never reads the
    # README and goes straight into the app.
    label = QLabel(text)
    label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
    label.setWordWrap(True)
    return label


def _build_page(title: str, subtitle: str, content: QWidget) -> QWidget:
    # Every page in the shell gets the identical [title, subtitle,
    # content] shape and the identical page-level margins (Phase 3's
    # own documented layout convention) — this is the one place that
    # convention actually gets enforced, rather than each page copying
    # setContentsMargins/setSpacing by hand and drifting.
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(
        theme.SPACING_XL, theme.SPACING_LG,
        theme.SPACING_XL, theme.SPACING_LG,
    )
    layout.setSpacing(theme.SPACING_MD)

    title_label = QLabel(title)
    title_label.setStyleSheet(
        f"font-size: 18px; font-weight: 600; color: {theme.TEXT};"
    )
    layout.addWidget(title_label)
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

    missing_count = sum(
        1 for status in facts.track_statuses if status.state == NOT_FOUND
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


def _build_progress_widget(
        download: ActiveDownload,
        eta_text: str | None,
) -> QWidget:
    request = download.request

    if request.status not in _PROGRESS_ELIGIBLE_STATUSES:
        return QWidget()

    bar = QProgressBar()

    if not (request.total_bytes and request.bytes_transferred is not None):
        # No bytes reported yet — indeterminate ("busy") rather than a
        # 0%-forever bar that looks identical to actually being stuck.
        # No ETA either (Task 2): there's nothing determinate to
        # estimate against.
        bar.setRange(0, 0)
        return bar

    bar.setRange(0, request.total_bytes)
    bar.setValue(request.bytes_transferred)
    theme.style_determinate_progress_bar(bar)

    # ETA only ever shown once the bar is determinate, per Task 2's own
    # scoping — the indeterminate branch above is left exactly as it
    # was before this feature.
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(bar, 1)
    layout.addWidget(QLabel(eta_text or "Calculating…"))

    return container


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
        # uses; no SDK, no embedded payment UI.
        support_row = QHBoxLayout()
        for name, url in help_text.SUPPORT_LINKS.items():
            if not help_text.is_real_support_link(url):
                continue

            support_button = QPushButton(f"Support on {name}")
            support_button.setToolTip(help_text.TOOLTIP_SUPPORT_LINK)
            support_button.clicked.connect(
                lambda _=False, url=url: webbrowser.open(url)
            )
            support_row.addWidget(support_button)
        layout.addLayout(support_row)

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
    """

    def __init__(
            self,
            parent: QWidget,
            playlist_name: str,
            locations: list[LibraryLocation],
            default_location_id: int | None,
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

        self.subfolder_field = QLineEdit(playlist_name)
        form.addRow("Subfolder:", self.subfolder_field)

        layout.addLayout(form)

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

    def selected_location_id(self) -> int | None:
        data = self.location_combo.currentData()
        return int(data) if data is not None else None

    def selected_subfolder(self) -> str | None:
        text = self.subfolder_field.text().strip()
        return text or None

    def remember_for_playlist(self) -> bool:
        return self.remember_checkbox.isChecked()


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

        self.setWindowTitle("Seeker")
        self.resize(1180, 760)
        self.setMinimumSize(960, 640)

        self._build_ui()
        self._render_no_playlist_selected()
        self._load_playlists()
        self._poll_active_downloads()
        self._poll_review_items()
        self._poll_next_step()

        # DB-polling pattern for live status: rebuild the visible model
        # each tick rather than diffing for minimal repaints — an
        # acceptable v1 simplification, matching this project's habit
        # of shipping a working real version before optimizing. Applies
        # to the Review tab too: a checkbox toggled mid-interval can get
        # reset by the next tick's rebuild, same accepted tradeoff as
        # everywhere else this pattern is used.
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_INTERVAL_MS)
        self.poll_timer.timeout.connect(self._poll_selected_playlist)
        self.poll_timer.timeout.connect(self._poll_active_downloads)
        self.poll_timer.timeout.connect(self._poll_review_items)
        self.poll_timer.timeout.connect(self._poll_next_step)
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
        self.backend_poll_timer.start()

    def _build_ui(self) -> None:
        self._build_help_menu()

        shell = QWidget()
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        shell_layout.addWidget(self._build_sidebar())

        self.stacked_widget = QStackedWidget()
        shell_layout.addWidget(self.stacked_widget, 1)

        self._page_indices: dict[str, int] = {}
        self._register_page("dashboard", self._build_dashboard_page())
        self._register_page("downloads", self._build_downloads_page())
        self._register_page("review", _build_page(
            "Review", help_text.REVIEW_TAB_SUBTITLE,
            self._build_review_content(),
        ))
        self._register_page("duplicates", _build_page(
            "Duplicates", help_text.DUPLICATES_TAB_SUBTITLE,
            self._build_duplicates_content(),
        ))
        self._register_page("history", self._build_history_page())
        self._register_page("help", self._build_help_page())

        # Locations load lazily, the first time this page is actually
        # shown, rather than eagerly in _build_ui() — every MainWindow
        # construction runs _build_ui() once, and an eager worker here
        # was confirmed live to compound into a real, reproducible
        # deadlock (Qt's internal connection-list mutex vs. the GIL)
        # under the rapid, repeated MainWindow construction this
        # project's own test suite does — see CLAUDE.md/docs/HISTORY.md.
        # A real user only reaches this page by clicking it, which is
        # comparatively rare and human-paced, so this never fires in a
        # tight loop the way construction does.
        self._duplicates_page_index = self._page_indices["duplicates"]
        self._duplicates_locations_loaded = False
        # Same lazy-load-on-first-real-visit reasoning as Duplicates
        # above — a plain, cheap local-DB read, but there's no reason
        # to pay it on every MainWindow construction when a real user
        # may never open this page in a given session.
        self._history_page_index = self._page_indices["history"]
        self._history_loaded = False
        self.stacked_widget.currentChanged.connect(self._on_page_changed)

        self.setCentralWidget(shell)
        self._show_page("dashboard")

    def _register_page(self, key: str, widget: QWidget) -> None:
        self._page_indices[key] = self.stacked_widget.addWidget(widget)

    def _show_page(self, key: str) -> None:
        self.stacked_widget.setCurrentIndex(self._page_indices[key])

        button = self._nav_buttons.get(key)
        if button is not None:
            button.setChecked(True)

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

        wordmark = QLabel("Seeker")
        wordmark.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {theme.TEXT}; "
            f"padding-bottom: {theme.SPACING_MD}px;"
        )
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

        # Settings deliberately stays a plain (non-checkable, non-nav-
        # group) button that opens the existing SettingsWindow dialog —
        # it was never one of the "tab bodies" this shell restructure
        # turns into pages (see the task's own scoping), just relocated
        # here from the toolbar.
        self.settings_button = QPushButton("Settings")
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

        self.scan_button = QPushButton("Rescan library folders")
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
        layout.addWidget(self.playlist_list, 1)

        right = QVBoxLayout()

        self.track_table = QTableWidget(0, 4)
        self.track_table.setHorizontalHeaderLabels(
            ["Track", "Status", "Progress", "Actions"]
        )
        self.track_table.horizontalHeader().setStretchLastSection(True)
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
        self.track_area_stack = QStackedWidget()
        self.track_area_stack.addWidget(self.track_table)
        self._track_empty_panel = self._build_track_empty_panel()
        self.track_area_stack.addWidget(self._track_empty_panel)
        right.addWidget(self.track_area_stack)

        right.addLayout(self._build_tagging_controls())

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
        layout.addWidget(self.downloads_table)

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
        layout.addWidget(self.history_table)

        # Raw, unfiltered events from the last real fetch — the filter
        # combo re-renders from this in memory rather than re-querying,
        # since it's already a bounded, already-fetched list (DEFAULT_
        # LIMIT), not a live/paginated one.
        self._history_events: list[HistoryEvent] = []

        return _build_page(
            "History", help_text.HISTORY_PAGE_SUBTITLE, content,
        )

    def _refresh_history(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.history_service.get_recent_events,
            button=self.history_refresh_button,
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

    def _build_tagging_controls(self) -> QHBoxLayout:
        # Shared by all three triggers (per-track, "Tag selected",
        # "Tag playlist") — one set of options, not three independently
        # configurable copies. --bpm-range requiring --analyze-audio
        # (the CLI's own validation) is enforced structurally here by
        # hiding the range fields entirely while the checkbox is
        # unchecked, rather than validating the combination after the
        # fact the way the CLI has to.
        controls = QHBoxLayout()

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
            f"Tagged: {result['tagged']}, "
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

        container = QWidget()
        actions_layout = QHBoxLayout(container)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        track_id = status.track.id

        if status.tagged_at is None:
            tag_button = QPushButton("Tag")
            tag_button.setToolTip(help_text.TOOLTIP_TAG_TRACK_ROW)
            tag_button.clicked.connect(
                lambda: self._on_tag_track_clicked(track_id, tag_button)
            )
            actions_layout.addWidget(tag_button)
        else:
            tagged_label = QLabel("Tagged")
            tagged_label.setProperty("badge", "muted")
            tagged_label.setToolTip(
                f"Tagged {format_timestamp(status.tagged_at)}"
            )
            actions_layout.addWidget(tagged_label)

        return container

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

        run_worker(
            self.thread_pool,
            lambda: self.application.metadata_service.tag_tracks(
                track_ids,
                analyze_audio=analyze_audio,
                expected_bpm_range=bpm_range,
                force=force,
            ),
            button=self.tag_selected_button,
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

        run_worker(
            self.thread_pool,
            lambda: self.application.metadata_service.tag_playlist(
                playlist_name,
                analyze_audio=analyze_audio,
                expected_bpm_range=bpm_range,
                force=force,
            ),
            button=self.tag_playlist_button,
            status_label=self.status_label,
            on_finished=self._render_tag_result,
        )
        self.status_label.setText(f"Tagging playlist '{playlist_name}'...")

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
        self.review_needs_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.review_needs_table)

        layout.addWidget(QLabel("Downloaded upgrades ready for review"))

        self.review_upgrades_table = QTableWidget(0, 4)
        self.review_upgrades_table.setHorizontalHeaderLabels(
            ["Track", "Current", "New quality", "Actions"]
        )
        self.review_upgrades_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.review_upgrades_table)

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

        controls = QHBoxLayout()

        self.duplicates_location_combo = QComboBox()
        self.duplicates_location_combo.setToolTip(
            help_text.TOOLTIP_DUPLICATES_LOCATION_COMBO
        )
        controls.addWidget(self.duplicates_location_combo)

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

        self.duplicates_status_label = QLabel("")
        layout.addWidget(self.duplicates_status_label)

        self.duplicates_table = QTableWidget(0, 7)
        self.duplicates_table.setHorizontalHeaderLabels(
            [
                "Group", "File", "Format", "Bitrate", "Similarity",
                "Keep", "Actions",
            ]
        )
        self.duplicates_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.duplicates_table)

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

        return tab

    def _on_page_changed(self, index: int) -> None:
        if (
                index == self._duplicates_page_index
                and not self._duplicates_locations_loaded
        ):
            self._duplicates_locations_loaded = True
            self._refresh_duplicates_locations()

        if index == self._history_page_index and not self._history_loaded:
            self._history_loaded = True
            self._refresh_history()

    def _refresh_duplicates_locations(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.library_service.list_locations,
            on_finished=self._render_duplicates_locations,
        )

    def _render_duplicates_locations(
            self,
            locations: list[tuple[Any, bool]],
    ) -> None:
        self.duplicates_location_combo.clear()

        for location, _ in locations:
            self.duplicates_location_combo.addItem(
                location.name, location.name
            )

    def _selected_duplicates_location(self) -> str | None:
        name = self.duplicates_location_combo.currentData()
        return str(name) if name is not None else None

    def _on_compute_fingerprints_clicked(self) -> None:
        location_name = self._selected_duplicates_location()

        if location_name is None:
            self.duplicates_status_label.setText(
                "Select a library location first."
            )
            return

        run_worker(
            self.thread_pool,
            lambda: self.application.duplicate_service.compute_fingerprints(
                location_name
            ),
            button=self.compute_fingerprints_button,
            status_label=self.duplicates_status_label,
            on_finished=self._render_fingerprint_result,
        )
        self.duplicates_status_label.setText(
            f"Computing fingerprints for '{location_name}'..."
        )

    def _render_fingerprint_result(self, result: dict[str, Any]) -> None:
        self.duplicates_status_label.setText(
            f"Fingerprinted: {result['computed']}, "
            f"Skipped (already computed): "
            f"{result['skipped_already_computed']}, "
            f"Failed: {result['failed']}."
        )

    def _on_find_duplicates_clicked(self) -> None:
        location_name = self._selected_duplicates_location()

        if location_name is None:
            self.duplicates_status_label.setText(
                "Select a library location first."
            )
            return

        run_worker(
            self.thread_pool,
            lambda: self.application.duplicate_service.find_duplicate_groups(
                location_name
            ),
            button=self.find_duplicates_button,
            status_label=self.duplicates_status_label,
            on_finished=self._render_duplicate_groups,
        )
        self.duplicates_status_label.setText(
            f"Searching for duplicates in '{location_name}'..."
        )

    def _render_duplicate_groups(self, groups: list[DuplicateGroup]) -> None:
        self._duplicate_button_groups = []
        # Kept so a single-group resolution can drop just that group and
        # re-render locally afterward — see _on_delete_duplicates_finished's
        # own docstring for why re-fetching via find_duplicate_groups()
        # after every resolution is not an option at real scale.
        self._current_duplicate_groups = groups

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

            for file_index, duplicate_file in enumerate(group.files):
                local_file = duplicate_file.local_file
                quality = duplicate_file.quality
                assert local_file.id is not None

                self.duplicates_table.setItem(
                    row, 0, QTableWidgetItem(str(group_index)),
                )
                self.duplicates_table.setItem(
                    row, 1, QTableWidgetItem(local_file.relative_path),
                )
                self.duplicates_table.setItem(
                    row, 2, QTableWidgetItem(local_file.format),
                )
                bitrate_text = (
                    f"{quality.bitrate_kbps} kbps"
                    if quality.bitrate_kbps
                    else "—"
                )
                self.duplicates_table.setItem(
                    row, 3, QTableWidgetItem(bitrate_text),
                )
                self.duplicates_table.setItem(
                    row, 4, QTableWidgetItem(f"{group.similarity:.1%}"),
                )

                keep_radio = QRadioButton()
                keep_radio.setToolTip(help_text.TOOLTIP_KEEP_FILE_RADIO)
                keep_radio.setChecked(file_index == 0)
                # The button's own id IS the local_file_id -- checkedId()
                # below reads it back directly, no separate id-to-file
                # mapping needed.
                button_group.addButton(keep_radio, id=local_file.id)
                self.duplicates_table.setCellWidget(row, 5, keep_radio)

                row += 1

            self.duplicates_table.setCellWidget(
                group_first_row,
                6,
                self._build_duplicate_group_actions(group, button_group),
            )

            for other_row in range(group_first_row + 1, row):
                # Blank cell, not a misleading control -- same "the
                # action lives once per group, not once per row"
                # precedent as item 27's per-track Tag button only
                # rendering for IN_LIBRARY rows.
                self.duplicates_table.setCellWidget(other_row, 6, QWidget())

            self.duplicates_table.setSpan(
                group_first_row, 6, len(group.files), 1,
            )

    def _build_duplicate_group_actions(
            self,
            group: DuplicateGroup,
            button_group: QButtonGroup,
    ) -> QWidget:
        container = QWidget()
        actions_layout = QHBoxLayout(container)
        actions_layout.setContentsMargins(0, 0, 0, 0)

        confirm_checkbox = QCheckBox("Confirm delete")
        confirm_checkbox.setToolTip(
            help_text.TOOLTIP_DELETE_DUPLICATES_CHECKBOX
        )
        actions_layout.addWidget(confirm_checkbox)

        delete_button = QPushButton("Delete")
        delete_button.setToolTip(help_text.TOOLTIP_DELETE_DUPLICATES_BUTTON)
        delete_button.clicked.connect(
            lambda: self._on_delete_duplicates_clicked(
                group, button_group, confirm_checkbox, delete_button,
            )
        )
        actions_layout.addWidget(delete_button)

        return container

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
        delete_ids = [
            duplicate_file.local_file.id
            for duplicate_file in group.files
            if duplicate_file.local_file.id is not None
            and duplicate_file.local_file.id != keep_id
        ]

        run_worker(
            self.thread_pool,
            lambda: self.application.duplicate_service.delete_local_files(
                delete_ids, keep_id,
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

        self.track_area_stack.setCurrentWidget(self.track_table)

        self.track_table.setRowCount(len(statuses))

        for row, status in enumerate(statuses):
            label = f"{status.track.artist} - {status.track.title}"
            self.track_table.setItem(row, 0, QTableWidgetItem(label))

            state_text = _STATE_LABELS[status.state]
            if status.soulseek_candidate is not None:
                state_text += " (SoulSeek candidate found)"
            self.track_table.setItem(row, 1, QTableWidgetItem(state_text))

            if (
                    status.state == DOWNLOADING
                    and status.total_bytes
                    and status.bytes_transferred is not None
            ):
                progress = QProgressBar()
                progress.setMaximum(status.total_bytes)
                progress.setValue(status.bytes_transferred)
                theme.style_determinate_progress_bar(progress)
                self.track_table.setCellWidget(row, 2, progress)
            else:
                self.track_table.setCellWidget(row, 2, QWidget())

            self.track_table.setCellWidget(
                row, 3, self._build_track_actions(status),
            )

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
        run_worker(
            self.thread_pool,
            self._fetch_next_step_facts,
            on_finished=self._render_next_step,
        )

    def _render_next_step(self, facts: _NextStepFacts) -> None:
        step = _decide_next_step(facts)

        if step is None:
            self.next_step_notice.dismiss()
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
        self.sync_button.setEnabled(facts.spotify_configured)
        self.scan_button.setEnabled(facts.has_library_location)
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
            eta_text = (
                self._eta_tracker.describe(request.id, request.total_bytes)
                if request.id is not None and request.total_bytes
                else None
            )
            self.downloads_table.setCellWidget(
                row, 4, _build_progress_widget(download, eta_text),
            )

    def _render_aggregate_eta(self, downloads: list[ActiveDownload]) -> None:
        # No reserved-but-blank strip when there's nothing active — the
        # empty string collapses the label to zero height, matching
        # this project's "blank, not a misleading control" precedent
        # (item 27) rather than showing "0 transferring" forever.
        if not downloads:
            self.downloads_eta_label.setText("")
            self.downloads_eta_label.setToolTip("")
            return

        pairs = [
            (download.request.id, download.request.total_bytes)
            for download in downloads
            if download.request.id is not None
        ]
        result = self._eta_tracker.aggregate(pairs)
        self.downloads_eta_label.setText(format_aggregate_header(result))
        self.downloads_eta_label.setToolTip(AGGREGATE_ETA_TOOLTIP)

    def _poll_review_items(self) -> None:
        # Both halves are cheap, local-DB-only reads (like
        # get_active_downloads above) — no real slskd network calls, so
        # this belongs on the 2s display-refresh timer, not the 20s
        # backend-poll one. Bundled into one worker call rather than two
        # so both tables update from the same consistent DB snapshot.
        def fetch() -> tuple[NeedsReviewCandidates, PendingUpgrades]:
            service = self.application.download_service
            return (service.get_review_candidates(), service.get_pending_upgrade_reviews())

        run_worker(
            self.thread_pool,
            fetch,
            on_finished=self._render_review_items,
        )

    def _render_review_items(
            self,
            data: tuple[NeedsReviewCandidates, PendingUpgrades],
    ) -> None:
        candidates, upgrades = data
        self._update_nav_badge("review", len(candidates) + len(upgrades))
        self._render_needs_review_candidates(candidates)
        self._render_pending_upgrades(upgrades)

    def _render_needs_review_candidates(
            self,
            candidates: NeedsReviewCandidates,
    ) -> None:
        self.review_needs_table.setRowCount(len(candidates))

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

            self.review_needs_table.setCellWidget(
                row, 3, self._build_needs_review_actions(track.id),
            )

    def _build_needs_review_actions(self, track_id: str) -> QWidget:
        container = QWidget()
        actions_layout = QHBoxLayout(container)
        actions_layout.setContentsMargins(0, 0, 0, 0)

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

        actions_layout.addWidget(confirm_button)
        actions_layout.addWidget(reject_button)

        return container

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
        self.review_upgrades_table.setRowCount(len(upgrades))

        for row, details in enumerate(upgrades):
            label = f"{details.track.artist} - {details.track.title}"
            self.review_upgrades_table.setItem(row, 0, QTableWidgetItem(label))
            self.review_upgrades_table.setItem(
                row, 1, QTableWidgetItem(details.current_description),
            )
            self.review_upgrades_table.setItem(
                row, 2, QTableWidgetItem(details.quality_descriptor or "—"),
            )
            self.review_upgrades_table.setCellWidget(
                row, 3, self._build_upgrade_actions(details),
            )

    def _build_upgrade_actions(self, details: UpgradeReviewDetails) -> QWidget:
        container = QWidget()
        actions_layout = QHBoxLayout(container)
        actions_layout.setContentsMargins(0, 0, 0, 0)

        replace_button = QPushButton("Replace")
        replace_button.setToolTip(help_text.TOOLTIP_REPLACE_UPGRADE)
        decline_button = QPushButton("Decline")
        decline_button.setToolTip(help_text.TOOLTIP_DECLINE_UPGRADE)

        # The "delete old file?" control only ever appears when there's
        # a real old file to delete — mirrors the CLI's own guard around
        # its second input() prompt (get_upgrade_review_details leaves
        # old_file_path unset when there's nothing to replace).
        delete_checkbox: QCheckBox | None = None
        if details.old_file_path is not None:
            delete_checkbox = QCheckBox("Delete old file")
            delete_checkbox.setToolTip(
                help_text.TOOLTIP_DELETE_OLD_FILE_CHECKBOX
            )
            actions_layout.addWidget(delete_checkbox)

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

        actions_layout.addWidget(replace_button)
        actions_layout.addWidget(decline_button)

        return container

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

        def on_poll_error(_: str) -> None:
            self._backend_poll_in_progress = False

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

    def _on_sync_clicked(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.sync_service.sync_playlists,
            button=self.sync_button,
            status_label=self.status_label,
            on_finished=lambda _: self._load_playlists(),
        )

    def _on_scan_clicked(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.library_service.scan_all,
            button=self.scan_button,
            status_label=self.status_label,
        )

    def _on_match_clicked(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.track_matcher.match_all,
            button=self.match_button,
            status_label=self.status_label,
            on_finished=lambda _: self._poll_selected_playlist(),
        )

    def _on_download_clicked(self) -> None:
        if self.selected_playlist is None:
            self.dashboard_notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        playlist_name = self.selected_playlist.name

        # Roadmap item 6 §3 — check resolvability first rather than
        # letting download_playlist() raise and dead-end the user at
        # an error. Shares DownloadService._resolve_destination with
        # the real move step (via get_resolved_destination), so this
        # can never drift into a second, different notion of
        # "resolvable."
        run_worker(
            self.thread_pool,
            lambda: self.application.download_service
            .get_resolved_destination(playlist_name),
            button=self.download_button,
            on_finished=lambda resolved: self._on_destination_checked(
                playlist_name, resolved,
            ),
        )

    def _on_destination_checked(
            self,
            playlist_name: str,
            resolved: tuple[LibraryLocation, str | None] | None,
    ) -> None:
        if resolved is not None:
            self._start_download(playlist_name)
            return

        run_worker(
            self.thread_pool,
            self.application.library_service.list_locations,
            on_finished=lambda locations: self._open_destination_dialog(
                playlist_name, locations,
            ),
        )

    def _open_destination_dialog(
            self,
            playlist_name: str,
            locations: list[tuple[LibraryLocation, bool]],
    ) -> None:
        if not locations:
            self.dashboard_notice.show_message(
                help_text.NO_LOCATIONS_FOR_DESTINATION_DIALOG,
                kind="warning",
            )
            return

        location_objects = [location for location, _ in locations]
        default_location_id = (
            self.application._config_store.default_download_location_id
        )

        dialog = DestinationDialog(
            self, playlist_name, location_objects, default_location_id,
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        location_id = dialog.selected_location_id()

        if location_id is None:
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

        run_worker(
            self.thread_pool,
            do_persist,
            on_finished=lambda _: self._start_download(playlist_name),
        )

    def _start_download(self, playlist_name: str) -> None:
        run_worker(
            self.thread_pool,
            lambda: self.application.download_service.download_playlist(
                playlist_name
            ),
            button=self.download_button,
            status_label=self.status_label,
            on_finished=lambda _: self._poll_selected_playlist(),
        )

    def _on_sync_tracks_clicked(self) -> None:
        if self.selected_playlist is None:
            return

        playlist = self.selected_playlist

        def do_sync() -> Any:
            self.application.sync_service.sync_playlist_tracks(playlist)

        run_worker(
            self.thread_pool,
            do_sync,
            button=self.sync_tracks_button,
            status_label=self.status_label,
            on_finished=lambda _: self._poll_selected_playlist(),
        )

    def _on_settings_clicked(self, initial_tab: str | None = None) -> None:
        # A held reference is required — a local-only QMainWindow with
        # nothing else pointing at it gets garbage-collected as soon as
        # this method returns (same class of bug item 22's
        # ui/workers.py _callbacks registry exists to prevent for
        # in-flight background tasks, applied here to a window
        # instead).
        self.settings_window = SettingsWindow(
            self.application, initial_tab=initial_tab,
        )
        self.settings_window.show()
