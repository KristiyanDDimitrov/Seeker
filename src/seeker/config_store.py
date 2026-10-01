import json
import logging
import os
from dataclasses import Field, asdict, dataclass, fields, replace
from pathlib import Path
from typing import get_args

import platformdirs

from seeker.files.atomic import write_text_locked

logger = logging.getLogger(__name__)


@dataclass
class SeekerConfig:
    slskd_base_url: str | None = None
    slskd_api_key: str | None = None
    slskd_download_dir: str | None = None
    spotify_client_id: str | None = None
    spotify_redirect_uri: str | None = None
    # SoulSeek NETWORK login — plain text in this file (0600, see
    # save_config).
    slskd_username: str | None = None
    slskd_password: str | None = None
    # The slskd WEB UI login — distinct from slskd_username/password
    # above, despite the name (soulseek/docker_setup.py documents this naming
    # trap). Generated once by Application.ensure_slskd_web_credentials()
    # and never rotated silently afterward. HISTORY §23, §116.
    slskd_web_username: str | None = None
    slskd_web_password: str | None = None
    # None means "use matching.py's hardcoded default" — same
    # unset-means-unchanged discipline as every optional override in
    # this codebase (e.g. the BPM-range feature). Resolved per-call by
    # TrackMatcher/DownloadService, never cached at import time.
    auto_match_threshold: float | None = None
    needs_review_threshold: float | None = None
    # A playlist-specific download_location_id/download_subfolder still
    # wins when set — this is only the fallback once neither is. None
    # means "no default configured yet."
    default_download_location_id: int | None = None
    default_download_subfolder_per_playlist: bool = True
    # Checked inside DownloadService.poll_downloads() itself (not just
    # the UI's own timer), so pausing is authoritative regardless of
    # caller. Persisted so a paused session doesn't silently resume on
    # restart.
    downloads_paused: bool = False
    # Shown at most once, ever: the first time the window is hidden to
    # the menu bar instead of closed.
    tray_hide_notice_shown: bool = False
    # Per-category notification toggles, all defaulting on.
    notify_downloads_finished: bool = True
    notify_needs_decision: bool = True
    notify_errors: bool = True
    # "system" (default), "light", or "dark". An unrecognized value (a
    # garbage/future-version string) falls back to "system" at LOAD
    # time (see _resolve_theme_mode below) rather than raising or
    # propagating a bad value into theme.py.
    theme_mode: str = "system"
    # Round 8 §12.1 — base64 of QMainWindow.saveGeometry()'s QByteArray
    # (size, position, maximized/fullscreen state). Written once, at
    # real quit (MainWindow.cleanup_before_quit), never on every
    # resize/move — restoreGeometry() tolerates a missing/corrupt value
    # by leaving the window at its hardcoded default, so no validation
    # is needed here.
    window_geometry: str | None = None
    # The nav sidebar key (e.g. "dashboard") shown when the window was
    # last closed. An unrecognized value (a key a later version removed)
    # is ignored at restore time the same way theme_mode's own garbage
    # value is — falls back to the hardcoded "dashboard" default.
    last_open_page: str | None = None
    # Round 9 §3.2 — whether "start at login" is on lives entirely in
    # macOS's own ServiceManagement registration (login_item.py reads
    # it live, never mirrored here — a user revoking it in System
    # Settings must not leave a stale True behind). This field is only
    # the companion "start hidden in the menu bar" preference, which
    # has no equivalent platform-owned state of its own. Defaulted to
    # True by the Settings checkbox the moment login-at-startup is
    # first enabled, but stored independently and always overridable.
    start_hidden_at_login: bool = False
    # Round 9 §6 — base64 of the Review page's three-section
    # QSplitter.saveState() (proportions between needs-review/upgrades/
    # local-matches). Written once, at real quit
    # (MainWindow.cleanup_before_quit reaching into ReviewPage, same
    # seam it already uses for other page-owned state), never on every
    # drag — restoreState() tolerates a missing/corrupt value by
    # leaving the splitter at its hardcoded first-run proportions, so
    # no validation is needed here.
    review_splitter_state: str | None = None
    # Round 10 §5 — whether the window was closed fullscreen or
    # maximized/zoomed, so a reopen (Dock/menu-bar icon) or a relaunch
    # can come back filling the screen as a normal window rather than
    # re-entering macOS fullscreen (Kris's decision, 2026-09-23: never
    # re-enter fullscreen on reopen — that transition is round 7's E1).
    # Mirrors window_geometry's own "written at real close, tolerant of
    # a missing key" shape; WindowLifecycleController.restore_window_geometry() is
    # the actual enforcement point, not this field alone (a saved
    # window_geometry blob from a fullscreen close still carries Qt's
    # own FullScreen state bit and has to be corrected there too).
    window_reopen_filled: bool = False


def resolve_config_path() -> Path:
    # Same per-user app-data directory the database lives in (see
    # application.py's _resolve_database_path) — one location, not two.
    data_dir = Path(platformdirs.user_data_dir("Seeker", appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)

    return data_dir / "config.json"


def _resolve_theme_mode(raw: object) -> str:
    if isinstance(raw, str) and raw in ("system", "light", "dark"):
        return raw
    return "system"


def load_config(path: Path) -> SeekerConfig:
    if not path.exists():
        return SeekerConfig()

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return SeekerConfig()

    if not isinstance(data, dict):
        return SeekerConfig()

    # Unknown keys (e.g. a field a later version removed) are ignored,
    # not an error — no migration/tolerance code is needed when a field
    # goes away. HISTORY §100. A missing or wrongly typed key takes the
    # field's default.
    values = {
        field.name: _checked_value(field, data[field.name])
        for field in fields(SeekerConfig)
        if field.name in data
    }
    loaded = SeekerConfig(**values)  # type: ignore[arg-type]

    return replace(loaded, theme_mode=_resolve_theme_mode(loaded.theme_mode))


def _checked_value(field: Field[object], raw: object) -> object:
    """`raw` when it matches the field's annotation, else the field's
    default. Deliberately narrow: `bool` is never accepted as an int
    (JSON `true` is not a location id), and an int is widened to float
    only for a float field."""
    allowed = get_args(field.type) or (field.type,)

    if raw is None and type(None) in allowed:
        return None

    if isinstance(raw, bool):
        matches = bool in allowed
    elif isinstance(raw, int) and float in allowed and int not in allowed:
        return float(raw)
    else:
        matches = any(
            isinstance(raw, kind) for kind in allowed
            if isinstance(kind, type) and kind is not bool
        )

    if matches:
        return raw

    # The type, never the value: some of these fields are credentials.
    logger.warning(
        "Ignoring config.json's %s: a %s, expected %s; using the default.",
        field.name, type(raw).__name__, field.type,
    )
    return field.default


def save_config(seeker_config: SeekerConfig, path: Path) -> None:
    # This file holds real SoulSeek/Spotify credentials — write_text_
    # locked() both locks it down (0600, a no-op on Windows) and makes
    # the write atomic, so a crash mid-write can't leave truncated JSON
    # in its place.
    write_text_locked(path, json.dumps(asdict(seeker_config), indent=2) + "\n")


# Field name -> the legacy .env var it was previously read from. Covers
# both SLSKD_* and SPOTIFY_* — one resolution chain for every field the
# store owns, not a second mechanism per field group.
_ENV_VAR_BY_FIELD = {
    "slskd_base_url": "SLSKD_BASE_URL",
    "slskd_api_key": "SLSKD_API_KEY",
    "slskd_download_dir": "SLSKD_DOWNLOAD_DIR",
    "spotify_client_id": "SPOTIFY_CLIENT_ID",
    "spotify_redirect_uri": "SPOTIFY_REDIRECT_URI",
}


def migrate_legacy_env_config(path: Path) -> SeekerConfig:
    # Never overwrite a value the store already has (guards against a
    # stale env var clobbering a value changed since via a future
    # Settings screen), copy in only fields the store is missing, no-op
    # (and no print) when there's nothing to migrate, idempotent on
    # repeat calls. The real .env file itself is never read from or
    # written to directly — only os.environ (already populated by
    # config.load_env_file() in the entry point) is read.
    seeker_config = load_config(path)
    migrated_fields = []

    for field_name, env_var in _ENV_VAR_BY_FIELD.items():
        if getattr(seeker_config, field_name) is not None:
            continue

        env_value = os.getenv(env_var)

        if not env_value:
            continue

        # _ENV_VAR_BY_FIELD only ever lists str-typed fields (env vars
        # are always strings) — mypy can't verify that statically once
        # SeekerConfig also has float-typed fields, since **kwargs here
        # is keyed by a runtime field_name string.
        seeker_config = replace(
            seeker_config, **{field_name: env_value},  # type: ignore[arg-type]
        )
        migrated_fields.append(env_var)

    if migrated_fields:
        save_config(seeker_config, path)
        logger.info(
            "Migrated config from .env to the local config store "
            "(%s): %s.", path, ", ".join(migrated_fields),
        )

    return seeker_config
