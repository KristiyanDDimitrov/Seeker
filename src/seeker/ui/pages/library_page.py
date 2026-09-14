"""The Library page (round 8 §12.6) — tagging operations split out of
the Dashboard, which now only picks a playlist and shows its tracks.
Library has no selection state of its own: it acts on whatever
playlist/track selection is currently live in `PageContext.
playlist_selection` (round9 §7.1), written by the Dashboard page.
`LibraryHost` now carries only `refresh_track_table` — the same cross-
page "reach a live seam on an already-migrated page" pattern
`ReviewHost` still uses for Dashboard's status_label/
_poll_selected_playlist (main_window.py), since that's an action, not
selection state. TaggingPanel itself (tagging_panel.py) is unchanged
by this move; only which page constructs and hosts it changed.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from seeker.ui import help_text
from seeker.ui.notice import InlineNotice
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.pages.tagging_panel import TaggingPanel, TaggingPanelHost


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
