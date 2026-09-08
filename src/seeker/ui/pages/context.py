"""The seam between MainWindow (the shell) and page widgets — round 8
Phase 6 (docs/BRIEF-2026-09-08-refactor.md §9.2).

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

    `run_busy_worker` is a real addition beyond §9.2's own four-field
    sketch (application/thread_pool/busy_actions/navigate) — found
    necessary extracting the first page (History) that actually calls
    MainWindow._run_busy_worker(). It's bound from that exact method, so
    a page gets the identical begin()/end()/activity-strip-render
    behavior every existing call site already has, not a reimplemented
    copy. thread_pool and busy_actions stay in the context too, for a
    future page that builds its own bespoke run_worker() call (custom
    progress reporting, no button) the way several MainWindow methods
    already do.

    §9.2's `notify` field is deliberately NOT included yet — no page
    moved so far needs it, and there's no single real shell-side
    implementation to bind it to today (InlineNotice instances are
    built per-page, not through one shared MainWindow method). Add it,
    wired to something real, when a page that needs it moves.

    `update_nav_badge` and `is_hidden_to_tray` are two more additions
    beyond §9.2's original sketch, both found extracting Downloads
    (round 8 Phase 6, S7): `_render_active_downloads` needs to set the
    sidebar's "Downloads (N)" badge (shell state — `self._nav_buttons`
    — no page owns it) and to skip its own table rebuild while the
    window is hidden to the tray (R7.6; `_hidden_to_tray` is real
    MainWindow lifecycle state, set by `closeEvent`/tray reopen, not
    something a page should own a second copy of). Same
    read-through-the-seam treatment as `run_busy_worker` above, for the
    same reason: a page reaches the shell through one narrow named
    callable, never by importing MainWindow or reaching past this
    object.

    `render_activity_strip` (same S7 session, found extracting the
    Tagging panel) is the persistent activity strip's own re-render —
    genuinely shell chrome (visible above every page, not owned by
    any one of them), needed by a call site that begins a busy action
    by hand (`busy_actions.begin(...)` directly) rather than through
    `run_busy_worker`, so the render has to be triggered the same way
    the hand-rolled begin() was.
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
    # Persistent, not hover-dependent (Task 1) — a muted one-liner under
    # each tab's own header, aimed at someone who never reads the
    # README and goes straight into the app.
    label = QLabel(text)
    # Roadmap item C5.3 — routed through the global stylesheet's
    # QLabel[badge="muted"] rule (theme.py) rather than a per-widget
    # setStyleSheet() call, so a runtime theme switch re-colors this
    # automatically with no MainWindow.on_theme_changed() code needed.
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
    # content] shape and the identical page-level margins (Phase 3's
    # own documented layout convention) — this is the one place that
    # convention actually gets enforced, rather than each page copying
    # setContentsMargins/setSpacing by hand and drifting.
    #
    # header_extra (roadmap item 56 Phase 3) — an optional widget placed
    # to the LEFT of the title, in the same row. Only the Settings page
    # uses this today (its "← Back" button), but it's a real, reusable
    # extension point rather than a Settings-specific special case
    # bolted onto this shared helper.
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
    # Roadmap item C5.3 — QLabel#pageTitleLabel in theme.py.
    title_label.setObjectName("pageTitleLabel")
    title_row.addWidget(title_label)
    title_row.addStretch()

    layout.addLayout(title_row)
    layout.addWidget(build_subtitle_label(subtitle))
    layout.addWidget(content, 1)

    return page
