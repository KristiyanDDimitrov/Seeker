"""The Library page (round 8 §12.6) — tagging operations split out of
the Dashboard, which now only picks a playlist and shows its tracks.
Library has no selection state of its own: it operates on whatever
playlist/track selection is currently live on the Dashboard page, via
`LibraryHost` — the same cross-page "reach a live seam on an already-
migrated page" pattern `ReviewHost` already uses for Dashboard's
status_label/_poll_selected_playlist (main_window.py). TaggingPanel
itself (tagging_panel.py) is unchanged by this move; only which page
constructs and hosts it changed.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from seeker.models.playlist import Playlist
from seeker.ui import help_text
from seeker.ui.notice import InlineNotice
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.pages.tagging_panel import TaggingPanel, TaggingPanelHost


@dataclass(frozen=True)
class LibraryHost:
    """What the Library page needs from the Dashboard page it reads
    its live playlist/track selection from (round 8 §12.6)."""
    get_selected_playlist: Callable[[], Playlist | None]
    get_selected_track_ids: Callable[[], list[str]]
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

        self.status_label = QLabel("")

        self._tagging_panel = TaggingPanel(
            context,
            TaggingPanelHost(
                status_label=self.status_label,
                notice=self.notice,
                get_selected_playlist=host.get_selected_playlist,
                get_selected_track_ids=host.get_selected_track_ids,
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
