"""The Tagging panel — round 8 Phase 6 (§9.3.1), moved verbatim out of
main_window.py. Unlike every other module in this package, this is not
a top-level page registered on the shell's QStackedWidget — it is a
sub-widget embedded inside the (still-unmigrated) Dashboard page, so it
needs a second, narrower seam beyond PageContext: `TaggingPanelHost`,
exactly the pieces of Dashboard state (its selected-playlist, its own
status_label/notice widgets, resolving the track table's current
selection) this panel reaches into. Found necessary the same way
PageContext's own extra fields were: by grepping every method being
moved for what it actually touches before assuming a clean lift.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from seeker.library.metadata_service import RenamePlan
from seeker.models.playlist import Playlist
from seeker.ui import help_text, theme
from seeker.ui.dialogs import RenamePreviewDialog
from seeker.ui.flow_layout import FlowLayout
from seeker.ui.notice import InlineNotice
from seeker.ui.pages.context import PageContext
from seeker.ui.workers import run_worker


@dataclass(frozen=True)
class TaggingPanelHost:
    """What the Tagging panel needs from the Dashboard that hosts it.
    `status_label`/`dashboard_notice` are real widget references (like
    PageContext's own `thread_pool`/`busy_actions` — they never get
    reassigned, so a direct reference is enough); the rest are live
    reads/actions on Dashboard's own mutable state, so they have to be
    callables, not values captured once at construction time."""
    status_label: QLabel
    dashboard_notice: InlineNotice
    get_selected_playlist: Callable[[], Playlist | None]
    get_selected_track_ids: Callable[[], list[str]]
    refresh_track_table: Callable[[], None]


class TaggingPanel(QWidget):
    def __init__(self, context: PageContext, host: TaggingPanelHost):
        super().__init__()
        self._context = context
        self._host = host

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tagging_controls_layout = self._build_tagging_controls()
        layout.addLayout(self.tagging_controls_layout)

        self.tagging_results = QPlainTextEdit()
        self.tagging_results.setReadOnly(True)
        self.tagging_results.setMaximumHeight(120)
        self.tagging_results.setPlaceholderText(
            "Tagging results will appear here."
        )
        layout.addWidget(self.tagging_results)

    def _build_tagging_controls(self) -> FlowLayout:
        # Shared by all three triggers (per-track, "Tag selected",
        # "Tag playlist") — one set of options, not three independently
        # configurable copies. --bpm-range requiring --analyze-audio
        # (the CLI's own validation) is enforced structurally here by
        # hiding the range fields entirely while the checkbox is
        # unchecked, rather than validating the combination after the
        # fact the way the CLI has to.
        #
        # Roadmap item 72 (P1) — a plain QHBoxLayout's minimum width is
        # the SUM of its children's minimum widths, which made this
        # 9-widget row impose a ~900-1000px floor on the whole
        # dashboard page, squeezing the playlist panel next to it down
        # to almost nothing. FlowLayout fixes both halves at once: it
        # reflows 1-row -> 2-row -> 3-row purely from available width,
        # and its own minimumSize() is just the widest single item.
        # Roadmap item 79 (P11) — bare FlowLayout() leaves h_spacing/
        # v_spacing at -1, which falls through to _smart_spacing()'s
        # PM_LayoutHorizontalSpacing style query — approximately zero
        # under this app's Fusion styling, so the buttons touched.
        # These are deliberate, chosen values, not style-derived ones.
        controls = FlowLayout(
            h_spacing=theme.SPACING_SM, v_spacing=theme.SPACING_SM,
        )

        self.analyze_audio_checkbox = QCheckBox("Analyze audio (BPM/Key)")
        self.analyze_audio_checkbox.setToolTip(
            help_text.TOOLTIP_ANALYZE_AUDIO_CHECKBOX
        )
        self.analyze_audio_checkbox.toggled.connect(
            self._on_analyze_audio_toggled
        )
        controls.addWidget(self.analyze_audio_checkbox)

        self.bpm_min_edit = QLineEdit()
        self.bpm_min_edit.setPlaceholderText("Min BPM")
        self.bpm_min_edit.setToolTip(help_text.TOOLTIP_BPM_MIN)
        self.bpm_min_edit.hide()
        controls.addWidget(self.bpm_min_edit)

        self.bpm_max_edit = QLineEdit()
        self.bpm_max_edit.setPlaceholderText("Max BPM")
        self.bpm_max_edit.setToolTip(help_text.TOOLTIP_BPM_MAX)
        self.bpm_max_edit.hide()
        controls.addWidget(self.bpm_max_edit)

        self.force_retag_checkbox = QCheckBox("Re-tag already tagged files")
        self.force_retag_checkbox.setToolTip(
            help_text.TOOLTIP_FORCE_RETAG_CHECKBOX
        )
        controls.addWidget(self.force_retag_checkbox)

        self.tag_selected_button = QPushButton("Tag selected")
        self.tag_selected_button.setToolTip(help_text.TOOLTIP_TAG_SELECTED)
        self.tag_selected_button.clicked.connect(
            self._on_tag_selected_clicked
        )
        controls.addWidget(self.tag_selected_button)

        self.tag_playlist_button = QPushButton("Tag playlist")
        self.tag_playlist_button.setToolTip(help_text.TOOLTIP_TAG_PLAYLIST)
        self.tag_playlist_button.clicked.connect(
            self._on_tag_playlist_clicked
        )
        controls.addWidget(self.tag_playlist_button)

        # Roadmap item 66 (Phase 5.2) — a narrower, safer repair than
        # forcing a full re-tag: re-embeds art only, never text tags.
        self.fix_missing_art_button = QPushButton("Fix missing cover art")
        self.fix_missing_art_button.setToolTip(
            help_text.TOOLTIP_FIX_MISSING_ART
        )
        self.fix_missing_art_button.clicked.connect(
            self._on_fix_missing_art_clicked
        )
        controls.addWidget(self.fix_missing_art_button)

        # Roadmap item 66 (Phase 5.3) — the one-click fix for the
        # "no_url" case: a real sync-tracks call, honest about being a
        # real Spotify API call.
        self.fill_missing_art_urls_button = QPushButton(
            "Fill missing art URLs"
        )
        self.fill_missing_art_urls_button.setToolTip(
            help_text.TOOLTIP_FILL_MISSING_ART_URLS
        )
        self.fill_missing_art_urls_button.clicked.connect(
            self._on_fill_missing_art_urls_clicked
        )
        controls.addWidget(self.fill_missing_art_urls_button)

        # Roadmap item 67 (Phase 6.4) — always a preview first (item
        # 27's "no gate for tag-writing" precedent does NOT extend
        # here: this moves/replaces a real file).
        self.rename_files_button = QPushButton(
                "Rename files to match metadata"
        )
        self.rename_files_button.setToolTip(help_text.TOOLTIP_RENAME_FILES)
        self.rename_files_button.clicked.connect(
            self._on_rename_files_clicked
        )
        controls.addWidget(self.rename_files_button)

        return controls

    def _on_analyze_audio_toggled(self, checked: bool) -> None:
        self.bpm_min_edit.setVisible(checked)
        self.bpm_max_edit.setVisible(checked)

    def _resolve_tag_options(
            self,
    ) -> tuple[bool, tuple[float, float] | None, bool]:
        force = self.force_retag_checkbox.isChecked()
        analyze_audio = self.analyze_audio_checkbox.isChecked()

        if not analyze_audio:
            return False, None, force

        min_text = self.bpm_min_edit.text().strip()
        max_text = self.bpm_max_edit.text().strip()

        if not min_text and not max_text:
            # A range is optional even with analysis on — matches the
            # CLI, where --analyze-audio alone (no --bpm-range) is
            # perfectly valid.
            return True, None, force

        if not min_text or not max_text:
            raise ValueError(
                "Enter both a min and max BPM, or leave both blank."
            )

        try:
            return True, (float(min_text), float(max_text)), force
        except ValueError as error:
            raise ValueError("BPM range must be numeric.") from error

    def _render_tag_result(self, result: dict[str, Any]) -> None:
        self._host.status_label.setText("")

        lines = [
            f"Tagged: {result['tagged']} "
            f"({result['tagged_without_art']} without cover art, "
            f"{result['tagged_art_rarely_supported_format']} with art "
            f"in a rarely-supported format), "
            f"Skipped (no match): {result['skipped_no_match']}, "
            f"Skipped (unsupported format): "
            f"{result['skipped_format_unsupported']}, "
            f"Skipped (already tagged): "
            f"{result['skipped_already_tagged']}, "
            f"Skipped (already analyzed): "
            f"{result['skipped_already_analyzed']}, "
            f"Failed: {result['failed']}."
        ]

        for detail in result["details"]:
            lines.append(f"  [{detail['reason']}] {detail['message']}")

        self.tagging_results.setPlainText("\n".join(lines))

        # Roadmap item 56 Phase 4.2 — the UI must never show a bare
        # "success" when any part of it wasn't: routed through
        # InlineNotice (item 47), not status_label, so it survives the
        # next 2s poll tick; per-track detail is already reachable in
        # the persistent tagging_results panel above, itself unaffected
        # by that same clearing bug (a real QPlainTextEdit, never wired
        # into status_label's plumbing at all).
        self._show_tag_result_notice(result)

    def _show_tag_result_notice(self, result: dict[str, Any]) -> None:
        # Roadmap item 66 (Phase 5.1) — the real gap found in Phase 0.4:
        # this early return is still correct (nothing was even in
        # scope), but every real outcome AFTER it — including "every
        # selected track was already tagged" — now gets a message via
        # help_text.format_tag_result_notice, not just tagged/without_
        # art/failed.
        if result["tagged"] == 0 and not result["details"]:
            return

        message, kind = help_text.format_tag_result_notice(result)

        # Roadmap item 75 (P6, 6.2) — any track this run skipped as
        # already-tagged had its cover art never even looked at (see
        # format_tag_result_notice's own docstring); offer the real
        # next action right on the notice rather than leaving the user
        # to find "Fix missing cover art" on their own.
        if result.get("skipped_already_tagged", 0) > 0:
            self._host.dashboard_notice.show_message(
                message, kind=kind,
                action_text="Fix missing cover art",
                on_action=self._on_fix_missing_art_clicked,
            )
        else:
            self._host.dashboard_notice.show_message(message, kind=kind)

    # Called directly by the Dashboard's own track_table row
    # Actions-column button (`_build_track_actions`, still in
    # main_window.py — the track_table itself hasn't moved) — same
    # "reach the private method on the page/panel object directly"
    # pattern History/Sharing already established for a cross-widget
    # call, not a public rename.
    def _on_tag_track_clicked(
            self,
            track_id: str,
            button: QPushButton,
    ) -> None:
        try:
            analyze_audio, bpm_range, force = self._resolve_tag_options()
        except ValueError as error:
            self._host.dashboard_notice.show_message(str(error), kind="error")
            return

        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.metadata_service.tag_tracks(
                [track_id],
                analyze_audio=analyze_audio,
                expected_bpm_range=bpm_range,
                force=force,
            ),
            button=button,
            status_label=self._host.status_label,
            on_finished=self._render_tag_result,
        )

    # Called directly by the Dashboard's own track_table context menu
    # (`_on_track_table_context_menu`, still in main_window.py) — same
    # cross-widget "private method" call as `_on_tag_track_clicked`.
    def _on_retag_track_clicked(self, track_id: str) -> None:
        # The context menu's "Re-tag" always forces, independent of the
        # tagging panel's own checkbox — right-clicking a specific
        # already-tagged row and choosing "Re-tag" is an explicit,
        # unambiguous request to redo exactly this one file, the same
        # way the CLI's --force does for a whole playlist.
        try:
            analyze_audio, bpm_range, _ = self._resolve_tag_options()
        except ValueError as error:
            self._host.dashboard_notice.show_message(str(error), kind="error")
            return

        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.metadata_service.tag_tracks(
                [track_id],
                analyze_audio=analyze_audio,
                expected_bpm_range=bpm_range,
                force=True,
            ),
            status_label=self._host.status_label,
            on_finished=self._render_tag_result,
        )

    def _on_tag_selected_clicked(self) -> None:
        track_ids = self._host.get_selected_track_ids()

        if not track_ids:
            self._host.dashboard_notice.show_message(
                "Select at least one track first.", kind="warning",
            )
            return

        try:
            analyze_audio, bpm_range, force = self._resolve_tag_options()
        except ValueError as error:
            self._host.dashboard_notice.show_message(str(error), kind="error")
            return

        self._context.run_busy_worker(
            "tag_selected", self.tag_selected_button,
            lambda: self._context.application.metadata_service.tag_tracks(
                track_ids,
                analyze_audio=analyze_audio,
                expected_bpm_range=bpm_range,
                force=force,
            ),
            status_label=self._host.status_label,
            on_finished=self._render_tag_result,
        )
        # Analysis in particular does real, potentially slow per-track
        # work — an in-progress note beyond just the disabled button,
        # for anything wider than a single track.
        self._host.status_label.setText(
                f"Tagging {len(track_ids)} selected track(s)..."
        )

    def _on_tag_playlist_clicked(self) -> None:
        playlist = self._host.get_selected_playlist()

        if playlist is None:
            self._host.dashboard_notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        try:
            analyze_audio, bpm_range, force = self._resolve_tag_options()
        except ValueError as error:
            self._host.dashboard_notice.show_message(str(error), kind="error")
            return

        playlist_name = playlist.name

        self._context.run_busy_worker(
            "tag_playlist", self.tag_playlist_button,
            lambda: self._context.application.metadata_service.tag_playlist(
                playlist_name,
                analyze_audio=analyze_audio,
                expected_bpm_range=bpm_range,
                force=force,
            ),
            status_label=self._host.status_label,
            on_finished=self._render_tag_result,
        )
        self._host.status_label.setText(
            f"Tagging playlist '{playlist_name}'..."
        )

    def _on_fix_missing_art_clicked(self) -> None:
        playlist = self._host.get_selected_playlist()

        if playlist is None:
            self._host.dashboard_notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        playlist_name = playlist.name

        self._context.run_busy_worker(
            "fix_missing_art", self.fix_missing_art_button,
            lambda: self._context.application.metadata_service
            .fix_missing_art_for_playlist(playlist_name),
            status_label=self._host.status_label,
            on_finished=self._render_fix_art_result,
        )
        self._host.status_label.setText(
            f"Fixing cover art for '{playlist_name}'..."
        )

    def _render_fix_art_result(self, result: dict[str, Any]) -> None:
        self._host.status_label.setText("")

        lines = [
            f"Fixed: {result['fixed']}, "
            f"Fixed (rarely-supported format): "
            f"{result['fixed_wav_rarely_supported']}, "
            f"Already correct: {result['already_correct']}, "
            f"No art URL: {result['no_url']}, "
            f"Download failed: {result['download_failed']}, "
            f"Embed failed: {result['embed_failed']}, "
            f"Unsupported format: {result['format_unsupported']}, "
            f"Skipped (no match): {result['skipped_no_match']}, "
            f"Failed: {result['failed']}."
        ]

        for detail in result["details"]:
            lines.append(f"  [{detail['reason']}] {detail['message']}")

        self.tagging_results.setPlainText("\n".join(lines))

        message, kind = help_text.format_fix_art_result_message(result)
        self._host.dashboard_notice.show_message(message, kind=kind)

    def _on_fill_missing_art_urls_clicked(self) -> None:
        playlist = self._host.get_selected_playlist()

        if playlist is None:
            self._host.dashboard_notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        self._context.run_busy_worker(
            "fill_missing_art_urls", self.fill_missing_art_urls_button,
            lambda: self._context.application.sync_service
            .sync_playlist_tracks(playlist),
            status_label=self._host.status_label,
            on_finished=self._on_fill_missing_art_urls_finished,
        )
        self._host.status_label.setText(
            f"Refreshing '{playlist.name}' from Spotify..."
        )

    def _on_fill_missing_art_urls_finished(self, art_urls_filled: int) -> None:
        self._host.refresh_track_table()

        if art_urls_filled:
            plural = "s" if art_urls_filled != 1 else ""
            self._host.dashboard_notice.show_message(
                f"Filled in {art_urls_filled} missing album art "
                f"URL{plural}.",
                kind="success",
            )
        else:
            self._host.dashboard_notice.show_message(
                "No missing album art URLs found.", kind="info",
            )

    def _on_rename_files_clicked(self) -> None:
        playlist = self._host.get_selected_playlist()

        if playlist is None:
            self._host.dashboard_notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        playlist_name = playlist.name

        self._context.run_busy_worker(
            "rename_files", self.rename_files_button,
            lambda: self._context.application.metadata_service.plan_renames(
                playlist_name=playlist_name,
            ),
            status_label=self._host.status_label,
            on_finished=lambda plans: self._open_rename_preview_dialog(
                playlist_name, plans,
            ),
        )

    def _open_rename_preview_dialog(
            self, playlist_name: str, plans: list[RenamePlan],
    ) -> None:
        dialog = RenamePreviewDialog(self, playlist_name, plans)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._context.busy_actions.begin(
            "rename_files", self.rename_files_button, "Renaming…",
        )
        self._context.render_activity_strip()

        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.metadata_service.apply_renames(
                plans
            ),
            status_label=self._host.status_label,
            on_finished=self._on_rename_files_finished,
            on_error=lambda _message: self._reset_rename_files_button(),
        )

    def _reset_rename_files_button(self) -> None:
        self._context.busy_actions.end("rename_files")
        self._context.render_activity_strip()

    def _on_rename_files_finished(self, result: Any) -> None:
        self._reset_rename_files_button()
        self._host.refresh_track_table()

        counts = {
            "renamed": result.renamed,
            "collisions": result.collisions,
            "failed": result.failed,
        }
        lines = [
            f"Renamed: {result.renamed} ({result.collisions} with a "
            f"numbered suffix), Already correct: {result.already_correct}, "
            f"Not auto-matched: {result.skipped_not_auto_matched}, "
            f"No local file: {result.skipped_no_local_file}, "
            f"Failed: {result.failed}."
        ]

        for detail in result.details:
            lines.append(f"  [{detail['reason']}] {detail['message']}")

        self.tagging_results.setPlainText("\n".join(lines))

        message, kind = help_text.format_rename_result_message(counts)
        self._host.dashboard_notice.show_message(message, kind=kind)
