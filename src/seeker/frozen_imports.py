"""Modules a frozen build must bundle that PyInstaller cannot find.

`packaging/seeker.spec` passes these as `hiddenimports`, and
`seeker-ui --smoke-test` imports each on macOS, so the two read one
list. Each is imported only inside a function, which PyInstaller's
import scanner does not follow: `ui/tray.py`'s `from AppKit import ...`
(the Dock-icon-hiding activation-policy switch) and `login_item.py`'s
`from ServiceManagement import ...`; `Foundation` and `objc` are the
pyobjc modules they rest on. It also lists the package's own modules
for the bundle's manifest (HISTORY §257). This module imports only the
standard library, so the spec can import it at build time.
"""

from pathlib import Path

HIDDEN_IMPORTS = ("AppKit", "Foundation", "objc", "ServiceManagement")


MANIFEST_NAME = "module_manifest.txt"
"""The file the spec writes at the bundle's root: one module name a
line. Frozen, `pkgutil.walk_packages` lists only what PyInstaller
bundled, so a module its analysis missed would never be listed; the
smoke test's import check compares its walk with this list."""

NOT_BUNDLED = frozenset({"seeker.cli", "seeker.main"})
"""The CLI's modules: the entry point is `seeker-ui`, and nothing in it
imports them, so the frozen app has no use for them (observed 2026-11-02,
HISTORY §257: the one build whose PYZ was compared held every other
module)."""


def source_modules(package_dir: Path) -> frozenset[str]:
    """Every module under `package_dir` (the `seeker` folder) that a
    frozen build is expected to hold."""
    names = set()
    for file in package_dir.rglob("*.py"):
        parts = file.relative_to(package_dir.parent).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        names.add(".".join(parts))
    return frozenset(names) - NOT_BUNDLED
