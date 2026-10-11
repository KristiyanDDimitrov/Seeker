"""Measures the three window-reopen paths on a real Mac.

    uv run --no-project tools/window_checks.py [path/to/Seeker.app]

For release-candidate acceptance, run by a person with Seeker already
open from that bundle (default `/Applications/Seeker.app`). The
terminal needs Accessibility permission (System Settings → Privacy &
Security → Accessibility), or System Events refuses every query.

Each path prints the raw numbers it compares, and PASS or FAIL:

1. fullscreen close → reopen: the window fills the visible frame and
   is not fullscreen;
2. windowed resize → close → reopen: the same size comes back;
3. fullscreen close → quit from the tray → relaunch: as in 1.

A fullscreen window's close button is not in the accessibility tree
(HISTORY §116) and Seeker has no ⌘W, so paths 1 and 3 ask the person
to click it; the tray's Quit is clicked by hand for the same reason.
Reopen is `open <bundle>`, as a Dock click is UNVERIFIED to be
scriptable. A scripted `open` may leave the window behind the
terminal (HISTORY §116); sizes are read regardless.
"""
import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

PROCESS = "Seeker"
DEFAULT_BUNDLE = Path("/Applications/Seeker.app")
# Points of slack between a filled window and the screen's visible
# frame: the frame is fractional on a scaled display.
TOLERANCE = 2
WINDOWED_SIZE = (900, 650)


def osascript(script: str, *, language: str = "AppleScript") -> str:
    result = subprocess.run(
        ["/usr/bin/osascript", "-l", language, "-e", script],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def system_events(command: str) -> str:
    return osascript(
        'tell application "System Events" to tell process '
        f'"{PROCESS}" to {command}'
    )


def visible_frame() -> tuple[int, int]:
    width, height = json.loads(osascript(
        'ObjC.import("AppKit");'
        "var f = $.NSScreen.mainScreen.visibleFrame;"
        "JSON.stringify([f.size.width, f.size.height])",
        language="JavaScript",
    ))
    return round(width), round(height)


def window_size() -> tuple[int, int]:
    width, height = system_events("get size of window 1").split(", ")
    return int(width), int(height)


def is_fullscreen() -> bool:
    return system_events(
        'get value of attribute "AXFullScreen" of window 1'
    ) == "true"


def set_fullscreen(on: bool) -> None:
    value = "true" if on else "false"
    system_events(
        f'set value of attribute "AXFullScreen" of window 1 to {value}'
    )
    time.sleep(2)  # the macOS space transition


def application_type() -> str:
    # "Foreground" with a Dock tile, "UIElement" once hidden to the tray.
    result = subprocess.run(
        ["/usr/bin/lsappinfo", "info", "-only", "ApplicationType", PROCESS],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() or "(not running)"


def is_running() -> bool:
    return subprocess.run(
        ["/usr/bin/pgrep", "-x", PROCESS], capture_output=True, check=False,
    ).returncode == 0


def wait_for(condition: str, check: Callable[[], bool]) -> None:
    for _ in range(60):
        if check():
            return
        time.sleep(0.5)
    raise SystemExit(f"Timed out waiting for {condition}.")


def reopen(bundle: Path) -> None:
    subprocess.run(["/usr/bin/open", str(bundle)], check=True)

    def has_window() -> bool:
        try:
            return int(system_events("count windows")) > 0
        except subprocess.CalledProcessError:
            return False

    wait_for("a window", has_window)
    time.sleep(1)  # geometry settles after the first show


def ask(instruction: str) -> None:
    input(f"\n>>> {instruction}\n    Press Return when done. ")


def report(name: str, passed: bool, detail: str) -> bool:
    print(f"{'PASS' if passed else 'FAIL'}  {name}: {detail}")
    return passed


def check_filled(name: str) -> bool:
    frame = visible_frame()
    size = window_size()
    fullscreen = is_fullscreen()
    filled = all(
        abs(got - want) <= TOLERANCE
        for got, want in zip(size, frame, strict=True)
    )
    return report(
        name, filled and not fullscreen,
        f"window {size}, visible frame {frame}, fullscreen {fullscreen}",
    )


def path_fullscreen_close(bundle: Path) -> bool:
    set_fullscreen(True)
    ask(
        "Path 1: move the pointer to the top of the screen and click "
        "the red close button."
    )
    print(f"    after close: {application_type()}")
    reopen(bundle)
    return check_filled("fullscreen close → reopen")


def path_windowed_resize(bundle: Path) -> bool:
    if is_fullscreen():
        set_fullscreen(False)
    system_events("set position of window 1 to {120, 120}")
    system_events(
        f"set size of window 1 to {{{WINDOWED_SIZE[0]}, {WINDOWED_SIZE[1]}}}"
    )
    time.sleep(1)
    before = window_size()
    system_events(
        'click (first button of window 1 whose subrole is "AXCloseButton")'
    )
    wait_for("the hide to the tray", lambda: "UIElement" in application_type())
    reopen(bundle)
    after = window_size()
    return report(
        "windowed resize → close → reopen", after == before,
        f"before {before}, after {after}, fullscreen {is_fullscreen()}",
    )


def path_fullscreen_quit(bundle: Path) -> bool:
    set_fullscreen(True)
    ask(
        "Path 3: click the red close button at the top of the screen, "
        "then choose Quit Seeker from the menu-bar (tray) icon."
    )
    wait_for("Seeker to quit", lambda: not is_running())
    reopen(bundle)
    return check_filled("fullscreen close → quit → relaunch")


def main() -> int:
    bundle = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BUNDLE
    if not is_running():
        print(f"Open {bundle} first, then run this again.")
        return 2
    print(f"Bundle: {bundle}; visible frame {visible_frame()}")
    results = [
        path_fullscreen_close(bundle),
        path_windowed_resize(bundle),
        path_fullscreen_quit(bundle),
    ]
    print(f"\n{sum(results)} of {len(results)} paths passed.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
