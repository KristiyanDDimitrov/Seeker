"""Long text in a table or list elides on one line, and its full text
is one hover away.

Every table gets this from `theme.apply_table_defaults`; a list of
names opts in with `elide_list_items`. A path column (a
`theme.ColumnLayout.paths` entry) elides in the middle, so two copies
of one track in different folders still show different filenames.

A cell can carry a short badge ("Upgrade") in `BADGE_ROLE`: it is
painted as a pill before the text, which elides in the space left.
It can also carry secondary text in `SECONDARY_ROLE` (a candidate's
quality and peer beside its filename): quieter and right-aligned. It
takes whatever the primary text leaves, and at least
`_SECONDARY_MIN_SHARE` of the cell, eliding when that is not enough.
"""

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QHelpEvent,
    QPainter,
    QPalette,
)
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
SECONDARY_ROLE = Qt.ItemDataRole.UserRole + 65
_BADGE_PADDING = 6
_BADGE_GAP = 6
_BADGE_FONT_SCALE = 0.85
_SECONDARY_GAP = 12
_SECONDARY_MIN_SHARE = 0.45
# How much of the text colour secondary text keeps over its ground.
# 0.7 measures at least 5.9:1 on every row ground in both palettes
# (test_elided_text checks 4.5:1), and still reads as the quieter line.
_SECONDARY_TEXT_WEIGHT = 0.7


def secondary_text_color(text: QColor, ground: QColor) -> QColor:
    """`text` blended toward `ground`: derived from the cell's own
    palette, so it follows a theme switch and a selected row without
    this module reading the theme's tokens (theme.py imports it)."""
    weight = _SECONDARY_TEXT_WEIGHT
    return QColor(
        round(text.red() * weight + ground.red() * (1 - weight)),
        round(text.green() * weight + ground.green() * (1 - weight)),
        round(text.blue() * weight + ground.blue() * (1 - weight)),
    )


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


def _secondary_width(option: QStyleOptionViewItem, index: _Index) -> int:
    """The width a cell's secondary text wants, with the gap before it
    and the margin after it (`_secondary_area`); 0 without any."""
    secondary = index.data(SECONDARY_ROLE)
    if not secondary:
        return 0
    return (
        _SECONDARY_GAP + option.fontMetrics.horizontalAdvance(str(secondary))
        + _BADGE_GAP
    )


def _icon_width(option: QStyleOptionViewItem) -> int:
    """How far an icon (a status lamp) pushes the text in from the
    cell's left edge; 0 without one. `option` has been through the
    delegate's `initStyleOption`, which records the icon."""
    widget = option.widget
    has_icon = option.features & QStyleOptionViewItem.ViewItemFeature.HasDecoration
    if widget is None or not has_icon:
        return 0
    text = widget.style().subElementRect(
        QStyle.SubElement.SE_ItemViewItemText, option, widget,
    )
    return text.left() - option.rect.left()


def _secondary_share(option: QStyleOptionViewItem, index: _Index) -> int:
    """What the secondary text takes from this cell's width: what it
    wants, out of what the icon and primary text leave or the view's
    minimum share, whichever is more. `option` is a styled one (see
    `_icon_width`)."""
    wanted = _secondary_width(option, index)
    if not wanted:
        return 0
    cell = option.rect.width()
    primary = (
        _icon_width(option)
        + option.fontMetrics.horizontalAdvance(
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
        )
        + 2 * _BADGE_GAP + _badge_width(option, index)
    )
    delegate = (
        option.widget.itemDelegate()
        if isinstance(option.widget, QAbstractItemView) else None
    )
    min_share = (
        delegate.secondary_min_share
        if isinstance(delegate, ElidedTextDelegate) else _SECONDARY_MIN_SHARE
    )
    available = max(0, cell - primary, int(cell * min_share))
    return min(wanted, available)


def _secondary_area(option: QStyleOptionViewItem, width: int) -> QRect:
    """Where secondary text given `width` of the cell is drawn: right-
    aligned, after its gap, clear of the cell's right edge."""
    return QRect(
        option.rect.right() - width + _SECONDARY_GAP,
        option.rect.top(),
        max(0, width - _SECONDARY_GAP - _BADGE_GAP),
        option.rect.height(),
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
        self.secondary_min_share = _SECONDARY_MIN_SHARE

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
        secondary = index.data(SECONDARY_ROLE)
        if not badge and not secondary:
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

        text = QStyleOptionViewItem(option)
        self.initStyleOption(text, index)
        reserved = _badge_width(option, index)
        if badge:
            self._paint_badge(painter, option, str(badge), reserved)
        trailing = _secondary_share(text, index)
        if secondary:
            self._paint_secondary(painter, option, str(secondary), trailing)

        text.rect = option.rect.adjusted(reserved, 0, -trailing, 0)
        text.state &= ~QStyle.StateFlag.State_HasFocus
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, text, painter, widget,
        )

    @staticmethod
    def _paint_badge(
            painter: QPainter,
            option: QStyleOptionViewItem,
            badge: str,
            reserved: int,
    ) -> None:
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
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, badge)
        painter.restore()

    @staticmethod
    def _paint_secondary(
            painter: QPainter,
            option: QStyleOptionViewItem,
            secondary: str,
            width: int,
    ) -> None:
        palette = option.palette
        if option.state & QStyle.StateFlag.State_Selected:
            text_role = QPalette.ColorRole.HighlightedText
            ground_role = QPalette.ColorRole.Highlight
        else:
            text_role = QPalette.ColorRole.Text
            ground_role = QPalette.ColorRole.Base
        area = _secondary_area(option, width)
        painter.save()
        painter.setFont(option.font)
        painter.setPen(secondary_text_color(
            palette.color(text_role), palette.color(ground_role),
        ))
        painter.drawText(
            area,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            option.fontMetrics.elidedText(
                secondary, Qt.TextElideMode.ElideRight, area.width(),
            ),
        )
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: _Index) -> QSize:
        hint = super().sizeHint(option, index)
        hint.setWidth(
            hint.width() + _badge_width(option, index)
            + _secondary_width(option, index),
        )
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
            secondary = index.data(SECONDARY_ROLE)
            if secondary:
                text = f"{text}\n{secondary}"
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
        available = (
            text_rect.width() - 2 * margin - _badge_width(option, index)
            - _secondary_share(styled, index)
        )
        if metrics.horizontalAdvance(text) > available:
            return True
        secondary = index.data(SECONDARY_ROLE)
        return bool(
            secondary
            and _secondary_width(option, index)
            > _secondary_share(styled, index)
        )


def elide_table_cells(view: QTableView) -> None:
    """One line per cell, elided, with the full text on hover."""
    view.setWordWrap(False)
    view.setItemDelegate(ElidedTextDelegate(view))


def set_path_columns(view: QAbstractItemView, columns: tuple[int, ...]) -> None:
    """Elide these columns in the middle, keeping a filename's end."""
    delegate = view.itemDelegate()
    if isinstance(delegate, ElidedTextDelegate):
        delegate.path_columns = frozenset(columns)


def set_secondary_min_share(view: QAbstractItemView, share: float) -> None:
    """The least of a cell's width its secondary text keeps; 0 lets
    the primary text take the whole cell first (a status label beside
    its percentage)."""
    delegate = view.itemDelegate()
    if isinstance(delegate, ElidedTextDelegate):
        delegate.secondary_min_share = share


def elide_list_items(widget_list: QListWidget) -> None:
    """Items as wide as the list, elided, never a sideways scrollbar."""
    widget_list.setWordWrap(False)
    widget_list.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
    )
    widget_list.setItemDelegate(ElidedTextDelegate(widget_list, fill_width=True))
