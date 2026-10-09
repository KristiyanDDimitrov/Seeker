"""Standalone dialogs used across the shell — About, a
missing-destination prompt, and the three "review everything before it
happens" confirmations for rename/bulk-replace/bulk-resolve. Each is a
self-contained QDialog subclass with no MainWindow dependency.
"""

import contextlib
import html
import webbrowser
from importlib.metadata import version
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from seeker import _build_info
from seeker.audio.formats import AUDIO_EXTENSIONS
from seeker.destination_resolution import (
    InvalidDestinationSubfolderError,
    validate_destination_subfolder,
)
from seeker.files.sanitize import sanitize_path_component
from seeker.formatting import format_file_size
from seeker.library.duplicate_service import GroupResolutionPlan
from seeker.library.metadata_service import RenamePlan
from seeker.models.leftover_result import LeftoverListing
from seeker.models.library_location import LibraryLocation
from seeker.models.upgrade_review import UpgradeReviewDetails
from seeker.ui import help_text, theme
from seeker.ui.elided_text import ElidedTextDelegate, elide_list_items
from seeker.ui.plain_text import PlainLabel, RichLabel, plain_tooltip


def build_support_links_row() -> QHBoxLayout:
    # Shared between AboutDialog and the Support page — both render the
    # same real, filtered SUPPORT_LINKS set the same way, so this lives
    # once rather than as two copies of the identical loop.
    row = QHBoxLayout()
    for name, url in help_text.SUPPORT_LINKS.items():
        if not help_text.is_real_support_link(url):
            continue

        button = QPushButton(f"Support on {name}")
        button.setToolTip(help_text.TOOLTIP_SUPPORT_LINK)
        button.clicked.connect(
            lambda _=False, url=url: webbrowser.open(url)
        )
        row.addWidget(button)
    row.addStretch()
    return row


class AboutDialog(QDialog):
    """The Help menu's "About Seeker" entry — app description, real
    installed version (read from package metadata rather than a second
    hardcoded literal that could drift from pyproject.toml), and
    support-the-creator links (Help/About is one of two deliberate spots
    for those, not the daily-use Dashboard/Downloads/Review screens).
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(help_text.ABOUT_DIALOG_TITLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING_XL, theme.SPACING_LG,
            theme.SPACING_XL, theme.SPACING_LG,
        )
        layout.setSpacing(theme.SPACING_MD)

        try:
            installed_version = version("seeker")
        except Exception:
            # Package metadata isn't always available (e.g. a frozen
            # PyInstaller build without an installed dist-info) — the
            # dialog should still open, just without a version line.
            installed_version = None

        body = help_text.ABOUT_DIALOG_BODY
        if installed_version is not None:
            body += f"<p>Version {html.escape(installed_version)}</p>"
        build_identity = help_text.format_build_identity(
            _build_info.GIT_SHA, _build_info.GIT_DESCRIBE,
            _build_info.BUILT_AT,
        )
        body += (
            f"<p>{help_text.HELP_BUILD_IDENTITY_LABEL} "
            f"{html.escape(build_identity)}</p>"
        )

        text_label = RichLabel(body)
        text_label.setWordWrap(True)
        layout.addWidget(text_label)

        # setOpenExternalLinks(True) — Qt opens mailto:/https: links via
        # the OS default handler itself (QDesktopServices), no separate
        # webbrowser.open() wiring needed for a plain clickable label
        # (unlike the support buttons below, which need an explicit
        # click handler since they're QPushButtons, not link text).
        author_label = RichLabel(help_text.ABOUT_DIALOG_AUTHOR_LINE)
        author_label.setWordWrap(True)
        author_label.setOpenExternalLinks(True)
        layout.addWidget(author_label)

        license_label = RichLabel(help_text.ABOUT_DIALOG_LICENSE_LINE)
        license_label.setWordWrap(True)
        layout.addWidget(license_label)

        notices_label = RichLabel(help_text.ABOUT_DIALOG_THIRD_PARTY_NOTICES)
        notices_label.setWordWrap(True)
        # QLabel[badge="faint"] in theme.py.
        notices_label.setProperty("badge", "faint")
        layout.addWidget(notices_label)

        # SUPPORT_LINKS holds only real URLs (Revolut, PayPal) —
        # is_real_support_link() stays as a guard against a future
        # still-TODO placeholder never actually rendering as a dead,
        # non-URL button. Same webbrowser.open() mechanism the Spotify
        # OAuth flow already uses; no SDK, no embedded payment UI.
        # Shared with the Support page via build_support_links_row().
        layout.addLayout(build_support_links_row())

        close_row = QHBoxLayout()
        close_button = QPushButton("Close")
        close_button.setProperty("variant", "primary")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        close_row.addStretch()
        layout.addLayout(close_row)


class DestinationDialog(QDialog):
    """"No dead end" (HISTORY §50): shown instead of letting Download
    raise NoDestinationConfiguredError. Confirming it always persists a
    real destination somewhere (never a one-time, unpersisted choice —
    DownloadPlacement.resolve_destination is re-evaluated later, on a
    separate poll cycle, when the file actually completes, so nothing
    durable would be left for it to find otherwise) and then the caller
    continues straight into the real download.

    Reused (not a second dialog) for a SECOND, more common trigger: a
    playlist with no destination of its own AND a configured default
    that WOULD resolve. `initial_subfolder` lets the caller pre-fill
    with the real current fallback (rather than always the raw playlist
    name) so the default stays one click away, and
    `location_path_preview`/`_update_preview` shows the exact absolute
    path that choice resolves to, live, as the user changes either field
    — including whether it already exists and how many audio files are
    already there, since that's what turns "it downloaded into a folder
    I didn't choose" into an informed choice.
    """

    def __init__(
            self,
            parent: QWidget,
            playlist_name: str,
            locations: list[LibraryLocation],
            default_location_id: int | None,
            initial_subfolder: str | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(help_text.DESTINATION_DIALOG_TITLE)
        self._locations = locations

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING_LG, theme.SPACING_LG,
            theme.SPACING_LG, theme.SPACING_LG,
        )
        layout.setSpacing(theme.SPACING_MD)

        intro = PlainLabel(
            help_text.DESTINATION_DIALOG_INTRO.format(playlist=playlist_name)
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()

        self.location_combo = QComboBox()
        for location in locations:
            self.location_combo.addItem(location.name, location.id)
        form.addRow("Location:", self.location_combo)

        # Prefill: the configured default, else the only location if
        # there's exactly one — never left on an arbitrary first entry
        # when there's a real, obvious choice.
        preselect_id = default_location_id
        if preselect_id is None and len(locations) == 1:
            preselect_id = locations[0].id
        if preselect_id is not None:
            index = self.location_combo.findData(preselect_id)
            if index >= 0:
                self.location_combo.setCurrentIndex(index)

        # The playlist's own folder, named as the per-playlist default
        # rule names it ("240KM/H" becomes "240KM-H", one folder).
        self.subfolder_field = QLineEdit(
            initial_subfolder if initial_subfolder is not None
            else sanitize_path_component(playlist_name)
        )
        form.addRow("Subfolder:", self.subfolder_field)

        layout.addLayout(form)

        # A real, live-updating preview of exactly where confirming
        # would download to, and what's already there. Recomputed on
        # every relevant field change, not just once at open, so it
        # never goes stale while the user is still deciding.
        self.location_path_preview = PlainLabel()
        self.location_path_preview.setWordWrap(True)
        # QLabel[badge="muted"] in theme.py.
        self.location_path_preview.setProperty("badge", "muted")
        layout.addWidget(self.location_path_preview)

        self.location_combo.currentIndexChanged.connect(self._update_preview)
        self.subfolder_field.textChanged.connect(self._update_preview)

        self.remember_checkbox = QCheckBox("Remember this for this playlist")
        self.remember_checkbox.setChecked(True)
        self.remember_checkbox.setToolTip(plain_tooltip(
            help_text.TOOLTIP_REMEMBER_DESTINATION_CHECKBOX.format(
                playlist=playlist_name,
            )
        ))
        layout.addWidget(self.remember_checkbox)

        button_row = QHBoxLayout()
        self.confirm_button = QPushButton("Download")
        self.confirm_button.setProperty("variant", "primary")
        self.confirm_button.clicked.connect(self.accept)
        button_row.addWidget(self.confirm_button)
        button_row.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        # After confirm_button exists: an unsafe subfolder disables it.
        self._update_preview()

    def _resolved_path(self) -> Path | None:
        location_id = self.selected_location_id()
        location = next(
            (loc for loc in self._locations if loc.id == location_id), None,
        )
        if location is None:
            return None

        subfolder = self.selected_subfolder()
        path = Path(location.path)
        return path / subfolder if subfolder else path

    def _update_preview(self) -> None:
        try:
            path = self._resolved_path()
        except InvalidDestinationSubfolderError as error:
            self.location_path_preview.setText(str(error))
            self.confirm_button.setEnabled(False)
            return

        self.confirm_button.setEnabled(True)

        if path is None:
            self.location_path_preview.setText("")
            return

        exists = path.exists()
        audio_file_count: int | None = None

        if exists:
            # An unreadable folder shouldn't block the dialog — just
            # show the path itself without a file count (None).
            with contextlib.suppress(OSError):
                audio_file_count = sum(
                    1 for entry in path.iterdir()
                    if entry.is_file()
                    and entry.suffix.lower() in AUDIO_EXTENSIONS
                )

        self.location_path_preview.setText(
            help_text.format_destination_preview(
                str(path), exists, audio_file_count,
            )
        )

    def selected_location_id(self) -> int | None:
        data = self.location_combo.currentData()
        return int(data) if data is not None else None

    def selected_subfolder(self) -> str | None:
        """Exactly what set_destination will save. Raises
        InvalidDestinationSubfolderError for an unsafe subfolder, which
        the disabled Download button keeps from being confirmed."""
        return validate_destination_subfolder(self.subfolder_field.text())

    def remember_for_playlist(self) -> bool:
        return self.remember_checkbox.isChecked()


class RenamePreviewDialog(QDialog):
    """Every planned change, grouped by action, unchanged and refused
    tracks visible too. Nothing is written until the user explicitly
    clicks Rename — unlike tag-writing, which has no such gate, since
    renaming moves/replaces a file on disk and tag-writing never does.
    """

    def __init__(
            self,
            parent: QWidget,
            playlist_name: str,
            plans: list[RenamePlan],
    ):
        super().__init__(parent)
        self.setWindowTitle(help_text.RENAME_PREVIEW_DIALOG_TITLE)
        self.resize(640, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING_LG, theme.SPACING_LG,
            theme.SPACING_LG, theme.SPACING_LG,
        )
        layout.setSpacing(theme.SPACING_MD)

        intro = PlainLabel(
            f"'{playlist_name}': "
            + help_text.RENAME_PREVIEW_DIALOG_INTRO
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.renames = [p for p in plans if p.action == "rename"]
        self.collisions = [p for p in plans if p.action == "collision"]
        already_correct = [p for p in plans if p.action == "already_correct"]
        not_auto_matched = [
            p for p in plans if p.action == "not_auto_matched"
        ]
        refused = [
            p for p in plans if p.action in ("no_local_file", "error")
        ]

        list_widget = QListWidget()
        list_widget.setAlternatingRowColors(False)

        def add_section(heading: str, rows: list[RenamePlan]) -> None:
            if not rows:
                return

            header_item = QListWidgetItem(f"{heading} ({len(rows)})")
            font = header_item.font()
            font.setBold(True)
            header_item.setFont(font)
            header_item.setFlags(Qt.ItemFlag.NoItemFlags)
            list_widget.addItem(header_item)

            for plan in rows:
                # The location-relative path (e.g. "Neuro/Audio, REEBZ -
                # Tractor Beam.flac"), not just the basename: a
                # basename-only "Already correct" row for a file
                # elsewhere in the same library location was
                # indistinguishable from the file the user was actually
                # looking at (HISTORY §93). Absolute path stays
                # available as the tooltip for anyone who needs it.
                if (
                        plan.current_relative is not None
                        and plan.proposed_relative is not None
                ):
                    text = (
                        f"  {plan.current_relative}  →  "
                        f"{plan.proposed_relative}"
                    )
                elif plan.current_relative is not None:
                    text = f"  {plan.current_relative}"
                else:
                    text = f"  {plan.message or plan.track_id}"

                if plan.destination_note:
                    text = f"{text}\n    ⚠ {plan.destination_note}"

                item = QListWidgetItem(text)
                item.setFlags(Qt.ItemFlag.NoItemFlags)

                tooltip_parts = [
                    str(path) for path in (plan.current_path, plan.proposed_path)
                    if path is not None
                ]
                if tooltip_parts:
                    item.setToolTip(plain_tooltip("\n".join(tooltip_parts)))

                list_widget.addItem(item)

        add_section(
            help_text.RENAME_PREVIEW_SECTION_RENAME, self.renames,
        )
        add_section(
            help_text.RENAME_PREVIEW_SECTION_COLLISION, self.collisions,
        )
        add_section(
            help_text.RENAME_PREVIEW_SECTION_ALREADY_CORRECT,
            already_correct,
        )
        add_section(
            help_text.RENAME_PREVIEW_SECTION_NOT_AUTO_MATCHED,
            not_auto_matched,
        )
        add_section(
            help_text.RENAME_PREVIEW_SECTION_REFUSED, refused,
        )

        if list_widget.count() == 0:
            list_widget.addItem(help_text.RENAME_PREVIEW_NO_CHANGES)

        layout.addWidget(theme.make_card(list_widget), 1)

        button_row = QHBoxLayout()
        total_to_rename = len(self.renames) + len(self.collisions)
        self.confirm_button = QPushButton(f"Rename {total_to_rename} file(s)")
        self.confirm_button.setProperty("variant", "primary")
        self.confirm_button.setEnabled(total_to_rename > 0)
        self.confirm_button.clicked.connect(self.accept)
        button_row.addWidget(self.confirm_button)
        button_row.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)


class BulkReplaceUpgradesDialog(QDialog):
    """"Replace all" pending upgrades (HISTORY §88). Same shape as
    RenamePreviewDialog: every row named plainly, nothing applied until
    the user explicitly confirms — this is one of the two most
    destructive actions in the app (it can delete real old files), so it
    inherits the project's standing "never modify/delete a real user
    file without explicit confirmation" rule in full, via the "Delete
    the old files" checkbox below (default OFF)."""

    def __init__(
            self, parent: QWidget, upgrades: list[UpgradeReviewDetails],
    ):
        super().__init__(parent)
        self.setWindowTitle(help_text.BULK_REPLACE_UPGRADES_DIALOG_TITLE)
        self.resize(560, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING_LG, theme.SPACING_LG,
            theme.SPACING_LG, theme.SPACING_LG,
        )
        layout.setSpacing(theme.SPACING_MD)

        intro = PlainLabel(
            help_text.format_bulk_replace_upgrades_intro(len(upgrades))
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        list_widget = QListWidget()
        list_widget.setAlternatingRowColors(False)
        for details in upgrades:
            text = (
                f"{details.track.artist} - {details.track.title}  —  "
                f"{details.current_description} → "
                f"{details.quality_descriptor or 'unknown'}"
            )
            item = QListWidgetItem(text)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            list_widget.addItem(item)
        layout.addWidget(theme.make_card(list_widget), 1)

        self.delete_old_checkbox = QCheckBox("Delete the old files")
        self.delete_old_checkbox.setToolTip(
            help_text.TOOLTIP_BULK_DELETE_OLD_FILES_CHECKBOX
        )
        layout.addWidget(self.delete_old_checkbox)

        button_row = QHBoxLayout()
        self.confirm_button = QPushButton(
                f"Replace {len(upgrades)} upgrade(s)"
        )
        self.confirm_button.setProperty("variant", "primary")
        self.confirm_button.setEnabled(len(upgrades) > 0)
        self.confirm_button.clicked.connect(self.accept)
        button_row.addWidget(self.confirm_button)
        button_row.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)


class BulkResolveDuplicatesDialog(QDialog):
    """"Resolve all groups" (HISTORY §88). Lists REAL absolute paths of
    every file that would be deleted and every file that would be kept,
    since this deletes real user files — a bare count is not enough for
    this specific action. Groups already set to "Keep all" are never
    passed in here at all (skipped by the caller before this dialog is
    even built) — this dialog only ever shows groups that would actually
    change something."""

    def __init__(
            self,
            parent: QWidget,
            plans_with_labels: list[tuple[GroupResolutionPlan, str, list[str]]],
    ):
        super().__init__(parent)
        self.setWindowTitle(help_text.BULK_RESOLVE_DUPLICATES_DIALOG_TITLE)
        self.resize(640, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING_LG, theme.SPACING_LG,
            theme.SPACING_LG, theme.SPACING_LG,
        )
        layout.setSpacing(theme.SPACING_MD)

        total_files_to_delete = sum(
            len(plan.delete_local_file_ids) for plan, _, _ in plans_with_labels
        )
        intro = PlainLabel(
            help_text.format_bulk_resolve_duplicates_intro(
                len(plans_with_labels), total_files_to_delete,
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        list_widget = QListWidget()
        list_widget.setAlternatingRowColors(False)

        def add_line(text: str) -> None:
            item = QListWidgetItem(text)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            list_widget.addItem(item)

        for index, (_plan, keep_path, delete_paths) in enumerate(
                plans_with_labels, start=1,
        ):
            header_item = QListWidgetItem(f"Group {index}")
            font = header_item.font()
            font.setBold(True)
            header_item.setFont(font)
            header_item.setFlags(Qt.ItemFlag.NoItemFlags)
            list_widget.addItem(header_item)
            add_line(f"  Keep: {keep_path}")
            for delete_path in delete_paths:
                add_line(f"  Delete: {delete_path}")

        if list_widget.count() == 0:
            list_widget.addItem(help_text.BULK_RESOLVE_DUPLICATES_NO_GROUPS)

        layout.addWidget(theme.make_card(list_widget), 1)

        self.confirm_checkbox = QCheckBox(
            f"Permanently delete {total_files_to_delete} file(s)"
        )
        self.confirm_checkbox.setToolTip(
            help_text.TOOLTIP_BULK_DELETE_DUPLICATES_CHECKBOX
        )
        layout.addWidget(self.confirm_checkbox)

        button_row = QHBoxLayout()
        self.confirm_button = QPushButton(
            f"Resolve {len(plans_with_labels)} group(s)"
        )
        self.confirm_button.setProperty("variant", "danger")
        # Same two-step gate as the single-group Delete flow: the
        # checkbox is required before the button can do anything, not
        # just informational text next to it.
        self.confirm_button.setEnabled(False)
        has_plans = len(plans_with_labels) > 0
        self.confirm_checkbox.toggled.connect(
            lambda checked: self.confirm_button.setEnabled(checked and has_plans)
        )
        self.confirm_button.clicked.connect(self.accept)
        button_row.addWidget(self.confirm_button)
        button_row.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)


class LeftoverCleanupDialog(QDialog):
    """slskd's leftover files, each with its size and folder, before
    any is deleted. Nothing is deleted unless the user clicks Delete;
    the service then re-checks each file (`LeftoverService`)."""

    def __init__(self, parent: QWidget, listing: LeftoverListing):
        super().__init__(parent)
        self.setWindowTitle(help_text.LEFTOVER_CLEANUP_DIALOG_TITLE)
        self.resize(640, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING_LG, theme.SPACING_LG,
            theme.SPACING_LG, theme.SPACING_LG,
        )
        layout.setSpacing(theme.SPACING_MD)

        intro = PlainLabel(help_text.leftover_cleanup_intro(listing))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        list_widget = QListWidget()
        list_widget.setAlternatingRowColors(False)
        elide_list_items(list_widget)
        # Elided in the middle, so the file's name outlasts its folders.
        delegate = list_widget.itemDelegate()
        assert isinstance(delegate, ElidedTextDelegate)
        delegate.path_columns = frozenset({0})
        for file in listing.files:
            item = QListWidgetItem(
                f"{format_file_size(file.size)} · {file.relative_path}"
            )
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setToolTip(plain_tooltip(file.path))
            list_widget.addItem(item)
        layout.addWidget(theme.make_card(list_widget), 1)

        if listing.held_back:
            held_back = PlainLabel(
                help_text.leftover_held_back_text(listing.held_back)
            )
            held_back.setWordWrap(True)
            held_back.setProperty("badge", "muted")
            layout.addWidget(held_back)

        button_row = QHBoxLayout()
        self.confirm_button = QPushButton(
            help_text.leftover_confirm_text(listing)
        )
        self.confirm_button.setProperty("variant", "danger")
        self.confirm_button.setEnabled(bool(listing.files))
        self.confirm_button.clicked.connect(self.accept)
        button_row.addWidget(self.confirm_button)
        button_row.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.setDefault(True)
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)
