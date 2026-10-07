"""The Tagging panel (HISTORY §119). Not itself a top-level page
registered on the shell's QStackedWidget — it is the sole content of
`library_page.py`, which owns its own status_label/notice widgets. The
playlist/track selection it acts on is read straight off
`PageContext.playlist_selection` (HISTORY §133); the narrower seam it
needs beyond PageContext, `TaggingPanelHost`, is only its own widgets
plus `refresh_track_table`, an action, not selection state.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from seeker.library.metadata_service import RenamePlan, RenameResult
from seeker.models.spotify_sync import TrackSyncResult
from seeker.models.tag_result import FixArtResult, TagResult
from seeker.ui import help_text, theme
from seeker.ui.dialogs import RenamePreviewDialog
from seeker.ui.notice import FeedbackTarget, InlineNotice
from seeker.ui.pages.context import PageContext
from seeker.ui.plain_text import PlainLabel
from seeker.ui.tag_result_panel import (
    TagResultPanel,
    summarize_fix_art_result,
    summarize_rename_result,
    summarize_tag_result,
)
from seeker.ui.workers import run_worker


def _action_group(
        title: str, explanation: str, *buttons: QPushButton,
) -> QGroupBox:
    """One job's actions under its title, after one sentence saying
    what they do."""
    group = QGroupBox(title)
    layout = QVBoxLayout(group)
    label = PlainLabel(explanation)
    label.setWordWrap(True)
    layout.addWidget(label)
    layout.addLayout(theme.action_row(*buttons))
    return group


@dataclass(frozen=True)
class TaggingPanelHost:
    """What the Tagging panel needs beyond PageContext: its own
    `status_label`/`notice` (real widget references, like PageContext's
    own `thread_pool`/`busy_actions` — they never get reassigned, so a
    direct reference is enough, and they're LibraryPage's own widgets,
    not Dashboard's), plus `refresh_track_table`, which has to be a
    callable rather than a value captured once at construction time."""
    status_label: QLabel
    notice: InlineNotice
    refresh_track_table: Callable[[], None]

    @property
    def feedback(self) -> FeedbackTarget:
        return FeedbackTarget(self.status_label, self.notice)


class TaggingPanel(QWidget):
    def __init__(self, context: PageContext, host: TaggingPanelHost):
        super().__init__()
        self._context = context
        self._host = host

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tagging_controls_layout = self._build_tagging_controls()
        layout.addLayout(self.tagging_controls_layout)

        # Retry only makes a real tag_tracks([track_id]) call for
        # tag-result failures (see TagResultPanel's own docstring for
        # why fix-art/rename results don't get one).
        self.results_panel = TagResultPanel(
            on_retry_track=self.retag_track,
        )
        layout.addWidget(self.results_panel)

    def _build_tagging_controls(self) -> QVBoxLayout:
        controls = QVBoxLayout()
        controls.setSpacing(theme.SPACING_MD)

        # One set of options shared by all three tag triggers
        # (per-track, "Tag selected", "Tag playlist"), never three
        # copies. --bpm-range requiring --analyze-audio (the CLI's own
        # validation) is enforced structurally: the range fields are
        # hidden while the checkbox is unchecked.
        self.analyze_audio_checkbox = QCheckBox("Analyze audio (BPM/Key)")
        self.analyze_audio_checkbox.setToolTip(
            help_text.TOOLTIP_ANALYZE_AUDIO_CHECKBOX
        )
        self.analyze_audio_checkbox.toggled.connect(
            self._on_analyze_audio_toggled
        )

        self.bpm_min_edit = QLineEdit()
        self.bpm_min_edit.setPlaceholderText("Min BPM")
        self.bpm_min_edit.setToolTip(help_text.TOOLTIP_BPM_MIN)
        self.bpm_min_edit.hide()

        self.bpm_max_edit = QLineEdit()
        self.bpm_max_edit.setPlaceholderText("Max BPM")
        self.bpm_max_edit.setToolTip(help_text.TOOLTIP_BPM_MAX)
        self.bpm_max_edit.hide()

        self.force_retag_checkbox = QCheckBox("Re-tag already tagged files")
        self.force_retag_checkbox.setToolTip(
            help_text.TOOLTIP_FORCE_RETAG_CHECKBOX
        )

        options = QGroupBox("Tag Options")
        options_layout = QVBoxLayout(options)
        options_layout.addLayout(theme.action_row(
            self.analyze_audio_checkbox, self.bpm_min_edit, self.bpm_max_edit,
        ))
        options_layout.addWidget(self.force_retag_checkbox)
        controls.addWidget(options)

        self.tag_selected_button = QPushButton("Tag selected")
        self.tag_selected_button.setToolTip(help_text.TOOLTIP_TAG_SELECTED)
        self.tag_selected_button.clicked.connect(
            self._on_tag_selected_clicked
        )

        self.tag_playlist_button = QPushButton("Tag playlist")
        self.tag_playlist_button.setToolTip(help_text.TOOLTIP_TAG_PLAYLIST)
        self.tag_playlist_button.clicked.connect(
            self._on_tag_playlist_clicked
        )

        controls.addWidget(_action_group(
            "Tags", help_text.LIBRARY_TAGS_TEXT,
            self.tag_selected_button, self.tag_playlist_button,
        ))

        # A narrower, safer repair than forcing a full re-tag: re-embeds
        # art only, never text tags (HISTORY §66).
        self.fix_missing_art_button = QPushButton("Fix missing cover art")
        self.fix_missing_art_button.setToolTip(
            help_text.TOOLTIP_FIX_MISSING_ART
        )
        self.fix_missing_art_button.clicked.connect(
            self._on_fix_missing_art_clicked
        )

        # The one-click fix for the "no_url" case: a real sync-tracks
        # call, honest about being a real Spotify API call (HISTORY §66).
        self.fill_missing_art_urls_button = QPushButton(
            "Get cover art from Spotify"
        )
        self.fill_missing_art_urls_button.setToolTip(
            help_text.TOOLTIP_FILL_MISSING_ART_URLS
        )
        self.fill_missing_art_urls_button.clicked.connect(
            self._on_fill_missing_art_urls_clicked
        )

        controls.addWidget(_action_group(
            "Cover Art", help_text.LIBRARY_COVER_ART_TEXT,
            self.fix_missing_art_button, self.fill_missing_art_urls_button,
        ))

        # Always a preview first (HISTORY §67) — HISTORY §27's "no gate
        # for tag-writing" precedent does NOT extend here: this
        # moves/replaces a real file.
        self.rename_files_button = QPushButton(
                "Rename files to match metadata"
        )
        self.rename_files_button.setToolTip(help_text.TOOLTIP_RENAME_FILES)
        self.rename_files_button.clicked.connect(
            self._on_rename_files_clicked
        )

        controls.addWidget(_action_group(
            "File Names", help_text.LIBRARY_FILE_NAMES_TEXT,
            self.rename_files_button,
        ))

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

    def _render_tag_result(
            self,
            result: TagResult,
            feedback: FeedbackTarget | None = None,
    ) -> None:
        feedback = feedback or self._host.feedback
        feedback.status_label.setText("")

        self.results_panel.set_result(
            summarize_tag_result(result), result.details,
            retryable_reason="failed",
        )

        # The UI must never show a bare "success" when any part of it
        # wasn't: routed through InlineNotice (HISTORY §47), not
        # status_label, so it survives the next 2s poll tick; per-track
        # detail is already reachable in the persistent results_panel
        # above, itself unaffected by that same clearing bug (a real
        # widget, never wired into status_label's plumbing at all)
        # (HISTORY §56).
        self._show_tag_result_notice(result, feedback)

    def _show_tag_result_notice(
            self,
            result: TagResult,
            feedback: FeedbackTarget,
    ) -> None:
        # This early return is still correct (nothing was even in
        # scope), but every real outcome AFTER it — including "every
        # selected track was already tagged" — now gets a message via
        # help_text.format_tag_result_notice, not just tagged/without_
        # art/failed (HISTORY §75).
        if result.tagged == 0 and not result.details:
            return

        message, kind = help_text.format_tag_result_notice(result)

        # Any track this run skipped as already-tagged had its cover
        # art never even looked at (see format_tag_result_notice's own
        # docstring); offer the real next action right on the notice
        # rather than leaving the user to find "Fix missing cover art"
        # on their own (HISTORY §75).
        if result.skipped_already_tagged > 0:
            feedback.notice.show_message(
                message, kind=kind,
                action_text="Fix missing cover art",
                on_action=lambda: self._fix_missing_art(feedback),
            )
        else:
            feedback.notice.show_message(message, kind=kind)

    # Called directly by the Dashboard's own track_table row
    # Actions-column button (`_build_track_actions`, still in
    # main_window.py — the track_table itself hasn't moved) — same
    # "reach the private method on the page/panel object directly"
    # pattern History/Sharing already established for a cross-widget
    # call, not a public rename.
    def tag_track(
            self,
            track_id: str,
            button: QPushButton,
            feedback: FeedbackTarget | None = None,
    ) -> None:
        target = feedback or self._host.feedback

        try:
            analyze_audio, bpm_range, force = self._resolve_tag_options()
        except ValueError as error:
            target.show_error(str(error))
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
            on_finished=lambda result: self._render_tag_result(result, target),
            on_error=target.show_error,
        )

    # Called directly by the Dashboard's own track_table context menu
    # (`_on_track_table_context_menu`, still in main_window.py) — same
    # cross-widget "private method" call as `tag_track`.
    def retag_track(
            self,
            track_id: str,
            feedback: FeedbackTarget | None = None,
    ) -> None:
        # The context menu's "Re-tag" always forces, independent of the
        # tagging panel's own checkbox — right-clicking a specific
        # already-tagged row and choosing "Re-tag" is an explicit,
        # unambiguous request to redo exactly this one file, the same
        # way the CLI's --force does for a whole playlist.
        target = feedback or self._host.feedback

        try:
            analyze_audio, bpm_range, _ = self._resolve_tag_options()
        except ValueError as error:
            target.show_error(str(error))
            return

        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.metadata_service.tag_tracks(
                [track_id],
                analyze_audio=analyze_audio,
                expected_bpm_range=bpm_range,
                force=True,
            ),
            on_finished=lambda result: self._render_tag_result(result, target),
            on_error=target.show_error,
        )

    def _on_tag_selected_clicked(self) -> None:
        track_ids = self._context.playlist_selection.track_ids

        if not track_ids:
            self._host.notice.show_message(
                "Select at least one track first.", kind="warning",
            )
            return

        try:
            analyze_audio, bpm_range, force = self._resolve_tag_options()
        except ValueError as error:
            self._host.notice.show_message(str(error), kind="error")
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
        self.tag_playlist(self._host.feedback)

    def tag_playlist(self, feedback: FeedbackTarget) -> None:
        playlist = self._context.playlist_selection.playlist

        if playlist is None:
            feedback.notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        try:
            analyze_audio, bpm_range, force = self._resolve_tag_options()
        except ValueError as error:
            feedback.show_error(str(error))
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
            on_finished=lambda result: self._render_tag_result(
                result, feedback,
            ),
            on_error=feedback.show_error,
        )
        feedback.show_progress(f"Tagging playlist '{playlist_name}'...")

    def _on_fix_missing_art_clicked(self) -> None:
        self._fix_missing_art(self._host.feedback)

    def _fix_missing_art(self, feedback: FeedbackTarget) -> None:
        playlist = self._context.playlist_selection.playlist

        if playlist is None:
            feedback.notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        playlist_name = playlist.name

        self._context.run_busy_worker(
            "fix_missing_art", self.fix_missing_art_button,
            lambda: self._context.application.metadata_service
            .fix_missing_art_for_playlist(playlist_name),
            on_finished=lambda result: self._render_fix_art_result(
                result, feedback,
            ),
            on_error=feedback.show_error,
        )
        feedback.show_progress(f"Fixing cover art for '{playlist_name}'...")

    def _render_fix_art_result(
            self,
            result: FixArtResult,
            feedback: FeedbackTarget,
    ) -> None:
        self.results_panel.set_result(
            summarize_fix_art_result(result), result.details,
        )

        message, kind = help_text.format_fix_art_result_message(result)
        feedback.show_outcome(message, kind=kind)

    def _on_fill_missing_art_urls_clicked(self) -> None:
        playlist = self._context.playlist_selection.playlist

        if playlist is None:
            self._host.notice.show_message(
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

    def _on_fill_missing_art_urls_finished(
            self, result: TrackSyncResult,
    ) -> None:
        self._host.refresh_track_table()
        art_urls_filled = result.art_urls_filled

        if art_urls_filled:
            plural = "s" if art_urls_filled != 1 else ""
            self._host.notice.show_message(
                f"Found cover art on Spotify for {art_urls_filled} "
                f"track{plural}. Fix missing cover art adds it to the "
                f"files.",
                kind="success",
            )
        else:
            self._host.notice.show_message(
                "No track was missing cover art on Spotify.", kind="info",
            )

    def _on_rename_files_clicked(self) -> None:
        playlist = self._context.playlist_selection.playlist

        if playlist is None:
            self._host.notice.show_message(
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

    def _on_rename_files_finished(self, result: RenameResult) -> None:
        self._reset_rename_files_button()
        self._host.refresh_track_table()

        self.results_panel.set_result(
            summarize_rename_result(result), result.details,
        )

        message, kind = help_text.format_rename_result_message(result)
        self._host.notice.show_message(message, kind=kind)
