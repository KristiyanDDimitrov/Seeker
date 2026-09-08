"""The History page — HISTORY §119, the first page extraction that
actually touched PageContext (dialogs.py, moved before this, was a
pure class move with no MainWindow state attached).
"""

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.models.history_event import DOWNLOADED, TAGGED, HistoryEvent
from seeker.ui import help_text, theme
from seeker.ui.formatting import format_timestamp
from seeker.ui.pages.context import PageContext, build_page

# Plain-language labels for HistoryEvent.event_type — see
# models/history_event.py for the two real values.
_HISTORY_EVENT_LABELS = {
    DOWNLOADED: "Downloaded",
    TAGGED: "Tagged",
}


class HistoryPage(QWidget):
    def __init__(self, context: PageContext):
        super().__init__()
        self._context = context

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
        # No ColumnLayout shape here either — see the same note on
        # `downloads_table` in downloads_page.py.
        self.history_table.horizontalHeader().setStretchLastSection(True)
        theme.apply_table_defaults(self.history_table)
        theme.apply_column_floors(self.history_table)
        layout.addWidget(theme.make_card(self.history_table))

        # Raw, unfiltered events from the last real fetch — the filter
        # combo re-renders from this in memory rather than re-querying,
        # since it's already a bounded, already-fetched list (DEFAULT_
        # LIMIT), not a live/paginated one.
        self._history_events: list[HistoryEvent] = []

        page = build_page(
            "History", help_text.HISTORY_PAGE_SUBTITLE, content,
        )
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

    def _refresh_history(self) -> None:
        self._context.run_busy_worker(
            "history_refresh", self.history_refresh_button,
            self._context.application.history_service.get_recent_events,
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
