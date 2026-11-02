"""Modules a frozen build must bundle that PyInstaller cannot find.

`packaging/seeker.spec` passes these as `hiddenimports`, and
`seeker-ui --smoke-test` imports each on macOS, so the two read one
list. Each is imported only inside a function, which PyInstaller's
import scanner does not follow: `ui/tray.py`'s `from AppKit import ...`
(the Dock-icon-hiding activation-policy switch) and `login_item.py`'s
`from ServiceManagement import ...`; `Foundation` and `objc` are the
pyobjc modules they rest on. This module imports nothing, so the spec
can import it at build time.
"""

HIDDEN_IMPORTS = ("AppKit", "Foundation", "objc", "ServiceManagement")
