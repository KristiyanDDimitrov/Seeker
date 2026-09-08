"""The seam between MainWindow (the shell) and page widgets
(HISTORY §119).

Also carries the shared page-chrome builders (`build_page`/
`build_subtitle_label`), moved verbatim out of main_window.py — every
page, migrated or not, wraps its content through `build_page` for the
identical [title, subtitle, content] shape, so it needs to live
somewhere both main_window.py and every ui/pages/*.py module can import
without a circular dependency.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from seeker.application import Application
from seeker.ui import theme
from seeker.ui.busy_actions import BusyActionRegistry


@dataclass(frozen=True)
class PageContext:
    """What a page widget gets from the shell — deliberately small and
    explicit, so a page module never reaches past it to call MainWindow
    directly (the same "presentation must go through the service layer,
    not around it" discipline CLAUDE.md already requires one layer
    down, applied within the UI layer itself).

    Every field beyond application/thread_pool/busy_actions/navigate
    was added only once a real page being extracted needed it, each
    bound to the one real MainWindow implementation rather than a
    reimplemented copy — see HISTORY §119 for which page found which
    field necessary, and for the deliberately-not-yet-added `notify`.
    """
    application: Application
    thread_pool: QThreadPool
    busy_actions: BusyActionRegistry
    navigate: Callable[[str], None]
    run_busy_worker: Callable[..., None]
    update_nav_badge: Callable[[str, int], None]
    is_hidden_to_tray: Callable[[], bool]
    render_activity_strip: Callable[[], None]


def build_subtitle_label(text: str) -> QLabel:
    # Persistent, not hover-dependent — a muted one-liner under each
    # tab's own header, aimed at someone who never reads the README and
    # goes straight into the app.
    label = QLabel(text)
    # Routed through the global stylesheet's QLabel[badge="muted"] rule
    # (theme.py) rather than a per-widget setStyleSheet() call, so a
    # runtime theme switch re-colors this automatically with no
    # MainWindow.on_theme_changed() code needed.
    label.setProperty("badge", "muted")
    label.setWordWrap(True)
    return label


def build_page(
        title: str,
        subtitle: str,
        content: QWidget,
        header_extra: QWidget | None = None,
) -> QWidget:
    # Every page in the shell gets the identical [title, subtitle,
    # content] shape and the identical page-level margins — this is the
    # one place that convention actually gets enforced, rather than
    # each page copying setContentsMargins/setSpacing by hand and
    # drifting.
    #
    # header_extra — an optional widget placed to the LEFT of the
    # title, in the same row. Only the Settings page uses this today
    # (its "← Back" button), but it's a real, reusable extension point
    # rather than a Settings-specific special case bolted onto this
    # shared helper.
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(
        theme.SPACING_XL, theme.SPACING_LG,
        theme.SPACING_XL, theme.SPACING_LG,
    )
    layout.setSpacing(theme.SPACING_MD)

    title_row = QHBoxLayout()
    title_row.setSpacing(theme.SPACING_SM)

    if header_extra is not None:
        title_row.addWidget(header_extra)

    title_label = QLabel(title)
    # QLabel#pageTitleLabel in theme.py.
    title_label.setObjectName("pageTitleLabel")
    title_row.addWidget(title_label)
    title_row.addStretch()

    layout.addLayout(title_row)
    layout.addWidget(build_subtitle_label(subtitle))
    layout.addWidget(content, 1)

    return page
