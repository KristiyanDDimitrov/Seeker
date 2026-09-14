"""The Library page (round 8 §12.6) — tagging operations split out of
the Dashboard, which now only picks a playlist and shows its tracks.
Library has no selection state of its own — it acts on whatever
playlist/track selection is currently live in `PageContext.
playlist_selection` (round9 §7.1) — but as of round9 §7.2 it is a
writer too: the context header's inline picker lets a playlist be
chosen right here, not only on Dashboard, via the same shared object
(`DashboardPage._on_shared_selection_changed` is what keeps Dashboard's
own list highlight and track table in step with a write that
originates here). `LibraryHost` still carries only
`refresh_track_table` — the same cross-page "reach a live seam on an
already-migrated page" pattern `ReviewHost` still uses for Dashboard's
status_label/_poll_selected_playlist (main_window.py), since that's an
action, not selection state. TaggingPanel itself (tagging_panel.py) is
unchanged by this page's context header; only which page constructs
and hosts it changed back in round 8.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from seeker.models.playlist import Playlist
from seeker.ui import help_text, theme
from seeker.ui.notice import InlineNotice
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.pages.tagging_panel import TaggingPanel, TaggingPanelHost
from seeker.ui.workers import run_worker


@dataclass(frozen=True)
class LibraryHost:
    """What the Library page needs from the Dashboard page beyond its
    live playlist/track selection (`PageContext.playlist_selection`,
    round9 §7.1)."""
    refresh_track_table: Callable[[], None]


class LibraryPage(QWidget):
    def __init__(self, context: PageContext, host: LibraryHost):
        super().__init__()
        self._context = context
        self._host = host

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)

        self.notice = InlineNotice()
        layout.addWidget(self.notice)

        layout.addWidget(self._build_context_header())

        self.status_label = QLabel("")

        self._tagging_panel = TaggingPanel(
            context,
            TaggingPanelHost(
                status_label=self.status_label,
                notice=self.notice,
                refresh_track_table=host.refresh_track_table,
            ),
        )
        layout.addWidget(self._tagging_panel)
        layout.addWidget(self.status_label)
        layout.addStretch()

        page = build_page(
            "Library", help_text.LIBRARY_TAB_SUBTITLE, content,
        )
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

        self._context.playlist_selection.changed.connect(
            self._render_context_header
        )
        self._render_context_header()

    def _build_context_header(self) -> QWidget:
        # round9 §7.2 — Kris: "Library section is currently confusing
        # — it doesn't say which playlist it's acting upon." This is
        # the fix: a persistent header above the tagging controls
        # naming the playlist and its track count, plus an inline
        # picker to change it without leaving the page. A modal was
        # considered and rejected — this is frequent enough (every
        # session, potentially every few minutes) that a dialog's
        # extra click/focus-shift would be friction, not safety; an
        # inline collapse/expand costs nothing when not in use.
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(theme.SPACING_SM)

        summary_row = QHBoxLayout()
        self._context_label = QLabel("")
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
