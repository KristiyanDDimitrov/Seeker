from dataclasses import replace

import pytest

from seeker.application import (
    Application,
    _migrate_legacy_database,
    _migrate_legacy_spotify_token,
    _resolve_database_path,
    _resolve_spotify_token_path,
)
from seeker.config_store import (
    SeekerConfig,
    load_config,
    resolve_config_path,
    save_config,
)
from seeker.database.connection import Database
from seeker.spotify.auth_manager import SpotifyAuthManager
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
        tmp_path, caplog,
):
    legacy_path = tmp_path / "old" / ".seeker" / "seeker.db"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(b"real sqlite bytes, not a fresh empty db")

    new_path = tmp_path / "new" / "seeker.db"
    new_path.parent.mkdir(parents=True)

    with caplog.at_level("INFO"):
        migrated = _migrate_legacy_database(new_path, legacy_path=legacy_path)

    assert migrated is True
    assert not legacy_path.exists()
    assert (
        new_path.read_bytes() == b"real sqlite bytes, not a fresh empty db"
    )

    assert "Migrated existing database" in caplog.text
    assert str(legacy_path) in caplog.text
    assert str(new_path) in caplog.text


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
        tmp_path, monkeypatch, caplog,
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

    with caplog.at_level("INFO"):
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

    assert "Migrated existing database" in caplog.text


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


def test_resolve_spotify_token_path_creates_directory_and_uses_platformdirs(
        tmp_path, monkeypatch,
):
    fake_data_dir = tmp_path / "AppData" / "Seeker"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(fake_data_dir),
    )

    assert not fake_data_dir.exists()

    token_path = _resolve_spotify_token_path()

    assert token_path == fake_data_dir / "spotify_token.json"
    assert fake_data_dir.is_dir()


def test_migrate_legacy_spotify_token_moves_existing_file(tmp_path, caplog):
    legacy_path = tmp_path / "old" / ".seeker" / "spotify_token.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text('{"access_token": "real-token"}')

    new_path = tmp_path / "new" / "spotify_token.json"
    new_path.parent.mkdir(parents=True)

    with caplog.at_level("INFO"):
        migrated = _migrate_legacy_spotify_token(
            new_path, legacy_path=legacy_path,
        )

    assert migrated is True
    assert not legacy_path.exists()
    assert new_path.read_text() == '{"access_token": "real-token"}'

    assert "Migrated existing Spotify token" in caplog.text
    assert str(legacy_path) in caplog.text
    assert str(new_path) in caplog.text


def test_migrate_legacy_spotify_token_does_nothing_when_neither_exists(
        tmp_path,
):
    legacy_path = tmp_path / "old" / ".seeker" / "spotify_token.json"
    new_path = tmp_path / "new" / "spotify_token.json"

    migrated = _migrate_legacy_spotify_token(new_path, legacy_path=legacy_path)

    assert migrated is False
    assert not legacy_path.exists()
    assert not new_path.exists()


def test_migrate_legacy_spotify_token_does_not_overwrite_existing_new_token(
        tmp_path,
):
    legacy_path = tmp_path / "old" / ".seeker" / "spotify_token.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text('{"access_token": "stale"}')

    new_path = tmp_path / "new" / "spotify_token.json"
    new_path.parent.mkdir(parents=True)
    new_path.write_text('{"access_token": "current"}')

    migrated = _migrate_legacy_spotify_token(new_path, legacy_path=legacy_path)

    assert migrated is False
    assert legacy_path.exists()
    assert new_path.read_text() == '{"access_token": "current"}'


def test_application_migrates_real_legacy_spotify_token_on_startup(
        tmp_path, monkeypatch, caplog,
):
    # Mirrors test_application_migrates_real_legacy_database_on_startup
    # above — the real bug this covers only ever showed up via an
    # actual double-clicked .app launch (CWD forced to `/`), never the
    # offscreen test harness, since chdir(tmp_path) here already makes
    # the legacy path writable either way. This locks in that a
    # pre-existing CWD-relative token gets moved into the same
    # platformdirs directory the DB already uses, rather than left
    # behind as dead weight or silently ignored.
    monkeypatch.chdir(tmp_path)

    legacy_token_path = tmp_path / ".seeker" / "spotify_token.json"
    legacy_token_path.parent.mkdir(parents=True)
    legacy_token_path.write_text('{"access_token": "real-legacy-token"}')

    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )

    with caplog.at_level("INFO"):
        app = Application()

    new_token_path = data_dir / "spotify_token.json"
    assert app._spotify_token_path == new_token_path
    assert new_token_path.exists()
    assert not legacy_token_path.exists()
    assert new_token_path.read_text() == '{"access_token": "real-legacy-token"}'

    assert "Migrated existing Spotify token" in caplog.text


def test_application_spotify_token_path_is_not_cwd_relative(
        tmp_path, monkeypatch,
):
    # The actual bug: launched via a double-clicked .app, macOS sets
    # CWD to `/` (read-only), so a CWD-relative token path would fail
    # to even mkdir its parent. Simulated here by constructing the
    # Application from a directory that is neither the project root
    # nor the platformdirs data dir, and confirming the resolved token
    # path still lands under the (fake) platformdirs directory, with
    # no `.seeker` directory created anywhere near the CWD.
    other_cwd = tmp_path / "some" / "unrelated" / "directory"
    other_cwd.mkdir(parents=True)
    monkeypatch.chdir(other_cwd)

    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )

    app = Application()

    assert app._spotify_token_path == data_dir / "spotify_token.json"
    assert not (other_cwd / ".seeker").exists()


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
    assert app.slskd_base_url == "http://current-store-value:5030"
    assert app.slskd_api_key == "current-store-key"
    assert app.slskd_download_dir == "/current/store/dir"
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
    assert app.slskd_base_url == "http://env-value:5030"
    assert app.slskd_api_key == "env-key"
    assert app.slskd_download_dir is None

    # Isolate the property-level fallback itself, independent of
    # migration having already copied the values into the store — force
    # the store back to empty and confirm resolution still works.
    app._config_store = SeekerConfig()

    assert app.soulseek_configured is True
    assert app.slskd_base_url == "http://env-value:5030"
    assert app.slskd_api_key == "env-key"
    assert app.slskd_download_dir is None


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
        app.auth_manager  # noqa: B018 -- the access itself is the test


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
    # callback_server) — connect_spotify()'s last line calls
    # auth_manager.get_valid_token() directly (round 8 §4.8.6 — B018:
    # this used to be a bare `self.spotify` statement, which turned out
    # to be a real, separate bug of its own: SpotifyClient.__init__
    # only stores its token_source/force_refresh callables, it never
    # calls them, so the old code never actually triggered OAuth at
    # all until something later made a real API call). Replacing
    # get_valid_token confirms the real seam is reached without opening
    # a real browser.
    triggered = []
    monkeypatch.setattr(
        SpotifyAuthManager,
        "get_valid_token",
        lambda self, force_refresh=False: triggered.append(True),
    )

    app._auth_manager = "stale-sentinel"  # type: ignore[assignment]

    app.connect_spotify("real-client-id")

    assert triggered == [True]
    # The stale sentinel is gone — replaced by a freshly-constructed
    # SpotifyAuthManager (round 8 §4.8.6: unlike the old lazy
    # `self.spotify` access, get_valid_token() being called directly
    # means accessing `self.auth_manager` above genuinely reconstructs
    # and caches a new one immediately, it doesn't stay None).
    assert isinstance(app._auth_manager, SpotifyAuthManager)
    assert app._config_store.spotify_client_id == "real-client-id"

    # Persisted to disk too, not just the in-memory attribute — a
    # second Application() in the same session would see it.
    reloaded = load_config(resolve_config_path())
    assert reloaded.spotify_client_id == "real-client-id"


def test_connect_spotify_force_reauthorize_clears_cached_token(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    # Neuter the real trigger (no real browser/network round trip)
    # without caring whether it fires -- these tests only check the
    # token-file side effects. round 8 §4.8.6: the seam moved from
    # the old lazy `self.spotify` property to auth_manager.
    # get_valid_token() being called directly.
    monkeypatch.setattr(
        SpotifyAuthManager, "get_valid_token",
        lambda self, force_refresh=False: None,
    )

    app._spotify_token_path.parent.mkdir(parents=True, exist_ok=True)
    TokenStore(app._spotify_token_path).save(
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
    assert not app._spotify_token_path.exists()


def test_connect_spotify_without_force_leaves_cached_token_untouched(
        tmp_path, monkeypatch,
):
    # The wizard's first-time-connect path — no token exists yet in
    # practice, but confirms force_reauthorize's default (False) really
    # is inert, not silently always-clearing.
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    # Neuter the real trigger (no real browser/network round trip)
    # without caring whether it fires -- these tests only check the
    # token-file side effects. round 8 §4.8.6: the seam moved from
    # the old lazy `self.spotify` property to auth_manager.
    # get_valid_token() being called directly.
    monkeypatch.setattr(
        SpotifyAuthManager, "get_valid_token",
        lambda self, force_refresh=False: None,
    )

    app._spotify_token_path.parent.mkdir(parents=True, exist_ok=True)
    TokenStore(app._spotify_token_path).save(
        SpotifyToken(
            access_token="still-valid",
            refresh_token="still-valid-refresh",
            expires_at=9_999_999_999.0,
        )
    )

    app.connect_spotify("real-client-id")

    assert app._spotify_token_path.exists()


def test_connect_spotify_reruns_authorization_when_client_already_cached(
        tmp_path, monkeypatch,
):
    # B8's own regression test: before the fix, `self.spotify` at the
    # end of connect_spotify() short-circuited on an already-populated
    # `_spotify` cache from an earlier call in the same session, so
    # Settings' "Re-authorize" silently did nothing and the app kept
    # using the dead client — the exact bug that made B8's 401
    # unrecoverable without restarting the app. round 8 §4.8.6: the
    # trigger itself moved to auth_manager.get_valid_token(), a
    # separate real fix (see the first test in this group) — this
    # regression test's own concern (does the STALE _spotify/
    # _sync_service cache get cleared and the trigger still reached)
    # is orthogonal and still applies identically to the new seam.
    app = _application_with_tmp_config(tmp_path, monkeypatch)

    triggered = []
    monkeypatch.setattr(
        SpotifyAuthManager,
        "get_valid_token",
        lambda self, force_refresh=False: triggered.append(True),
    )

    # Simulate a prior real call having already populated the cache.
    app._spotify = "stale-client"  # type: ignore[assignment]
    app._sync_service = "stale-sync-service"  # type: ignore[assignment]

    app.connect_spotify("real-client-id", force_reauthorize=True)

    assert triggered == [True]
    assert app._spotify is None
    assert app._sync_service is None


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


def test_ensure_slskd_web_credentials_generates_and_persists_once(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)

    username, password = app.ensure_slskd_web_credentials()

    assert username == "seeker"
    assert password
    assert app._config_store.slskd_web_username == username
    assert app._config_store.slskd_web_password == password

    reloaded = load_config(resolve_config_path())
    assert reloaded.slskd_web_username == username
    assert reloaded.slskd_web_password == password


def test_ensure_slskd_web_credentials_never_rotates_an_existing_value(
        tmp_path, monkeypatch,
):
    # Roadmap item 116 (round 8, §6.1.2) — a second call (e.g. a later
    # "Update SoulSeek credentials" or Sharing add-location recreate)
    # must return the SAME login, not silently generate a new one that
    # would lock the user out of a web UI session they're already in.
    app = _application_with_tmp_config(tmp_path, monkeypatch)

    first_username, first_password = app.ensure_slskd_web_credentials()
    second_username, second_password = app.ensure_slskd_web_credentials()

    assert second_username == first_username
    assert second_password == first_password


def test_persist_default_destination_updates_store_and_disk(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)

    app.persist_default_destination(4, False)

    assert app._config_store.default_download_location_id == 4
    assert app._config_store.default_download_subfolder_per_playlist is False

    reloaded = load_config(resolve_config_path())
    assert reloaded.default_download_location_id == 4
    assert reloaded.default_download_subfolder_per_playlist is False


def test_persist_default_destination_reflected_by_download_service_immediately(
        tmp_path, monkeypatch,
):
    # No cached-client reset needed here, unlike persist_soulseek_config
    # — DownloadService reads config fresh via get_config on every
    # resolution, never a cached snapshot (this project's standing
    # rule for every config-backed threshold).
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    service = app.download_service

    app.persist_default_destination(7, True)

    assert service._get_config().default_download_location_id == 7


def test_download_service_constructs_without_soulseek_configured(
        tmp_path, monkeypatch,
):
    # Real gap found building Settings (Step 8): download_service used
    # to eagerly construct a SoulseekClient, so accessing it at all
    # raised when SoulSeek wasn't configured — even for
    # set_destination()/get_review_candidates(), which never touch
    # SoulSeek. SoulSeek is the wizard's own optional, skippable step,
    # so this was a real usability gap, not a hypothetical one.
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "seeker.application.config.SLSKD_BASE_URL", None,
    )
    monkeypatch.setattr("seeker.application.config.SLSKD_API_KEY", None)
    app._config_store = SeekerConfig()

    assert app.soulseek_configured is False

    service = app.download_service  # must not raise

    with pytest.raises(RuntimeError, match="SoulSeek is not configured"):
        service.soulseek  # noqa: B018 -- the access itself is the test


def test_persist_soulseek_config_resets_cached_download_service(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "seeker.application.config.SLSKD_BASE_URL", None,
    )
    monkeypatch.setattr("seeker.application.config.SLSKD_API_KEY", None)
    app._config_store = SeekerConfig()

    # Accessed once while genuinely unconfigured — this cached instance
    # must not linger forever once real credentials land.
    unconfigured_service = app.download_service
    assert unconfigured_service._soulseek_client is None

    app.persist_soulseek_config(
        "http://localhost:5030",
        "real-api-key",
        "/data/downloads",
        "real-username",
        "real-password",
    )

    assert app._download_service is None
    assert app.download_service is not unconfigured_service
    assert app.download_service.soulseek is not None  # must not raise


# --- UI polish pass: onboarding_complete's actual boolean correctness
# was previously exercised only via a subprocess smoke test asserting
# it doesn't raise (test_lazy_spotify_config.py) — real, but coverage.py
# can't see across a process boundary, and nothing anywhere asserted
# the TRUE/FALSE value was actually correct for a given state. Real
# gap: main_ui.py's wizard-vs-dashboard routing depends entirely on
# this property returning the right answer.

def test_onboarding_complete_false_when_neither_spotify_nor_library_done(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    monkeypatch.setattr("seeker.application.config.SPOTIFY_CLIENT_ID", None)
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_REDIRECT_URI", None,
    )
    app._config_store = SeekerConfig()

    assert app.onboarding_complete is False


def test_onboarding_complete_false_when_spotify_done_but_no_library(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    app._config_store = replace(
        app._config_store,
        spotify_client_id="real-client-id",
        spotify_redirect_uri="http://127.0.0.1:8888/callback",
    )

    assert app.spotify_configured is True
    assert app.library_service.list_locations() == []
    assert app.onboarding_complete is False


def test_onboarding_complete_false_when_library_done_but_not_spotify(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    monkeypatch.setattr("seeker.application.config.SPOTIFY_CLIENT_ID", None)
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_REDIRECT_URI", None,
    )
    app._config_store = SeekerConfig()
    app.library_service.add_location("Main", str(tmp_path))

    assert app.spotify_configured is False
    assert app.onboarding_complete is False


def test_onboarding_complete_true_when_spotify_and_library_both_done(
        tmp_path, monkeypatch,
):
    # The real gating condition main_ui.py depends on — SoulSeek
    # deliberately excluded (it's the wizard's optional, skippable
    # step), confirmed here rather than just asserted in a comment.
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    app._config_store = replace(
        app._config_store,
        spotify_client_id="real-client-id",
        spotify_redirect_uri="http://127.0.0.1:8888/callback",
    )
    app.library_service.add_location("Main", str(tmp_path))

    assert app.onboarding_complete is True


def test_dashboard_service_is_a_cached_singleton_across_app_lifetime(
        tmp_path, monkeypatch,
):
    # Task 2 (download ETA) needs DashboardService to genuinely persist
    # across a whole UI session, the same way track_matcher already
    # does (item 28 §4) — a live confirmation of the actual property
    # behavior, not an assumption carried over from that precedent.
    app = _application_with_tmp_config(tmp_path, monkeypatch)

    first = app.dashboard_service
    second = app.dashboard_service

    assert first is second


def test_track_matcher_is_a_cached_singleton_across_app_lifetime(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)

    first = app.track_matcher
    second = app.track_matcher

    assert first is second


def test_data_locations_resolves_real_paths_in_one_shared_directory(
        tmp_path, monkeypatch,
):
    # database_path/config_path/spotify_token_path all resolve into the
    # identical per-user app-data directory (base_dir) — slskd_data_dir
    # is the one real subfolder of it. Every module that independently
    # computes platformdirs.user_data_dir("Seeker", ...) is patched here
    # so this test is fully isolated from the real machine's actual
    # app-data directory, not just the database's own.
    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.chdir(tmp_path)
    for module in (
            "seeker.application.platformdirs",
            "seeker.config_store.platformdirs",
            "seeker.docker_setup.platformdirs",
    ):
        monkeypatch.setattr(
            f"{module}.user_data_dir", _fake_user_data_dir(data_dir),
        )

    app = Application()

    locations = app.data_locations

    assert locations.database_path == data_dir / "seeker.db"
    assert locations.config_path == data_dir / "config.json"
    assert locations.spotify_token_path == data_dir / "spotify_token.json"
    assert locations.slskd_data_dir == data_dir / "slskd-data"
    assert locations.base_dir == data_dir
