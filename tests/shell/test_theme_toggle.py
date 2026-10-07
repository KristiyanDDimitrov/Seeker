"""The theme toggle and system-scheme following, and the wordmark's
rendering.
"""

from dataclasses import astuple

import pytest
from PySide6.QtWidgets import (
    QLabel,
)

from fakes import (
    FakeApplication,
)
from seeker.ui import theme
from seeker.ui.main_window import (
    _THEME_MODE_CYCLE,
    MainWindow,
)
from seeker.ui.widgets import ThemeToggleButton

# --- Roadmap item E4 (round 7): wordmark, plain QLabel, no brows ------------


def test_wordmark_bottom_row_has_no_text_colored_pixel(qtbot):
    # Roadmap item E4.5 (round 7) — the actual invariant the user cares
    # about, which the deleted `_Wordmark`'s own D1.3 test never
    # expressed (it asserted a `sizeHint()` number, not a real pixel):
    # nothing in the rendered label may touch its own bottom edge. A
    # plain QLabel reserves real font-metric ascent/descent internally,
    # so this holds structurally rather than by any hand-tuned padding
    # constant. Real pixel scan (item 77's own lesson — geometry alone
    # can't prove a paint result), not a geometry-only check.
    label = QLabel("Seeker")
    label.setObjectName("wordmark")
    qtbot.addWidget(label)
    from seeker.ui import theme as theme_module
    label.setStyleSheet(theme_module.build_stylesheet(theme_module.DARK))
    label.resize(label.sizeHint())
    label.show()
    qtbot.waitExposed(label)

    image = label.grab().toImage()
    text_rgb = tuple(int(theme.DARK.TEXT[i:i + 2], 16) for i in (1, 3, 5))
    bottom_row = image.height() - 1
    for x in range(image.width()):
        color = image.pixelColor(x, bottom_row)
        assert (color.red(), color.green(), color.blue()) != text_rgb, (
            f"text-colored pixel at x={x} on the label's own bottom "
            f"row — the wordmark is touching its own edge"
        )


# --- Roadmap item C5: light/dark themes, with system-follow -----------------

def test_theme_toggle_cycles_system_light_dark_and_persists(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._theme_mode == "system"
    assert window._theme_toggle._mode == "system"

    window._theme_toggle.click()
    assert window._theme_mode == "light"
    assert window._theme_toggle._mode == "light"

    window._theme_toggle.click()
    assert window._theme_mode == "dark"

    window._theme_toggle.click()
    assert window._theme_mode == "system"

    # Every click persists through Application.set_theme_mode — a
    # restart must not lose the choice.
    assert application.set_theme_mode_calls == ["light", "dark", "system"]


def test_theme_toggle_and_settings_radios_stay_in_sync_both_directions(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    # Sidebar toggle -> Settings radios.
    window._theme_toggle.click()  # system -> light
    assert window.settings_page._theme_mode_radios["light"].isChecked()
    assert not window.settings_page._theme_mode_radios["system"].isChecked()

    # Settings radios -> sidebar toggle.
    window.settings_page._theme_mode_radios["dark"].setChecked(True)
    assert window._theme_mode == "dark"
    assert window._theme_toggle._mode == "dark"


def test_theme_mode_starts_from_the_persisted_config_value(qtbot):
    application = FakeApplication()
    application.set_theme_mode("dark")

    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._theme_mode == "dark"
    assert window._theme_toggle._mode == "dark"
    assert window.settings_page._theme_mode_radios["dark"].isChecked()


def test_system_scheme_signal_only_connected_while_mode_is_system(qtbot):
    # Roadmap item C5.6 — an explicit light/dark choice must never be
    # silently overridden by the OS's own appearance changing later.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._system_scheme_connected is True

    window._theme_toggle.click()  # system -> light, an explicit choice
    assert window._theme_mode == "light"
    assert window._system_scheme_connected is False

    window._theme_toggle.click()  # light -> dark, still explicit
    assert window._system_scheme_connected is False

    window._theme_toggle.click()  # dark -> system, back to following
    assert window._system_scheme_connected is True


def test_cleanup_before_quit_disconnects_the_system_scheme_signal(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    assert window._system_scheme_connected is True

    window.cleanup_before_quit()

    assert window._system_scheme_connected is False


# --- Roadmap item C5.8 — the palettes' own contrast floors are tested in
# test_theme.py directly; DARK's real-values-unchanged claim is checked
# structurally here. -------------------------------------------------------

@pytest.mark.parametrize(
        ("palette", "expected"),
        [
            (theme.DARK, (
                "#17191C", "#101113", "#1E2125", "#282C31", "#353A40",
                "#4C535B", "#E8EAEC", "#A0A7AE", "#737B83", "#9A7DFF",
                "#AA91FF", "#8A6BF5", "#262236", "#35D07F", "#FFB020",
                "#FF6363", "#120E1F",
            )),
            (theme.LIGHT, (
                "#E8EAEC", "#DDE0E3", "#F9FAFA", "#F0F2F3", "#CBD0D5",
                "#9BA3AB", "#15181B", "#4D555D", "#757D85", "#6440E6",
                "#5734D6", "#4A2BBD", "#E9E4FB", "#11804A", "#9E5C00",
                "#C22B2B", "#FFFFFF",
            )),
        ],
        ids=["dark", "light"],
)
def test_palettes_carry_the_approved_tokens(palette, expected):
    # The literal values of docs/design/visual-direction.md's approved
    # direction (Booth, violet accent), in Palette's field order: a
    # pin, not a restatement of whatever theme.py currently says.
    assert astuple(palette) == expected


def test_apply_theme_with_dark_mode_produces_the_same_stylesheet_as_before(
        qtbot,
):
    # A real structural no-op check: resolve_palette("dark") must be
    # the exact same Palette object DARK already is (not a re-typed
    # copy that happens to compare equal).
    assert theme.resolve_palette("dark") is theme.DARK


# --- Roadmap item C5.10 — the theme toggle's own glyph rendering ------------

def test_theme_toggle_button_renders_all_three_modes_without_crashing(qtbot):
    for mode in _THEME_MODE_CYCLE:
        button = ThemeToggleButton(mode)
        qtbot.addWidget(button)
        button.show()
        qtbot.wait(10)
        assert button.toolTip() != ""


# --- Roadmap item D2 (round 6): the theme toggle actually applying -------
#
# D2.1's real finding: `QGuiApplication.styleHints().setColorScheme()`
# never actually changes `.colorScheme()` or emits `colorSchemeChanged`
# under the offscreen QPA platform this whole suite runs on (confirmed
# empirically, not assumed) — so the real re-entrancy bug (a live macOS
# `colorSchemeChanged` firing synchronously from INSIDE
# `theme.apply_theme()`'s own `setColorScheme()` call) cannot be forced
# through the real signal in a headless test the way it happens on a
# real Mac. The tests below exercise the actual fix mechanics directly
# instead: D2.2's reordering (behavioral — the stylesheet itself, not
# just the mode string/icon) and D2.3/D2.4's guard conditions.

def test_theme_toggle_actually_changes_the_applied_stylesheet(qtbot):
    # This is exactly the behavior D2 reports as broken: the mode
    # string and icon updated while the real stylesheet did not. Assert
    # the stylesheet itself, not just `window._theme_mode`.
    from PySide6.QtWidgets import QApplication

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    app = QApplication.instance()
    assert app is not None

    window._theme_toggle.click()  # system -> light
    assert theme.BG_SURFACE == theme.LIGHT.BG_SURFACE
    assert theme.LIGHT.BG_SURFACE in app.styleSheet()

    window._theme_toggle.click()  # light -> dark
    assert theme.BG_SURFACE == theme.DARK.BG_SURFACE
    assert theme.DARK.BG_SURFACE in app.styleSheet()

    window._theme_toggle.click()  # dark -> system
    resolved = theme.resolve_palette("system")
    assert theme.BG_SURFACE == resolved.BG_SURFACE
    assert resolved.BG_SURFACE in app.styleSheet()


def test_apply_theme_mode_survives_a_synchronous_scheme_signal_mid_apply(
        qtbot, monkeypatch,
):
    # Roadmap item D2.2/D2.3 — simulates the real defect directly: a
    # `colorSchemeChanged` emission firing SYNCHRONOUSLY from inside
    # `theme.apply_theme()`'s own `setColorScheme()` call, which is
    # exactly what a real macOS run does and the offscreen QPA plugin
    # does not (see the module comment above). Before the D2 fix, this
    # re-entrant call would re-resolve and silently reapply the SYSTEM
    # palette over the explicit "light" choice this call is making.
    from PySide6.QtWidgets import QApplication

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    real_apply_theme = theme.apply_theme

    def apply_theme_with_synchronous_signal(app, mode):
        result = real_apply_theme(app, mode)
        # A stray real-world signal arriving mid-call, regardless of
        # what triggered it — the guard must hold regardless of cause.
        window._on_system_color_scheme_changed(object())
        return result

    monkeypatch.setattr(
            theme,
            "apply_theme",
            apply_theme_with_synchronous_signal,
    )

    window._apply_theme_mode("light")

    assert window._theme_mode == "light"
    assert theme.BG_SURFACE == theme.LIGHT.BG_SURFACE
    app = QApplication.instance()
    assert app is not None
    assert theme.LIGHT.BG_SURFACE in app.styleSheet()


def test_system_scheme_handler_ignored_while_theme_is_being_applied(qtbot):
    # Roadmap item D2.3 — the `_applying_theme` guard directly, with no
    # dependency on whether the offscreen platform can emit the signal.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    calls: list[tuple[object, ...]] = []
    window._apply_theme_mode = lambda *a, **k: calls.append(a)  # type: ignore[method-assign]
    window._applying_theme = True

    window._on_system_color_scheme_changed(object())

    assert calls == []


def test_system_scheme_handler_ignored_once_mode_is_no_longer_system(qtbot):
    # Roadmap item D2.4 — the handler must not act just because it's
    # still connected; it must check the CURRENT mode too, not rely
    # solely on the subscription having been torn down in time.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._theme_mode = "light"
    calls: list[tuple[object, ...]] = []
    window._apply_theme_mode = lambda *a, **k: calls.append(a)  # type: ignore[method-assign]

    window._on_system_color_scheme_changed(object())

    assert calls == []
