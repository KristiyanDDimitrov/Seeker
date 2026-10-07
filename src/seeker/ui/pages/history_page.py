"""The History page — HISTORY §119, the first page extraction that
actually touched PageContext (dialogs.py, moved before this, was a
pure class move with no MainWindow state attached).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.formatting import format_timestamp
from seeker.models.history_event import DOWNLOADED, TAGGED, HistoryEvent
from seeker.ui import help_text, theme
from seeker.ui.elided_text import SECONDARY_ROLE, set_secondary_min_share
from seeker.ui.empty_state import EmptyGlyph, EmptyState
from seeker.ui.notice import FeedbackTarget, InlineNotice
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.plain_text import PlainLabel
from seeker.ui.table_sort import SortKeyItem, preserving_sort_order

# Plain-language labels for HistoryEvent.event_type — see
# models/history_event.py for the two real values.
_HISTORY_EVENT_LABELS = {
    DOWNLOADED: "Downloaded",
    TAGGED: "Tagged",
}

_HISTORY_COLUMNS = theme.ColumnLayout(stretch=(2,), fit_content=(0, 1, 3))


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

        # A failed refresh, which outlives the progress line.
        self.notice = InlineNotice()
        layout.addWidget(self.notice)

        controls = QHBoxLayout()
        show_label = PlainLabel("Show")
        controls.addWidget(show_label)

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
        show_label.setBuddy(self.history_filter_combo)
        controls.addWidget(self.history_filter_combo)

        # The progress line shares the controls' row: empty, it would
        # hold a blank line of its own above the table.
        self.history_status_label = PlainLabel("")
        controls.addSpacing(theme.SPACING_MD)
        controls.addWidget(self.history_status_label)
        controls.addStretch()

        self.history_refresh_button = QPushButton("Refresh")
        self.history_refresh_button.setToolTip(
            help_text.TOOLTIP_HISTORY_REFRESH_BUTTON
        )
        self.history_refresh_button.clicked.connect(self.refresh_history)
        controls.addWidget(self.history_refresh_button)

        layout.addLayout(controls)
        self.feedback = FeedbackTarget(self.history_status_label, self.notice)

        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(
            ["When", "What", "Track", "Detail"]
        )
        theme.apply_table_defaults(self.history_table)
        theme.configure_columns(self.history_table, _HISTORY_COLUMNS)
        # The track reads in full; its playlist gives way first.
        set_secondary_min_share(self.history_table, 0.0)
        layout.addWidget(theme.make_card(self.history_table))
        self.history_empty_action = QPushButton(help_text.GO_TO_DASHBOARD_TEXT)
        self.history_empty_action.clicked.connect(
            lambda: self._context.navigate("dashboard")
        )
        self.history_empty = EmptyState(
            self.history_table, EmptyGlyph.RECORD, help_text.HISTORY_EMPTY,
            action=self.history_empty_action,
        )

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

    def refresh_history(self) -> None:
        self._context.run_busy_worker(
            "history_refresh", self.history_refresh_button,
            self._context.application.history_service.get_recent_events,
            status_label=self.history_status_label,
            on_finished=self._on_history_fetched,
            on_error=self.feedback.show_error,
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

        if self._history_events:
            self.history_empty.set_text(
                help_text.format_history_filter_empty(
                    self.history_filter_combo.currentText()
                )
            )
        else:
            self.history_empty.set_text(help_text.HISTORY_EMPTY)
        # Only an empty history has a first step to offer; an empty
        # filter is undone from the combo above the table.
        self.history_empty_action.setVisible(not self._history_events)

        # Sorting is live on this table; disabled for the body of this
        # rebuild (see preserving_sort_order's own docstring for why)
        # and restored afterward.
        with preserving_sort_order(self.history_table):
            self.history_table.setRowCount(len(events))

            for row, event in enumerate(events):
                # occurred_at is a real ISO 8601 string (sorts
                # chronologically as plain text); the DISPLAYED "Feb 03,
                # 2026" label would sort by month name instead if used
                # as the sort key directly (see SortKeyItem).
                self.history_table.setItem(
                    row, 0,
                    SortKeyItem(
                        format_timestamp(event.occurred_at), event.occurred_at,
                    ),
                )
                self.history_table.setItem(
                    row, 1,
                    QTableWidgetItem(_HISTORY_EVENT_LABELS[event.event_type]),
                )
                # The track reads first; its playlist sits quieter
                # beside it, as on Library and Review.
                label = f"{event.track_artist} - {event.track_title}"
                track_item = QTableWidgetItem(label)
                track_item.setData(SECONDARY_ROLE, event.playlist_name)
                track_item.setData(
                    Qt.ItemDataRole.AccessibleTextRole,
                    f"{label}, {event.playlist_name}",
                )
                self.history_table.setItem(row, 2, track_item)
                self.history_table.setItem(
                    row, 3, QTableWidgetItem(event.detail),
                )
        theme.size_columns(self.history_table, _HISTORY_COLUMNS, [])
