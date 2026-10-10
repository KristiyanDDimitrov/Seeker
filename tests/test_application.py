import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from seeker.application import (
    Application,
    _resolve_database_path,
    _resolve_spotify_token_path,
    resolve_log_dir,
)
from seeker.config_store import (
    SeekerConfig,
    load_config,
    resolve_config_path,
    save_config,
)
from seeker.models.library_location import LibraryLocation
from seeker.models.slskd_start import SlskdDataFolderState
from seeker.soulseek.docker_setup import (
    DockerState,
    SlskdBringUpError,
    SlskdSetupNeededError,
    SlskdStartRefusedError,
)
from seeker.soulseek.sharing_service import ContainerPresence
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


@pytest.fixture
def umask_022():
    # The common default, which leaves a new directory 0755.
    previous = os.umask(0o022)
    yield
    os.umask(previous)


@pytest.mark.parametrize("pre_existing", [False, True])
@pytest.mark.parametrize(
    ("platformdirs_name", "resolve"),
    [
        ("user_data_dir", _resolve_database_path),
        ("user_data_dir", _resolve_spotify_token_path),
        ("user_log_dir", resolve_log_dir),
    ],
)
def test_seeker_data_and_log_dirs_are_private_to_the_user(
        tmp_path, monkeypatch, umask_022, platformdirs_name, resolve,
        pre_existing,
):
    # On Linux the parents are usually 0755, so a dir at the umask
    # lets another local user read the DB, the logs and the downloads.
    seeker_dir = tmp_path / "Seeker"
    if pre_existing:
        seeker_dir.mkdir(mode=0o755)
    monkeypatch.setattr(
        f"seeker.application.platformdirs.{platformdirs_name}",
        _fake_user_data_dir(seeker_dir),
    )

    resolve()

    assert stat.S_IMODE(seeker_dir.stat().st_mode) == 0o700


def test_a_data_dir_that_refuses_chmod_still_opens(
        tmp_path, monkeypatch, caplog,
):
    # A dir owned by another user (one made under sudo, say) refuses
    # chmod with EPERM. Privacy is hardening; it must not stop Seeker
    # starting.
    seeker_dir = tmp_path / "Seeker"
    seeker_dir.mkdir()
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(seeker_dir),
    )

    def refuse(self, mode):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr("pathlib.Path.chmod", refuse)

    assert _resolve_database_path() == seeker_dir / "seeker.db"
    assert "Could not make" in caplog.text


def test_application_fresh_install_creates_database_at_new_location(
        tmp_path, monkeypatch,
):
    # Nothing exists at the platformdirs location yet — a genuinely
    # fresh install — and nothing is created relative to the CWD.
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
    monkeypatch.setenv("SLSKD_BASE_URL", "http://stale-env-value:5030")
    monkeypatch.setenv("SLSKD_API_KEY", "stale-env-key")
    monkeypatch.setenv("SLSKD_DOWNLOAD_DIR", "/stale/env/dir")

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
    assert (
        app.download_service.placement.slskd_download_dir
        == "/current/store/dir"
    )
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
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "stale-env-client-id")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://stale-env-redirect/callback")

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
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "env-client-id")
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)

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
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)

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
        lambda self, force_refresh=False, cancel=None: triggered.append(True),
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
        lambda self, force_refresh=False, cancel=None: None,
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
        lambda self, force_refresh=False, cancel=None: None,
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
        lambda self, force_refresh=False, cancel=None: triggered.append(True),
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
    # Settings' Start slskd or Sharing's add-location recreate)
    # must return the SAME login, not silently generate a new one that
    # would lock the user out of a web UI session they're already in.
    app = _application_with_tmp_config(tmp_path, monkeypatch)

    first_username, first_password = app.ensure_slskd_web_credentials()
    second_username, second_password = app.ensure_slskd_web_credentials()

    assert second_username == first_username
    assert second_password == first_password


def _fake_slskd_bring_up(tmp_path, monkeypatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(
        "seeker.application.bring_up_slskd",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        "seeker.application.slskd_data_dir", lambda: tmp_path / "slskd-data",
    )
    monkeypatch.setattr(
        "seeker.application.compose_file_path",
        lambda: tmp_path / "slskd-data" / "docker-compose.yml",
    )
    monkeypatch.setattr(
        "seeker.application.generate_api_key", lambda: "generated-key",
    )
    _fake_live_slskd_mounts(monkeypatch, {})
    return calls


def _fake_live_slskd_mounts(monkeypatch, mounts: dict[str, str]) -> None:
    monkeypatch.setattr(
        "seeker.soulseek.sharing_service._get_live_container_mounts",
        lambda container_name: mounts,
    )


def test_start_slskd_brings_up_with_generated_key_and_web_login(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    calls = _fake_slskd_bring_up(tmp_path, monkeypatch)

    result = app.start_slskd("netuser", "netpass", "/music", persist=False)

    web_username, web_password = app.ensure_slskd_web_credentials()
    assert calls == [{
        "compose_file": str(tmp_path / "slskd-data" / "docker-compose.yml"),
        "soulseek_username": "netuser",
        "soulseek_password": "netpass",
        "api_key": "generated-key",
        "slskd_data_dir": str(tmp_path / "slskd-data"),
        "web_username": web_username,
        "web_password": web_password,
        "library_location_path": "/music",
    }]
    assert (tmp_path / "slskd-data").is_dir()
    assert result.api_key == "generated-key"
    assert result.download_dir == str(tmp_path / "slskd-data" / "downloads")


def test_start_slskd_keeps_the_live_containers_data_dir(
        tmp_path, monkeypatch,
):
    # A container created elsewhere (a manual `docker compose up` from
    # the repository) keeps its slskd state and downloads: a recreate
    # reuses its /app mount instead of starting an empty per-user one.
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    calls = _fake_slskd_bring_up(tmp_path, monkeypatch)
    live_data_dir = tmp_path / "repo" / "slskd-data"
    _fake_live_slskd_mounts(monkeypatch, {
        "/app": str(live_data_dir),
        "/shared/music": "/music",
    })

    result = app.start_slskd("netuser", "netpass", "/music", persist=True)

    assert calls[0]["slskd_data_dir"] == str(live_data_dir)
    assert result.download_dir == str(live_data_dir / "downloads")
    assert load_config(resolve_config_path()).slskd_download_dir == str(
        live_data_dir / "downloads"
    )
    assert not (tmp_path / "slskd-data").exists()


def test_start_slskd_without_persist_saves_no_connection_details(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    _fake_slskd_bring_up(tmp_path, monkeypatch)
    before = load_config(resolve_config_path())

    app.start_slskd("netuser", "netpass", "/music", persist=False)

    after = load_config(resolve_config_path())
    assert after.slskd_api_key == before.slskd_api_key != "generated-key"
    assert after.slskd_username == before.slskd_username
    assert app.settings.slskd_api_key == before.slskd_api_key


def test_start_slskd_with_persist_saves_what_it_started_with(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    _fake_slskd_bring_up(tmp_path, monkeypatch)

    app.start_slskd("netuser", "netpass", "/music", persist=True)

    reloaded = load_config(resolve_config_path())
    assert reloaded.slskd_base_url == "http://127.0.0.1:5030"
    assert reloaded.slskd_api_key == "generated-key"
    assert reloaded.slskd_download_dir == str(
        tmp_path / "slskd-data" / "downloads"
    )
    assert reloaded.slskd_username == "netuser"
    assert reloaded.slskd_password == "netpass"


def test_start_slskd_compose_failure_propagates_and_persists_nothing(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    _fake_slskd_bring_up(tmp_path, monkeypatch)

    def failing_bring_up(**kwargs):
        raise SlskdBringUpError("docker compose up failed: boom")

    monkeypatch.setattr("seeker.application.bring_up_slskd", failing_bring_up)
    before = load_config(resolve_config_path())

    with pytest.raises(SlskdBringUpError, match="boom"):
        app.start_slskd("netuser", "netpass", "/music", persist=True)

    after = load_config(resolve_config_path())
    assert after.slskd_api_key == before.slskd_api_key != "generated-key"
    assert after.slskd_username == before.slskd_username


def test_start_slskd_records_the_share_and_data_folder_it_used(
        tmp_path, monkeypatch,
):
    # A recreate after the container is deleted can't read them from
    # Docker any more, so every bring-up saves them, the wizard's
    # deferred-persist one included.
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    _fake_slskd_bring_up(tmp_path, monkeypatch)

    app.start_slskd("netuser", "netpass", "/music", persist=False)

    reloaded = load_config(resolve_config_path())
    assert reloaded.slskd_share_path == "/music"
    assert reloaded.slskd_data_dir == str(tmp_path / "slskd-data")
    assert Path(reloaded.slskd_data_dir).is_absolute()
    assert app.settings.slskd_data_dir == reloaded.slskd_data_dir


def test_start_slskd_records_nothing_when_compose_fails(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    _fake_slskd_bring_up(tmp_path, monkeypatch)

    def failing_bring_up(**kwargs):
        raise SlskdBringUpError("docker compose up failed: boom")

    monkeypatch.setattr("seeker.application.bring_up_slskd", failing_bring_up)

    with pytest.raises(SlskdBringUpError):
        app.start_slskd("netuser", "netpass", "/music", persist=True)

    reloaded = load_config(resolve_config_path())
    assert reloaded.slskd_share_path is None
    assert reloaded.slskd_data_dir is None


def test_sharing_recreate_records_the_share_and_data_folder(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)

    app.sharing_service._record_bring_up("/Volumes/Music", "/data/slskd")

    reloaded = load_config(resolve_config_path())
    assert reloaded.slskd_share_path == "/Volumes/Music"
    assert reloaded.slskd_data_dir == "/data/slskd"


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


def test_remove_location_clears_the_default_destination_it_was(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    music = tmp_path / "music"
    music.mkdir()
    location = app.library_service.add_location("Music", str(music))
    assert location.id is not None
    app.persist_default_destination(location.id, True)

    summary = app.remove_location("Music")

    assert summary.was_default is True
    assert app.settings.default_download_location_id is None
    assert load_config(resolve_config_path()).default_download_location_id is None


def test_preview_remove_location_reports_the_default_and_changes_nothing(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    (tmp_path / "music").mkdir()
    location = app.library_service.add_location("Music", str(tmp_path / "music"))
    assert location.id is not None
    app.persist_default_destination(location.id, True)

    preview = app.preview_remove_location("Music")

    assert preview.was_default is True
    assert app.settings.default_download_location_id == location.id
    assert len(app.library_service.list_locations()) == 1


def test_remove_location_keeps_a_default_destination_elsewhere(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    for name in ("Music", "Other"):
        (tmp_path / name).mkdir()
        app.library_service.add_location(name, str(tmp_path / name))
    kept_id = next(
        location.id
        for location, _ in app.library_service.list_locations()
        if location.name == "Other"
    )
    assert kept_id is not None
    app.persist_default_destination(kept_id, False)

    summary = app.remove_location("Music")

    assert summary.was_default is False
    assert app.settings.default_download_location_id == kept_id


def test_merge_location_clears_the_default_destination_it_was(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    inner = tmp_path / "music" / "Test"
    inner.mkdir(parents=True)
    app.library_service.add_location("Music", str(tmp_path / "music"))
    service = app.library_service
    with service.database.transaction() as connection:
        # Registered unchecked, as builds before the nesting guard did.
        service.locations.add(
            LibraryLocation(name="Test", path=str(inner), added_at="t"),
            connection,
        )
        test = service.locations.get_by_name("Test", connection)
    assert test is not None and test.id is not None
    app.persist_default_destination(test.id, True)

    preview = app.preview_merge_location("Test", "Music")
    assert app.settings.default_download_location_id == test.id
    summary = app.merge_location("Test", "Music")

    assert preview.was_default is summary.was_default is True
    assert app.settings.default_download_location_id is None
    assert load_config(resolve_config_path()).default_download_location_id is None


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


def test_a_finished_sweep_is_saved_as_last_sweep_at(tmp_path, monkeypatch):
    # The due check reads it after a restart, so it must reach
    # config.json, not only the in-memory settings.
    app = _application_with_tmp_config(tmp_path, monkeypatch)

    app.sweep_service.run_sweep()

    saved = load_config(resolve_config_path()).last_sweep_at
    assert saved is not None
    assert app.settings.last_sweep_at == saved


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
    monkeypatch.delenv("SLSKD_BASE_URL", raising=False)
    monkeypatch.delenv("SLSKD_API_KEY", raising=False)
    app._config_store = SeekerConfig()

    assert app.soulseek_configured is False

    service = app.download_service  # must not raise

    with pytest.raises(RuntimeError, match="SoulSeek is not configured"):
        service.soulseek  # noqa: B018 -- the access itself is the test


def test_persist_soulseek_config_resets_cached_download_service(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    monkeypatch.delenv("SLSKD_BASE_URL", raising=False)
    monkeypatch.delenv("SLSKD_API_KEY", raising=False)
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


def test_review_service_works_without_soulseek_and_shares_placement(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    monkeypatch.delenv("SLSKD_BASE_URL", raising=False)
    monkeypatch.delenv("SLSKD_API_KEY", raising=False)
    app._config_store = SeekerConfig()

    review_service = app.review_service  # must not raise

    assert review_service.placement is app.download_service.placement
    assert review_service.get_review_candidates() == []
    assert review_service.get_pending_upgrade_reviews() == []


def test_persist_soulseek_config_resets_cached_review_service(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    monkeypatch.delenv("SLSKD_BASE_URL", raising=False)
    monkeypatch.delenv("SLSKD_API_KEY", raising=False)
    app._config_store = SeekerConfig()
    unconfigured = app.review_service

    app.persist_soulseek_config(
        "http://localhost:5030",
        "real-api-key",
        "/data/downloads",
        "real-username",
        "real-password",
    )

    assert app.review_service is not unconfigured
    assert app.review_service.placement is app.download_service.placement
    assert app.review_service.placement.slskd_download_dir == "/data/downloads"


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
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)
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
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)
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
            "seeker.soulseek.docker_setup.platformdirs",
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


def test_login_item_supported_delegates_to_login_item_module(
        tmp_path, monkeypatch,
):
    # Round 9 §3.2 — Application.login_item_supported/login_item_
    # status/set_login_item_enabled are thin passthroughs to
    # login_item.py (the real ServiceManagement wrapper is exercised
    # directly in test_login_item.py); this just confirms the wiring.
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    monkeypatch.setattr("seeker.application.login_item.is_supported",
                         lambda: True)

    assert app.login_item_supported is True


def test_login_item_status_delegates_to_login_item_module(
        tmp_path, monkeypatch,
):
    from seeker.login_item import LoginItemStatus

    app = _application_with_tmp_config(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "seeker.application.login_item.get_status",
        lambda: LoginItemStatus.REQUIRES_APPROVAL,
    )

    assert app.login_item_status() is LoginItemStatus.REQUIRES_APPROVAL


def test_set_login_item_enabled_delegates_to_login_item_module(
        tmp_path, monkeypatch,
):
    from seeker.login_item import LoginItemStatus

    app = _application_with_tmp_config(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        "seeker.application.login_item.set_enabled",
        lambda enabled: (calls.append(enabled), LoginItemStatus.ENABLED)[1],
    )

    result = app.set_login_item_enabled(True)

    assert calls == [True]
    assert result is LoginItemStatus.ENABLED


def _restartable_slskd(
        tmp_path,
        monkeypatch,
        *,
        self_managed: bool = True,
        presence: ContainerPresence = ContainerPresence.PRESENT,
) -> tuple[Application, list[dict]]:
    """An app whose saved SoulSeek login and self-managed, stopped
    container make "Start slskd" possible."""
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    calls = _fake_slskd_bring_up(tmp_path, monkeypatch)
    app.persist_soulseek_config(
        "http://127.0.0.1:5030", "old-key", "/dl", "netuser", "netpass",
    )
    monkeypatch.setattr(
        "seeker.application.detect_docker_state", lambda: DockerState.RUNNING,
    )
    monkeypatch.setattr(
        "seeker.soulseek.sharing_service.SharingService.container_presence",
        lambda self: presence,
    )
    monkeypatch.setattr(
        "seeker.soulseek.sharing_service.SharingService.is_self_managed",
        lambda self: self_managed,
    )
    _fake_live_slskd_mounts(monkeypatch, {
        "/app": str(tmp_path / "slskd-data"),
        "/shared/music": "/Volumes/Music/Shared",
    })
    return app, calls


def test_restart_slskd_keeps_the_live_share_and_the_saved_login(
        tmp_path, monkeypatch,
):
    app, calls = _restartable_slskd(tmp_path, monkeypatch)

    app.restart_slskd()

    assert len(calls) == 1
    assert calls[0]["library_location_path"] == "/Volumes/Music/Shared"
    assert calls[0]["soulseek_username"] == "netuser"
    assert calls[0]["soulseek_password"] == "netpass"
    assert load_config(resolve_config_path()).slskd_api_key == (
        "generated-key"
    )


@pytest.mark.parametrize(
    ("docker_state", "expected"),
    [
        (DockerState.INSTALLED_NOT_RUNNING, "Docker isn't running"),
        (DockerState.NOT_INSTALLED, "Docker isn't installed"),
    ],
)
def test_restart_slskd_without_docker_refuses_and_says_why(
        tmp_path, monkeypatch, docker_state, expected,
):
    app, calls = _restartable_slskd(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "seeker.application.detect_docker_state", lambda: docker_state,
    )

    with pytest.raises(SlskdStartRefusedError, match=expected):
        app.restart_slskd()

    assert calls == []


def test_restart_slskd_never_recreates_a_container_it_did_not_create(
        tmp_path, monkeypatch,
):
    app, calls = _restartable_slskd(
        tmp_path, monkeypatch, self_managed=False,
    )

    with pytest.raises(SlskdStartRefusedError, match="won't guess"):
        app.restart_slskd()

    assert calls == []


def test_restart_slskd_never_guesses_the_share(tmp_path, monkeypatch):
    app, calls = _restartable_slskd(tmp_path, monkeypatch)
    _fake_live_slskd_mounts(monkeypatch, {"/app": str(tmp_path / "x")})

    with pytest.raises(SlskdStartRefusedError, match="won't guess"):
        app.restart_slskd()

    assert calls == []


def test_restart_slskd_without_a_saved_login_points_at_settings(
        tmp_path, monkeypatch,
):
    app, calls = _restartable_slskd(tmp_path, monkeypatch)
    app.persist_soulseek_config(
        "http://127.0.0.1:5030", "old-key", "/dl", "", "",
    )

    with pytest.raises(SlskdStartRefusedError, match="Settings"):
        app.restart_slskd()

    assert calls == []


def _deleted_container(tmp_path, monkeypatch) -> tuple[Application, list[dict]]:
    """An app whose slskd container is gone, with nothing to inspect."""
    app, calls = _restartable_slskd(
        tmp_path,
        monkeypatch,
        self_managed=False,
        presence=ContainerPresence.ABSENT,
    )
    _fake_live_slskd_mounts(monkeypatch, {})
    return app, calls


def test_restart_slskd_recreates_a_deleted_container_from_the_record(
        tmp_path, monkeypatch,
):
    app, calls = _deleted_container(tmp_path, monkeypatch)
    share = tmp_path / "Music"
    data_dir = tmp_path / "repo" / "slskd-data"
    share.mkdir()
    data_dir.mkdir(parents=True)
    app.update_settings(
        slskd_share_path=str(share), slskd_data_dir=str(data_dir),
    )

    app.restart_slskd()

    assert len(calls) == 1
    assert calls[0]["library_location_path"] == str(share)
    assert calls[0]["slskd_data_dir"] == str(data_dir)
    assert calls[0]["soulseek_username"] == "netuser"
    assert calls[0]["soulseek_password"] == "netpass"
    reloaded = load_config(resolve_config_path())
    assert reloaded.slskd_api_key == "generated-key"
    assert reloaded.slskd_download_dir == str(data_dir / "downloads")


@pytest.mark.parametrize(
    ("record", "login", "named", "not_named"),
    [
        (
            {}, ("netuser", "netpass"),
            ["the folder to share", "slskd's data folder"],
            ["SoulSeek login"],
        ),
        (
            {"slskd_share_path": "SHARE"}, ("netuser", ""),
            ["slskd's data folder", "SoulSeek login"],
            ["the folder to share"],
        ),
    ],
)
def test_restart_slskd_says_which_saved_facts_a_recreate_lacks(
        tmp_path, monkeypatch, record, login, named, not_named,
):
    app, calls = _deleted_container(tmp_path, monkeypatch)
    app.persist_soulseek_config(
        "http://127.0.0.1:5030", "old-key", "/dl", *login,
    )
    app.update_settings(**{
        field: str(tmp_path) for field in record
    })

    with pytest.raises(SlskdStartRefusedError) as refusal:
        app.restart_slskd()

    message = str(refusal.value)
    assert "Settings → Connections" in message
    assert all(fact in message for fact in named)
    assert not any(fact in message for fact in not_named)
    assert calls == []


def test_restart_slskd_never_recreates_onto_a_folder_that_is_not_there(
        tmp_path, monkeypatch,
):
    # Compose creates a missing bind source, so an unplugged drive
    # would get an empty folder under /Volumes instead of slskd's data.
    app, calls = _deleted_container(tmp_path, monkeypatch)
    share = tmp_path / "Music"
    share.mkdir()
    missing = tmp_path / "Unplugged" / "slskd-data"
    app.update_settings(
        slskd_share_path=str(share), slskd_data_dir=str(missing),
    )

    with pytest.raises(SlskdStartRefusedError, match="isn't there") as refusal:
        app.restart_slskd()

    assert str(missing) in str(refusal.value)
    assert str(share) not in str(refusal.value)
    assert not missing.exists()
    assert calls == []


def test_restart_slskd_refuses_when_docker_cannot_say_if_it_exists(
        tmp_path, monkeypatch,
):
    app, calls = _restartable_slskd(
        tmp_path, monkeypatch, presence=ContainerPresence.UNKNOWN,
    )

    with pytest.raises(SlskdStartRefusedError, match="Try again"):
        app.restart_slskd()

    assert calls == []


def test_start_slskd_uses_a_chosen_data_folder_over_the_live_one(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    calls = _fake_slskd_bring_up(tmp_path, monkeypatch)
    _fake_live_slskd_mounts(monkeypatch, {"/app": str(tmp_path / "live")})
    chosen = tmp_path / "chosen"
    chosen.mkdir()

    result = app.start_slskd(
        "netuser", "netpass", "/music", persist=False, data_dir=str(chosen),
    )

    assert calls[0]["slskd_data_dir"] == str(chosen)
    assert result.download_dir == str(chosen / "downloads")


def test_start_slskd_refuses_a_relative_data_folder(tmp_path, monkeypatch):
    # A .app's working directory is not the repository, so a relative
    # folder would point somewhere else on every launch.
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    calls = _fake_slskd_bring_up(tmp_path, monkeypatch)

    with pytest.raises(SlskdStartRefusedError, match="full path"):
        app.start_slskd(
            "netuser", "netpass", "/music",
            persist=True, data_dir="./slskd-data",
        )

    assert calls == []


def test_start_slskd_never_creates_a_chosen_data_folder(tmp_path, monkeypatch):
    # A chosen folder on an unplugged drive would otherwise become an
    # empty one under /Volumes, and slskd would start with no state.
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    calls = _fake_slskd_bring_up(tmp_path, monkeypatch)
    missing = tmp_path / "Unplugged" / "slskd-data"

    with pytest.raises(SlskdSetupNeededError, match="isn't there"):
        app.start_slskd(
            "netuser", "netpass", "/music",
            persist=True, data_dir=str(missing),
        )

    assert not missing.exists()
    assert calls == []


def test_start_slskd_creates_the_default_data_folder_when_named(
        tmp_path, monkeypatch,
):
    # The form always names its folder; on a fresh install the default
    # one doesn't exist until the first bring-up.
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    calls = _fake_slskd_bring_up(tmp_path, monkeypatch)
    defaults = app.slskd_start_defaults()

    app.start_slskd(
        "netuser", "netpass", "/music",
        persist=True, data_dir=defaults.data_dir,
    )

    assert defaults.data_dir_state is SlskdDataFolderState.FRESH
    assert (tmp_path / "slskd-data").is_dir()
    assert calls[0]["slskd_data_dir"] == str(tmp_path / "slskd-data")


def test_restart_refusals_settings_can_resolve_are_setup_needed(
        tmp_path, monkeypatch,
):
    app, _ = _deleted_container(tmp_path, monkeypatch)

    with pytest.raises(SlskdSetupNeededError):
        app.restart_slskd()

    present, _ = _restartable_slskd(tmp_path, monkeypatch, self_managed=False)

    with pytest.raises(SlskdSetupNeededError):
        present.restart_slskd()

    present.persist_soulseek_config("http://127.0.0.1:5030", "k", "/dl", "", "")
    monkeypatch.setattr(
        "seeker.soulseek.sharing_service.SharingService.is_self_managed",
        lambda self: True,
    )

    with pytest.raises(SlskdSetupNeededError, match="login"):
        present.restart_slskd()


def test_a_docker_refusal_is_not_one_settings_can_resolve(
        tmp_path, monkeypatch,
):
    app, _ = _restartable_slskd(
        tmp_path, monkeypatch, presence=ContainerPresence.UNKNOWN,
    )

    with pytest.raises(SlskdStartRefusedError) as refusal:
        app.restart_slskd()

    assert not isinstance(refusal.value, SlskdSetupNeededError)


def test_start_defaults_prefer_the_live_container_then_the_record(
        tmp_path, monkeypatch,
):
    app, _ = _restartable_slskd(tmp_path, monkeypatch)
    app.update_settings(
        slskd_share_path="/recorded/share",
        slskd_data_dir="/recorded/slskd-data",
    )

    defaults = app.slskd_start_defaults()

    assert defaults.username == "netuser"
    assert defaults.password == "netpass"
    assert defaults.share_path == "/Volumes/Music/Shared"
    assert defaults.data_dir == str(tmp_path / "slskd-data")

    _fake_live_slskd_mounts(monkeypatch, {})

    defaults = app.slskd_start_defaults()

    assert defaults.share_path == "/recorded/share"
    assert defaults.data_dir == "/recorded/slskd-data"
    assert defaults.data_dir_state is SlskdDataFolderState.MISSING


def test_start_defaults_with_nothing_saved_offer_the_default_folder(
        tmp_path, monkeypatch,
):
    app = _application_with_tmp_config(tmp_path, monkeypatch)
    _fake_slskd_bring_up(tmp_path, monkeypatch)

    defaults = app.slskd_start_defaults()

    assert (defaults.username, defaults.password) == ("", "")
    assert defaults.share_path is None
    assert defaults.data_dir == str(tmp_path / "slskd-data")


def test_a_data_folder_state_says_what_slskd_keeps(tmp_path):
    from seeker.soulseek.docker_setup import slskd_data_folder_state

    assert slskd_data_folder_state(str(tmp_path / "gone")) is (
        SlskdDataFolderState.MISSING
    )
    assert slskd_data_folder_state(str(tmp_path)) is SlskdDataFolderState.FRESH

    (tmp_path / "slskd.yml").write_text("soulseek: {}\n")

    assert slskd_data_folder_state(str(tmp_path)) is (
        SlskdDataFolderState.HOLDS_STATE
    )


def test_leftover_service_reads_the_download_folder_at_call_time(
        tmp_path, monkeypatch,
):
    from seeker.soulseek.leftovers import LeftoverFolderUnknownError

    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )
    data_dir.mkdir(parents=True)
    save_config(
        SeekerConfig(
            slskd_base_url="http://slskd.test",
            slskd_api_key="key",
            slskd_download_dir=str(tmp_path / "first"),
        ),
        data_dir / "config.json",
    )
    app = Application()
    service = app.leftover_service

    app.persist_soulseek_config(
        "http://slskd.test", "key", str(tmp_path / "second"), "user", "pass",
    )

    with pytest.raises(LeftoverFolderUnknownError, match="second"):
        service.list_leftover_files()
