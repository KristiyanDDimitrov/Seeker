"""The Library page: the selected playlist's tracks that are in the
library, each with its tag and cover-art state, beside the tagging
actions (TaggingPanel) that act on them.

The playlist and the track selection live in
`PageContext.playlist_selection` (HISTORY §133), which both this page
and the Dashboard write: the context header's picker sets the playlist
(HISTORY §134), and this page's track list sets the tracks "Tag
selected" tags, as the Dashboard's does. The list shows a selection
made on either page. `LibraryHost` carries only `refresh_track_table`,
the Dashboard's, an action rather than selection state.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.models.playlist import Playlist
from seeker.models.track_status import IN_LIBRARY, TrackStatus
from seeker.ui import help_text, status_lamp, theme
from seeker.ui.elided_text import (
    SECONDARY_ROLE,
    elide_list_items,
    set_secondary_min_share,
)
from seeker.ui.empty_state import EmptyGlyph, EmptyState
from seeker.ui.notice import FeedbackTarget, InlineNotice
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.pages.tagging_panel import TaggingPanel, TaggingPanelHost
from seeker.ui.plain_text import PlainLabel
from seeker.ui.table_sort import SortKeyItem, preserving_sort_order
from seeker.ui.workers import run_worker

_TRACK_COLUMNS = theme.ColumnLayout(stretch=(0,), fit_content=(1, 2))

# The action cards' column; their buttons wrap inside it, and the
# track list takes the rest.
_ACTIONS_WIDTH = 280


@dataclass(frozen=True)
class LibraryHost:
    """What the Library page needs from the Dashboard page beyond its
    live playlist/track selection (`PageContext.playlist_selection`;
    HISTORY §133)."""
    refresh_track_table: Callable[[], None]


# A cell's lamp, label and quieter note, then its sort key: closest
# to done first.
_LampCell = tuple[status_lamp.Lamp, str, str, int]


def _tags_cell(status: TrackStatus) -> _LampCell:
    if status.tagged_at is None:
        return status_lamp.CUE_WAITING, "Not tagged", "", 1
    return status_lamp.PLAY, "Tagged", "", 0


def _art_cell(status: TrackStatus) -> _LampCell:
    """The file's cover art, and what it takes to fix it: Fix missing
    cover art needs Spotify's image URL, which Get cover art from
    Spotify fetches."""
    if status.has_art is None:
        return status_lamp.STANDBY, "Not checked", "Scan to check", 2
    if status.has_art:
        return status_lamp.PLAY, "Embedded", "", 0
    if status.track.album_art_url is None:
        return status_lamp.CUE_WAITING, "Missing", "Get from Spotify", 1
    return status_lamp.CUE_WAITING, "Missing", "", 1


class LibraryPage(QWidget):
    def __init__(self, context: PageContext, host: LibraryHost):
        super().__init__()
        self._context = context
        self._host = host
        # The playlist the track list was last loaded for; a change of
        # track selection alone reloads nothing.
        self._loaded_playlist_id: str | None = None

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)

        self.notice = InlineNotice()
        layout.addWidget(self.notice)

        layout.addWidget(self._build_context_header())

        self.status_label = PlainLabel("")

        self._tagging_panel = TaggingPanel(
            context,
            TaggingPanelHost(
                status_label=self.status_label,
                notice=self.notice,
                refresh_track_table=self._refresh_after_a_run,
            ),
        )

        tracks_column = QVBoxLayout()
        tracks_column.addWidget(theme.make_card(self._build_track_table()), 1)
        tracks_column.addWidget(self._tagging_panel.results_panel)

        actions = theme.scrollable(self._tagging_panel)
        actions.setFixedWidth(_ACTIONS_WIDTH)

        body = QHBoxLayout()
        body.setSpacing(theme.SPACING_MD)
        body.addLayout(tracks_column, 1)
        body.addWidget(actions)
        layout.addLayout(body, 1)
        layout.addWidget(self.status_label)

        page = build_page("Library", help_text.LIBRARY_TAB_SUBTITLE, content)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

        self._context.playlist_selection.changed.connect(
            self._on_shared_selection_changed
        )
        self._render_context_header()
        self.refresh_tracks()

    # The Dashboard's Tag and Re-tag row actions and its next-step
    # "tag playlist" CTA run here, reporting to the caller's feedback.
    def tag_track(
            self,
            track_id: str,
            button: QPushButton,
            feedback: FeedbackTarget,
    ) -> None:
        self._tagging_panel.tag_track(track_id, button, feedback=feedback)

    def retag_track(self, track_id: str, feedback: FeedbackTarget) -> None:
        self._tagging_panel.retag_track(track_id, feedback=feedback)

    def tag_playlist(self, feedback: FeedbackTarget) -> None:
        self._tagging_panel.tag_playlist(feedback)

    def refresh_tracks(self) -> None:
        """Reloads the track list for the selected playlist: on show,
        after a theme switch (the lamps are drawn in the palette), and
        after a run here changes the files."""
        playlist = self._context.playlist_selection.playlist
        self._loaded_playlist_id = None if playlist is None else playlist.id

        if playlist is None:
            self._render_tracks([])
            self.track_empty_state.set_text(
                help_text.LIBRARY_TRACKS_NO_PLAYLIST_TEXT
            )
            return

        playlist_id = playlist.id
        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.dashboard_service
            .get_playlist_track_status(playlist.name),
            on_finished=lambda statuses: self._on_tracks_loaded(
                playlist_id, statuses,
            ),
        )

    def _refresh_after_a_run(self) -> None:
        self._host.refresh_track_table()
        self.refresh_tracks()

    def _build_track_table(self) -> QTableWidget:
        self.track_table = QTableWidget(0, 3)
        self.track_table.setHorizontalHeaderLabels(
            ["Track", "Tags", "Cover art"]
        )
        theme.apply_table_defaults(self.track_table)
        self.track_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.track_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.track_table.setIconSize(
            QSize(status_lamp.LAMP_SIZE, status_lamp.LAMP_SIZE),
        )
        self.track_table.itemSelectionChanged.connect(
            self._on_track_selection_changed
        )
        # A state reads in full; its note gives way first.
        set_secondary_min_share(self.track_table, 0.0)
        theme.configure_columns(self.track_table, _TRACK_COLUMNS)
        self.track_empty_state = EmptyState(
            self.track_table,
            EmptyGlyph.RECORD,
            help_text.LIBRARY_TRACKS_NO_PLAYLIST_TEXT,
        )
        return self.track_table

    def _on_tracks_loaded(
            self, playlist_id: str, statuses: list[TrackStatus],
    ) -> None:
        # A load for a playlist since replaced is dropped; the load for
        # the new one is already running.
        if playlist_id != self._loaded_playlist_id:
            return

        self._render_tracks(
            [status for status in statuses if status.state == IN_LIBRARY]
        )
        self.track_empty_state.set_text(
            help_text.LIBRARY_TRACKS_NONE_IN_LIBRARY_TEXT
        )

    def _render_tracks(self, statuses: list[TrackStatus]) -> None:
        palette = theme.active_palette()
        table = self.track_table
        # A rebuild clears the selection; the shared one stays as it
        # was and is shown again below.
        table.blockSignals(True)
        try:
            with preserving_sort_order(table):
                table.setRowCount(len(statuses))
                for row, status in enumerate(statuses):
                    label = QTableWidgetItem(
                        f"{status.track.artist} - {status.track.title}"
                    )
                    label.setData(Qt.ItemDataRole.UserRole, status.track.id)
                    table.setItem(row, 0, label)
                    for column, cell in (
                            (1, _tags_cell(status)),
                            (2, _art_cell(status)),
                    ):
                        table.setItem(row, column, _lamp_item(*cell, palette))
        finally:
            table.blockSignals(False)
        theme.configure_columns(table, _TRACK_COLUMNS)
        self._show_shared_track_selection()

    def _on_track_selection_changed(self) -> None:
        rows = {index.row() for index in self.track_table.selectedIndexes()}
        items = [self.track_table.item(row, 0) for row in sorted(rows)]
        self._context.playlist_selection.set_track_ids([
            item.data(Qt.ItemDataRole.UserRole)
            for item in items
            if item is not None
        ])

    def _on_shared_selection_changed(self) -> None:
        self._render_context_header()
        # The table's part is deferred: `changed` can fire from inside
        # its own itemSelectionChanged (HISTORY §134).
        QTimer.singleShot(0, self._reconcile_track_table)

    def _reconcile_track_table(self) -> None:
        playlist = self._context.playlist_selection.playlist
        playlist_id = None if playlist is None else playlist.id
        if playlist_id != self._loaded_playlist_id:
            self.refresh_tracks()
        else:
            self._show_shared_track_selection()

    def _show_shared_track_selection(self) -> None:
        wanted = set(self._context.playlist_selection.track_ids)
        table = self.track_table
        selection = QItemSelection()
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) in wanted:
                selection.select(
                    table.model().index(row, 0),
                    table.model().index(row, table.columnCount() - 1),
                )
        # Signals blocked: showing the shared selection must not write
        # it back, trimmed to the rows this list has.
        table.blockSignals(True)
        table.selectionModel().blockSignals(True)
        try:
            table.selectionModel().select(
                selection, QItemSelectionModel.SelectionFlag.ClearAndSelect,
            )
        finally:
            table.selectionModel().blockSignals(False)
            table.blockSignals(False)
        table.viewport().update()

    def _build_context_header(self) -> QWidget:
        # A persistent header above the tagging controls naming the
        # playlist it acts on and its track count, plus an inline picker
        # to change it without leaving the page. Not a modal — this is
        # frequent enough (every session, potentially every few minutes)
        # that a dialog's extra click/focus-shift would be friction, not
        # safety; an inline collapse/expand costs nothing when not in
        # use.
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(theme.SPACING_SM)

        summary_row = QHBoxLayout()
        self._context_label = PlainLabel("")
        self._context_label.setWordWrap(True)
        summary_row.addWidget(self._context_label, 1)

        self._change_playlist_button = QPushButton("Change playlist")
        self._change_playlist_button.setToolTip(
            help_text.TOOLTIP_CHANGE_LIBRARY_PLAYLIST
        )
        self._change_playlist_button.setCheckable(True)
        self._change_playlist_button.toggled.connect(
            self._on_change_playlist_toggled
        )
        summary_row.addWidget(self._change_playlist_button)
        inner_layout.addLayout(summary_row)

        # Same list-of-playlists shape as Dashboard's own playlist_list
        # (same source, same "name (N tracks)" row text) — hidden by
        # default once a playlist is selected, forced open for the
        # empty state (see _render_context_header) so "no playlist
        # selected" offers the picker directly instead of only naming
        # the problem.
        self._playlist_picker = QListWidget()
        elide_list_items(self._playlist_picker)
        self._playlist_picker.setMaximumHeight(160)
        self._playlist_picker.itemClicked.connect(self._on_playlist_picked)
        self._playlist_picker.itemActivated.connect(self._on_playlist_picked)
        self._playlist_picker.hide()
        inner_layout.addWidget(self._playlist_picker)

        return theme.make_card(inner)

    def _render_context_header(self) -> None:
        playlist = self._context.playlist_selection.playlist

        if playlist is None:
            self._context_label.setText(help_text.LIBRARY_NO_PLAYLIST_TEXT)
            theme.set_dynamic_property(self._context_label, "badge", "warn")
            self._change_playlist_button.hide()
            self._set_playlist_picker_visible(True)
        else:
            unit = "track" if playlist.track_count == 1 else "tracks"
            self._context_label.setText(
                f"Acting on '{playlist.name}' — "
                f"{playlist.track_count} {unit} in this playlist."
            )
            theme.set_dynamic_property(self._context_label, "badge", "muted")
            self._change_playlist_button.show()
            self._change_playlist_button.setChecked(False)
            self._set_playlist_picker_visible(False)

    def _set_playlist_picker_visible(self, visible: bool) -> None:
        self._playlist_picker.setVisible(visible)
        if visible:
            self._load_playlist_picker()

    def _on_change_playlist_toggled(self, checked: bool) -> None:
        self._set_playlist_picker_visible(checked)

    def _load_playlist_picker(self) -> None:
        run_worker(
            self._context.thread_pool,
            self._context.application.sync_service.list_playlists,
            status_label=self.status_label,
            on_finished=self._populate_playlist_picker,
        )

    def _populate_playlist_picker(self, playlists: list[Playlist]) -> None:
        self._playlist_picker.clear()

        for playlist in playlists:
            item = QListWidgetItem(
                f"{playlist.name} ({playlist.track_count} tracks)"
            )
            item.setData(Qt.ItemDataRole.UserRole, playlist)
            self._playlist_picker.addItem(item)

    def _on_playlist_picked(self, item: QListWidgetItem) -> None:
        playlist = item.data(Qt.ItemDataRole.UserRole)
        self._context.playlist_selection.set_playlist(playlist)
        # Collapse explicitly rather than relying on _render_context_
        # header alone — picking the ALREADY-selected playlist is a
        # no-op on PlaylistSelection (no `changed` emitted), and the
        # panel should still close on that click.
        self._change_playlist_button.setChecked(False)


def _lamp_item(
        lamp: status_lamp.Lamp,
        text: str,
        secondary: str,
        sort_key: int,
        palette: theme.Palette,
) -> QTableWidgetItem:
    item = SortKeyItem(text, sort_key)
    item.setIcon(status_lamp.lamp_icon(lamp, palette))
    if secondary:
        item.setData(SECONDARY_ROLE, secondary)
    return item
