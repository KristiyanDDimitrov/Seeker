"""Long text in a table or list elides on one line, and its full text
is one hover away.

Every table gets this from `theme.apply_table_defaults`; a list of
names opts in with `elide_list_items`. A path column (a
`theme.ColumnLayout.paths` entry) elides in the middle, so two copies
of one track in different folders still show different filenames.

A cell can carry a short badge ("Upgrade") in `BADGE_ROLE`: it is
painted as a pill before the text, which elides in the space left.
"""

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
)
from PySide6.QtGui import QFont, QFontMetrics, QHelpEvent, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QToolTip,
    QWidget,
)

from seeker.ui.plain_text import plain_tooltip

_Index = QModelIndex | QPersistentModelIndex

# Clear of the UserRole a page stores its own row ids under.
BADGE_ROLE = Qt.ItemDataRole.UserRole + 64
_BADGE_PADDING = 6
_BADGE_GAP = 6
_BADGE_FONT_SCALE = 0.85


def _badge_font(base: QFont) -> QFont:
    font = QFont(base)
    font.setPointSizeF(base.pointSizeF() * _BADGE_FONT_SCALE)
    return font


def _badge_width(option: QStyleOptionViewItem, index: _Index) -> int:
    """The width a cell's badge takes from its text, gaps included;
    0 without a badge."""
    badge = index.data(BADGE_ROLE)
    if not badge:
        return 0
    metrics = QFontMetrics(_badge_font(option.font))
    return (
        _BADGE_GAP + metrics.horizontalAdvance(str(badge))
        + 2 * _BADGE_PADDING + _BADGE_GAP
    )


class ElidedTextDelegate(QStyledItemDelegate):
    """Shows a cell's full text as its tooltip when the view elides
    it, unless the cell has a tooltip of its own.

    `fill_width` makes every item exactly as wide as the viewport: a
    list in list mode sizes an item to its text, so a long name would
    otherwise scroll sideways instead of eliding.
    """

    def __init__(self, view: QAbstractItemView, *, fill_width: bool = False):
        super().__init__(view)
        self._fill_width = fill_width
        self.path_columns: frozenset[int] = frozenset()

    def elide_mode(self, index: _Index) -> Qt.TextElideMode:
        if index.column() in self.path_columns:
            return Qt.TextElideMode.ElideMiddle
        return Qt.TextElideMode.ElideRight

    def initStyleOption(
            self, option: QStyleOptionViewItem, index: _Index,
    ) -> None:
        super().initStyleOption(option, index)
        option.textElideMode = self.elide_mode(index)

    def paint(
            self,
            painter: QPainter,
            option: QStyleOptionViewItem,
            index: _Index,
    ) -> None:
        badge = index.data(BADGE_ROLE)
        if not badge:
            super().paint(painter, option, index)
            return

        widget = option.widget
        style = widget.style() if widget is not None else None
        if style is None:
            super().paint(painter, option, index)
            return

        # The row's background, selection and focus over the whole
        # cell first, then the text in what the pill leaves.
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ""
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, background, painter, widget,
        )

        reserved = _badge_width(option, index)
        font = _badge_font(option.font)
        metrics = QFontMetrics(font)
        pill = QRect(
            option.rect.left() + _BADGE_GAP,
            option.rect.center().y() - (metrics.height() + 4) // 2,
            reserved - 2 * _BADGE_GAP,
            metrics.height() + 4,
        )
        # The palette `theme.apply_theme` sets (Highlight is ACCENT),
        # so the pill follows a theme switch; theme.py imports this
        # module, so it cannot read the tokens itself.
        palette = option.palette
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(palette.color(QPalette.ColorRole.Highlight))
        painter.setBrush(palette.color(QPalette.ColorRole.AlternateBase))
        radius = pill.height() / 2
        painter.drawRoundedRect(pill, radius, radius)
        painter.setFont(font)
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, str(badge))
        painter.restore()

        text = QStyleOptionViewItem(option)
        self.initStyleOption(text, index)
        text.rect = option.rect.adjusted(reserved, 0, 0, 0)
        text.state &= ~QStyle.StateFlag.State_HasFocus
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, text, painter, widget,
        )

    def sizeHint(self, option: QStyleOptionViewItem, index: _Index) -> QSize:
        hint = super().sizeHint(option, index)
        hint.setWidth(hint.width() + _badge_width(option, index))
        if self._fill_width:
            # In list mode an item spans the wider of its own hint and
            # the viewport (probed: a zero-width hint tracks the
            # viewport on resize, and the view elides the text).
            hint.setWidth(0)
        return hint

    def helpEvent(
            self,
            event: QHelpEvent,
            view: QAbstractItemView,
            option: QStyleOptionViewItem,
            index: _Index,
    ) -> bool:
        if (
                event.type() == QEvent.Type.ToolTip
                and not index.data(Qt.ItemDataRole.ToolTipRole)
                and self._is_elided(option, index, view)
        ):
            text = str(index.data(Qt.ItemDataRole.DisplayRole))
            QToolTip.showText(event.globalPos(), plain_tooltip(text), view)
            return True
        return super().helpEvent(event, view, option, index)

    def _is_elided(
            self,
            option: QStyleOptionViewItem,
            index: _Index,
            view: QWidget,
    ) -> bool:
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        text: str = styled.text
        if not text:
            return False
        style = view.style()
        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, styled, view,
        )
        # Qt's item painter insets the text by the focus-frame margin
        # plus one pixel on each side before it elides
        # (QCommonStylePrivate::viewItemDrawText, qcommonstyle.cpp).
        margin = style.pixelMetric(
            QStyle.PixelMetric.PM_FocusFrameHMargin, styled, view,
        ) + 1
        metrics = styled.fontMetrics
        available = text_rect.width() - 2 * margin - _badge_width(option, index)
        return bool(metrics.horizontalAdvance(text) > available)


def elide_table_cells(view: QTableView) -> None:
    """One line per cell, elided, with the full text on hover."""
    view.setWordWrap(False)
    view.setItemDelegate(ElidedTextDelegate(view))


def set_path_columns(view: QAbstractItemView, columns: tuple[int, ...]) -> None:
    """Elide these columns in the middle, keeping a filename's end."""
    delegate = view.itemDelegate()
    if isinstance(delegate, ElidedTextDelegate):
        delegate.path_columns = frozenset(columns)


def elide_list_items(widget_list: QListWidget) -> None:
    """Items as wide as the list, elided, never a sideways scrollbar."""
    widget_list.setWordWrap(False)
    widget_list.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
    )
    widget_list.setItemDelegate(ElidedTextDelegate(widget_list, fill_width=True))
