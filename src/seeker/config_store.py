import json
import logging
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import platformdirs

from seeker.atomic_file import write_text_locked

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
    # above, despite the name (docker_setup.py documents this naming
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
    # goes away. HISTORY §100.
    return SeekerConfig(
        slskd_base_url=data.get("slskd_base_url"),
        slskd_api_key=data.get("slskd_api_key"),
        slskd_download_dir=data.get("slskd_download_dir"),
        spotify_client_id=data.get("spotify_client_id"),
        spotify_redirect_uri=data.get("spotify_redirect_uri"),
        slskd_username=data.get("slskd_username"),
        slskd_password=data.get("slskd_password"),
        slskd_web_username=data.get("slskd_web_username"),
        slskd_web_password=data.get("slskd_web_password"),
        auto_match_threshold=data.get("auto_match_threshold"),
        needs_review_threshold=data.get("needs_review_threshold"),
        default_download_location_id=data.get("default_download_location_id"),
        default_download_subfolder_per_playlist=data.get(
            "default_download_subfolder_per_playlist", True,
        ),
        downloads_paused=data.get("downloads_paused", False),
        tray_hide_notice_shown=data.get("tray_hide_notice_shown", False),
        notify_downloads_finished=data.get("notify_downloads_finished", True),
        notify_needs_decision=data.get("notify_needs_decision", True),
        notify_errors=data.get("notify_errors", True),
        theme_mode=_resolve_theme_mode(data.get("theme_mode")),
    )


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
    # Mirrors application.py's _migrate_legacy_database contract exactly:
    # never overwrite a value the store already has (guards against a
    # stale env var clobbering a value changed since via a future
    # Settings screen), copy in only fields the store is missing, no-op
    # (and no print) when there's nothing to migrate, idempotent on
    # repeat calls. The real .env file itself is never read from or
    # written to directly — only os.environ (already populated by
    # config.py's load_dotenv()) is read.
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
