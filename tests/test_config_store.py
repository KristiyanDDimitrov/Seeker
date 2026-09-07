import json
import stat
import sys

import pytest

from seeker.config_store import (
    SeekerConfig,
    load_config,
    migrate_legacy_env_config,
    resolve_config_path,
    save_config,
)

skip_on_windows = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="POSIX chmod semantics don't apply on Windows",
)


def _fake_user_data_dir(data_dir):
    def fake(appname, **kwargs):
        return str(data_dir)

    return fake


def test_resolve_config_path_creates_directory_and_uses_platformdirs(
        tmp_path, monkeypatch,
):
    fake_data_dir = tmp_path / "AppData" / "Seeker"
    monkeypatch.setattr(
        "seeker.config_store.platformdirs.user_data_dir",
        _fake_user_data_dir(fake_data_dir),
    )

    assert not fake_data_dir.exists()

    config_path = resolve_config_path()

    assert config_path == fake_data_dir / "config.json"
    assert fake_data_dir.is_dir()


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "config.json"

    original = SeekerConfig(
        slskd_base_url="http://localhost:5030",
        slskd_api_key="real-api-key",
        slskd_download_dir="/mnt/slskd/downloads",
    )

    save_config(original, path)
    loaded = load_config(path)

    assert loaded == original


def test_save_then_load_round_trips_spotify_fields(tmp_path):
    path = tmp_path / "config.json"

    original = SeekerConfig(
        spotify_client_id="real-client-id",
        spotify_redirect_uri="http://127.0.0.1:8888/callback",
    )

    save_config(original, path)
    loaded = load_config(path)

    assert loaded == original


def test_save_then_load_round_trips_soulseek_credential_fields(tmp_path):
    path = tmp_path / "config.json"

    original = SeekerConfig(
        slskd_username="realuser",
        slskd_password="real-password",
    )

    save_config(original, path)
    loaded = load_config(path)

    assert loaded == original


def test_save_then_load_round_trips_threshold_fields(tmp_path):
    # Step 8's new editable-thresholds feature — None (unset) must
    # round-trip as None, not 0.0 or some other falsy stand-in, since
    # None is what tells TrackMatcher/DownloadService to fall back to
    # matching.py's hardcoded defaults.
    path = tmp_path / "config.json"

    original = SeekerConfig(
        auto_match_threshold=92.5,
        needs_review_threshold=65.0,
    )

    save_config(original, path)
    loaded = load_config(path)

    assert loaded == original
    assert loaded.auto_match_threshold == 92.5
    assert loaded.needs_review_threshold == 65.0


def test_save_then_load_round_trips_default_destination_fields(tmp_path):
    # Roadmap item 6 — default_download_location_id must round-trip as
    # a real int (not just present-vs-missing), and
    # default_download_subfolder_per_playlist must round-trip its
    # actual False value, not silently fall back to its True default.
    path = tmp_path / "config.json"

    original = SeekerConfig(
        default_download_location_id=4,
        default_download_subfolder_per_playlist=False,
    )

    save_config(original, path)
    loaded = load_config(path)

    assert loaded == original
    assert loaded.default_download_location_id == 4
    assert loaded.default_download_subfolder_per_playlist is False


def test_load_config_missing_default_destination_fields_uses_documented_defaults(
        tmp_path,
):
    # A config.json predating this field must load cleanly (this
    # project's own flat-additive-JSON design) — no location id set,
    # and the subfolder toggle defaults True (matches SeekerConfig's
    # own field default).
    path = tmp_path / "config.json"
    path.write_text('{"slskd_base_url": "http://localhost:5030"}')

    loaded = load_config(path)

    assert loaded.default_download_location_id is None
    assert loaded.default_download_subfolder_per_playlist is True


def test_load_config_missing_file_returns_defaults_no_crash(tmp_path):
    path = tmp_path / "does-not-exist" / "config.json"

    loaded = load_config(path)

    assert loaded == SeekerConfig(
        slskd_base_url=None, slskd_api_key=None, slskd_download_dir=None,
    )


def test_load_config_partial_shape_missing_key_does_not_crash(tmp_path):
    # Old/partial JSON — a key added in a later version isn't present.
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"slskd_base_url": "http://localhost:5030"}))

    loaded = load_config(path)

    assert loaded.slskd_base_url == "http://localhost:5030"
    assert loaded.slskd_api_key is None
    assert loaded.slskd_download_dir is None


def test_load_config_tolerates_a_removed_field_still_present_in_the_file(
        tmp_path,
):
    # Roadmap item 100 (B7.2) — write_cover_jpg_sidecars was removed
    # from SeekerConfig (R4.2 reversed). A real config.json written by
    # an earlier version of the app may still hold that key; loading it
    # now must simply ignore the unknown key, not raise.
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "slskd_base_url": "http://localhost:5030",
        "write_cover_jpg_sidecars": True,
    }))

    loaded = load_config(path)

    assert loaded.slskd_base_url == "http://localhost:5030"
    assert not hasattr(loaded, "write_cover_jpg_sidecars")


def test_load_config_corrupt_json_does_not_crash(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not valid json at all")

    loaded = load_config(path)

    assert loaded == SeekerConfig()


def test_load_config_missing_theme_mode_defaults_to_system(tmp_path):
    # A config.json predating item C5 (round 5) has no theme_mode key
    # at all — same flat-additive-JSON tolerance as every other field.
    path = tmp_path / "config.json"
    path.write_text('{"slskd_base_url": "http://localhost:5030"}')

    loaded = load_config(path)

    assert loaded.theme_mode == "system"


def test_load_config_garbage_theme_mode_falls_back_to_system(tmp_path):
    # Roadmap item C5.7 — a garbage/future-version value in this key
    # must not raise or propagate into theme.py; same guarded-default
    # discipline as every other field this store owns.
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"theme_mode": "not-a-real-mode"}))

    loaded = load_config(path)

    assert loaded.theme_mode == "system"


@pytest.mark.parametrize("mode", ["system", "light", "dark"])
def test_load_config_real_theme_mode_values_round_trip(tmp_path, mode):
    path = tmp_path / "config.json"
    save_config(SeekerConfig(theme_mode=mode), path)

    loaded = load_config(path)

    assert loaded.theme_mode == mode


@skip_on_windows
def test_save_config_sets_restrictive_permissions(tmp_path):
    path = tmp_path / "config.json"

    save_config(SeekerConfig(slskd_api_key="secret"), path)

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_save_config_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "config.json"

    save_config(SeekerConfig(slskd_api_key="secret"), path)

    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]


def test_migrate_copies_env_into_empty_store(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SLSKD_BASE_URL", "http://localhost:5030")
    monkeypatch.setenv("SLSKD_API_KEY", "env-api-key")
    monkeypatch.setenv("SLSKD_DOWNLOAD_DIR", "/mnt/slskd/downloads")

    path = tmp_path / "config.json"

    result = migrate_legacy_env_config(path)

    assert result.slskd_base_url == "http://localhost:5030"
    assert result.slskd_api_key == "env-api-key"
    assert result.slskd_download_dir == "/mnt/slskd/downloads"

    persisted = load_config(path)
    assert persisted == result

    output = capsys.readouterr().out
    assert "Migrated config from .env" in output
    assert "SLSKD_BASE_URL" in output
    assert "SLSKD_API_KEY" in output
    assert "SLSKD_DOWNLOAD_DIR" in output


def test_migrate_copies_spotify_env_into_empty_store(
        tmp_path, monkeypatch, capsys,
):
    # Same chain, extended fields (this task's onboarding wizard) — not
    # a separate mechanism, just two more entries in the same
    # _ENV_VAR_BY_FIELD map.
    _clear_migration_env(monkeypatch)
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "real-client-id")
    monkeypatch.setenv(
        "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback",
    )

    path = tmp_path / "config.json"

    result = migrate_legacy_env_config(path)

    assert result.spotify_client_id == "real-client-id"
    assert result.spotify_redirect_uri == "http://127.0.0.1:8888/callback"

    output = capsys.readouterr().out
    assert "SPOTIFY_CLIENT_ID" in output
    assert "SPOTIFY_REDIRECT_URI" in output


def _clear_migration_env(monkeypatch):
    # This process's real .env may have real SLSKD_*/SPOTIFY_* values
    # loaded into os.environ already (config.py's load_dotenv() at
    # import time) — migrate_legacy_env_config reads os.environ live,
    # so a test that only sets/asserts on a subset of fields must
    # explicitly clear the rest first, rather than relying on however
    # this machine happens to be configured.
    monkeypatch.delenv("SLSKD_BASE_URL", raising=False)
    monkeypatch.delenv("SLSKD_API_KEY", raising=False)
    monkeypatch.delenv("SLSKD_DOWNLOAD_DIR", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)


def test_migrate_never_overwrites_value_already_in_store(
        tmp_path, monkeypatch, capsys,
):
    # A value the user has since changed via (future) Settings must
    # never be clobbered by a stale env var.
    _clear_migration_env(monkeypatch)
    monkeypatch.setenv("SLSKD_BASE_URL", "http://stale-env-value:5030")

    path = tmp_path / "config.json"
    save_config(
        SeekerConfig(slskd_base_url="http://current-store-value:5030"),
        path,
    )

    result = migrate_legacy_env_config(path)

    assert result.slskd_base_url == "http://current-store-value:5030"

    output = capsys.readouterr().out
    assert output == ""


def test_migrate_noop_when_neither_store_nor_env_has_a_value(
        tmp_path, monkeypatch, capsys,
):
    _clear_migration_env(monkeypatch)

    path = tmp_path / "config.json"

    result = migrate_legacy_env_config(path)

    assert result == SeekerConfig()
    assert not path.exists()

    output = capsys.readouterr().out
    assert output == ""


def test_migrate_is_idempotent_on_second_call(tmp_path, monkeypatch, capsys):
    _clear_migration_env(monkeypatch)
    monkeypatch.setenv("SLSKD_BASE_URL", "http://localhost:5030")
    monkeypatch.setenv("SLSKD_API_KEY", "env-api-key")

    path = tmp_path / "config.json"

    first = migrate_legacy_env_config(path)
    capsys.readouterr()  # discard the first call's migration message

    second = migrate_legacy_env_config(path)

    assert second == first

    output = capsys.readouterr().out
    assert output == ""


def test_migrate_partial_fields_only_copies_the_missing_ones(
        tmp_path, monkeypatch, capsys,
):
    # Store already has base_url set (real, current); api_key is still
    # unset. Only api_key should be migrated in.
    _clear_migration_env(monkeypatch)
    monkeypatch.setenv("SLSKD_BASE_URL", "http://stale-env-value:5030")
    monkeypatch.setenv("SLSKD_API_KEY", "env-api-key")

    path = tmp_path / "config.json"
    save_config(
        SeekerConfig(slskd_base_url="http://current-store-value:5030"),
        path,
    )

    result = migrate_legacy_env_config(path)

    assert result.slskd_base_url == "http://current-store-value:5030"
    assert result.slskd_api_key == "env-api-key"
    assert result.slskd_download_dir is None

    output = capsys.readouterr().out
    assert "SLSKD_API_KEY" in output
    assert "SLSKD_BASE_URL" not in output
    assert "SLSKD_DOWNLOAD_DIR" not in output
