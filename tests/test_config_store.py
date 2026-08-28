import json
import stat
import sys

import pytest

from seeker.config_store import (
    SeekerConfig,
    load_config,
    migrate_legacy_slskd_env_config,
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


def test_load_config_corrupt_json_does_not_crash(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not valid json at all")

    loaded = load_config(path)

    assert loaded == SeekerConfig()


@skip_on_windows
def test_save_config_sets_restrictive_permissions(tmp_path):
    path = tmp_path / "config.json"

    save_config(SeekerConfig(slskd_api_key="secret"), path)

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_migrate_copies_env_into_empty_store(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SLSKD_BASE_URL", "http://localhost:5030")
    monkeypatch.setenv("SLSKD_API_KEY", "env-api-key")
    monkeypatch.setenv("SLSKD_DOWNLOAD_DIR", "/mnt/slskd/downloads")

    path = tmp_path / "config.json"

    result = migrate_legacy_slskd_env_config(path)

    assert result.slskd_base_url == "http://localhost:5030"
    assert result.slskd_api_key == "env-api-key"
    assert result.slskd_download_dir == "/mnt/slskd/downloads"

    persisted = load_config(path)
    assert persisted == result

    output = capsys.readouterr().out
    assert "Migrated SoulSeek config from .env" in output
    assert "SLSKD_BASE_URL" in output
    assert "SLSKD_API_KEY" in output
    assert "SLSKD_DOWNLOAD_DIR" in output


def _clear_slskd_env(monkeypatch):
    # This process's real .env may have real SLSKD_* values loaded into
    # os.environ already (config.py's load_dotenv() at import time) —
    # migrate_legacy_slskd_env_config reads os.environ live, so a test
    # that only sets/asserts on a subset of the three fields must
    # explicitly clear the rest first, rather than relying on however
    # this machine happens to be configured.
    monkeypatch.delenv("SLSKD_BASE_URL", raising=False)
    monkeypatch.delenv("SLSKD_API_KEY", raising=False)
    monkeypatch.delenv("SLSKD_DOWNLOAD_DIR", raising=False)


def test_migrate_never_overwrites_value_already_in_store(
        tmp_path, monkeypatch, capsys,
):
    # A value the user has since changed via (future) Settings must
    # never be clobbered by a stale env var.
    _clear_slskd_env(monkeypatch)
    monkeypatch.setenv("SLSKD_BASE_URL", "http://stale-env-value:5030")

    path = tmp_path / "config.json"
    save_config(
        SeekerConfig(slskd_base_url="http://current-store-value:5030"),
        path,
    )

    result = migrate_legacy_slskd_env_config(path)

    assert result.slskd_base_url == "http://current-store-value:5030"

    output = capsys.readouterr().out
    assert output == ""


def test_migrate_noop_when_neither_store_nor_env_has_a_value(
        tmp_path, monkeypatch, capsys,
):
    _clear_slskd_env(monkeypatch)

    path = tmp_path / "config.json"

    result = migrate_legacy_slskd_env_config(path)

    assert result == SeekerConfig()
    assert not path.exists()

    output = capsys.readouterr().out
    assert output == ""


def test_migrate_is_idempotent_on_second_call(tmp_path, monkeypatch, capsys):
    _clear_slskd_env(monkeypatch)
    monkeypatch.setenv("SLSKD_BASE_URL", "http://localhost:5030")
    monkeypatch.setenv("SLSKD_API_KEY", "env-api-key")

    path = tmp_path / "config.json"

    first = migrate_legacy_slskd_env_config(path)
    capsys.readouterr()  # discard the first call's migration message

    second = migrate_legacy_slskd_env_config(path)

    assert second == first

    output = capsys.readouterr().out
    assert output == ""


def test_migrate_partial_fields_only_copies_the_missing_ones(
        tmp_path, monkeypatch, capsys,
):
    # Store already has base_url set (real, current); api_key is still
    # unset. Only api_key should be migrated in.
    _clear_slskd_env(monkeypatch)
    monkeypatch.setenv("SLSKD_BASE_URL", "http://stale-env-value:5030")
    monkeypatch.setenv("SLSKD_API_KEY", "env-api-key")

    path = tmp_path / "config.json"
    save_config(
        SeekerConfig(slskd_base_url="http://current-store-value:5030"),
        path,
    )

    result = migrate_legacy_slskd_env_config(path)

    assert result.slskd_base_url == "http://current-store-value:5030"
    assert result.slskd_api_key == "env-api-key"
    assert result.slskd_download_dir is None

    output = capsys.readouterr().out
    assert "SLSKD_API_KEY" in output
    assert "SLSKD_BASE_URL" not in output
    assert "SLSKD_DOWNLOAD_DIR" not in output
