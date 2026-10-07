import html
import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import (
    QEvent,
    QObject,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QGuiApplication,
    QKeySequence,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from seeker.application import Application
from seeker.soulseek.client import SlskdUnreachableError
from seeker.ui import help_text, plain_text, theme
from seeker.ui.busy_actions import BusyActionRegistry
from seeker.ui.dialogs import (
    AboutDialog,
)
from seeker.ui.icons import nav_icon
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.pages.dashboard_page import (
    DashboardHost,
    DashboardPage,
    # Re-exported for tests/test_next_step.py, which imports both from
    # this module's namespace; nothing below uses them.
    _decide_next_step,  # noqa: F401
    _NextStepFacts,  # noqa: F401
)
from seeker.ui.pages.downloads_page import DownloadsPage
from seeker.ui.pages.duplicates_page import DuplicatesPage
from seeker.ui.pages.history_page import HistoryPage
from seeker.ui.pages.library_page import LibraryHost, LibraryPage
from seeker.ui.pages.review_page import (
    ReviewHost,
    ReviewPage,
)
from seeker.ui.pages.search_page import SearchPage
from seeker.ui.pages.sharing_page import SharingPage
from seeker.ui.pages.static_pages import HelpPage, SupportPage
from seeker.ui.plain_text import PlainLabel
from seeker.ui.playlist_selection import PlaylistSelection
from seeker.ui.settings_window import SettingsPage
from seeker.ui.slskd_status import START_SLSKD_KEY, SlskdStatus
from seeker.ui.tray import TrayController, TrayHost
from seeker.ui.widgets import ThemeToggleButton
from seeker.ui.window_lifecycle import (
    WindowLifecycleController,
    WindowLifecycleHost,
)
from seeker.ui.wordmark import BROW_ROOM_PX, Wordmark
from seeker.ui.workers import run_worker
from seeker.update_check import UpdateCheckResult, UpdateStatus, check_for_update

logger = logging.getLogger(__name__)


# Untuned constant — matches the ~2s cadence observed against real slskd
# elsewhere in this project; revisit once real usage data exists, same
# convention as every other threshold here.
POLL_INTERVAL_MS = 2_000

# Untuned constant — this timer makes real network calls to slskd (via
# poll_downloads()), so it deliberately runs far less often than the
# local-DB-only display refresh above. Revisit once real usage data
# exists.
BACKEND_POLL_INTERVAL_MS = 20_000

# Untuned constant — a fixed sidebar width narrow enough to leave real
# room for content, wide enough that "Duplicates" (the longest nav
# label) never wraps or clips.
SIDEBAR_WIDTH = 200

# key -> (nav label, page title). One source of truth for both the
# sidebar button text (via _update_nav_badge, which appends a live
# count to the label half) and the page header's own title — a nav
# label and its page title only ever differ if a future page wants
# them to (none do yet).
_NAV_PAGES = (
    ("dashboard", "Dashboard"),
    ("library", "Library"),
    ("search", "Search"),
    ("downloads", "Downloads"),
    ("review", "Review"),
    ("duplicates", "Duplicates"),
    ("sharing", "Sharing"),
    ("history", "History"),
)

# Human-readable label for each busy_actions key, shown on the global
# activity strip. Any key with no entry here falls back to a generic
# "Working…" rather than a raw key string leaking into the UI.
_BUSY_ACTION_LABELS: dict[str, str] = {
    "sync": "Refreshing playlists…",
    "scan": "Scanning library and matching tracks…",
    "match": "Matching tracks…",
    "download": "Requesting downloads…",
    "sync_tracks": "Loading tracks…",
    "tag_selected": "Tagging selected tracks…",
    "tag_playlist": "Tagging playlist…",
    "compute_fingerprints": "Computing fingerprints…",
    "find_duplicates": "Searching for duplicates…",
    "sharing_refresh": "Checking sharing status…",
    START_SLSKD_KEY: "Starting slskd…",
    "history_refresh": "Loading history…",
    "search_manual": "Searching SoulSeek…",
    "download_manual": "Requesting download…",
}


_THEME_MODE_CYCLE = ("system", "light", "dark")


def _build_nav_button(key: str, label: str) -> QPushButton:
    # A checkable, flat QPushButton rather than a bespoke widget —
    # QPushButton is already painted through Qt's style system (unlike
    # a plain QWidget, which needs WA_StyledBackground — see notice.py/
    # the sidebar's own comment), so its checked state can be styled
    # directly via the `[navItem="true"]:checked` QSS rule with no
    # extra plumbing. Text-only badge counts (via _update_nav_badge)
    # rather than a separate sibling widget, to keep one exclusive
    # QButtonGroup member per nav item instead of a composite row.
    button = QPushButton(nav_icon(key), label)
    button.setIconSize(QSize(theme.NAV_ICON_PX, theme.NAV_ICON_PX))
    button.setCheckable(True)
    button.setFlat(True)
    button.setProperty("navItem", True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class MainWindow(QMainWindow):
    def __init__(self, application: Application):
        super().__init__()
        self.application = application
        # WA_DeleteOnClose is decided in exactly one place,
        # TrayController._build_tray_icon(), for both branches — never
        # here (HISTORY §125).
        self._init_shared_state()
        self._tray = self._build_tray_controller()
        self._lifecycle = self._build_lifecycle_controller()
        self._connect_application_events()

        self.setWindowTitle("Seeker")
        self.resize(1180, 760)
        self.setMinimumSize(960, 640)
        self._build_ui()
        # After _build_ui(): restored before the central widget
        # existed, the first layout activation discarded the geometry
        # (confirmed live). Even here it lost that race on a CI runner,
        # so the lifecycle's after_show() re-applies it on the first
        # real show; this call only avoids a flash at the default size.
        self._lifecycle.restore_window_geometry()
        # After _build_ui(), so a scheme change mid-construction can't
        # reach a half-built UI.
        self._sync_system_scheme_subscription()
        # Keyboard focus starts where the Dashboard's work starts.
        # Left to Qt, it lands on the first focusable widget in the
        # chain, the sidebar's theme toggle, which then wears its
        # focus ring from launch.
        self._dashboard_page.playlist_list.setFocus()

        self._load_initial_page_state()
        self._start_poll_timers()

    def _init_shared_state(self) -> None:
        self.thread_pool = QThreadPool()
        # The single source of truth for "is this named action currently
        # running," consulted by every poll-driven render method so it
        # can skip a button whose own action is still in flight instead
        # of fighting run_worker's own busy-disable.
        self.busy_actions = BusyActionRegistry()
        # The shared playlist/track selection Dashboard and Library
        # both write (HISTORY §133).
        self.playlist_selection = PlaylistSelection()
        # Written only by _trigger_backend_poll.
        self.slskd_status = SlskdStatus()
        # Keyed the same as busy_actions; populated by a
        # run_worker(on_progress=...) callback (via
        # _on_activity_progress), consulted by _render_activity_strip.
        self._activity_progress: dict[str, tuple[str, int, int]] = {}
        self._backend_poll_in_progress = False

        # The persisted mode ("system" by default); the resolved
        # Palette is already active (main_ui.py applies the theme
        # before any window exists). Read before _build_ui() so the
        # sidebar's theme toggle starts on its real icon.
        self._theme_mode = self.application.theme_mode
        self._system_scheme_connected = False
        # Re-entrancy guard: `apply_theme`'s own `setColorScheme()`
        # emits `colorSchemeChanged`, which (in "system" mode) is
        # connected back to `_on_system_color_scheme_changed` — without
        # this flag that handler re-enters `_apply_theme_mode` before
        # the outer call's chosen mode applies its stylesheet. See
        # `_apply_theme_mode`.
        self._applying_theme = False

    def _build_lifecycle_controller(self) -> WindowLifecycleController:
        return WindowLifecycleController(WindowLifecycleHost(
            application=self.application,
            window=self,
            thread_pool=self.thread_pool,
            tray=self._tray,
            page_to_reopen=self._page_to_reopen,
            release_shell=self._release_for_quit,
        ))

    def _connect_application_events(self) -> None:
        # macOS routes every "reopen a running app" gesture (Dock icon
        # click, Finder, Spotlight, `open -a Seeker`) through
        # applicationShouldHandleReopen:hasVisibleWindows:, which Qt's
        # Cocoa plugin turns into exactly this signal
        # (ApplicationActive, forcePropagate=true) without showing any
        # window itself (HISTORY §116). A connection to a GLOBAL
        # object, so cleanup_before_quit tears it down explicitly.
        #
        # Gated on a real tray icon: without one, closeEvent really
        # closes, so there is no hidden state to reopen from. The signal
        # does fire organically under offscreen QPA (see conftest.py's
        # `_ignore_organic_application_state_changes`).
        app = QApplication.instance()
        self._app_state_connected = False
        if app is not None and self._tray.has_icon:
            # QApplication.instance() is typed as QCoreApplication;
            # this app always constructs a QApplication.
            assert isinstance(app, QGuiApplication)
            # Connected to this window's own delegating slot, never to
            # `self._tray.on_application_state_changed` directly:
            # PySide only auto-disconnects a bound method whose
            # `__self__` is a QObject when that QObject is destroyed.
            # TrayController is a plain Python object, so a direct
            # connection outlived a torn-down window in tests and then
            # hit a deleted C++ object (reproduced, a RuntimeError).
            app.applicationStateChanged.connect(
                self._on_application_state_changed
            )
            self._app_state_connected = True

        # The one seam both real quit routes pass through
        # (HISTORY §123, §124): tray Quit's `app.quit()` and the native
        # ⌘Q/Dock "Quit Seeker" both deliver a `QEvent.Type.Quit` to the
        # QApplication before `aboutToQuit`. This window's eventFilter
        # can still cancel that exact event; `aboutToQuit` is too late.
        if app is not None:
            app.installEventFilter(self)

    def _load_initial_page_state(self) -> None:
        self._dashboard_page.load_playlists()
        self._downloads_page.poll_active_downloads()
        self._review_page.poll_review_items()
        self._dashboard_page.poll_next_step()
        self._tray.seed_notification_cutoff()

    def _start_poll_timers(self) -> None:
        # The display poll rebuilds each visible model every tick
        # rather than diffing. That is accepted for DISPLAY state only,
        # never user INPUT: an interactive control in a polled table
        # survives a rebuild only through a state map keyed by stable
        # identity (`_upgrade_delete_checked`,
        # `_duplicates_keep_selection`), never row index.
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_INTERVAL_MS)
        self.poll_timer.timeout.connect(self._dashboard_page.poll_selected_playlist)
        self.poll_timer.timeout.connect(
            self._downloads_page.poll_active_downloads
        )
        self.poll_timer.timeout.connect(self._review_page.poll_review_items)
        self.poll_timer.timeout.connect(self._dashboard_page.poll_next_step)
        # A safety net: every busy-action call site already renders the
        # strip itself; this keeps it right if a future one forgets.
        self.poll_timer.timeout.connect(self._render_activity_strip)
        # Cheap (reads counts the polls above already set), so it rides
        # the fast tick.
        self.poll_timer.timeout.connect(self._tray.render_tray_menu)
        self.poll_timer.start()

        # The only thing that runs poll_downloads() (real slskd network
        # calls) without an explicit `seeker downloads status`. It never
        # prompts, so it is safe on a bare timer.
        self.backend_poll_timer = QTimer(self)
        self.backend_poll_timer.setInterval(BACKEND_POLL_INTERVAL_MS)
        self.backend_poll_timer.timeout.connect(self._trigger_backend_poll)
        self.backend_poll_timer.timeout.connect(
            self._sharing_page.poll_sharing
        )
        self.backend_poll_timer.start()

    def _build_tray_controller(self) -> TrayController:
        # The tray/notification group (ui/tray.py). The `window`,
        # `poll_*`, `navigate` and `render_activity_strip` hooks are
        # lambdas or bound methods rather than values captured now,
        # since the pages they reach
        # (`_downloads_page`/`_review_page`/`_dashboard_page`) don't
        # exist yet at this point in construction (this runs before
        # _build_ui()) — TrayController only calls them later, on a real
        # reopen. Reopening the window itself goes through
        # `window.reopen()`, so the hide-to-tray state stays owned by
        # the lifecycle controller alone.
        return TrayController(TrayHost(
            application=self.application,
            thread_pool=self.thread_pool,
            window=self,
            navigate=self._show_page,
            render_activity_strip=self._render_activity_strip,
            trigger_backend_poll=self._trigger_backend_poll,
            # Deliberately still lambdas, not bound-method references:
            # `_downloads_page`/`_review_page`/`_dashboard_page` don't
            # exist yet at this point (they're built by _build_ui(),
            # which itself needs self._tray already constructed — see
            # ReviewHost below) — a bound-method reference here would
            # raise immediately, so these stay real lambdas for
            # genuinely deferred attribute lookup, not an unnecessary
            # wrap ruff's PLW0108 would otherwise flag.
            poll_selected_playlist=(
                lambda: self._dashboard_page.poll_selected_playlist()  # noqa: PLW0108
            ),
            poll_active_downloads=(
                lambda: self._downloads_page.poll_active_downloads()  # noqa: PLW0108
            ),
            poll_review_items=(
                lambda: self._review_page.poll_review_items()  # noqa: PLW0108
            ),
            poll_next_step=(
                lambda: self._dashboard_page.poll_next_step()  # noqa: PLW0108
            ),
            needs_review_count=lambda: self._review_page.needs_review_count,
            pending_upgrades_count=(
                lambda: self._review_page.pending_upgrades_count
            ),
            active_downloads_count=(
                lambda: self._downloads_page.active_downloads_count
            ),
        ))

    def _build_ui(self) -> None:
        self._build_view_menu()
        self._build_window_menu()
        self._build_help_menu()

        shell = QWidget()
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        shell_layout.addWidget(self._build_sidebar())

        # A persistent activity strip lives between the sidebar/header
        # and the page content itself, visible regardless of which page
        # the user has navigated to (button state alone is invisible
        # once you've left the page a long-running action was started
        # from). A separate column rather than widening shell_layout
        # further, so the strip spans only the content area, not the
        # sidebar.
        content_column = QWidget()
        content_column_layout = QVBoxLayout(content_column)
        content_column_layout.setContentsMargins(0, 0, 0, 0)
        content_column_layout.setSpacing(0)

        self.activity_strip = self._build_activity_strip()
        content_column_layout.addWidget(self.activity_strip)

        self.stacked_widget = QStackedWidget()
        content_column_layout.addWidget(self.stacked_widget, 1)

        shell_layout.addWidget(content_column, 1)

        # The seam a page gets instead of reaching past it to MainWindow
        # directly; PageContext's own docstring describes each field.
        page_context = PageContext(
            application=self.application,
            thread_pool=self.thread_pool,
            busy_actions=self.busy_actions,
            navigate=self._show_page,
            run_busy_worker=self._run_busy_worker,
            update_nav_badge=self._update_nav_badge,
            is_hidden_to_tray=self._lifecycle.is_hidden_to_tray,
            render_activity_strip=self._render_activity_strip,
            playlist_selection=self.playlist_selection,
            slskd_status=self.slskd_status,
        )

        self._page_indices: dict[str, int] = {}
        self._dashboard_page = DashboardPage(
            page_context,
            DashboardHost(
                open_settings=self._on_settings_clicked,
                navigate_to_review=lambda track_id: self._show_page(
                    "review", focus_track_id=track_id,
                ),
                # Lambdas, not bound methods: the Library page is built
                # after this one, so the lookup has to wait for a click.
                tag_track=lambda track_id, button, feedback: (  # noqa: PLW0108
                    self._library_page.tag_track(track_id, button, feedback)
                ),
                retag_track=lambda track_id, feedback: (  # noqa: PLW0108
                    self._library_page.retag_track(track_id, feedback)
                ),
                tag_playlist=lambda feedback: (  # noqa: PLW0108
                    self._library_page.tag_playlist(feedback)
                ),
            ),
        )
        self._register_page("dashboard", self._dashboard_page)
        self._library_page = LibraryPage(
            page_context,
            LibraryHost(
                refresh_track_table=self._dashboard_page.poll_selected_playlist,
            ),
        )
        self._register_page("library", self._library_page)
        self._search_page = SearchPage(page_context)
        self._register_page("search", self._search_page)
        self._downloads_page = DownloadsPage(page_context)
        self._register_page("downloads", self._downloads_page)
        self._review_page = ReviewPage(
            page_context,
            ReviewHost(
                refresh_track_table=self._dashboard_page.poll_selected_playlist,
                check_for_needs_decision_notification=(
                    self._tray.check_for_needs_decision_notification
                ),
            ),
        )
        self._register_page("review", self._review_page)
        self._duplicates_page = DuplicatesPage(page_context)
        self._register_page("duplicates", self._duplicates_page)
        self._sharing_page = SharingPage(page_context)
        self._register_page("sharing", self._sharing_page)

        self._history_page = HistoryPage(page_context)
        self._register_page("history", self._history_page)
        self._help_page = HelpPage(page_context)
        self._register_page("help", self._help_page)
        self._support_page = SupportPage(page_context)
        self._register_page("support", self._support_page)

        # Settings is a page, hosted the same way as everything else
        # here, not a separate dialog, and left the same way: through
        # the sidebar, which has a button for every page.
        self.settings_page = SettingsPage(
            self.application, on_about_requested=self._on_about_clicked,
            on_theme_mode_changed=self._apply_theme_mode,
        )
        self._register_page("settings", build_page(
            "Settings", help_text.SETTINGS_WINDOW_SUBTITLE,
            self.settings_page,
        ))
        self._settings_page_index = self._page_indices["settings"]

        # Locations load lazily, on every real show of this page rather
        # than eagerly in _build_ui() — an eager worker at construction
        # compounds into a reproducible deadlock (Qt's internal
        # connection-list mutex vs. the GIL) under the rapid, repeated
        # MainWindow construction the test suite does. A page SHOW is
        # rare and human-paced, so refreshing on every one (a location
        # added since the last visit must appear) doesn't reintroduce
        # that hazard. See HISTORY §39.
        self._duplicates_page_index = self._page_indices["duplicates"]
        # Lazy-loaded like Duplicates (first real page SHOW, never at
        # construction), but ALSO joins the standing 20s
        # backend_poll_timer once visited, same shape as Downloads' own
        # real-slskd-call poll — sharing status/uploads are live
        # external state, not a one-shot local read like
        # Duplicates/History. The visited/in-progress flags and the ETA
        # tracker live on SharingPage itself; only the page index stays
        # here, for _on_page_changed's dispatch.
        self._sharing_page_index = self._page_indices["sharing"]
        # Same lazy-load-on-first-real-visit reasoning as Duplicates
        # above — a plain, cheap local-DB read, but there's no reason
        # to pay it on every MainWindow construction when a real user
        # may never open this page in a given session.
        self._history_page_index = self._page_indices["history"]
        self._history_loaded = False
        # Tracks the currently-shown page key so _page_to_reopen knows
        # the page Settings was opened from, and so _on_page_changed can
        # detect "we just left Settings" regardless of which navigation
        # path was used (sidebar click or a CTA/double-click action —
        # every one of them goes through _show_page).
        self._current_page_key = "dashboard"
        self._previous_page_key = "dashboard"
        self.stacked_widget.currentChanged.connect(self._on_page_changed)

        self.setCentralWidget(shell)
        # Restore the last-open page; an unrecognized/missing key (a
        # fresh install, or a page a later version removed) falls back
        # to the hardcoded "dashboard" default.
        restored_page = self.application.settings.last_open_page
        self._show_page(
            restored_page if restored_page in self._page_indices
            else "dashboard"
        )

    def _register_page(self, key: str, widget: QWidget) -> None:
        self._page_indices[key] = self.stacked_widget.addWidget(widget)

    def _page_to_reopen(self) -> str:
        # Settings is reached FROM a nav page rather than being one
        # itself (_show_page's own settings-transition tracking already
        # treats it this way, via _previous_page_key) — persisting the
        # page the user was actually on before that detour reopens on
        # the page they meant to return to, not a transient stop.
        return (
            self._previous_page_key
            if self._current_page_key == "settings"
            else self._current_page_key
        )

    def _show_page(self, key: str, focus_track_id: str | None = None) -> None:
        # Every navigation path in this app (sidebar click, a Dashboard
        # CTA action, a double-click) goes through this one method, so
        # it's the single place both the page Settings was opened from
        # and the settings-exit invalidation can hook into without a
        # Settings-specific special case at each call site.
        if key == "settings" and self._current_page_key != "settings":
            self._previous_page_key = self._current_page_key
        elif self._current_page_key == "settings" and key != "settings":
            self._invalidate_after_leaving_settings()

        self._current_page_key = key
        # Hiding the focused widget would pass focus down the tab chain
        # into the next page, as if by Tab, and Fusion would frame
        # whatever it lands on. The stack holds it instead; Tab enters
        # the new page from there.
        focused = self.focusWidget()
        outgoing = self.stacked_widget.currentWidget()
        if (
                focused is not None
                and outgoing is not None
                and outgoing.isAncestorOf(focused)
        ):
            self.stacked_widget.setFocus()
        self.stacked_widget.setCurrentIndex(self._page_indices[key])

        button = self._nav_buttons.get(key)
        if button is not None:
            button.setChecked(True)

        if key == "review" and focus_track_id is not None:
            self._review_page.focus_track(focus_track_id)

    def _invalidate_after_leaving_settings(self) -> None:
        # A Settings change can affect the Duplicates page's location
        # combo (a location added/removed) and the Dashboard's own
        # next-step CTA (Spotify/library-location/threshold facts). Both
        # already have a real refresh method; this just calls them
        # immediately on exit rather than waiting for their own standing
        # poll/lazy-load to eventually catch up.
        self._duplicates_page.refresh_locations()
        self._dashboard_page.poll_next_step()

    def _build_activity_strip(self) -> QWidget:
        # Hidden whenever nothing is running (the common case); see
        # _render_activity_strip for what populates it.
        strip = QWidget()
        strip.setObjectName("activityStrip")
        # A plain QWidget subclass doesn't paint its own stylesheet
        # background by default in Qt (HISTORY §47).
        strip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # The #activityStrip rule lives in the global stylesheet
        # (theme.py's build_stylesheet), not a per-instance string here,
        # so it re-colors on a runtime theme switch automatically.

        layout = QHBoxLayout(strip)
        layout.setContentsMargins(
            theme.SPACING_MD, theme.SPACING_XS,
            theme.SPACING_MD, theme.SPACING_XS,
        )
        layout.setSpacing(theme.SPACING_SM)

        self.activity_strip_label = PlainLabel("")
        layout.addWidget(self.activity_strip_label)

        # Untuned fixed width — wide enough to read a real percentage
        # without dominating the strip.
        self.activity_strip_bar = QProgressBar()
        self.activity_strip_bar.setFixedWidth(160)
        self.activity_strip_bar.setTextVisible(False)
        layout.addWidget(self.activity_strip_bar)

        layout.addStretch()

        strip.hide()
        return strip

    def _render_activity_strip(self) -> None:
        # A visual-only header strip; pure waste to keep updating while
        # nobody can see it.
        if self._lifecycle.is_hidden_to_tray():
            return

        running = sorted(self.busy_actions.running_keys())

        if not running:
            self.activity_strip.hide()
            return

        self.activity_strip.show()

        if len(running) > 1:
            # Multiple actions running at once — a real count, not an
            # invented merged progress number: unrelated work never
            # folds into one fake percentage.
            self.activity_strip_label.setText(
                f"{len(running)} actions running"
            )
            self.activity_strip_bar.setRange(0, 0)
            return

        key = running[0]
        label = _BUSY_ACTION_LABELS.get(key, "Working…")
        progress = self._activity_progress.get(key)

        if progress is not None:
            stage, current, total = progress
            self.activity_strip_label.setText(
                f"{label} {stage} ({current}/{total})" if stage else
                f"{label} ({current}/{total})"
            )
            self.activity_strip_bar.setRange(0, total)
            self.activity_strip_bar.setValue(current)
            theme.style_determinate_progress_bar(self.activity_strip_bar)
        else:
            self.activity_strip_label.setText(label)
            self.activity_strip_bar.setRange(0, 0)  # indeterminate

    def _on_activity_progress(
            self, key: str, stage: str, current: int, total: int,
    ) -> None:
        # Populated by any run_worker(..., on_progress=...) caller that
        # also passes a matching key through here (fingerprinting and
        # the duplicate search). Cleared the moment the action itself
        # ends, via _run_busy_worker's own
        # wrapped_finished/wrapped_error.
        self._activity_progress[key] = (stage, current, total)
        self._render_activity_strip()

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebarPanel")
        # A plain QWidget subclass doesn't paint its own stylesheet
        # background by default in Qt (HISTORY §47) — the
        # `#sidebarPanel` QSS rule below would otherwise silently do
        # nothing.
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        # The #sidebarPanel rule lives in the global stylesheet
        # (theme.py's build_stylesheet), like #activityStrip above.

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(
            theme.SPACING_MD, theme.SPACING_LG - BROW_ROOM_PX,
            theme.SPACING_MD, theme.SPACING_LG,
        )
        layout.setSpacing(theme.SPACING_XS)

        wordmark_row = QHBoxLayout()
        wordmark_row.setContentsMargins(0, 0, 0, 0)
        self._wordmark = Wordmark()
        wordmark_row.addWidget(self._wordmark)
        wordmark_row.addStretch()
        # Right-aligned on the wordmark's own row, cycling system ->
        # light -> dark -> system.
        self._theme_toggle = ThemeToggleButton(self._theme_mode)
        self._theme_toggle.clicked.connect(self._on_theme_toggle_clicked)
        wordmark_row.addWidget(self._theme_toggle)
        layout.addLayout(wordmark_row)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: dict[str, QPushButton] = {}

        for key, label in _NAV_PAGES:
            button = _build_nav_button(key, label)
            self._nav_group.addButton(button)
            self._nav_buttons[key] = button
            button.clicked.connect(
                lambda _checked=False, key=key: self._show_page(key)
            )
            layout.addWidget(button)

        layout.addStretch()

        help_button = _build_nav_button("help", "Help")
        self._nav_group.addButton(help_button)
        self._nav_buttons["help"] = help_button
        help_button.clicked.connect(lambda: self._show_page("help"))
        layout.addWidget(help_button)

        # Directly below Help, same individually-built pattern (a simple
        # _show_page(key) lambda, no initial-tab-aware handler needed).
        support_button = _build_nav_button("support", "Support")
        self._nav_group.addButton(support_button)
        self._nav_buttons["support"] = support_button
        support_button.clicked.connect(lambda: self._show_page("support"))
        layout.addWidget(support_button)

        # A page, not a separate dialog: in fullscreen, a second window
        # reads as a dead end with no way back to the shell. A real,
        # checkable, nav-group page like Help, just built individually
        # (like Help) rather than via the generic _NAV_PAGES loop, since
        # it needs the initial_tab-aware handler below, not the loop's
        # plain `_show_page(key)`.
        self.settings_button = _build_nav_button("settings", "Settings")
        self._nav_group.addButton(self.settings_button)
        self._nav_buttons["settings"] = self.settings_button
        self.settings_button.setToolTip(help_text.TOOLTIP_OPEN_SETTINGS)
        # clicked emits a bool (checked state) — never connect it
        # directly to _on_settings_clicked, whose first real parameter
        # is initial_tab, not a checked flag.
        self.settings_button.clicked.connect(
            lambda: self._on_settings_clicked()  # noqa: PLW0108
        )
        layout.addWidget(self.settings_button)

        return sidebar

    # --- Theme mode ------------------------------------------------------

    def _on_theme_toggle_clicked(self) -> None:
        current_index = _THEME_MODE_CYCLE.index(self._theme_mode)
        next_mode = _THEME_MODE_CYCLE[
                (current_index + 1) % len(_THEME_MODE_CYCLE)
        ]
        self._apply_theme_mode(next_mode)

    def _apply_theme_mode(self, mode: str, persist: bool = True) -> None:
        """The one entry point every theme-mode change routes through —
        the sidebar toggle, Settings' three-way radio control, and the
        system `colorSchemeChanged` signal (when subscribed) all call
        this, never `theme.apply_theme()` directly. Keeps the toggle
        icon, Settings' own radios, and the persisted config in sync in
        every direction.

        Ordering is load-bearing, not cosmetic. `self._theme_mode` is
        set and the system-scheme subscription is synced BEFORE
        `theme.apply_theme()` runs, so an explicit light/dark choice has
        already disconnected `_on_system_color_scheme_changed` by the
        time `apply_theme()`'s own `setColorScheme()` call emits
        `colorSchemeChanged`; a still-connected handler would re-apply
        the SYSTEM palette mid-call while the mode, icon and settings
        showed the requested one. `_applying_theme` is a second,
        independent guard for the "system" -> "system" path, where the
        subscription legitimately stays connected throughout. See
        HISTORY §109.
        """
        self._theme_mode = mode
        self._sync_system_scheme_subscription()

        app = QApplication.instance()
        assert isinstance(app, QApplication)
        self._applying_theme = True
        try:
            theme.apply_theme(app, mode)
        finally:
            self._applying_theme = False

        if persist:
            self.application.set_theme_mode(mode)

        self._theme_toggle.set_mode(mode)
        self.settings_page.sync_theme_mode(mode)
        self.on_theme_changed()

    def _sync_system_scheme_subscription(self) -> None:
        # Subscribed ONLY while mode is "system": an explicit light/dark
        # choice must never be silently overridden by the OS flipping
        # its own appearance later.
        style_hints = QGuiApplication.styleHints()
        if self._theme_mode == "system" and not self._system_scheme_connected:
            style_hints.colorSchemeChanged.connect(
                self._on_system_color_scheme_changed
            )
            self._system_scheme_connected = True
        elif self._theme_mode != "system" and self._system_scheme_connected:
            style_hints.colorSchemeChanged.disconnect(
                self._on_system_color_scheme_changed
            )
            self._system_scheme_connected = False

    def _on_system_color_scheme_changed(self, scheme: object) -> None:
        # The OS flipped appearance while mode == "system" — re-resolve
        # rather than reading `scheme` directly, so this stays correct
        # even if Qt's own Unknown-scheme fallback (DARK) is in play.
        #
        # Two independent bail-outs, since a handler that re-applies
        # unconditionally breaks on the next re-entrancy path:
        # `_theme_mode != "system"` (the subscription should already be
        # disconnected whenever this is true, but a handler must not
        # depend on that alone) and `_applying_theme` (this signal
        # firing as a direct side effect of `_apply_theme_mode`'s own
        # in-flight `theme.apply_theme()` call, not a genuine later OS
        # change).
        if self._theme_mode != "system" or self._applying_theme:
            return
        self._apply_theme_mode("system", persist=False)

    def on_theme_changed(self) -> None:
        """Re-applies anything that bakes a color
        into a specific widget instance rather than reading it fresh
        through the global stylesheet (see theme.py's own module
        docstring for the taxonomy). QSS-driven widgets need nothing
        here — `QApplication.setStyleSheet()` (already called by
        `_apply_theme_mode` above) re-polishes every one of them
        automatically.
        """
        # The wordmark is a QLabel#wordmark, re-polished by
        # `_apply_theme_mode`'s `setStyleSheet()` call; nothing to do
        # here for it.
        self._theme_toggle.update()

        # The accent colours baked into table items are re-computed on
        # every one of these render calls, which the 2s poll_timer
        # already re-runs regularly (self-healing within ~2s) — but
        # re-running them here too means the switch is correct
        # IMMEDIATELY, not after up to a 2s wait.
        self._dashboard_page.poll_selected_playlist()
        self._downloads_page.poll_active_downloads()
        self._review_page.poll_review_items()
        self._render_activity_strip()

    def _update_nav_badge(self, key: str, count: int) -> None:
        label = dict(_NAV_PAGES).get(key) or key.capitalize()
        button = self._nav_buttons[key]
        button.setText(f"{label}  ({count})" if count > 0 else label)

    def _build_view_menu(self) -> None:
        # ⌘1-⌘7 for the nav pages, plus ⌘R refresh, ⌘F focus search and
        # ⌘, Settings, all surfaced here for discoverability rather than
        # left as invisible shortcuts.
        view_menu = self.menuBar().addMenu("&View")

        for index, (key, label) in enumerate(_NAV_PAGES, start=1):
            action = QAction(label, self)
            action.setShortcut(QKeySequence(f"Ctrl+{index}"))
            action.triggered.connect(
                lambda _checked=False, key=key: self._show_page(key)
            )
            view_menu.addAction(action)

        view_menu.addSeparator()

        refresh_action = QAction("Refresh", self)
        refresh_action.setShortcut(QKeySequence("Ctrl+R"))
        # The pages are built after the menus, so the lookup waits for
        # the shortcut.
        refresh_action.triggered.connect(
            lambda _checked=False: self._dashboard_page.refresh_playlists()
        )
        view_menu.addAction(refresh_action)

        focus_search_action = QAction("Focus Search", self)
        focus_search_action.setShortcut(QKeySequence("Ctrl+F"))
        focus_search_action.triggered.connect(self._on_focus_search_clicked)
        view_menu.addAction(focus_search_action)

        view_menu.addSeparator()

        toggle_theme_action = QAction("Toggle Theme", self)
        toggle_theme_action.triggered.connect(self._on_theme_toggle_clicked)
        view_menu.addAction(toggle_theme_action)

        # triggered emits a bool — _on_settings_clicked's first real
        # parameter is initial_tab, not a checked flag (same reasoning
        # as settings_button's own connection in _build_sidebar).
        settings_action = QAction("Settings…", self)
        settings_action.setShortcut(
            QKeySequence(QKeySequence.StandardKey.Preferences)
        )
        settings_action.triggered.connect(
            lambda: self._on_settings_clicked()  # noqa: PLW0108
        )
        view_menu.addAction(settings_action)

    def _on_focus_search_clicked(self) -> None:
        self._show_page("search")
        self._search_page.search_artist_edit.setFocus()

    def _build_window_menu(self) -> None:
        # The standard macOS Window-menu pair; Qt supplies the rest of
        # the app's window management for free.
        window_menu = self.menuBar().addMenu("&Window")

        minimize_action = QAction("Minimize", self)
        minimize_action.setShortcut(QKeySequence("Ctrl+M"))
        minimize_action.triggered.connect(self.showMinimized)
        window_menu.addAction(minimize_action)

        zoom_action = QAction("Zoom", self)
        zoom_action.triggered.connect(self._on_zoom_clicked)
        window_menu.addAction(zoom_action)

    def _on_zoom_clicked(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _build_help_menu(self) -> None:
        menu_bar = self.menuBar()
        help_menu = menu_bar.addMenu("&Help")

        about_action = QAction(help_text.ABOUT_MENU_TEXT, self)
        about_action.triggered.connect(self._on_about_clicked)
        help_menu.addAction(about_action)

        # Real, live GitHub call — user-triggered ONLY (this one menu
        # action), never on a timer or anywhere near startup/
        # construction. See update_check.py's own docstring for why.
        self.check_for_updates_action = QAction(
            help_text.CHECK_FOR_UPDATES_MENU_TEXT, self,
        )
        self.check_for_updates_action.triggered.connect(
            self._on_check_for_updates_clicked
        )
        help_menu.addAction(self.check_for_updates_action)

    def _on_about_clicked(self) -> None:
        dialog = AboutDialog(self)
        dialog.exec()

    def _on_check_for_updates_clicked(self) -> None:
        self.check_for_updates_action.setEnabled(False)
        run_worker(
            self.thread_pool,
            check_for_update,
            on_finished=self._show_update_check_result,
            on_error=self._on_update_check_error,
        )

    def _show_update_check_result(self, result: UpdateCheckResult) -> None:
        self.check_for_updates_action.setEnabled(True)

        box = QMessageBox(self)
        box.setWindowTitle(help_text.UPDATE_CHECK_DIALOG_TITLE)
        # The version, URL and reason come from GitHub's response.
        box.setTextFormat(Qt.TextFormat.PlainText)

        if result.status == UpdateStatus.UP_TO_DATE:
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(
                f"You're up to date (v{result.installed_version})."
            )
        elif result.status == UpdateStatus.UPDATE_AVAILABLE:
            box.setIcon(QMessageBox.Icon.Information)
            text = (
                f"A new version is available: {result.latest_version} "
                f"(you have v{result.installed_version})."
            )
            if result.release_url:
                text = (
                    f"{html.escape(text)}<br>"
                    f'<a href="{html.escape(result.release_url)}">'
                    f"View the release</a>"
                )
                box.setTextFormat(Qt.TextFormat.RichText)
            box.setText(text)
        elif result.status == UpdateStatus.NO_RELEASES_PUBLISHED:
            # A repo with nothing published yet isn't a fault, so this
            # gets its own honest, un-alarming rendering rather than
            # falling into the UNAVAILABLE branch's Warning icon and
            # "Couldn't check for updates:" framing.
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(result.reason or "No releases have been published yet.")
        else:
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(f"Couldn't check for updates: {result.reason}")

        box.exec()

    def _on_update_check_error(self, message: str) -> None:
        # check_for_update() itself never raises (see its own
        # docstring) — this only exists as a defensive fallback for a
        # failure in run_worker's own dispatch, not an expected path.
        self.check_for_updates_action.setEnabled(True)
        plain_text.warning(
            self, help_text.UPDATE_CHECK_DIALOG_TITLE,
            f"Couldn't check for updates: {message}",
        )

    def _on_page_changed(self, index: int) -> None:
        # Refreshed on every show (a location added since the last visit
        # must appear): the Qt/GIL deadlock came from fetching at
        # MainWindow *construction* time, and a page SHOW is a
        # different, human-paced trigger (HISTORY §39). Leaving Settings
        # calls this same method directly.
        if index == self._duplicates_page_index:
            self._duplicates_page.refresh_locations()
            self._duplicates_page.refresh_milestone()

        if index == self._sharing_page_index:
            self._sharing_page.on_shown()

        if index == self._history_page_index and not self._history_loaded:
            self._history_loaded = True
            self._history_page.refresh_history()

        if index == self._settings_page_index:
            self.settings_page.refresh_login_item_state()

    def _trigger_backend_poll(self) -> None:
        if self._backend_poll_in_progress:
            # A previous poll_downloads() call (real slskd network
            # calls) is still running — a slow or hanging response must
            # not cause a second, overlapping writer to start on top of
            # it. Skip this tick; the next one will try again.
            return

        if not self.application.soulseek_configured:
            return

        self._backend_poll_in_progress = True

        def poll() -> SlskdUnreachableError | None:
            # Returned, not raised: on_error only receives text, and an
            # outage is state to show, not an error to report.
            try:
                self.application.download_service.poll_downloads()
            except SlskdUnreachableError as outage:
                return outage
            return None

        def on_poll_finished(outage: SlskdUnreachableError | None) -> None:
            self._backend_poll_in_progress = False

            if outage is None:
                self.slskd_status.mark_reachable()
            elif self.slskd_status.mark_unreachable(str(outage)):
                self._tray.notify_outage(str(outage))

            self._downloads_page.sample_download_progress()
            # A settled download completing during this real poll (Phase
            # 1's indexing fix) flips a track straight to IN_LIBRARY —
            # refresh the selected playlist's own track table right now
            # rather than waiting up to POLL_INTERVAL_MS for the next
            # 2s display tick to happen to catch it.
            self._dashboard_page.poll_selected_playlist()
            # Checked on the same real 20s cycle that can actually
            # produce a newly-completed download, not a new timer of its
            # own.
            self._tray.check_for_download_notifications()

        def on_poll_error(message: str) -> None:
            self._backend_poll_in_progress = False
            self._tray.notify_error(message)

        run_worker(
            self.thread_pool,
            poll,
            on_finished=on_poll_finished,
            on_error=on_poll_error,
        )

    def _run_busy_worker(
            self,
            key: str,
            button: QPushButton,
            fn: Callable[[], Any] | Callable[[Callable[[str, int, int], None]], Any],
            *,
            busy_text: str | None = None,
            status_label: QLabel | None = None,
            on_finished: Callable[[Any], None] | None = None,
            on_error: Callable[[str], None] | None = None,
            reports_progress: bool = False,
    ) -> None:
        # The shared shape for a long-running action that should
        # register in busy_actions/the activity strip: begin() before
        # submitting, end() on every real completion path (success or
        # error) so it's never left marked running past its own task.
        # The registry, not run_worker, owns the button's enable/disable
        # and text for the duration.
        self.busy_actions.begin(key, button, busy_text)
        self._render_activity_strip()

        def wrapped_finished(result: Any) -> None:
            self.busy_actions.end(key)
            self._activity_progress.pop(key, None)
            self._render_activity_strip()
            if on_finished is not None:
                on_finished(result)

        def wrapped_error(message: str) -> None:
            self.busy_actions.end(key)
            self._activity_progress.pop(key, None)
            self._render_activity_strip()
            if on_error is not None:
                on_error(message)

        run_worker(
            self.thread_pool, fn, status_label=status_label,
            on_finished=wrapped_finished, on_error=wrapped_error,
            on_progress=(
                (lambda stage, current, total:
                 self._on_activity_progress(key, stage, current, total))
                if reports_progress else None
            ),
        )

    def _on_settings_clicked(self, initial_tab: str | None = None) -> None:
        # self.settings_page is a single, long-lived page built once in
        # _build_ui(), never constructed-and-discarded, so it needs no
        # held reference of its own.
        if initial_tab is not None:
            self.settings_page.select_tab(initial_tab)

        self._show_page("settings")

    # --- The window lifecycle (ui/window_lifecycle.py) ------------------
    #
    # The tray/notification group lives in `ui/tray.py`'s
    # `TrayController` (`self._tray`); geometry, hide-to-tray and quit
    # live in `ui/window_lifecycle.py`'s `WindowLifecycleController`
    # (`self._lifecycle`). What stays here is what only this QObject
    # can do: the Qt event overrides, the event filter on the
    # QApplication, and `_on_application_state_changed`, the real
    # QObject-bound slot `applicationStateChanged` is connected to
    # (see that connect() call's own comment) — a plain Python
    # object's method can't hold that connection safely.

    def show_restored(self) -> None:
        """Show the window filled or windowed, the way it was closed."""
        self._lifecycle.show_restored()

    def reopen(self) -> None:
        """Bring the window back from the menu bar."""
        self._lifecycle.reopen()

    def start_hidden_to_tray(self) -> bool:
        """Start in the menu bar without ever showing the window;
        False when there is no tray icon to start behind."""
        return self._lifecycle.start_hidden_to_tray()

    def _on_application_state_changed(
            self, state: Qt.ApplicationState,
    ) -> None:
        self._tray.on_application_state_changed(state)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # Installed on the QApplication instance itself (see __init__'s
        # own comment on this same mechanism); every other event passes
        # through untouched via the base implementation, same pattern as
        # any other QObject-level filter in this codebase would use.
        if (
            watched is QApplication.instance()
            and event.type() == QEvent.Type.Quit
        ):
            return not self._lifecycle.confirm_quit_if_downloads_active()
        return super().eventFilter(watched, event)

    def cleanup_before_quit(self) -> None:
        # Connected to QApplication.aboutToQuit in main_ui.py: the one
        # cleanup path every quit route reaches.
        self._lifecycle.cleanup_before_quit()

    def _release_for_quit(self) -> None:
        # The shell's own part of cleanup_before_quit (see
        # WindowLifecycleHost.release_shell).
        self.poll_timer.stop()
        self.backend_poll_timer.stop()

        # Unlike window geometry, there is no hide-to-tray visibility
        # race to guard against: the Review page's splitter keeps
        # reporting its real current sizes whether or not MainWindow
        # itself is visible, since hiding to the tray never destroys
        # either widget. Unconditional, unlike the lifecycle's
        # `_hidden_to_tray` gate on geometry.
        self._review_page.persist_splitter_state()

        # A real Qt signal connection to a GLOBAL object
        # (QGuiApplication.styleHints(), not this window), so it must be
        # torn down explicitly rather than relying on this window's own
        # destruction to drop it.
        if self._system_scheme_connected:
            QGuiApplication.styleHints().colorSchemeChanged.disconnect(
                self._on_system_color_scheme_changed
            )
            self._system_scheme_connected = False

        # Same reasoning as _system_scheme_connected just above: a
        # connection to the GLOBAL QApplication instance, not this
        # window. Disconnects the same MainWindow-owned stub that was
        # connected in __init__ (see that connect() call's own comment
        # for why it's not `self._tray.on_application_state_changed`
        # directly).
        if self._app_state_connected:
            app = QApplication.instance()
            if app is not None:
                assert isinstance(app, QGuiApplication)
                app.applicationStateChanged.disconnect(
                    self._on_application_state_changed
                )
            self._app_state_connected = False

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._lifecycle.after_show()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._lifecycle.close_event(event)
