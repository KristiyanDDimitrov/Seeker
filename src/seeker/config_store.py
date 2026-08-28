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


def resolve_config_path() -> Path:
    # Same per-user app-data directory the database lives in (see
    # application.py's _resolve_database_path) — one location, not two.
    data_dir = Path(platformdirs.user_data_dir("Seeker", appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)

    return data_dir / "config.json"


def load_config(path: Path) -> SeekerConfig:
    if not path.exists():
        return SeekerConfig()

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return SeekerConfig()

    if not isinstance(data, dict):
        return SeekerConfig()

    return SeekerConfig(
        slskd_base_url=data.get("slskd_base_url"),
        slskd_api_key=data.get("slskd_api_key"),
        slskd_download_dir=data.get("slskd_download_dir"),
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


# Field name -> the legacy .env var it was previously read from.
_ENV_VAR_BY_FIELD = {
    "slskd_base_url": "SLSKD_BASE_URL",
    "slskd_api_key": "SLSKD_API_KEY",
    "slskd_download_dir": "SLSKD_DOWNLOAD_DIR",
}


def migrate_legacy_slskd_env_config(path: Path) -> SeekerConfig:
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

        seeker_config = replace(seeker_config, **{field_name: env_value})
        migrated_fields.append(env_var)

    if migrated_fields:
        save_config(seeker_config, path)
        print(
            f"Migrated SoulSeek config from .env to the local config "
            f"store ({path}): {', '.join(migrated_fields)}."
        )

    return seeker_config
