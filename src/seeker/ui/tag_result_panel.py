"""TagResultPanel (round 8 §12.7) — replaces the old scrolling
QPlainTextEdit dump (`tagging_results`, tagging_panel.py) with a
one-line summary plus a collapsed-by-default expandable list of
per-item outcomes. Better information in less space: the summary
answers "did it work" at a glance, the details answer "which ones and
why" only for someone who asks.

Retry is only wired for `tag_tracks` failures — `tag_tracks([track_id],
...)` already exists and is exactly what a track row's own "Tag"
button calls, so a retry button here is a real, meaningful action.
Fix-missing-art and rename results have no single-track retry endpoint
in metadata_service (both are playlist-scoped operations), so their
detail rows stay read-only rather than offering a button that can't do
anything real.
"""

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from seeker.ui import theme


def summarize_tag_result(result: dict[str, Any]) -> str:
    total = (
        result["tagged"] + result["skipped_no_match"]
        + result["skipped_format_unsupported"]
        + result["skipped_already_tagged"]
        + result["skipped_already_analyzed"] + result["failed"]
    )
    line = f"Tagged {result['tagged']} of {total}"
    if result["failed"]:
        plural = "s" if result["failed"] != 1 else ""
        line += f" — {result['failed']} failed{plural}"
    return line


def summarize_fix_art_result(result: dict[str, Any]) -> str:
    total = (
        result["fixed"] + result["already_correct"] + result["no_url"]
        + result["download_failed"] + result["embed_failed"]
        + result["format_unsupported"] + result["skipped_no_match"]
        + result["failed"]
    )
    line = f"Fixed {result['fixed']} of {total}"
    real_failures = (
        result["download_failed"] + result["embed_failed"] + result["failed"]
    )
    if real_failures:
        plural = "s" if real_failures != 1 else ""
        line += f" — {real_failures} failed{plural}"
    return line


def summarize_rename_result(result: dict[str, Any]) -> str:
    total = (
        result["renamed"] + result["already_correct"]
        + result["skipped_not_auto_matched"] + result["skipped_no_local_file"]
        + result["failed"]
    )
    line = f"Renamed {result['renamed']} of {total}"
    if result["failed"]:
        plural = "s" if result["failed"] != 1 else ""
        line += f" — {result['failed']} failed{plural}"
    return line


class TagResultPanel(QWidget):
    def __init__(self, on_retry_track: Callable[[str], None] | None = None):
        super().__init__()
        self._on_retry_track = on_retry_track

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING_XS)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setProperty("badge", "muted")
        layout.addWidget(self.summary_label)

        self.details_toggle = QPushButton("Show details")
        self.details_toggle.setCheckable(True)
        self.details_toggle.setFlat(True)
        self.details_toggle.toggled.connect(self._on_toggle)
        self.details_toggle.hide()
        layout.addWidget(self.details_toggle)

        self.details_list = QListWidget()
        self.details_list.setMaximumHeight(160)
        # theme.make_card's own docstring: an edge-reaching child (the
        # per-row Retry button here) paints straight over a bare
        # QListWidget's rounded corner — every other list/table in this
        # app goes through this same wrapper (structural sweep test
        # test_every_table_and_list_goes_through_the_shared_chrome_
        # helpers enforces it). The CARD, not the list itself, is what
        # gets shown/hidden — hiding just the inner list would leave an
        # empty card frame visible.
        self._details_card = theme.make_card(self.details_list)
        self._details_card.hide()
        layout.addWidget(self._details_card)

    def _on_toggle(self, checked: bool) -> None:
        self._details_card.setVisible(checked)
        self.details_toggle.setText("Hide details" if checked else "Show details")

    def clear(self) -> None:
        self.summary_label.setText("")
        self.details_list.clear()
        self.details_toggle.hide()
        self._details_card.hide()
        self.details_toggle.setChecked(False)

    def set_result(
            self,
            summary: str,
            details: list[dict[str, Any]],
            retryable_reason: str | None = None,
    ) -> None:
        self.summary_label.setText(summary)
        self.details_list.clear()

        if not details:
            self.details_toggle.hide()
            self._details_card.hide()
            self.details_toggle.setChecked(False)
            return

        self.details_toggle.show()

        for detail in details:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(
                theme.SPACING_XS, theme.SPACING_XS,
                theme.SPACING_XS, theme.SPACING_XS,
            )
            label = QLabel(f"[{detail['reason']}] {detail['message']}")
            label.setWordWrap(True)
            row_layout.addWidget(label, 1)

            on_retry_track = self._on_retry_track
            if (
                    retryable_reason is not None
                    and detail["reason"] == retryable_reason
                    and on_retry_track is not None
            ):
                track_id = detail["track_id"]
                retry_button = QPushButton("Retry")
                retry_button.clicked.connect(
                    lambda _checked=False, tid=track_id, cb=on_retry_track:
                    cb(tid)
                )
                row_layout.addWidget(retry_button)

            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            self.details_list.addItem(item)
            self.details_list.setItemWidget(item, row)
