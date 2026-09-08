"""Help and Support — the two static pages (HISTORY §119). Grouped in
one module since they share `_open_in_file_manager`/
`build_support_links_row`.
"""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from seeker import _build_info
from seeker.ui import help_text, theme
from seeker.ui.dialogs import build_support_links_row
from seeker.ui.pages.context import PageContext, build_page


def _open_in_file_manager(path: Path) -> None:
    # Cross-platform "reveal in Finder/Explorer" — same
    # subprocess/best-effort spirit as docker_setup.py's own OS calls,
    # just for the desktop file manager instead of Docker. `path.mkdir`
    # first since a brand-new install's slskd-data subfolder in
    # particular may not exist yet (SoulSeek skipped in the wizard) —
    # opening a folder that doesn't exist would otherwise silently do
    # nothing on every platform. check=False is explicit, not
    # forgotten: nothing useful to do with a failure here beyond what
    # the user already sees (the folder just doesn't open).
    path.mkdir(parents=True, exist_ok=True)

    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform == "win32":
        subprocess.run(["explorer", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


class HelpPage(QWidget):
    def __init__(self, context: PageContext):
        super().__init__()
        self._context = context

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

        locations = context.application.data_locations

        data_heading = QLabel(help_text.HELP_DATA_LOCATIONS_HEADING)
        data_heading.setTextFormat(Qt.TextFormat.RichText)
        inner_layout.addWidget(data_heading)

        intro_label = QLabel(help_text.HELP_DATA_LOCATIONS_INTRO)
        intro_label.setWordWrap(True)
        inner_layout.addWidget(intro_label)

        # Said explicitly, in the app, not just in a doc (HISTORY §81):
        # a "fix didn't work on the other account" report is very often
        # a different-database report, not a different-behavior one.
        per_account_label = QLabel(
            help_text.HELP_DATA_LOCATIONS_PER_ACCOUNT_NOTE
        )
        per_account_label.setWordWrap(True)
        inner_layout.addWidget(per_account_label)

        # Next to the data locations, not buried in About, since this
        # page is exactly where "which build is this?" troubleshooting
        # starts (HISTORY §81).
        build_identity = help_text.format_build_identity(
            _build_info.GIT_SHA, _build_info.GIT_DESCRIBE,
            _build_info.BUILT_AT,
        )
        build_label = QLabel(
            f"{help_text.HELP_BUILD_IDENTITY_LABEL} {build_identity}"
        )
        build_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        inner_layout.addWidget(build_label)

        locations_form = QFormLayout()
        for label_text, path in (
                (help_text.DATA_LOCATION_DATABASE_LABEL, locations.database_path),
                (help_text.DATA_LOCATION_CONFIG_LABEL, locations.config_path),
                (
                    help_text.DATA_LOCATION_SPOTIFY_TOKEN_LABEL,
                    locations.spotify_token_path,
                ),
                (help_text.DATA_LOCATION_SLSKD_LABEL, locations.slskd_data_dir),
                (help_text.DATA_LOCATION_LOG_LABEL, locations.log_dir),
        ):
            path_label = QLabel(str(path))
            path_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            path_label.setWordWrap(True)
            locations_form.addRow(label_text, path_label)
        inner_layout.addLayout(locations_form)

        buttons_row = QHBoxLayout()

        open_folder_button = QPushButton(
                help_text.OPEN_DATA_FOLDER_BUTTON_TEXT
        )
        open_folder_button.setToolTip(help_text.TOOLTIP_OPEN_DATA_FOLDER)
        open_folder_button.clicked.connect(self._on_open_data_folder_clicked)
        buttons_row.addWidget(open_folder_button)

        open_log_folder_button = QPushButton(
                help_text.OPEN_LOG_FOLDER_BUTTON_TEXT
        )
        open_log_folder_button.setToolTip(help_text.TOOLTIP_OPEN_LOG_FOLDER)
        open_log_folder_button.clicked.connect(
            self._on_open_log_folder_clicked
        )
        buttons_row.addWidget(open_log_folder_button)

        buttons_row.addStretch()
        inner_layout.addLayout(buttons_row)

        inner_layout.addStretch()

        # Scrollable — the walkthrough + troubleshooting + data-location
        # sections together are genuinely longer than this app's
        # 960x640 minimum window (HISTORY §48), unlike every other page.
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setWidget(inner)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(scroll_area)

        page = build_page("Help", help_text.HELP_PAGE_SUBTITLE, content)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

    def _on_open_data_folder_clicked(self) -> None:
        _open_in_file_manager(self._context.application.data_locations.base_dir)

    def _on_open_log_folder_clicked(self) -> None:
        _open_in_file_manager(self._context.application.data_locations.log_dir)


class SupportPage(QWidget):
    def __init__(self, context: PageContext):
        super().__init__()
        self._context = context

        # A real sidebar page, directly below Help (HISTORY §64). Every
        # string here is entirely static copy (no service/DB call at
        # all, unlike Duplicates/History) — built directly at
        # construction time, same "nothing to lazily load" reasoning as
        # HelpPage's own Application.data_locations lookup above, just
        # with even less to fetch here.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING_LG)

        framing_label = QLabel(help_text.SUPPORT_PAGE_FRAMING_BODY)
        framing_label.setTextFormat(Qt.TextFormat.RichText)
        framing_label.setWordWrap(True)
        layout.addWidget(framing_label)

        layout.addLayout(build_support_links_row())

        non_financial_heading = QLabel(
            help_text.SUPPORT_PAGE_NON_FINANCIAL_HEADING
        )
        non_financial_heading.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(non_financial_heading)

        report_bug_label = QLabel(help_text.SUPPORT_PAGE_REPORT_BUG_BODY)
        report_bug_label.setTextFormat(Qt.TextFormat.RichText)
        report_bug_label.setWordWrap(True)
        report_bug_label.setOpenExternalLinks(True)
        layout.addWidget(report_bug_label)

        share_library_label = QLabel(help_text.SUPPORT_PAGE_SHARE_LIBRARY_BODY)
        share_library_label.setTextFormat(Qt.TextFormat.RichText)
        share_library_label.setWordWrap(True)
        layout.addWidget(share_library_label)

        go_to_sharing_button = QPushButton(
            help_text.SUPPORT_PAGE_GO_TO_SHARING_BUTTON_TEXT
        )
        go_to_sharing_button.clicked.connect(
            lambda: context.navigate("sharing")
        )
        layout.addWidget(
            go_to_sharing_button, alignment=Qt.AlignmentFlag.AlignLeft,
        )

        author_label = QLabel(help_text.ABOUT_DIALOG_AUTHOR_LINE)
        author_label.setTextFormat(Qt.TextFormat.RichText)
        author_label.setWordWrap(True)
        author_label.setOpenExternalLinks(True)
        layout.addWidget(author_label)

        layout.addStretch()

        page = build_page(
            "Support", help_text.SUPPORT_TAB_SUBTITLE, content,
        )
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)
