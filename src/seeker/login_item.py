"""macOS "start at login" integration (round 9 §3.2).

`SMAppService` (ServiceManagement.framework, macOS 13+) is Apple's
current-generation login-item API — it registers *this bundle's*
login item and shows up under System Settings -> General -> Login
Items, user-revocable there. The legacy alternative (a
`~/Library/LaunchAgents/*.plist`) was deliberately rejected: it needs
no new dependency and works from source, but writes an opaque file
into the user's home directory and surfaces as a background item
rather than a real, user-manageable Login Items entry.

`SMAppService.mainAppService()` only resolves against a real bundle
identifier — a `uv run seeker-ui` dev process has none, so this is
gated on `sys.frozen` (the same PyInstaller-bundle signal every other
frozen-only code path in this project already keys on — see
docker_setup.py's compose_file_path, tray.py's
_resolve_tray_icon_path) in addition to `sys.platform`. Confirmed live
on a real Darwin 25.6.0 dev machine (unbundled `uv run python`):
`SMAppService.mainAppService().status()` returns
`SMAppServiceStatusNotFound` (3) rather than raising, and
`registerAndReturnError_`/`unregisterAndReturnError_` are real bound
methods on the returned object — but `is_supported()` never lets a dev
run reach those calls at all, so what actually registering/
unregistering does against a genuine `.app` bundle is unverified here
and must be confirmed on a real packaged build.
"""

import enum
import logging
import sys

logger = logging.getLogger(__name__)


class LoginItemStatus(enum.Enum):
    NOT_SUPPORTED = "not_supported"
    DISABLED = "disabled"
    ENABLED = "enabled"
    REQUIRES_APPROVAL = "requires_approval"
    NOT_FOUND = "not_found"


def is_supported() -> bool:
    return sys.platform == "darwin" and getattr(sys, "frozen", False)


def get_status() -> LoginItemStatus:
    """The REAL, live status — never a mirrored `config.json` boolean
    (round 9 §3.2's own "honest state reporting" requirement: a user
    revoking the login item in System Settings must not leave Seeker's
    own checkbox still claiming it's on)."""
    if not is_supported():
        return LoginItemStatus.NOT_SUPPORTED

    # Deferred import — matches this project's established pattern for
    # its other genuine platform-only dependencies (tray.py's AppKit
    # import inside _set_dock_icon_visible, docker_setup.py's
    # TokenStore-inside-_load_token).
    from ServiceManagement import (  # noqa: PLC0415
        SMAppService,
        SMAppServiceStatusEnabled,
        SMAppServiceStatusNotFound,
        SMAppServiceStatusRequiresApproval,
    )

    status = SMAppService.mainAppService().status()

    if status == SMAppServiceStatusEnabled:
        return LoginItemStatus.ENABLED
    if status == SMAppServiceStatusRequiresApproval:
        return LoginItemStatus.REQUIRES_APPROVAL
    if status == SMAppServiceStatusNotFound:
        return LoginItemStatus.NOT_FOUND

    # SMAppServiceStatusNotRegistered — the ordinary "off" state.
    return LoginItemStatus.DISABLED


def set_enabled(enabled: bool) -> LoginItemStatus:
    """Register/unregister the login item and return the resulting
    real status. A no-op (returning NOT_SUPPORTED) off macOS or
    outside a packaged build — see `is_supported()`."""
    if not is_supported():
        return LoginItemStatus.NOT_SUPPORTED

    from ServiceManagement import SMAppService  # noqa: PLC0415

    service = SMAppService.mainAppService()

    if enabled:
        ok, error = service.registerAndReturnError_(None)
        if not ok:
            logger.error("Failed to register login item: %s", error)
    else:
        ok, error = service.unregisterAndReturnError_(None)
        if not ok:
            logger.error("Failed to unregister login item: %s", error)

    return get_status()
