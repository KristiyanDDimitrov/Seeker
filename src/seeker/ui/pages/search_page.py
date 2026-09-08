"""The Search page (HISTORY §119)."""

from enum import IntEnum

from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.models.soulseek_file import SoulseekFile
from seeker.models.track import Track
from seeker.soulseek.quality import rank_candidates, score_candidate
from seeker.ui import help_text, theme
from seeker.ui.formatting import format_file_size
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.workers import run_worker


# Same "resolve by real header text, not a shared literal" precedent
# as the other tables' own column enums (HISTORY §82).
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

_SEARCH_COLUMNS = theme.ColumnLayout(
    stretch=(_SearchColumn.FILENAME,),
    fit_content=(
        _SearchColumn.USERNAME, _SearchColumn.FORMAT,
        _SearchColumn.BITRATE, _SearchColumn.SIZE,
        _SearchColumn.LOCKED, _SearchColumn.SCORE,
    ),
    actions=_SearchColumn.ACTIONS,
)


class SearchPage(QWidget):
    def __init__(self, context: PageContext):
        super().__init__()
        self._context = context

        # A dedicated page between Dashboard (already the most crowded
        # page — HISTORY §51) and Downloads (a status view, not a
        # search/results one). search_manual()/download_manual() reuse
        # the exact same search + quality-ranking logic download_playlist
        # uses; nothing new is ranked or scored here (HISTORY §82).
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
        self._configure_search_columns()

        self._search_artist = ""
        self._search_title = ""
        self._search_files: list[SoulseekFile] = []

        page = build_page("Search", help_text.SEARCH_TAB_SUBTITLE, content)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

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

        self._context.run_busy_worker(
            "search_manual", self.search_button,
            lambda: (
                self._context.application.download_service
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

    def _configure_search_columns(self) -> None:
        theme.configure_columns(self.search_results_table, _SEARCH_COLUMNS)

    def _size_search_columns(self, action_widgets: list[QWidget]) -> None:
        theme.size_columns(
            self.search_results_table, _SEARCH_COLUMNS, action_widgets,
        )

    def _build_search_result_actions(self, file: SoulseekFile) -> QWidget:
        download_button = QPushButton("Download this one")
        download_button.setToolTip(help_text.TOOLTIP_DOWNLOAD_THIS_ONE)
        download_button.clicked.connect(
            lambda: self._on_download_this_one_clicked(file, download_button)
        )
        return theme.cell_widget(download_button)

    def _on_download_best_clicked(self) -> None:
        # The headline action, so it gets the shared busy_actions/
        # activity-strip treatment like every other persistent-button
        # action on this page.
        if not self._search_files:
            return

        artist, title, files = (
            self._search_artist, self._search_title, self._search_files,
        )
        self._context.run_busy_worker(
            "download_manual", self.download_best_button,
            lambda: (
                self._context.application.download_service.download_manual(
                    artist, title, files=files,
                )
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
            self._context.thread_pool,
            lambda: self._context.application.download_service
            .download_manual(artist, title, chosen=file),
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
