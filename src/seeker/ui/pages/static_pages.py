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
    QFrame,
    QLabel,
    QLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from seeker import _build_info
from seeker.ui import help_text, theme
from seeker.ui.dialogs import build_support_links_row
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.plain_text import PlainLabel, RichLabel


def _open_in_file_manager(path: Path) -> None:
    # Cross-platform "reveal in Finder/Explorer" — same
    # subprocess/best-effort spirit as soulseek/docker_setup.py's own OS calls,
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


def _section(title: str, *items: QWidget | QLayout) -> QVBoxLayout:
    """A section of a reading page: its title in the panel lettering,
    then `items`, closer to each other than to the next section."""
    layout = QVBoxLayout()
    layout.setSpacing(theme.SPACING_SM)
    heading = PlainLabel(title)
    heading.setObjectName("sectionHeaderLabel")
    layout.addWidget(heading)
    for item in items:
        if isinstance(item, QLayout):
            layout.addLayout(item)
        else:
            layout.addWidget(item)
    return layout


def _prose(label: QLabel) -> QLabel:
    label.setWordWrap(True)
    return label


class HelpPage(QWidget):
    def __init__(self, context: PageContext):
        super().__init__()
        self._context = context

        # Every value here is already resolved and local
        # (Application.data_locations, the build identity), so the page
        # builds at construction, with no worker.
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(theme.SPACING_LG)

        inner_layout.addLayout(_section(
            help_text.HELP_WALKTHROUGH_HEADING,
            _prose(RichLabel(help_text.HELP_WALKTHROUGH_BODY)),
        ))
        inner_layout.addLayout(_section(
            help_text.HELP_TROUBLESHOOTING_HEADING,
            _prose(RichLabel(help_text.HELP_TROUBLESHOOTING_BODY)),
        ))

        # Said in the app, not just in a doc (HISTORY §81): a "fix
        # didn't work on the other account" report is very often a
        # different-database report, not a different-behaviour one.
        inner_layout.addLayout(_section(
            help_text.HELP_DATA_LOCATIONS_HEADING,
            _prose(PlainLabel(help_text.HELP_DATA_LOCATIONS_INTRO)),
            _prose(PlainLabel(help_text.HELP_DATA_LOCATIONS_PER_ACCOUNT_NOTE)),
            self._build_locations_card(),
        ))

        open_folder_button = QPushButton(
                help_text.OPEN_DATA_FOLDER_BUTTON_TEXT
        )
        open_folder_button.setToolTip(help_text.TOOLTIP_OPEN_DATA_FOLDER)
        open_folder_button.clicked.connect(self._on_open_data_folder_clicked)

        open_log_folder_button = QPushButton(
                help_text.OPEN_LOG_FOLDER_BUTTON_TEXT
        )
        open_log_folder_button.setToolTip(help_text.TOOLTIP_OPEN_LOG_FOLDER)
        open_log_folder_button.clicked.connect(
            self._on_open_log_folder_clicked
        )
        inner_layout.addLayout(
            theme.action_row(open_folder_button, open_log_folder_button),
        )
        inner_layout.addStretch()

        # The walkthrough, troubleshooting and data locations together
        # are taller than the 960x640 minimum window (HISTORY §48).
        page = build_page(
            "Help", help_text.HELP_PAGE_SUBTITLE,
            theme.scrollable(theme.reading_column(inner)),
        )
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

    def _build_locations_card(self) -> QFrame:
        """Each data path, then the build, in one card: the two things
        a problem report needs. Next to the paths rather than only in
        About, since this page is where "which build is this?" starts
        (HISTORY §81)."""
        locations = self._context.application.data_locations
        build_identity = help_text.format_build_identity(
            _build_info.GIT_SHA, _build_info.GIT_DESCRIBE,
            _build_info.BUILT_AT,
        )
        rows = (
            (help_text.DATA_LOCATION_DATABASE_LABEL, str(locations.database_path)),
            (help_text.DATA_LOCATION_CONFIG_LABEL, str(locations.config_path)),
            (
                help_text.DATA_LOCATION_SPOTIFY_TOKEN_LABEL,
                str(locations.spotify_token_path),
            ),
            (help_text.DATA_LOCATION_SLSKD_LABEL, str(locations.slskd_data_dir)),
            (help_text.DATA_LOCATION_LOG_LABEL, str(locations.log_dir)),
            (help_text.HELP_BUILD_IDENTITY_LABEL, build_identity),
        )

        inner = QWidget()
        form = QFormLayout(inner)
        margin = theme.SPACING_MD
        form.setContentsMargins(margin, margin, margin, margin)
        form.setHorizontalSpacing(theme.SPACING_LG)
        form.setVerticalSpacing(theme.SPACING_SM)
        for label_text, value in rows:
            name_label = PlainLabel(label_text)
            name_label.setProperty("badge", "muted")
            value_label = PlainLabel(value)
            value_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            value_label.setWordWrap(True)
            form.addRow(name_label, value_label)
        return theme.make_card(inner)

    def _on_open_data_folder_clicked(self) -> None:
        _open_in_file_manager(self._context.application.data_locations.base_dir)

    def _on_open_log_folder_clicked(self) -> None:
        _open_in_file_manager(self._context.application.data_locations.log_dir)


class SupportPage(QWidget):
    def __init__(self, context: PageContext):
        super().__init__()
        self._context = context

        # Static copy, built at construction, like Help.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING_LG)

        artists_label = _prose(RichLabel(help_text.SUPPORT_PAGE_ARTISTS_BODY))
        layout.addLayout(_section(
            help_text.SUPPORT_PAGE_ARTISTS_HEADING, artists_label,
        ))

        layout.addLayout(_section(
            help_text.SUPPORT_PAGE_DONATE_HEADING,
            _prose(PlainLabel(help_text.SUPPORT_PAGE_DONATE_BODY)),
            build_support_links_row(),
        ))

        report_bug_label = _prose(
            RichLabel(help_text.SUPPORT_PAGE_REPORT_BUG_BODY),
        )
        report_bug_label.setOpenExternalLinks(True)

        go_to_sharing_button = QPushButton(
            help_text.SUPPORT_PAGE_GO_TO_SHARING_BUTTON_TEXT
        )
        go_to_sharing_button.clicked.connect(
            lambda: context.navigate("sharing")
        )
        layout.addLayout(_section(
            help_text.SUPPORT_PAGE_NON_FINANCIAL_HEADING,
            report_bug_label,
            _prose(RichLabel(help_text.SUPPORT_PAGE_SHARE_LIBRARY_BODY)),
            theme.action_row(go_to_sharing_button),
        ))

        author_label = _prose(RichLabel(help_text.ABOUT_DIALOG_AUTHOR_LINE))
        author_label.setOpenExternalLinks(True)
        author_label.setProperty("badge", "muted")
        layout.addWidget(author_label)

        layout.addStretch()

        page = build_page(
            "Support", help_text.SUPPORT_TAB_SUBTITLE,
            theme.reading_column(content),
        )
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)
