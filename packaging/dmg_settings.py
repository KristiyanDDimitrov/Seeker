"""dmgbuild settings for the seeker-ui distributable .dmg installer.

Verified against dmgbuild 1.6.7's real, current settings-file API
(https://dmgbuild.readthedocs.io/en/latest/settings.html and
.../example.html, cross-checked against the installed package's own
dmgbuild/core.py — every option name assigned below is one of that
module's real `options` dict keys) rather than written from memory.
A settings file is dmgbuild's own `exec()`'d Python script — every
top-level name assigned here becomes (or overrides) one of those
options; `defines` is injected by dmgbuild itself from `-D key=value`
CLI flags, not something this file defines.

Usage (see packaging/build_dmg.py for the one-command version):

    uv run pyinstaller --noconfirm --clean packaging/seeker.spec
    uv run dmgbuild -s packaging/dmg_settings.py -Dapp=dist/Seeker.app \
        Seeker dist/Seeker.dmg
"""

import os.path

application = defines.get("app", "dist/Seeker.app")  # noqa: F821 — injected by dmgbuild
appname = os.path.basename(application)

# Item 4 (packaging polish): a plain-text first-launch note, alongside
# the app inside the volume — the "right-click -> Open" Gatekeeper
# workaround, spelled out for someone who's never hit it before. Not a
# substitute for real notarization (still out of scope — see
# seeker.spec's own docstring), just documentation for the friction
# that comes with skipping it.
readme = defines.get(  # noqa: F821 — injected by dmgbuild
    "readme", "packaging/Read Me First.txt",
)
readme_name = os.path.basename(readme)

format = defines.get("format", "UDBZ")  # noqa: F821 — bzip2-compressed, read-only
filesystem = "HFS+"

files = [application, readme]
symlinks = {"Applications": "/Applications"}

# The .dmg volume's own icon (shown in Finder's sidebar and on the
# mounted volume itself). Resolved the same way `readme` is above —
# dmgbuild `exec()`'s this file with no `__file__` in scope, so the
# path is relative to the caller's cwd (packaging/build_dmg.py runs
# with cwd=PROJECT_ROOT), not this file's own location.
icon = defines.get("icon", "packaging/icons/seeker_icon.icns")  # noqa: F821

window_rect = ((100, 100), (640, 400))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
show_icon_preview = True

icon_size = 128
text_size = 16
label_pos = "bottom"

# The one concrete layout ask for this pass: the app and the
# /Applications symlink side by side, so a drag-to-install is obvious
# the moment the volume opens, with the first-launch README below them.
# A background image is optional polish, not attempted here.
icon_locations = {
    appname: (160, 160),
    "Applications": (480, 160),
    readme_name: (320, 300),
}
