"""The Dashboard page (HISTORY §119): playlist list, track table,
next-step CTA. Dashboard picks a playlist and shows its tracks, routing
the track table's own Tag/Re-tag row actions through `DashboardHost` to
the Library page (library_page.py), which owns the Tagging panel.

The page owns its own actions — Refresh playlists, Rescan and match,
Re-match, Download (with its destination prompt) and Load tracks — and
runs them through `PageContext.run_busy_worker`. Beyond PageContext it
needs a second, narrower seam, `DashboardHost`, only for what lands on
another page: Settings at a given tab, Review with a track focused, and
the Library page's TaggingPanel.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
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

from seeker.formatting import format_timestamp
from seeker.models.download_result import PlaylistDownloadResult
from seeker.models.library_location import LibraryLocation
from seeker.models.library_result import MatchResult, ScanAndMatchResult
from seeker.models.playlist import Playlist
from seeker.models.spotify_sync import PlaylistRefreshResult, TrackSyncResult
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
from seeker.ui.dialogs import DestinationDialog
from seeker.ui.elided_text import elide_list_items
from seeker.ui.notice import FeedbackTarget, InlineNotice
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.plain_text import PlainLabel, plain_tooltip
from seeker.ui.settings_window import SETTINGS_TAB_CONNECTION, SETTINGS_TAB_LOCATIONS
from seeker.ui.slskd_status import START_SLSKD_TEXT, start_slskd
from seeker.ui.table_sort import SortKeyItem, preserving_sort_order
from seeker.ui.widgets import TwoToneProgressBar
from seeker.ui.workers import run_worker

_STATE_LABELS = {
    IN_LIBRARY: "In library",
    DOWNLOADING: "Downloading",
    AWAITING_REVIEW: "Awaiting review",
    # The file is locked or queued behind a peer; Seeker is retrying in
    # the background. Not waiting on a human, unlike AWAITING_REVIEW
    # above (the split this label exists to make visible) (HISTORY §66).
    RETRYING: "Retrying (locked/queued)",
    NEEDS_REVIEW: "Needs review",
    # A real SoulSeek candidate was found but wasn't auto-tier enough
    # to request — actionable from the Review page, hence the same
    # double-click affordance NEEDS_REVIEW/AWAITING_REVIEW get.
    REVIEW_CANDIDATE: "Candidate to review",
    NOT_FOUND: "Not found",
}

# The track table's column layout; see `theme.ColumnLayout`
# (HISTORY §118).
_TRACK_COLUMNS = theme.ColumnLayout(
    stretch=(0,), fit_content=(1, 2), actions=3,
)


# The accent color baked into the rows, and the visible statuses.
_RenderedRows = tuple[str, tuple[TrackStatus, ...]]


def _has_progress_bar(status: TrackStatus) -> bool:
    return (
        status.state == DOWNLOADING
        and bool(status.total_bytes)
        and status.bytes_transferred is not None
    )


def _row_layout(status: TrackStatus) -> tuple[TrackStatus, bool]:
    """A row's status apart from the progress that updates in place,
    and whether it has a bar to update."""
    if status.state != DOWNLOADING:
        return status, False

    return (
        replace(status, bytes_transferred=None, total_bytes=None),
        _has_progress_bar(status),
    )


def _differ_only_in_progress(
        previous: _RenderedRows, current: _RenderedRows,
) -> bool:
    previous_accent, previous_rows = previous
    current_accent, current_rows = current

    return (
        previous_accent == current_accent
        and len(previous_rows) == len(current_rows)
        and all(
            _row_layout(old) == _row_layout(new)
            for old, new in zip(previous_rows, current_rows, strict=True)
        )
    )


@dataclass
class _NextStepFacts:
    """Every real fact the Dashboard "next step" CTA needs to decide
    what to show (HISTORY §7) — each field traces to one real service
    (or Application) method; nothing here is computed or guessed.
    Bundled into one dataclass purely so _fetch_next_step_facts() can
    gather them in a single background-thread call rather than one
    run_worker round trip per fact.
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
    # Loaded playlists whose cached tracks predate their Spotify
    # snapshot (Playlist.tracks_are_stale), in playlist-list order.
    stale_playlist_names: list[str] = field(default_factory=list)
    # SlskdStatus.unreachable_message: set while the backend poll can't
    # reach slskd.
    slskd_unreachable_message: str | None = None


@dataclass
class _NextStep:
    message: str
    kind: str
    action_text: str | None
    action: str | None


def _decide_next_step(facts: _NextStepFacts) -> _NextStep | None:
    """Pure presentation logic (HISTORY §7) — every fact it reads was
    already resolved by a real service call in _fetch_next_step_facts();
    this function only ever branches on values already computed
    elsewhere. Returns None when
    there's nothing to show at all (no playlist selected yet, with
    every global prerequisite already satisfied — the existing empty-
    state panel already covers "pick a playlist" there).
    """
    # First: while slskd is down, nothing below can finish downloading.
    if facts.slskd_unreachable_message is not None:
        return _NextStep(
            facts.slskd_unreachable_message,
            "warning", START_SLSKD_TEXT, "start_slskd",
        )

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
        if facts.stale_playlist_names:
            return _NextStep(
                help_text.format_stale_playlist_message(
                    facts.stale_playlist_names,
                ),
                "info", "Refresh playlists", "sync",
            )
        return None

    playlist_name = facts.selected_playlist_name

    if playlist_name in facts.stale_playlist_names:
        return _NextStep(
            help_text.format_stale_playlist_message([playlist_name]),
            "info", "Refresh tracks", "sync_tracks",
        )

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

    # Counts both NOT_FOUND and REVIEW_CANDIDATE: both have no active
    # download_requests row at all, so both are exactly what
    # download_playlist() would actually attempt something for on the
    # next click (a fresh request, or a needs-review candidate
    # surfacing/staying surfaced). RETRYING/AWAITING_REVIEW are
    # deliberately excluded — those already have an active row, which
    # get_requests_blocking_redownload() would just skip as
    # already-in-progress, so counting them here would overstate what
    # clicking Download actually does (HISTORY §66).
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
    """What the Dashboard needs from the shell beyond PageContext: the
    actions that land on another page.

    `open_settings` and `navigate_to_review` each carry a second
    argument (an initial tab, a track id to focus) that
    `PageContext.navigate` cannot. The three tag callables reach the
    Library page's TaggingPanel, and take this page's `FeedbackTarget`
    so the outcome of an action started here is shown here.
    """
    open_settings: Callable[[str], None]
    navigate_to_review: Callable[[str], None]
    tag_track: Callable[[str, QPushButton, FeedbackTarget], None]
    retag_track: Callable[[str, FeedbackTarget], None]
    tag_playlist: Callable[[FeedbackTarget], None]


class DashboardPage(QWidget):
    def __init__(self, context: PageContext, host: DashboardHost):
        super().__init__()
        self._context = context
        self._host = host

        # `selected_playlist` itself lives on the shared
        # `PlaylistSelection` seam (see the property below), not as a
        # plain attribute here, so Library can read the same single
        # source of truth instead of reaching into this page
        # (HISTORY §133).
        #
        # The full statuses list for the currently-selected playlist,
        # rebuilt on every render. Never used to resolve a table row
        # back to its TrackStatus (the table is sortable, so a row's
        # visual position need not match this list's order);
        # _track_status_by_id below is what every row-position handler
        # reads instead.
        self._current_track_statuses: list[TrackStatus] = []
        self._track_status_by_id: dict[str, TrackStatus] = {}
        # What the table's rows were last built from, so a poll tick
        # that changes nothing (or only progress) skips the rebuild.
        self._rendered_track_rows: _RenderedRows | None = None
        # Which segment of _build_track_filter_row is active; "all"
        # shows every status, matching the table's original unfiltered
        # behavior.
        self._track_filter: str = "all"
        # The "next step" notice is re-rendered unconditionally on
        # every 2s poll tick (see _render_next_step), so dismissing it
        # needs its own memory: the key of whatever step was on screen
        # when the user clicked X. Cleared the moment the computed key
        # changes, so a genuinely different step (or the same step
        # recurring later) still surfaces (HISTORY §71).
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

        # "Next step" guidance, one primary CTA at a time. Above
        # dashboard_notice (errors/warnings), so guidance and errors
        # never overwrite each other (HISTORY §7).
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
        elide_list_items(self.playlist_list)
        self.playlist_list.currentItemChanged.connect(
            self._on_playlist_selected
        )
        # A real floor, sized to fit a realistic long playlist name
        # rather than 0px: FlowLayout above removes the tagging row's
        # own floor, but without this the playlist panel could still be
        # squeezed to a sliver by a wide window dominated by other
        # content (HISTORY §72). PLAYLIST_NAME_WIDTH_SAMPLE is an
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
        # Double-clicking a NEEDS_REVIEW/AWAITING_REVIEW row jumps
        # straight to the Review page. Wired on cellDoubleClicked (not
        # itemDoubleClicked) since the target column can hold plain text
        # with no QTableWidgetItem guarantee beyond what
        # _render_track_statuses always sets (HISTORY §56).
        self.track_table.cellDoubleClicked.connect(
            self._on_track_table_cell_double_clicked
        )
        # Keeps the shared PlaylistSelection.track_ids live so
        # Library/TaggingPanel can read it directly instead of pulling
        # through a get_selected_track_ids() callable.
        self.track_table.itemSelectionChanged.connect(
            self._on_track_selection_changed
        )
        self._configure_track_columns()
        right.addLayout(self._build_track_filter_row())
        self.track_area_stack = QStackedWidget()
        # The CARD, not the bare table, is the stack's real page;
        # setCurrentWidget() calls below target this card.
        # self.track_table itself is untouched by this and still the
        # widget every other call site reads/writes rows on
        # (HISTORY §80).
        self.track_table_card = theme.make_card(self.track_table)
        self.track_area_stack.addWidget(self.track_table_card)
        self._track_empty_panel = self._build_track_empty_panel()
        self.track_area_stack.addWidget(self._track_empty_panel)
        right.addWidget(self.track_area_stack)

        self.status_label = PlainLabel("")
        right.addWidget(self.status_label)
        # Every Dashboard action reports through this: progress on the
        # label, outcome and error on the notice, out of the poll's reach.
        self.feedback = FeedbackTarget(self.status_label, self.dashboard_notice)

        layout.addLayout(right, 3)

        page = build_page(
            "Dashboard", help_text.DASHBOARD_TAB_SUBTITLE, content,
        )
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

        self._render_no_playlist_selected()

        # Library is a second writer of the shared selection (its own
        # inline picker). A write from elsewhere needs this subscription
        # or Dashboard's own playlist_list highlight and track table go
        # stale (HISTORY §134).
        self._context.playlist_selection.changed.connect(
            self._on_shared_selection_changed
        )
        # An outage starting or ending shows at once, not on the next
        # 2 s tick.
        self._context.slskd_status.changed.connect(self.poll_next_step)

    def _on_shared_selection_changed(self) -> None:
        # Deferred, not synchronous: `changed` can fire from inside
        # this page's own track_table.itemSelectionChanged handler
        # (_on_track_selection_changed writes track_ids there) — a
        # synchronous poll_selected_playlist() re-entrantly mutating
        # that same table's row count, from inside its own selection-
        # changed signal's emission, is confirmed live to segfault.
        # QTimer.singleShot(0, ...) is this codebase's own established
        # pattern for exactly this — "react to a Qt signal by
        # deferring the real work off the current call stack"
        # (ui/workers.py's deferred native delete).
        QTimer.singleShot(0, self._reconcile_shared_selection)

    def _reconcile_shared_selection(self) -> None:
        self._sync_playlist_list_highlight()
        self.poll_selected_playlist()
        self.poll_next_step()

    def _sync_playlist_list_highlight(self) -> None:
        # blockSignals, not a bare setCurrentItem: setCurrentItem would
        # otherwise fire currentItemChanged -> _on_playlist_selected ->
        # set_playlist() right back, which is a harmless no-op given
        # the same value, but this keeps the direction of data flow
        # unambiguous — render follows state, it never re-derives it.
        selected = self.selected_playlist

        for row in range(self.playlist_list.count()):
            item = self.playlist_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == selected:
                if self.playlist_list.currentItem() is not item:
                    self.playlist_list.blockSignals(True)
                    self.playlist_list.setCurrentItem(item)
                    self.playlist_list.blockSignals(False)
                return

        # No matching row (e.g. picked from a fresher list than
        # Dashboard's own playlist_list has loaded) — clear rather than
        # leave a stale row highlighted.
        if self.playlist_list.currentItem() is not None:
            self.playlist_list.blockSignals(True)
            # setCurrentItem(None) isn't in PySide6's stub overloads
            # (even though Qt's C++ API accepts a null item) —
            # setCurrentRow(-1) is the typed way to clear it.
            self.playlist_list.setCurrentRow(-1)
            self.playlist_list.blockSignals(False)

    def _build_dashboard_action_row(self) -> QHBoxLayout:
        # Relocated from the old global QToolBar (visible on every page
        # regardless of which one was showing) onto the Dashboard page
        # itself, right after the "next step" CTA, as secondary buttons
        # (HISTORY §7). Sync/Scan/Match renamed from their old cryptic
        # labels; still global-scoped (all playlists/locations/tracks,
        # matching the CLI — HISTORY §22), unaffected by which playlist
        # is selected. Download is playlist-scoped (the one exception)
        # but lives in the same row since it's the other real action a
        # user takes from here.
        row = QHBoxLayout()

        self.download_button = QPushButton("Download selected playlist")
        self.download_button.setToolTip(
            help_text.TOOLTIP_DOWNLOAD_SELECTED_PLAYLIST
        )
        self.download_button.clicked.connect(self._on_download_clicked)
        row.addWidget(self.download_button)

        self.sync_button = QPushButton("Refresh playlists")
        self.sync_button.setToolTip(help_text.TOOLTIP_SYNC_ALL_PLAYLISTS)
        self.sync_button.clicked.connect(self.refresh_playlists)
        row.addWidget(self.sync_button)

        # A bare "&" in QPushButton text is a Qt keyboard-mnemonic
        # marker, consumed and rendered as an underline under the
        # following character ("Rescan _match library"), not a literal
        # ampersand. "&Help" at this file's menu-bar construction is a
        # real, intentional mnemonic and is the only place this should
        # ever appear unescaped (HISTORY §79).
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

    @property
    def selected_playlist(self) -> Playlist | None:
        # The shared PlaylistSelection is the single source of truth;
        # this page holds no parallel copy.
        return self._context.playlist_selection.playlist

    @selected_playlist.setter
    def selected_playlist(self, playlist: Playlist | None) -> None:
        self._context.playlist_selection.set_playlist(playlist)

    def _selected_track_ids(self) -> list[str]:
        rows = sorted(
            {index.row() for index in self.track_table.selectionModel().selectedRows()}
        )
        # Reads each row's own UserRole anchor (see _render_track_
        # statuses) rather than indexing _current_track_statuses by
        # row — sort-safe regardless of the table's current order.
        track_ids = []

        for row in rows:
            item = self.track_table.item(row, 0)
            if item is not None:
                track_ids.append(item.data(Qt.ItemDataRole.UserRole))

        return track_ids

    def _on_track_selection_changed(self) -> None:
        self._context.playlist_selection.set_track_ids(
            self._selected_track_ids()
        )

    def _build_track_actions(self, status: TrackStatus) -> QWidget | None:
        # No button at all outside IN_LIBRARY — tag_tracks would just
        # report skipped_no_match for anything else, so there's nothing
        # real to offer here (same "blank cell, not a misleading
        # control" precedent as the Downloads tab's progress bars).
        if status.state != IN_LIBRARY:
            return None

        track_id = status.track.id

        if status.tagged_at is None:
            tag_button = QPushButton("Tag")
            tag_button.setToolTip(help_text.TOOLTIP_TAG_TRACK_ROW)
            tag_button.clicked.connect(
                lambda: self._host.tag_track(
                    track_id, tag_button, self.feedback,
                )
            )
            return theme.cell_widget(
                tag_button,
                row_label=f"{status.track.artist} - {status.track.title}",
            )

        tagged_label = PlainLabel("Tagged")
        tagged_label.setProperty("badge", "muted")
        tagged_label.setToolTip(
            plain_tooltip(f"Tagged {format_timestamp(status.tagged_at)}"),
        )
        return theme.cell_widget(tagged_label)

    def _on_track_table_context_menu(self, position: Any) -> None:
        row = self.track_table.rowAt(position.y())
        status = self._track_status_at_row(row)

        if status is None:
            return

        if status.state != IN_LIBRARY or status.tagged_at is None:
            # Nothing this menu offers applies to an untagged or
            # not-in-library row — same "no control where there's
            # nothing real to do" precedent as the Actions column
            # itself, just via a context menu instead of a blank cell.
            return

        menu = QMenu(self)
        retag_action = QAction("Re-tag", self)
        retag_action.triggered.connect(
            lambda: self._host.retag_track(
                status.track.id, self.feedback,
            )
        )
        menu.addAction(retag_action)
        menu.exec(self.track_table.viewport().mapToGlobal(position))

    def load_playlists(self) -> None:
        run_worker(
            self._context.thread_pool,
            self._context.application.sync_service.list_playlists,
            on_finished=self._populate_playlists,
            on_error=self.feedback.show_error,
        )

    def _populate_playlists(self, playlists: list[Playlist]) -> None:
        self.playlist_list.clear()

        for playlist in playlists:
            item = QListWidgetItem(
                f"{playlist.name} ({playlist.track_count} tracks)"
            )
            item.setData(Qt.ItemDataRole.UserRole, playlist)
            self.playlist_list.addItem(item)

    # Filter key -> (label, predicate). "all" has no predicate (always
    # matches); order here is the row's own left-to-right button order.
    _TRACK_FILTERS: tuple[tuple[str, str], ...] = (
        ("all", "All"),
        ("missing", "Missing"),
        ("needs_review", "Needs review"),
        ("untagged", "Untagged"),
    )

    def _build_track_filter_row(self) -> QHBoxLayout:
        # A segmented filter over the same TrackStatus.state values
        # _decide_next_step already counts (missing_count/
        # untagged_count above) — "Missing" and "Untagged" read
        # identically to those two; "Needs review" is the two review-
        # bound states _decide_next_step deliberately excludes from
        # missing_count (an active download_requests row already
        # exists for them).
        row = QHBoxLayout()
        row.setSpacing(theme.SPACING_XS)

        self._track_filter_group = QButtonGroup(self)
        self._track_filter_group.setExclusive(True)
        self._track_filter_buttons: dict[str, QPushButton] = {}

        for key, label in self._TRACK_FILTERS:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("variant", "segment")
            button.setChecked(key == self._track_filter)
            button.toggled.connect(
                lambda checked, key=key: (
                    self._on_track_filter_toggled(key, checked)
                )
            )
            self._track_filter_group.addButton(button)
            self._track_filter_buttons[key] = button
            row.addWidget(button)

        row.addStretch()
        return row

    def _on_track_filter_toggled(self, key: str, checked: bool) -> None:
        if not checked:
            # Only the newly-checked button's own signal acts — the
            # QButtonGroup emits toggled(False) on the outgoing button
            # too, which would otherwise re-render twice per click.
            return

        self._track_filter = key
        self._apply_track_filter_and_render()

    def _status_matches_track_filter(self, status: TrackStatus) -> bool:
        if self._track_filter == "missing":
            return status.state in (NOT_FOUND, REVIEW_CANDIDATE)
        if self._track_filter == "needs_review":
            return status.state in (NEEDS_REVIEW, AWAITING_REVIEW)
        if self._track_filter == "untagged":
            return status.state == IN_LIBRARY and status.tagged_at is None
        return True

    def _build_track_empty_panel(self) -> QWidget:
        # "No playlist selected, or an empty table, renders a small
        # centred panel with one line of copy and the relevant button —
        # not a bare grid" (HISTORY §7). One panel, two real states (see
        # _render_no_playlist_selected/_render_track_statuses): no
        # playlist picked yet (no button — there's nothing to click but
        # the list on the left), and a real playlist whose tracks
        # haven't been loaded yet (a real "Load tracks" action).
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addStretch()

        self.track_empty_label = PlainLabel("")
        self.track_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.track_empty_label.setWordWrap(True)
        # QLabel[badge="muted"] in theme.py.
        self.track_empty_label.setProperty("badge", "muted")
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
        self._context.playlist_selection.set_playlist(
            current.data(Qt.ItemDataRole.UserRole)
            if current is not None
            else None
        )
        self.poll_selected_playlist()
        self.poll_next_step()

    def poll_selected_playlist(self) -> None:
        # The Dashboard's own track table has no tray-menu relevance at
        # all; skip entirely while hidden rather than just gating the
        # render half, since the fetch itself has no other consumer
        # either (HISTORY §90).
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
            # No status_label: run_worker clears it at submit, and this
            # runs every 2 s, so it would wipe whatever an action wrote.
            on_finished=self._render_track_statuses,
        )

    def _render_no_playlist_selected(self) -> None:
        self._current_track_statuses = []
        self._track_status_by_id = {}
        self._rendered_track_rows = None
        self.track_table.setRowCount(0)
        self.track_empty_label.setText(
            "Pick a playlist on the left to see its tracks."
        )
        self.sync_tracks_button.hide()
        self.track_area_stack.setCurrentWidget(self._track_empty_panel)

    def _render_track_statuses(self, statuses: list[TrackStatus]) -> None:
        self._current_track_statuses = statuses
        # Sorting is enabled on this table, which moves each row's
        # QTableWidgetItems (and their attached UserRole data) but never
        # touches this plain Python list, so any row-position lookup
        # keyed off `_current_track_statuses` directly (as opposed to
        # reading a row's own UserRole track id back and looking it up
        # here) goes stale the moment a user sorts. See
        # _selected_track_ids, _on_track_table_context_menu and
        # _on_track_table_cell_double_clicked.
        self._track_status_by_id = {
            status.track.id: status for status in statuses
        }
        self._apply_track_filter_and_render()

    def _apply_track_filter_and_render(self) -> None:
        # Split out of _render_track_statuses so a filter-button click
        # can re-render from the already-cached _current_track_statuses
        # without a fresh backend poll.
        statuses = self._current_track_statuses

        if not statuses:
            self._rendered_track_rows = None
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
            # and intentional (HISTORY §1).
            self.sync_tracks_button.show()
            self.track_area_stack.setCurrentWidget(self._track_empty_panel)
            return

        visible = [
            status for status in statuses
            if self._status_matches_track_filter(status)
        ]

        if not visible:
            # A real, distinct empty state from "tracks haven't been
            # loaded yet" above — tracks exist, none match the current
            # filter, so no Load-tracks button belongs here.
            self._rendered_track_rows = None
            self.track_table.setRowCount(0)
            self.track_empty_label.setText(
                "No tracks match this filter."
            )
            self.sync_tracks_button.hide()
            self.track_area_stack.setCurrentWidget(self._track_empty_panel)
            return

        self.track_area_stack.setCurrentWidget(self.track_table_card)

        # theme.ACCENT is baked into the review-link items, so a theme
        # switch must rebuild even when the statuses are unchanged.
        rendered: _RenderedRows = (theme.ACCENT, tuple(visible))
        previous = self._rendered_track_rows

        if rendered == previous:
            return

        if previous is not None and _differ_only_in_progress(
                previous, rendered,
        ):
            self._update_progress_in_place()
        else:
            self._rebuild_track_rows(visible)

        self._rendered_track_rows = rendered

    def _rebuild_track_rows(self, visible: list[TrackStatus]) -> None:
        # Sorting is live on this table; disabled for the body of this
        # rebuild (see preserving_sort_order's own docstring for why)
        # and restored afterward.
        with preserving_sort_order(self.track_table):
            self.track_table.setRowCount(len(visible))
            action_widgets: list[QWidget] = []

            for row, status in enumerate(visible):
                label = f"{status.track.artist} - {status.track.title}"
                label_item = QTableWidgetItem(label)
                # The row's own anchor back to its real data, read by
                # every row-position handler below instead of indexing
                # _current_track_statuses by row (see this method's own
                # comment above).
                label_item.setData(Qt.ItemDataRole.UserRole, status.track.id)
                self.track_table.setItem(row, 0, label_item)

                state_text = _STATE_LABELS[status.state]
                # Only meaningful for NEEDS_REVIEW now: REVIEW_CANDIDATE's
                # own label already says "Candidate to review," so
                # appending this here would just repeat itself
                # (dashboard_service.py's own _compute_status never sets
                # soulseek_candidate on any other state — see its
                # docstring) (HISTORY §66).
                if (
                        status.state == NEEDS_REVIEW
                        and status.soulseek_candidate is not None
                ):
                    state_text += " (SoulSeek candidate found)"
                status_item = QTableWidgetItem(state_text)

                # Only these states have anything to jump to on the
                # Review page; every other status is a genuine no-op on
                # double-click, so only these get the affordance rather
                # than a misleading cue on every row (HISTORY §56, §66).
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

                if _has_progress_bar(status):
                    # _has_progress_bar's own conditions, for mypy.
                    assert (
                        status.total_bytes
                        and status.bytes_transferred is not None
                    )
                    progress = TwoToneProgressBar()
                    progress.setMaximum(status.total_bytes)
                    progress.setValue(status.bytes_transferred)
                    theme.style_determinate_progress_bar(progress)
                    # A bare QProgressBar handed to setCellWidget gets
                    # resized to the whole (tall) cell rect, then the global
                    # `QProgressBar { max-height: 14px; }` rule clamps it to
                    # the TOP instead of centering it — the identical bug
                    # HISTORY §96 fixed on the Downloads page, in this
                    # Dashboard-only builder that fix never touched
                    # (HISTORY §105). `theme.wrap_progress_bar` is the one
                    # shared container both pages now go through (moved out
                    # of main_window.py alongside the Downloads page itself,
                    # the moment a second caller needed it — HISTORY §119);
                    # the Dashboard deliberately passes no label (`None`) —
                    # no ETA is tracked per-track here, unlike Downloads.
                    self.track_table.setCellWidget(
                        row, 2, theme.wrap_progress_bar(progress, None),
                    )
                    fraction = status.bytes_transferred / status.total_bytes
                    self.track_table.setItem(
                        row, 2, SortKeyItem("", fraction),
                    )
                else:
                    self.track_table.removeCellWidget(row, 2)
                    # No active transfer — sorts below every real
                    # fraction-complete value (SortKeyItem forbids None
                    # as a sort key; HISTORY §122).
                    self.track_table.setItem(
                        row, 2, SortKeyItem("", -1.0),
                    )

                track_actions = self._build_track_actions(status)
                if track_actions is None:
                    self.track_table.removeCellWidget(row, 3)
                else:
                    action_widgets.append(track_actions)
                    self.track_table.setCellWidget(row, 3, track_actions)

        self._size_track_columns(action_widgets)

    def _update_progress_in_place(self) -> None:
        with preserving_sort_order(self.track_table):
            for row in range(self.track_table.rowCount()):
                status = self._track_status_at_row(row)
                if status is None or not _has_progress_bar(status):
                    continue
                # _has_progress_bar's own conditions, for mypy.
                assert (
                    status.total_bytes
                    and status.bytes_transferred is not None
                )
                container = self.track_table.cellWidget(row, 2)
                # The rebuild gave every progress row its bar, and a
                # progress-only change keeps each row's bar or no-bar.
                assert container is not None
                bar = container.findChild(QProgressBar)
                assert bar is not None
                bar.setMaximum(status.total_bytes)
                bar.setValue(status.bytes_transferred)
                # The key in place: a setItem here costs ~2.4 ms a row
                # (HISTORY §166). preserving_sort_order re-sorts by it.
                sort_item = self.track_table.item(row, 2)
                assert isinstance(sort_item, SortKeyItem)
                sort_item.sort_key = (
                    status.bytes_transferred / status.total_bytes
                )

    def _configure_track_columns(self) -> None:
        theme.configure_columns(self.track_table, _TRACK_COLUMNS)

    def _size_track_columns(self, action_widgets: list[QWidget]) -> None:
        theme.size_columns(self.track_table, _TRACK_COLUMNS, action_widgets)

    def _track_status_at_row(self, row: int) -> TrackStatus | None:
        # Reads the row's own UserRole anchor (see
        # _render_track_statuses) rather than indexing
        # _current_track_statuses by row — sort-safe regardless of the
        # table's current order.
        if row < 0:
            return None

        item = self.track_table.item(row, 0)

        if item is None:
            return None

        return self._track_status_by_id.get(item.data(Qt.ItemDataRole.UserRole))

    def _on_track_table_cell_double_clicked(
            self, row: int, _column: int,
    ) -> None:
        status = self._track_status_at_row(row)

        if status is None:
            return

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
        playlists = self._context.application.sync_service.list_playlists()

        return _NextStepFacts(
            spotify_configured=self._context.application.spotify_configured,
            has_library_location=bool(
                self._context.application.library_service.list_locations()
            ),
            has_cached_playlists=bool(playlists),
            selected_playlist_name=playlist_name,
            track_statuses=track_statuses,
            has_scanned_library=(
                self._context.application.library_service.has_scanned_library()
            ),
            soulseek_configured=self._context.application.soulseek_configured,
            stale_playlist_names=[
                playlist.name for playlist in playlists
                if playlist.tracks_are_stale
            ],
            slskd_unreachable_message=(
                self._context.slskd_status.unreachable_message
            ),
        )

    def poll_next_step(self) -> None:
        # The Dashboard's own CTA banner has no tray-menu relevance;
        # skip entirely while hidden (HISTORY §90).
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

        # Identity of "the step currently being offered," so a
        # dismissal can be remembered per-step rather than globally: a
        # real fact change (playlist switched, or the underlying
        # next-step reason changed) always surfaces again (HISTORY §71).
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
        # Every setVisible/setEnabled call below first checks
        # busy_actions.is_running for that same button's own key, and
        # skips touching it entirely if so. This poll tick has no idea
        # a background action might still be mid-flight; without this
        # guard, this exact method re-enables a button within 2s of a
        # click regardless of whether its real work was still running
        # — and, for Download specifically, a real reported bug: this
        # setVisible call could hide the button out from under an
        # in-progress download the instant the CTA's own action was
        # still "download" (which it usually still is, since the
        # missing-track count hasn't changed yet) (HISTORY §65).
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

    def refresh_playlists(self) -> None:
        self._context.run_busy_worker(
            "sync", self.sync_button,
            self._context.application.sync_service.refresh_playlists,
            on_finished=self._on_sync_finished,
            on_error=self.feedback.show_error,
            reports_progress=True,
        )

    def _on_sync_finished(self, result: PlaylistRefreshResult) -> None:
        self.load_playlists()
        self.feedback.show_outcome(
            help_text.format_playlist_refresh_message(result),
            kind="warning" if result.local_files_skipped else "success",
        )

    def _on_scan_clicked(self) -> None:
        # scan_and_match() chains scan_all() + match_all() into one
        # background call, so newly-found files get a track_matches row
        # without a separate, non-obvious "Re-match library" click.
        # run_worker()'s single dispatcher gives no safe way to push a
        # genuine live "now matching..." update partway through one
        # background call (see ui/workers.py's own docstring on why a
        # per-task signal was deliberately removed) — this sets an
        # immediate placeholder instead, replaced by the real combined
        # result once the whole call finishes.
        self._context.run_busy_worker(
            "scan", self.scan_button,
            self._context.application.library_service.scan_and_match,
            busy_text="Scanning…",
            on_finished=self._on_scan_and_match_finished,
            on_error=self.feedback.show_error,
        )
        self.feedback.show_progress(
            "Scanning library, then matching tracks…"
        )

    def _on_scan_and_match_finished(self, result: ScanAndMatchResult) -> None:
        scan, match = result.scan, result.match
        self.feedback.show_outcome(
            f"Scanned: {scan.added} added, {scan.updated} "
            f"updated, {scan.removed} removed. "
            f"Matched: {match.auto} auto, "
            f"{match.needs_review} needs review, "
            f"{match.unmatched} unmatched.",
            kind="success",
        )
        self.poll_selected_playlist()

    def _on_match_clicked(self) -> None:
        self._context.run_busy_worker(
            "match", self.match_button,
            self._context.application.track_matcher.match_all,
            on_finished=self._on_match_finished,
            on_error=self.feedback.show_error,
        )

    def _on_match_finished(self, result: MatchResult) -> None:
        self.feedback.show_outcome(
            f"Matched: {result.auto} auto, "
            f"{result.needs_review} needs review, "
            f"{result.unmatched} unmatched.",
            kind="success",
        )
        self.poll_selected_playlist()

    def _set_download_button_busy(self) -> None:
        # Idempotent (BusyActionRegistry.begin() no-ops if already
        # running) — safe to call again at every hop of the download
        # chain below, matching this method's own pre-registry behavior.
        self._context.busy_actions.begin(
            "download", self.download_button, "Starting download…",
        )
        self._context.render_activity_strip()

    def _reset_download_button(self) -> None:
        self._context.busy_actions.end("download")
        self._context.render_activity_strip()

    def _on_download_clicked(self) -> None:
        if self.selected_playlist is None:
            self.dashboard_notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        playlist = self.selected_playlist
        playlist_name = playlist.name

        # The button shows that something started across this entire
        # multi-step chain (resolvability check, maybe a destination
        # dialog, then the real download): disabled + relabeled here and
        # re-asserted at the top of every continuation below
        # (run_worker's own success-path `button.setEnabled(True)` would
        # otherwise flip it back on between hops) so it never reads
        # "enabled but says Starting download…" at any point in the
        # chain; reset on every real exit path (cancelled dialog, no
        # locations, real completion, or a genuine error via on_error).
        self._set_download_button_busy()

        # A playlist with its OWN destination already set
        # (`playlist.download_location_id`, already loaded on the
        # Playlist itself — no extra query needed) always skips straight
        # to the real download; the prompt below is only for a playlist
        # that would otherwise silently fall through to the configured
        # default (HISTORY §50), so the user gets to see and confirm —
        # or change — where it's actually going, once per playlist.
        if playlist.download_location_id is not None:
            self._start_download(playlist_name)
            return

        # Fetches both the real current fallback (to pre-fill the
        # dialog with the exact path it would already use — shares
        # DownloadPlacement.resolve_destination with the real move step
        # via get_resolved_destination, so this can never drift into a
        # second, different notion of "resolvable") and every registered
        # location (for the picker), in one round trip.
        run_worker(
            self._context.thread_pool,
            lambda: (
                self._context.application.download_service
                .get_resolved_destination(playlist_name),
                self._context.application.library_service.list_locations(),
            ),
            on_finished=lambda result: self._open_destination_dialog(
                playlist_name, result[1], result[0],
            ),
            on_error=self._on_download_error,
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

        # When the real fallback already resolves (`resolved` given),
        # pre-fill with exactly what it would use: that location, and
        # its real subfolder (already sanitized by resolve_destination —
        # never re-sanitized here). Falls back to the app-wide
        # configured default only when nothing resolved at all.
        if resolved is not None:
            prefill_location, prefill_subfolder = resolved
            default_location_id: int | None = prefill_location.id
        else:
            prefill_subfolder = None
            default_location_id = (
                self._context.application.settings.default_download_location_id
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
                self._context.application.download_service.set_destination(
                    playlist_name, location.name, subfolder,
                )
            else:
                # Not remembered specifically for this playlist — the
                # only other real destination concept is the app-wide
                # default, so this becomes that. Deliberately always
                # True for the subfolder-per-playlist toggle here: the
                # field was prefilled with the playlist's own name, so
                # treating this choice as "per playlist" matches what
                # was actually shown, even if the text was hand-edited
                # to something else for this one confirmation.
                self._context.application.persist_default_destination(
                    location_id, True,
                )

        self._set_download_button_busy()

        run_worker(
            self._context.thread_pool,
            do_persist,
            on_finished=lambda _: self._start_download(playlist_name),
            on_error=self._on_download_error,
        )

    def _start_download(self, playlist_name: str) -> None:
        self._set_download_button_busy()

        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.download_service.download_playlist(
                playlist_name
            ),
            on_finished=self._on_download_finished,
            on_error=self._on_download_error,
        )

    def _on_download_error(self, message: str) -> None:
        self._reset_download_button()
        self.feedback.show_error(message)

    def _on_download_finished(self, result: PlaylistDownloadResult) -> None:
        self._reset_download_button()
        self.poll_selected_playlist()

        message = help_text.format_download_result_message(result)
        if result.failures:
            kind = "warning"
        elif result.requested:
            kind = "success"
        else:
            kind = "info"
        self.feedback.show_outcome(message, kind=kind)

    def _on_sync_tracks_clicked(self) -> None:
        if self.selected_playlist is None:
            return

        playlist = self.selected_playlist

        def do_sync() -> TrackSyncResult:
            return self._context.application.sync_service.sync_playlist_tracks(
                playlist,
            )

        def on_finished(result: TrackSyncResult) -> None:
            self.poll_selected_playlist()

            if result.local_files_skipped:
                self.dashboard_notice.show_message(
                    help_text.format_skipped_local_files_notice(
                        playlist.name, result.local_files_skipped,
                    ),
                    kind="warning",
                )

        self._context.run_busy_worker(
            "sync_tracks", self.sync_tracks_button, do_sync,
            on_finished=on_finished,
            on_error=self.feedback.show_error,
        )

    def _on_next_step_action(self, action: str) -> None:
        if action == "start_slskd":
            start_slskd(
                self._context, self.next_step_notice.action_button,
                self.feedback,
            )
        elif action == "settings_connection":
            self._host.open_settings(SETTINGS_TAB_CONNECTION)
        elif action == "settings_locations":
            self._host.open_settings(SETTINGS_TAB_LOCATIONS)
        elif action == "sync":
            self.refresh_playlists()
        elif action == "sync_tracks":
            self._on_sync_tracks_clicked()
        elif action == "scan":
            self._on_scan_clicked()
        elif action == "download":
            self._on_download_clicked()
        elif action == "tag_playlist":
            self._host.tag_playlist(self.feedback)
