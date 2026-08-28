import pytest

from seeker.application import (
    Application,
    SPOTIFY_TOKEN_PATH,
    _migrate_legacy_database,
    _resolve_database_path,
)
from seeker.config_store import SeekerConfig, load_config, resolve_config_path, save_config
from seeker.database.connection import Database
from seeker.spotify.token import SpotifyToken
from seeker.spotify.token_store import TokenStore


def _fake_user_data_dir(data_dir):
    # platformdirs.user_data_dir's real signature varies by OS
    # (appauthor is ignored on macOS/Linux, used on Windows) — accepting
    # **kwargs keeps this fake correct regardless of which platform the
    # test suite runs on.
    def fake(appname, **kwargs):
        return str(data_dir)

    return fake


def test_resolve_database_path_creates_directory_and_uses_platformdirs(
        tmp_path, monkeypatch,
):
    fake_data_dir = tmp_path / "AppData" / "Seeker"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(fake_data_dir),
    )

    assert not fake_data_dir.exists()

    db_path = _resolve_database_path()

    assert db_path == fake_data_dir / "seeker.db"
    assert fake_data_dir.is_dir()


def test_migrate_legacy_database_moves_existing_file_and_preserves_data(
        tmp_path, capsys,
):
    legacy_path = tmp_path / "old" / ".seeker" / "seeker.db"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(b"real sqlite bytes, not a fresh empty db")

    new_path = tmp_path / "new" / "seeker.db"
    new_path.parent.mkdir(parents=True)

    migrated = _migrate_legacy_database(new_path, legacy_path=legacy_path)

    assert migrated is True
    assert not legacy_path.exists()
    assert (
        new_path.read_bytes() == b"real sqlite bytes, not a fresh empty db"
    )

    output = capsys.readouterr().out
    assert "Migrated existing database" in output
    assert str(legacy_path) in output
    assert str(new_path) in output


def test_migrate_legacy_database_does_nothing_when_neither_exists(
        tmp_path,
):
    legacy_path = tmp_path / "old" / ".seeker" / "seeker.db"
    new_path = tmp_path / "new" / "seeker.db"

    migrated = _migrate_legacy_database(new_path, legacy_path=legacy_path)

    assert migrated is False
    assert not legacy_path.exists()
    assert not new_path.exists()


def test_migrate_legacy_database_does_not_overwrite_existing_new_db(
        tmp_path,
):
    # A DB already exists at the new location (e.g. the migration
    # already ran once before, on a prior startup) — a stale leftover
    # legacy file must never clobber it.
    legacy_path = tmp_path / "old" / ".seeker" / "seeker.db"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(b"stale legacy bytes")

    new_path = tmp_path / "new" / "seeker.db"
    new_path.parent.mkdir(parents=True)
    new_path.write_bytes(b"current real data")

    migrated = _migrate_legacy_database(new_path, legacy_path=legacy_path)

    assert migrated is False
    assert legacy_path.exists()
    assert new_path.read_bytes() == b"current real data"


def test_application_fresh_install_creates_database_at_new_location(
        tmp_path, monkeypatch,
):
    # Neither the new platformdirs location nor the old CWD-relative
    # .seeker/ path exist yet — a genuinely fresh install.
    monkeypatch.chdir(tmp_path)

    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )

    app = Application()

    expected_path = data_dir / "seeker.db"
    assert app.database.path == expected_path
    assert expected_path.exists()
    assert not (tmp_path / ".seeker").exists()


def test_application_migrates_real_legacy_database_on_startup(
        tmp_path, monkeypatch, capsys,
):
    # A real, non-empty database already exists at the old CWD-relative
    # .seeker/seeker.db location (e.g. a pre-migration install) — this
    # must be moved into the new location automatically, with real data
    # intact, not silently left behind while a fresh empty DB is
    # created at the new path.
    monkeypatch.chdir(tmp_path)

    legacy_db_path = tmp_path / ".seeker" / "seeker.db"
    legacy_db_path.parent.mkdir(parents=True)

    real_db = Database(legacy_db_path)
    real_db.initialize()

    with real_db.transaction() as connection:
        connection.execute(
            "INSERT INTO playlists (id, name, track_count) "
            "VALUES (?, ?, ?)",
            ("p1", "Real Playlist", 3),
        )

    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )

    app = Application()

    new_db_path = data_dir / "seeker.db"
    assert app.database.path == new_db_path
    assert new_db_path.exists()
    assert not legacy_db_path.exists()

    with app.database.transaction() as connection:
        row = connection.execute(
            "SELECT name, track_count FROM playlists WHERE id = 'p1'"
        ).fetchone()

    assert row["name"] == "Real Playlist"
    assert row["track_count"] == 3

    output = capsys.readouterr().out
    assert "Migrated existing database" in output


def test_application_does_not_migrate_when_new_database_already_exists(
        tmp_path, monkeypatch,
):
    # Both a legacy file and a real database at the new location exist
    # (e.g. this is the second startup after an earlier successful
    # migration) — the legacy leftover must not overwrite real, current
    # data.
    monkeypatch.chdir(tmp_path)

    legacy_db_path = tmp_path / ".seeker" / "seeker.db"
    legacy_db_path.parent.mkdir(parents=True)
    legacy_db_path.write_bytes(b"stale pre-migration bytes")

    data_dir = tmp_path / "platformdirs-data"
    data_dir.mkdir(parents=True)

    new_db_path = data_dir / "seeker.db"
    real_db = Database(new_db_path)
    real_db.initialize()

    with real_db.transaction() as connection:
        connection.execute(
            "INSERT INTO playlists (id, name, track_count) "
            "VALUES (?, ?, ?)",
            ("p1", "Current Real Playlist", 5),
        )

    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )

    app = Application()

    assert legacy_db_path.exists()

    with app.database.transaction() as connection:
        row = connection.execute(
            "SELECT name FROM playlists WHERE id = 'p1'"
        ).fetchone()

    assert row["name"] == "Current Real Playlist"


def test_application_soulseek_config_prefers_store_value_over_env(
        tmp_path, monkeypatch,
):
    # A stale env var must never win over a value the user has since
    # changed via (future) Settings — same guarantee config_store.py's
    # own migration tests assert, checked here end-to-end through
    # Application's actual resolution properties.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "seeker.application.config.SLSKD_BASE_URL",
        "http://stale-env-value:5030",
    )
    monkeypatch.setattr(
        "seeker.application.config.SLSKD_API_KEY", "stale-env-key",
    )
    monkeypatch.setattr(
        "seeker.application.config.SLSKD_DOWNLOAD_DIR", "/stale/env/dir",
    )

    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )
    data_dir.mkdir(parents=True)

    # The store already has every field populated — migration (which
    # never overwrites a populated field) is guaranteed to no-op here
    # regardless of the real process environment.
    save_config(
        SeekerConfig(
            slskd_base_url="http://current-store-value:5030",
            slskd_api_key="current-store-key",
            slskd_download_dir="/current/store/dir",
        ),
        data_dir / "config.json",
    )

    app = Application()

    assert app.soulseek_configured is True
    assert app._slskd_base_url == "http://current-store-value:5030"
    assert app._slskd_api_key == "current-store-key"
    assert app._slskd_download_dir == "/current/store/dir"
    assert app.download_service.slskd_download_dir == "/current/store/dir"
    assert app.soulseek_client.base_url == "http://current-store-value:5030"


def test_application_soulseek_config_falls_back_to_env_when_store_empty(
        tmp_path, monkeypatch,
):
    # An env-only setup (pre-migration, or one that intentionally never
    # touches the config store) must keep working exactly as before.
    monkeypatch.chdir(tmp_path)

    monkeypatch.setenv("SLSKD_BASE_URL", "http://env-value:5030")
    monkeypatch.setenv("SLSKD_API_KEY", "env-key")
    monkeypatch.delenv("SLSKD_DOWNLOAD_DIR", raising=False)

    # config.py's module-level constants are fixed at import time, not
    # re-read live from os.environ — patch them directly so the
    # property-level fallback (which reads config.SLSKD_*) is exercised
    # against the same values the env-var monkeypatches above represent.
    monkeypatch.setattr(
        "seeker.application.config.SLSKD_BASE_URL", "http://env-value:5030",
    )
    monkeypatch.setattr(
        "seeker.application.config.SLSKD_API_KEY", "env-key",
    )
    monkeypatch.setattr(
        "seeker.application.config.SLSKD_DOWNLOAD_DIR", None,
    )

    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )

    app = Application()

    # End-to-end: startup migration copies the env values into the
    # (empty) store, and resolution reflects them correctly either way.
    assert app.soulseek_configured is True
    assert app._slskd_base_url == "http://env-value:5030"
    assert app._slskd_api_key == "env-key"
    assert app._slskd_download_dir is None

    # Isolate the property-level fallback itself, independent of
    # migration having already copied the values into the store — force
    # the store back to empty and confirm resolution still works.
    app._config_store = SeekerConfig()

    assert app.soulseek_configured is True
    assert app._slskd_base_url == "http://env-value:5030"
    assert app._slskd_api_key == "env-key"
    assert app._slskd_download_dir is None


def test_application_spotify_config_prefers_store_value_over_env(
        tmp_path, monkeypatch,
):
    # Same store-or-env chain as SLSKD_* above, extended to the two new
    # Spotify fields — not a separate mechanism.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_CLIENT_ID", "stale-env-client-id",
    )
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_REDIRECT_URI",
        "http://stale-env-redirect/callback",
    )

    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )
    data_dir.mkdir(parents=True)

    save_config(
        SeekerConfig(
            spotify_client_id="current-store-client-id",
            spotify_redirect_uri="http://current-store-redirect/callback",
        ),
        data_dir / "config.json",
    )

    app = Application()

    assert app.spotify_configured is True
    assert app._spotify_client_id == "current-store-client-id"
    assert (
        app._spotify_redirect_uri == "http://current-store-redirect/callback"
    )
    assert app.auth_manager.client_id == "current-store-client-id"
    assert (
        app.auth_manager.redirect_uri
        == "http://current-store-redirect/callback"
    )


def test_application_spotify_config_falls_back_to_env_then_default(
        tmp_path, monkeypatch,
):
    monkeypatch.chdir(tmp_path)

    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )

    # Store and env both empty for redirect_uri — the fixed,
    # app-controlled default (matching callback_server.py's own
    # listening port) must be used instead of None.
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_CLIENT_ID", "env-client-id",
    )
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_REDIRECT_URI", None,
    )

    app = Application()
    app._config_store = SeekerConfig()

    assert app.spotify_configured is True
    assert app._spotify_client_id == "env-client-id"
    assert app._spotify_redirect_uri == "http://127.0.0.1:8888/callback"


def test_application_spotify_not_configured_raises_only_when_auth_manager_used(
        tmp_path, monkeypatch,
):
    # The whole point of the lazy-resolution fix: constructing
    # Application with nothing configured at all must not raise —
    # only actually touching auth_manager (i.e. Spotify auth being
    # triggered) does.
    monkeypatch.chdir(tmp_path)

    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )
    monkeypatch.setattr("seeker.application.config.SPOTIFY_CLIENT_ID", None)
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_REDIRECT_URI", None,
    )

    app = Application()  # must not raise
    app._config_store = SeekerConfig()

    assert app.spotify_configured is False

    with pytest.raises(RuntimeError, match="SPOTIFY_CLIENT_ID"):
        app.auth_manager


# --- Step 8 §3: connection-management extraction ----------------------
#
# connect_spotify()/persist_soulseek_config() are the shared logic the
# onboarding wizard's first-time connect/bring-up and Settings'
# re-authorize/update-credentials actions both call — extracted rather
# than duplicated. The real OAuth browser round-trip and the real
# docker-compose bring-up are out of scope for a unit test (matches
# this project's existing "verified live, not re-mocked" treatment of
# _authorize()); what's tested here is the persistence contract and the
# real invalidation side effects, which is genuinely new logic.

def _application_with_tmp_config(tmp_path, monkeypatch) -> Application:
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )
    return Application()


def test_connect_spotify_persists_config_and_resets_auth_manager(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)

    # Stand in for the real OAuth round-trip (auth_manager /
    # callback_server) — connect_spotify()'s last line just accesses
    # `self.spotify`, so replacing that property confirms it's reached
    # (a real trigger) without opening a real browser.
    triggered = []
    monkeypatch.setattr(
        Application, "spotify", property(lambda self: triggered.append(True)),
    )

    app._auth_manager = "stale-sentinel"  # type: ignore[assignment]

    app.connect_spotify("real-client-id")

    assert triggered == [True]
    assert app._auth_manager is None
    assert app._config_store.spotify_client_id == "real-client-id"

    # Persisted to disk too, not just the in-memory attribute — a
    # second Application() in the same session would see it.
    reloaded = load_config(resolve_config_path())
    assert reloaded.spotify_client_id == "real-client-id"


def test_connect_spotify_force_reauthorize_clears_cached_token(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    monkeypatch.setattr(Application, "spotify", property(lambda self: None))

    SPOTIFY_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TokenStore(SPOTIFY_TOKEN_PATH).save(
        SpotifyToken(
            access_token="stale-access",
            refresh_token="stale-refresh",
            expires_at=9_999_999_999.0,
        )
    )

    app.connect_spotify("real-client-id", force_reauthorize=True)

    # Without force_reauthorize, get_valid_token() would just silently
    # return this still-valid cached token and never re-trigger OAuth
    # at all — this is what makes "re-authorize" a real action instead
    # of a no-op for an already-connected setup.
    assert not SPOTIFY_TOKEN_PATH.exists()


def test_connect_spotify_without_force_leaves_cached_token_untouched(
        tmp_path, monkeypatch,
):
    # The wizard's first-time-connect path — no token exists yet in
    # practice, but confirms force_reauthorize's default (False) really
    # is inert, not silently always-clearing.
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    monkeypatch.setattr(Application, "spotify", property(lambda self: None))

    SPOTIFY_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TokenStore(SPOTIFY_TOKEN_PATH).save(
        SpotifyToken(
            access_token="still-valid",
            refresh_token="still-valid-refresh",
            expires_at=9_999_999_999.0,
        )
    )

    app.connect_spotify("real-client-id")

    assert SPOTIFY_TOKEN_PATH.exists()


def test_persist_soulseek_config_updates_store_disk_and_resets_client(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)

    # A previously-cached client (as if Settings is updating credentials
    # on an already-running, already-connected app) must not survive a
    # credential change silently pointing at the old base_url/api_key.
    app._soulseek_client = "stale-sentinel"  # type: ignore[assignment]

    app.persist_soulseek_config(
        "http://localhost:5030",
        "real-api-key",
        "/data/downloads",
        "real-username",
        "real-password",
    )

    assert app._soulseek_client is None
    assert app._config_store.slskd_base_url == "http://localhost:5030"
    assert app._config_store.slskd_api_key == "real-api-key"
    assert app._config_store.slskd_download_dir == "/data/downloads"
    assert app._config_store.slskd_username == "real-username"
    assert app._config_store.slskd_password == "real-password"

    reloaded = load_config(resolve_config_path())
    assert reloaded.slskd_username == "real-username"
    assert reloaded.slskd_password == "real-password"
