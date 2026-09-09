"""Round 8 §12.2 — keep a sortable QTableWidget's sort order intact
across a full rebuild.

Every table on a poll timer rebuilds by `setRowCount()` + `setItem()`
in fixed data order, addressing rows by loop index — with sorting live
during that loop, each `setItem()` call re-triggers Qt's own sort and
the loop's row indices stop lining up with the rows it just wrote
(round 7's R2 note: a wholesale rebuild already destroyed interactive
state once this way). `preserving_sort_order` disables sorting for the
body of the `with` block and restores the user's chosen column/order
afterward, the same way the keep-radio/delete-checkbox state already
survives a rebuild elsewhere in this app.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem


@contextmanager
def preserving_sort_order(table: QTableWidget) -> Iterator[None]:
    header = table.horizontalHeader()
    sort_column = header.sortIndicatorSection()
    sort_order = header.sortIndicatorOrder()
    was_sorting = table.isSortingEnabled()

    table.setSortingEnabled(False)
    try:
        yield
    finally:
        if was_sorting:
            table.setSortingEnabled(True)
            if sort_column >= 0:
                table.sortItems(sort_column, sort_order)


class SortKeyItem(QTableWidgetItem):
    """A QTableWidgetItem that sorts by an explicit key distinct from
    its displayed text — e.g. a raw byte count sorting numerically
    while the cell shows "3.2 MB" (which would otherwise sort
    alphabetically, ordering it before "512 KB"), or a raw ISO
    timestamp sorting chronologically while the cell shows a "Feb 03,
    2026" label (which would otherwise sort by month name, not date).
    Qt's default `QTableWidgetItem.__lt__` compares `Qt.DisplayRole` —
    the same text shown in the cell — so overriding it is the standard
    Qt idiom for the sort key and the display text not being the same
    value. `sort_key` must never be `None` — pass a real sentinel
    (`-1`, `""`, …) for a missing value instead.
    """

    def __init__(self, text: str, sort_key: Any) -> None:
        super().__init__(text)
        self.sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, SortKeyItem):
            return bool(self.sort_key < other.sort_key)
        return super().__lt__(other)
