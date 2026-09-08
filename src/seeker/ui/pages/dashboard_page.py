"""The Dashboard page — round 8 Phase 6 (§9.3.1), moved verbatim out of
main_window.py. The biggest single page moved so far (22 methods per
§9.1's table): playlist list, track table, next-step CTA, plus the
Tagging panel it hosts as a sub-widget (unchanged by this move — see
tagging_panel.py's own docstring).

Beyond PageContext, this page needs a second, narrower seam —
`DashboardHost` — for the handful of actions that live on MainWindow
because they're shared across several not-yet-migrated pages (Sync/
Scan/Match/Download/Settings-navigation) or because they need a second
argument PageContext.navigate's `Callable[[str], None]` shape can't
carry (jumping to Review with a specific track focused). Same "grep
every method being moved for what it actually touches before assuming a
clean lift" approach as TaggingPanelHost.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.models.playlist import Playlist
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
from seeker.ui import help_text, theme
from seeker.ui.formatting import format_timestamp
from seeker.ui.notice import InlineNotice
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.pages.tagging_panel import TaggingPanel, TaggingPanelHost
from seeker.ui.settings_window import SETTINGS_TAB_CONNECTION, SETTINGS_TAB_LOCATIONS
from seeker.ui.workers import run_worker

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

# Roadmap item 8.1 (round 8, Phase 5) — the declarative layout each
# table used to write out by hand across a `_configure_*_columns`/
# `_size_*_columns` pair; see `theme.ColumnLayout`.
_TRACK_COLUMNS = theme.ColumnLayout(
    stretch=(0,), fit_content=(1, 2), actions=3,
)


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


@dataclass(frozen=True)
class DashboardHost:
    """What the Dashboard needs from the shell beyond PageContext.
    Sync/Scan/Match/Download/"Load tracks" stay MainWindow methods —
    they're shared plumbing (§9.1's own grouping), not Dashboard-owned,
    so Dashboard reaches them the same read-through-a-seam way
    TaggingPanel reaches Dashboard's own state. `open_settings` and
    `navigate_to_review` both need a second argument PageContext's
    `navigate: Callable[[str], None]` can't carry (an initial tab, a
    track id to focus) — real MainWindow methods
    (`_on_settings_clicked`/`_show_page`) already have that extra
    parameter, this just binds to them directly instead of routing
    through the one-argument shell seam.
    """
    on_download_clicked: Callable[[], None]
    on_sync_clicked: Callable[[], None]
    on_scan_clicked: Callable[[], None]
    on_match_clicked: Callable[[], None]
    on_sync_tracks_clicked: Callable[[], None]
    open_settings: Callable[[str], None]
    navigate_to_review: Callable[[str], None]


class DashboardPage(QWidget):
    def __init__(self, context: PageContext, host: DashboardHost):
        super().__init__()
        self._context = context
        self._host = host

        self.selected_playlist: Playlist | None = None
        # Maps track_table row -> TrackStatus, rebuilt on every render —
        # needed to resolve a multi-selection back to real track ids for
        # "Tag selected" (Step 7).
        self._current_track_statuses: list[TrackStatus] = []
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
        self._configure_track_columns()
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

        # Roadmap item 9.3 (round 8, Phase 6) — created here, ahead of
        # its original position below `tagging_results`, purely
        # because TaggingPanel (constructed next) needs the real
        # QLabel instance up front, via TaggingPanelHost. Still added
        # to `right` in its original visual position — construction
        # order and layout order are independent in Qt.
        self.status_label = QLabel("")

        self._tagging_panel = TaggingPanel(
            context,
            TaggingPanelHost(
                status_label=self.status_label,
                dashboard_notice=self.dashboard_notice,
                get_selected_playlist=lambda: self.selected_playlist,
                get_selected_track_ids=self._selected_track_ids,
                refresh_track_table=self._poll_selected_playlist,
            ),
        )
        right.addWidget(self._tagging_panel)

        right.addWidget(self.status_label)

        layout.addLayout(right, 3)

        page = build_page(
            "Dashboard", help_text.DASHBOARD_TAB_SUBTITLE, content,
        )
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

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
        self.download_button.clicked.connect(self._host.on_download_clicked)
        row.addWidget(self.download_button)

        self.sync_button = QPushButton("Refresh playlists")
        self.sync_button.setToolTip(help_text.TOOLTIP_SYNC_ALL_PLAYLISTS)
        self.sync_button.clicked.connect(self._host.on_sync_clicked)
        row.addWidget(self.sync_button)

        # Roadmap item 79 (P12) — a bare "&" in QPushButton text is a
        # Qt keyboard-mnemonic marker, consumed and rendered as an
        # underline under the following character ("Rescan _match
        # library"), not a literal ampersand. "&Help" at this file's
        # menu-bar construction is a real, intentional mnemonic and is
        # the only place this should ever appear unescaped.
        self.scan_button = QPushButton("Rescan and match library")
        self.scan_button.setToolTip(help_text.TOOLTIP_SCAN_ALL_LOCATIONS)
        self.scan_button.clicked.connect(self._host.on_scan_clicked)
        row.addWidget(self.scan_button)

        self.match_button = QPushButton("Re-match library")
        self.match_button.setToolTip(help_text.TOOLTIP_MATCH_ALL_TRACKS)
        self.match_button.clicked.connect(self._host.on_match_clicked)
        row.addWidget(self.match_button)

        row.addStretch()
        return row

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
                lambda: self._tagging_panel._on_tag_track_clicked(
                    track_id, tag_button,
                )
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
            lambda: self._tagging_panel._on_retag_track_clicked(
                status.track.id
            )
        )
        menu.addAction(retag_action)
        menu.exec(self.track_table.viewport().mapToGlobal(position))

    # Roadmap item 9.3 (round 8, Phase 6) — temporary delegating
    # methods for TaggingPanel's own _render_tag_result/
    # _on_retag_track_clicked, called directly on a fresh MainWindow
    # instance by test_ui_smoke.py (via MainWindow's own further
    # delegation to this page).
    def _render_tag_result(self, result: dict[str, Any]) -> None:
        self._tagging_panel._render_tag_result(result)

    def _on_retag_track_clicked(self, track_id: str) -> None:
        self._tagging_panel._on_retag_track_clicked(track_id)

    def _load_playlists(self) -> None:
        run_worker(
            self._context.thread_pool,
            self._context.application.sync_service.list_playlists,
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
        # Roadmap item C5.3 — QLabel[badge="muted"] in theme.py.
        self.track_empty_label.setProperty("badge", "muted")
        layout.addWidget(self.track_empty_label)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.sync_tracks_button = QPushButton("Load tracks")
        self.sync_tracks_button.setToolTip(help_text.TOOLTIP_SYNC_TRACKS)
        self.sync_tracks_button.clicked.connect(
            self._host.on_sync_tracks_clicked
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
        if self._context.is_hidden_to_tray():
            return

        if self.selected_playlist is None:
            self._render_no_playlist_selected()
            return

        playlist_name = self.selected_playlist.name

        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.dashboard_service
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
            if status.state in (
                    NEEDS_REVIEW,
                    AWAITING_REVIEW,
                    REVIEW_CANDIDATE,
            ):
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
                # never touched. `theme.wrap_progress_bar` is the one
                # shared container both pages now go through (round 8
                # Phase 6 moved it out of main_window.py, alongside the
                # Downloads page itself, the moment a second caller
                # needed it); the Dashboard deliberately passes no label
                # (`None`) — no ETA is tracked per-track here, unlike
                # Downloads.
                self.track_table.setCellWidget(
                    row, 2, theme.wrap_progress_bar(progress, None),
                )
            else:
                self.track_table.setCellWidget(row, 2, QWidget())

            track_actions = self._build_track_actions(status)
            action_widgets.append(track_actions)
            self.track_table.setCellWidget(row, 3, track_actions)

        self._size_track_columns(action_widgets)

    def _configure_track_columns(self) -> None:
        theme.configure_columns(self.track_table, _TRACK_COLUMNS)

    def _size_track_columns(self, action_widgets: list[QWidget]) -> None:
        theme.size_columns(self.track_table, _TRACK_COLUMNS, action_widgets)

    def _on_track_table_cell_double_clicked(
            self, row: int, _column: int,
    ) -> None:
        if row < 0 or row >= len(self._current_track_statuses):
            return

        status = self._current_track_statuses[row]

        if status.state not in (
                NEEDS_REVIEW,
                AWAITING_REVIEW,
                REVIEW_CANDIDATE,
        ):
            # A genuine no-op — every other status has nothing to jump
            # to, so double-clicking those rows must not navigate at all.
            return

        self._host.navigate_to_review(status.track.id)

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
            self._context.application.dashboard_service
            .get_playlist_track_status(playlist_name)
            if playlist_name is not None
            else None
        )

        return _NextStepFacts(
            spotify_configured=self._context.application.spotify_configured,
            has_library_location=bool(
                self._context.application.library_service.list_locations()
            ),
            has_cached_playlists=bool(
                self._context.application.sync_service.list_playlists()
            ),
            selected_playlist_name=playlist_name,
            track_statuses=track_statuses,
            has_scanned_library=(
                self._context.application.library_service.has_scanned_library()
            ),
            soulseek_configured=self._context.application.soulseek_configured,
        )

    def _poll_next_step(self) -> None:
        # Roadmap item R7.6 — the Dashboard's own CTA banner has no
        # tray-menu relevance; skip entirely while hidden.
        if self._context.is_hidden_to_tray():
            return

        run_worker(
            self._context.thread_pool,
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
        if not self._context.busy_actions.is_running("download"):
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

        if not self._context.busy_actions.is_running("sync"):
            self.sync_button.setEnabled(facts.spotify_configured)

        if not self._context.busy_actions.is_running("scan"):
            self.scan_button.setEnabled(facts.has_library_location)

        if not self._context.busy_actions.is_running("match"):
            self.match_button.setEnabled(
                facts.has_cached_playlists and facts.has_library_location
            )

    def _on_next_step_action(self, action: str) -> None:
        if action == "settings_connection":
            self._host.open_settings(SETTINGS_TAB_CONNECTION)
        elif action == "settings_locations":
            self._host.open_settings(SETTINGS_TAB_LOCATIONS)
        elif action == "sync":
            self._host.on_sync_clicked()
        elif action == "sync_tracks":
            self._host.on_sync_tracks_clicked()
        elif action == "scan":
            self._host.on_scan_clicked()
        elif action == "download":
            self._host.on_download_clicked()
        elif action == "tag_playlist":
            self._tagging_panel._on_tag_playlist_clicked()
