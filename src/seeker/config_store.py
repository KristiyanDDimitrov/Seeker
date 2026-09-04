import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import platformdirs


@dataclass
class SeekerConfig:
    slskd_base_url: str | None = None
    slskd_api_key: str | None = None
    slskd_download_dir: str | None = None
    spotify_client_id: str | None = None
    spotify_redirect_uri: str | None = None
    # SoulSeek network login — plain text in this file (same 0600
    # chmod as every other field here; see save_config). Added for
    # Settings (Step 8) to have something real to display/re-collect
    # for "Update SoulSeek credentials" — item 19 deliberately left
    # these out of scope when the store was first built, pending
    # exactly this real consumer.
    slskd_username: str | None = None
    slskd_password: str | None = None
    # None means "use matching.py's hardcoded default" — same
    # unset-means-unchanged discipline as every optional override in
    # this codebase (e.g. the BPM-range feature). Resolved per-call by
    # TrackMatcher/DownloadService, never cached at import time.
    auto_match_threshold: float | None = None
    needs_review_threshold: float | None = None
    # Roadmap item 6 (the "no configured destination" dead end): a
    # playlist-specific download_location_id/download_subfolder still
    # wins when set — this is only the fallback once neither is. None
    # means "no default configured yet," the same unset-means-nothing
    # convention as every other optional field here.
    default_download_location_id: int | None = None
    default_download_subfolder_per_playlist: bool = True
    # Roadmap item R7.4 — a real service-level flag, checked inside
    # DownloadService.poll_downloads() itself (not just the UI's own
    # timer), so pausing is authoritative regardless of caller (the
    # menu-bar toggle, the main window's own mirrored control, or a
    # future automated caller). Persisted so a paused session doesn't
    # silently resume on restart.
    downloads_paused: bool = False
    # Roadmap item R7.1 — shown at most once, ever: the first time the
    # window is hidden to the menu bar instead of closed, per the
    # brief's own "a window that vanishes with no explanation is the
    # single most common complaint about this pattern."
    tray_hide_notice_shown: bool = False
    # Roadmap item R7.5 — per-category notification toggles, all
    # defaulting on per the brief's own instruction.
    notify_downloads_finished: bool = True
    notify_needs_decision: bool = True
    notify_errors: bool = True
    # Roadmap item C5 (round 5) — "system" (default), "light", or
    # "dark". Same guarded-default discipline as every other field
    # here: an unrecognized value (a garbage/future-version string)
    # falls back to "system" at LOAD time (see load_config below)
    # rather than raising or propagating a bad value into theme.py.
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

    # Roadmap item 100 (B7) — a config.json written by an earlier
    # version of the app may still hold a "write_cover_jpg_sidecars"
    # key (R4.2's own opt-in, reversed here). Deliberately not read: an
    # unknown key here is simply ignored, not an error, so no
    # migration/tolerance code is needed for it.
    return SeekerConfig(
        slskd_base_url=data.get("slskd_base_url"),
        slskd_api_key=data.get("slskd_api_key"),
        slskd_download_dir=data.get("slskd_download_dir"),
        spotify_client_id=data.get("spotify_client_id"),
        spotify_redirect_uri=data.get("spotify_redirect_uri"),
        slskd_username=data.get("slskd_username"),
        slskd_password=data.get("slskd_password"),
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(seeker_config), indent=2) + "\n")

    # This file will eventually hold real SoulSeek credentials — lock it
    # down where the OS supports POSIX chmod semantics. A platform where
    # chmod doesn't apply (Windows) is a no-op, not a failure.
    try:
        path.chmod(0o600)
    except OSError:
        pass


# Field name -> the legacy .env var it was previously read from. Covers
# both SLSKD_* (Task 1) and SPOTIFY_* (this task's onboarding wizard) —
# one resolution chain for every field the store owns, not a second
# mechanism per field group. Renamed from the SLSKD-only
# migrate_legacy_slskd_env_config now that its scope has genuinely
# broadened, same discipline as RECOGNIZED_REJECTION_PATTERNS's rename.
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
        print(
            f"Migrated config from .env to the local config "
            f"store ({path}): {', '.join(migrated_fields)}."
        )

    return seeker_config
