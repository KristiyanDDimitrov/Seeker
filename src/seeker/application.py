import logging
import threading
from dataclasses import replace
from pathlib import Path

import platformdirs

from seeker import config, login_item
from seeker.config_store import (
    SeekerConfig,
    load_config,
    migrate_legacy_env_config,
    resolve_config_path,
    save_config,
)
from seeker.dashboard_service import DashboardService
from seeker.database.connection import Database
from seeker.database.repositories.download_request_repository import (
    DownloadRequestRepository,
)
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.playlist_repository import (
    PlaylistRepository,
)
from seeker.database.repositories.rejection_repository import (
    RejectionRepository,
)
from seeker.database.repositories.soulseek_review_candidate_repository import (
    SoulseekReviewCandidateRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.docker_setup import (
    SLSKD_LOCAL_BASE_URL,
    DockerState,
    SlskdStartRefusedError,
    bring_up_slskd,
    compose_file_path,
    detect_docker_state,
    ensure_full_path_environment,
    generate_api_key,
    slskd_data_dir,
)
from seeker.history_service import HistoryService
from seeker.library.duplicate_service import DuplicateService
from seeker.library.matcher import TrackMatcher
from seeker.library.metadata_service import MetadataService
from seeker.library.service import LibraryService
from seeker.models.data_locations import DataLocations
from seeker.models.location_removal import LocationRemovalSummary
from seeker.models.slskd_start import SlskdStartResult
from seeker.sharing_service import SharingService
from seeker.soulseek.client import SoulseekClient
from seeker.soulseek.download_service import DownloadService
from seeker.spotify.auth_manager import SpotifyAuthManager
from seeker.spotify.callback_server import DEFAULT_REDIRECT_URI
from seeker.spotify.client import SpotifyClient
from seeker.spotify.sync_service import SpotifySyncService
from seeker.spotify.token_store import TokenStore

logger = logging.getLogger(__name__)


def _resolve_database_path() -> Path:
    data_dir = Path(platformdirs.user_data_dir("Seeker", appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)

    return data_dir / "seeker.db"


def resolve_log_dir() -> Path:
    # Shared by main_ui.py's RotatingFileHandler setup and
    # data_locations below — one resolved path, never a second,
    # drifting copy (§7.2.3).
    log_dir = Path(platformdirs.user_log_dir("Seeker", appauthor=False))
    log_dir.mkdir(parents=True, exist_ok=True)

    return log_dir


def _resolve_spotify_token_path() -> Path:
    # Lives alongside the DB in the same per-user app-data directory —
    # never CWD-relative: macOS starts a double-clicked .app with its
    # CWD at `/`, the read-only system volume (HISTORY §43).
    data_dir = Path(platformdirs.user_data_dir("Seeker", appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)

    return data_dir / "spotify_token.json"


class Application:
    def __init__(self) -> None:
        # Must run before anything Docker-related (wizard/Settings'
        # detect_docker_state/bring_up_slskd) — a GUI-launched .app
        # gets launchd's minimal PATH, which doesn't include
        # /usr/local/bin or /opt/homebrew/bin, so `docker` can't be
        # found even when genuinely installed and running. See item 44.
        ensure_full_path_environment()

        self.database = Database(_resolve_database_path())

        self.database.initialize()

        self._spotify_token_path = _resolve_spotify_token_path()

        # Runs before anything constructs a SoulseekClient, so
        # soulseek_client/soulseek_configured/download_service below
        # always see the post-migration config store state.
        self._config_store: SeekerConfig = migrate_legacy_env_config(
            resolve_config_path()
        )

        self._auth_manager: SpotifyAuthManager | None = None
        self._spotify: SpotifyClient | None = None
        self._sync_service: SpotifySyncService | None = None
        self._library_service: LibraryService | None = None
        self._track_matcher: TrackMatcher | None = None
        self._soulseek_client: SoulseekClient | None = None
        self._download_service: DownloadService | None = None
        self._metadata_service: MetadataService | None = None
        self._dashboard_service: DashboardService | None = None
        self._duplicate_service: DuplicateService | None = None
        self._history_service: HistoryService | None = None
        self._sharing_service: SharingService | None = None

    @property
    def settings(self) -> SeekerConfig:
        """Read-only view of the persisted config store — the public
        surface presentation-layer code reads instead of reaching into
        `self.application._config_store` directly (round 8 §7.1).
        """
        return self._config_store

    def update_settings(self, **changes: object) -> SeekerConfig:
        """Persist arbitrary `SeekerConfig` field changes and refresh
        the in-memory config store — the generic counterpart to the
        domain-specific setters below (persist_default_destination,
        set_notification_preference, etc.) for presentation-layer code
        saving fields that don't need their own single-purpose method
        (round 8 §7.1 — replaces a direct
        `self.application._config_store = updated` write from
        settings_window.py, which bypassed this class entirely). A
        change that also requires cache invalidation (a client_id or
        SoulSeek credential change) still goes through
        connect_spotify/persist_soulseek_config, not this.
        """
        config_path = resolve_config_path()
        current = load_config(config_path)
        updated = replace(current, **changes)  # type: ignore[arg-type]
        save_config(updated, config_path)
        self._config_store = updated

        return updated

    @property
    def _spotify_client_id(self) -> str | None:
        # Config store value takes precedence — env is only a fallback
        # for a setup that hasn't gone through migration (or is
        # env-only by choice) — same chain as the SLSKD_* properties
        # below. See config_store.py.
        return self._config_store.spotify_client_id or config.spotify_client_id()

    @property
    def _spotify_redirect_uri(self) -> str | None:
        # Unlike client_id, this one has a real, app-controlled default
        # rather than falling through to None — Spotify requires an
        # exact match against what's registered on the developer
        # dashboard, so a fixed, copy-pasteable value (matching what
        # callback_server.py actually listens on) is what the
        # onboarding wizard offers, not a free-text field.
        return (
            self._config_store.spotify_redirect_uri
            or config.spotify_redirect_uri()
            or DEFAULT_REDIRECT_URI
        )

    @property
    def spotify_configured(self) -> bool:
        return bool(self._spotify_client_id and self._spotify_redirect_uri)

    @property
    def auth_manager(self) -> SpotifyAuthManager:
        if self._auth_manager is None:
            if not self._spotify_client_id:
                raise RuntimeError("SPOTIFY_CLIENT_ID is not configured.")

            if not self._spotify_redirect_uri:
                raise RuntimeError(
                    "SPOTIFY_REDIRECT_URI is not configured."
                )

            self._auth_manager = SpotifyAuthManager(
                client_id=self._spotify_client_id,
                redirect_uri=self._spotify_redirect_uri,
                token_path=self._spotify_token_path,
            )

        return self._auth_manager

    def connect_spotify(
            self,
            client_id: str,
            force_reauthorize: bool = False,
            cancel: threading.Event | None = None,
    ) -> None:
        """Persist client_id to the config store and trigger the OAuth
        flow. Shared by the onboarding wizard's first-time connect and
        Settings' "Re-authorize" action (Step 8 §3) — extracted from
        the wizard's own inline do_connect() closure so both call the
        identical logic instead of two copies that could drift.

        force_reauthorize additionally clears any cached token first:
        get_valid_token() would otherwise just silently return an
        existing still-valid token without ever opening the browser,
        which is correct for the wizard's first connect (no token
        exists yet) but would make Settings' "Re-authorize" a no-op
        for an already-connected setup.

        Setting `cancel` from another thread ends the wait for the
        browser with AuthorizationCancelledError and frees the callback
        port.
        """
        config_path = resolve_config_path()
        current = load_config(config_path)
        updated = replace(
            current,
            spotify_client_id=client_id,
            spotify_redirect_uri=DEFAULT_REDIRECT_URI,
        )
        save_config(updated, config_path)
        self._config_store = updated
        self._auth_manager = None
        # B8.1 — a cached SpotifyClient (or a SpotifySyncService built on
        # top of one) from an earlier call in this same session must not
        # survive a new client_id/re-authorize: without this, `self.spotify`
        # below short-circuits on the already-non-None cache and never
        # calls auth_manager.get_valid_token() at all, so Settings'
        # "Re-authorize" was a silent no-op that kept the dead token.
        self._spotify = None
        self._sync_service = None

        if force_reauthorize:
            TokenStore(self._spotify_token_path).clear()

        # Triggers the existing OAuth flow — opens the system browser
        # and waits for the local callback. An explicit call, not a
        # bare property access relied on for its side effect (B018,
        # round 8 §4.8.6): a bare `self.spotify` statement reads as
        # dead code to a linter or a future cleanup and deleting it
        # would silently break first-time Spotify connect.
        self.auth_manager.get_valid_token(cancel=cancel)

    def persist_soulseek_config(
            self,
            base_url: str,
            api_key: str,
            download_dir: str,
            username: str,
            password: str,
    ) -> None:
        """Persist real SoulSeek connection details to the config
        store. Shared by the onboarding wizard's first bring-up and
        Settings' "Update SoulSeek credentials" action (Step 8 §3) —
        extracted from the wizard's own _persist_soulseek_config so
        both write the identical shape, including the network
        username/password this method is what first started
        persisting at all (see config_store.py — item 19 deliberately
        left them out, pending exactly this real consumer).
        """
        config_path = resolve_config_path()
        current = load_config(config_path)
        updated = replace(
            current,
            slskd_base_url=base_url,
            slskd_api_key=api_key,
            slskd_download_dir=download_dir,
            slskd_username=username,
            slskd_password=password,
        )
        save_config(updated, config_path)
        self._config_store = updated
        self._soulseek_client = None
        # A DownloadService constructed earlier in this session (e.g.
        # Settings' destinations tab, before SoulSeek was ever set up)
        # may have been built with soulseek_client=None — without this
        # reset too, it would keep raising on any SoulSeek-dependent
        # method forever, even after real credentials just landed.
        self._download_service = None
        self._sharing_service = None

    def start_slskd(
            self,
            soulseek_username: str,
            soulseek_password: str,
            share_path: str,
            *,
            persist: bool,
    ) -> SlskdStartResult:
        """(Re)create the slskd container with a freshly generated API
        key, sharing `share_path` read-only. Blocks on `docker compose
        up`, so callers run it on a worker; raises `SlskdBringUpError`
        when Compose fails.

        `persist` is explicit because the two callers save at different
        moments: Settings passes True and saves as soon as the
        container is up; the wizard passes False and saves the returned
        values only once its health poll confirms the network login.
        Sharing's recreate does not come through here — it keeps the
        saved key and login and the live container's data directory,
        so it calls `docker_setup.bring_up_slskd` directly.
        """
        api_key = generate_api_key()
        # An existing container keeps its data directory (slskd's own
        # state and any finished downloads), wherever it was created.
        live_data_dir = self.sharing_service.current_data_dir()
        data_dir = Path(live_data_dir) if live_data_dir else slskd_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        web_username, web_password = self.ensure_slskd_web_credentials()

        bring_up_slskd(
            compose_file=str(compose_file_path()),
            soulseek_username=soulseek_username,
            soulseek_password=soulseek_password,
            api_key=api_key,
            slskd_data_dir=str(data_dir),
            web_username=web_username,
            web_password=web_password,
            library_location_path=share_path,
        )

        result = SlskdStartResult(
            api_key=api_key, download_dir=str(data_dir / "downloads"),
        )

        if persist:
            self.persist_soulseek_config(
                SLSKD_LOCAL_BASE_URL,
                result.api_key,
                result.download_dir,
                soulseek_username,
                soulseek_password,
            )

        return result

    def restart_slskd(self) -> SlskdStartResult:
        """Start slskd again after an outage through `start_slskd`,
        sharing exactly what the stopped container shares and logging
        in with the saved SoulSeek login. Blocks on Docker, so callers
        run it on a worker.

        Raises `SlskdStartRefusedError` rather than guess: when Docker
        is not up, when the container is not one Seeker created (or is
        gone, so its share cannot be read), or when no login is saved.
        """
        docker_state = detect_docker_state()

        if docker_state is DockerState.NOT_INSTALLED:
            raise SlskdStartRefusedError(
                "Docker isn't installed, so Seeker can't start slskd."
            )

        if docker_state is not DockerState.RUNNING:
            raise SlskdStartRefusedError(
                "Docker isn't running. Open Docker Desktop, then try again."
            )

        share_path = (
            self.sharing_service.current_share_path()
            if self.sharing_service.is_self_managed() else None
        )

        if share_path is None:
            raise SlskdStartRefusedError(
                "Seeker can't find the slskd container it set up, so it "
                "won't guess what to share. Start slskd where it runs, or "
                "set it up again in Settings → Connection."
            )

        username = self._config_store.slskd_username
        password = self._config_store.slskd_password

        if not username or not password:
            raise SlskdStartRefusedError(
                "Seeker has no saved SoulSeek login. Enter it in "
                "Settings → Connection."
            )

        return self.start_slskd(username, password, share_path, persist=True)

    def ensure_slskd_web_credentials(self) -> tuple[str, str]:
        """Return the slskd WEB UI login, generating and persisting it
        once if it doesn't exist yet.

        Roadmap item 116 (round 8, §6.1.2) — Seeker never set this
        before this item, leaving slskd's web UI at its own vendor
        default ("slskd"/"slskd"). If both fields are already set,
        return them unchanged — never rotate a real, working login
        silently. This is the upgrade path for an existing install:
        nothing changes until the next real `bring_up_slskd` call
        (wizard bring-up, "Update SoulSeek credentials," or a Sharing
        add-location recreate), at which point it gets a real generated
        password instead of the vendor default, exactly once.
        """
        if (
                self._config_store.slskd_web_username
                and self._config_store.slskd_web_password
        ):
            return (
                self._config_store.slskd_web_username,
                self._config_store.slskd_web_password,
            )

        username = "seeker"
        password = generate_api_key()

        config_path = resolve_config_path()
        current = load_config(config_path)
        updated = replace(
            current,
            slskd_web_username=username,
            slskd_web_password=password,
        )
        save_config(updated, config_path)
        self._config_store = updated

        return username, password

    def persist_default_destination(
            self,
            location_id: int,
            subfolder_per_playlist: bool,
    ) -> None:
        """Persist the fallback destination roadmap item 6 adds — used
        once a playlist has no destination of its own (see
        DownloadService._resolve_destination). No client/service reset
        needed, unlike persist_soulseek_config's credential change:
        DownloadService already reads config fresh via its own
        get_config callable on every resolution, never a cached
        snapshot.
        """
        config_path = resolve_config_path()
        current = load_config(config_path)
        updated = replace(
            current,
            default_download_location_id=location_id,
            default_download_subfolder_per_playlist=subfolder_per_playlist,
        )
        save_config(updated, config_path)
        self._config_store = updated

    def preview_remove_location(self, name: str) -> LocationRemovalSummary:
        return self.library_service.preview_remove_location(
            name,
            default_location_id=self._config_store.default_download_location_id,
        )

    def remove_location(self, name: str) -> LocationRemovalSummary:
        """Removes a library location (see
        `LibraryService.remove_location`) and, when it was the default
        download destination, clears that too so `config.json` never
        keeps a dangling id.
        """
        summary = self.library_service.remove_location(
            name,
            default_location_id=self._config_store.default_download_location_id,
        )

        if summary.was_default:
            self.update_settings(default_download_location_id=None)

        return summary

    @property
    def downloads_paused(self) -> bool:
        return self._config_store.downloads_paused

    def set_downloads_paused(self, paused: bool) -> None:
        """Roadmap item R7.4 — persisted so pause/resume survives a
        restart, and read fresh by DownloadService.poll_downloads()
        itself on every call (via its own get_config callable) so
        pausing is authoritative regardless of which caller —
        menu-bar toggle or the main window's own mirrored control —
        set it last."""
        config_path = resolve_config_path()
        current = load_config(config_path)
        updated = replace(current, downloads_paused=paused)
        save_config(updated, config_path)
        self._config_store = updated

    @property
    def theme_mode(self) -> str:
        return self._config_store.theme_mode

    def set_theme_mode(self, mode: str) -> None:
        """Roadmap item C5 (round 5) — persisted so the choice survives
        a restart; read fresh by `main_ui.py` at startup and updated
        live by `MainWindow`'s own theme toggle/Settings control, same
        shape as `set_downloads_paused`."""
        config_path = resolve_config_path()
        current = load_config(config_path)
        updated = replace(current, theme_mode=mode)
        save_config(updated, config_path)
        self._config_store = updated

    def mark_tray_hide_notice_shown(self) -> None:
        """Roadmap item R7.1 — the one-off "still running in the menu
        bar" notification's own shown-once flag."""
        config_path = resolve_config_path()
        current = load_config(config_path)
        updated = replace(current, tray_hide_notice_shown=True)
        save_config(updated, config_path)
        self._config_store = updated

    def set_notification_preference(
            self,
            field_name: str,
            enabled: bool,
    ) -> None:
        """Roadmap item R7.5 — one setter for all three per-category
        toggles (notify_downloads_finished/notify_needs_decision/
        notify_errors), keyed by field name the same way
        migrate_legacy_env_config already does for its own field set,
        rather than three near-identical methods."""
        config_path = resolve_config_path()
        current = load_config(config_path)
        updated = replace(current, **{field_name: enabled})  # type: ignore[arg-type]
        save_config(updated, config_path)
        self._config_store = updated

    @property
    def login_item_supported(self) -> bool:
        """macOS-and-packaged-build-only (round 9 §3.2) — Settings uses
        this to show the "only available in the packaged app" state
        rather than silently no-opping the toggle under `uv run`."""
        return login_item.is_supported()

    def login_item_status(self) -> login_item.LoginItemStatus:
        """Always the REAL, live ServiceManagement status, never a
        mirrored config.json boolean — Settings calls this fresh every
        time its page renders so a login item the user revoked via
        System Settings shows as off here too."""
        return login_item.get_status()

    def set_login_item_enabled(self, enabled: bool) -> login_item.LoginItemStatus:
        """Register/unregister the login item and return the resulting
        real status (which can be REQUIRES_APPROVAL even after a
        successful register — Settings surfaces that distinctly rather
        than claiming it's simply on)."""
        return login_item.set_enabled(enabled)

    @property
    def spotify(self) -> SpotifyClient:
        if self._spotify is None:
            # A bound callable, not a frozen token string (roadmap item
            # 92 / B8.2) — a SpotifyClient built early in a long-running
            # session and used again after the access token's 1-hour
            # lifetime now gets a token get_valid_token() has already
            # refreshed, instead of replaying the same dead one forever.
            # force_refresh is the B8.3 safety net for a 401 the clock
            # didn't predict (get_valid_token(force_refresh=True) skips
            # the expiry check entirely).
            self._spotify = SpotifyClient(
                token_source=lambda: self.auth_manager.get_valid_token().access_token,
                force_refresh=lambda: self.auth_manager.get_valid_token(
                    force_refresh=True
                ).access_token,
            )

        return self._spotify

    @property
    def sync_service(self) -> SpotifySyncService:
        if self._sync_service is None:
            self._sync_service = SpotifySyncService(
                self.spotify,
                self.database,
                PlaylistRepository(),
                TrackRepository(),
            )

        return self._sync_service

    @property
    def library_service(self) -> LibraryService:
        if self._library_service is None:
            self._library_service = LibraryService(
                self.database,
                LibraryLocationRepository(),
                LocalFileRepository(),
                track_matcher=self.track_matcher,
                playlist_repo=PlaylistRepository(),
            )

        return self._library_service

    @property
    def track_matcher(self) -> TrackMatcher:
        if self._track_matcher is None:
            self._track_matcher = TrackMatcher(
                self.database,
                TrackRepository(),
                LocalFileRepository(),
                TrackMatchRepository(),
                get_config=lambda: self._config_store,
                rejection_repository=RejectionRepository(),
            )

        return self._track_matcher

    @property
    def slskd_base_url(self) -> str | None:
        # Config store value takes precedence — env is only a fallback
        # for a setup that hasn't gone through migration (or is
        # env-only by choice). See config_store.py. Public (round 8
        # §7.1): includes the env fallback `settings.slskd_base_url`
        # alone doesn't, so presentation-layer code that needs the
        # actually-resolved value reads this instead.
        return self._config_store.slskd_base_url or config.slskd_base_url()

    @property
    def slskd_api_key(self) -> str | None:
        return self._config_store.slskd_api_key or config.slskd_api_key()

    @property
    def slskd_download_dir(self) -> str | None:
        return (
            self._config_store.slskd_download_dir
            or config.slskd_download_dir()
        )

    @property
    def soulseek_configured(self) -> bool:
        # Deliberately a cheap config check, not a soulseek_client access
        # — the latter raises when unconfigured, and `check` (unlike the
        # download/status commands) must keep working without slskd set
        # up at all (see config.py). CLI code checks this before calling
        # anything that would otherwise force soulseek_client into
        # existence just to read already-persisted review candidates.
        return bool(self.slskd_base_url and self.slskd_api_key)

    @property
    def soulseek_client(self) -> SoulseekClient:
        if self._soulseek_client is None:
            if not self.slskd_base_url:
                raise RuntimeError("SLSKD_BASE_URL is not configured.")

            if not self.slskd_api_key:
                raise RuntimeError("SLSKD_API_KEY is not configured.")

            self._soulseek_client = SoulseekClient(
                self.slskd_base_url,
                self.slskd_api_key,
            )

        return self._soulseek_client

    @property
    def download_service(self) -> DownloadService:
        if self._download_service is None:
            # soulseek_configured, not self.soulseek_client directly —
            # the latter raises immediately when unconfigured, which
            # would make DownloadService itself unconstructable even
            # for methods that never touch SoulSeek at all
            # (set_destination, get_review_candidates,
            # get_pending_upgrade_reviews — Settings needs all three
            # usable regardless of SoulSeek setup, since it's the
            # wizard's own optional, skippable step). DownloadService's
            # own `soulseek` property raises the same clear error, just
            # deferred to the point a method that genuinely needs it is
            # actually called — same end-user-visible outcome for the
            # CLI/download path, no regression there.
            self._download_service = DownloadService(
                self.database,
                self.soulseek_client if self.soulseek_configured else None,
                PlaylistRepository(),
                TrackRepository(),
                LibraryLocationRepository(),
                DownloadRequestRepository(),
                TrackMatchRepository(),
                LocalFileRepository(),
                SoulseekReviewCandidateRepository(),
                self.slskd_download_dir,
                get_config=lambda: self._config_store,
                rejection_repository=RejectionRepository(),
            )

        return self._download_service

    @property
    def metadata_service(self) -> MetadataService:
        if self._metadata_service is None:
            self._metadata_service = MetadataService(
                self.database,
                TrackRepository(),
                TrackMatchRepository(),
                LocalFileRepository(),
                LibraryLocationRepository(),
                PlaylistRepository(),
                get_config=lambda: self._config_store,
            )

        return self._metadata_service

    @property
    def dashboard_service(self) -> DashboardService:
        if self._dashboard_service is None:
            self._dashboard_service = DashboardService(
                self.database,
                PlaylistRepository(),
                TrackRepository(),
                TrackMatchRepository(),
                DownloadRequestRepository(),
                SoulseekReviewCandidateRepository(),
                LocalFileRepository(),
            )

        return self._dashboard_service

    @property
    def duplicate_service(self) -> DuplicateService:
        if self._duplicate_service is None:
            self._duplicate_service = DuplicateService(
                self.database,
                LibraryLocationRepository(),
                LocalFileRepository(),
                TrackMatchRepository(),
            )

        return self._duplicate_service

    @property
    def history_service(self) -> HistoryService:
        if self._history_service is None:
            self._history_service = HistoryService(
                self.database,
                DownloadRequestRepository(),
                LocalFileRepository(),
                TrackMatchRepository(),
                TrackRepository(),
                PlaylistRepository(),
            )

        return self._history_service

    @property
    def sharing_service(self) -> SharingService:
        if self._sharing_service is None:
            # Same soulseek_configured-gated construction shape as
            # download_service above -- a caller that only wants
            # is_self_managed()/preview_add_location must not be forced
            # to have SoulSeek configured at all.
            self._sharing_service = SharingService(
                self.soulseek_client if self.soulseek_configured else None,
                self.database,
                LibraryLocationRepository(),
                get_config=lambda: self._config_store,
            )

        return self._sharing_service

    @property
    def data_locations(self) -> DataLocations:
        # Cheap, synchronous, purely local path resolution (no DB/
        # network I/O) — every value here was already computed once in
        # __init__ (self.database.path/self._spotify_token_path) or is
        # a plain platformdirs join (resolve_config_path()/
        # slskd_data_dir()), so this needs no lazy-load/run_worker
        # treatment the way a real DB read would.
        return DataLocations(
            database_path=self.database.path,
            config_path=resolve_config_path(),
            spotify_token_path=self._spotify_token_path,
            slskd_data_dir=slskd_data_dir(),
            base_dir=self.database.path.parent,
            log_dir=resolve_log_dir(),
        )

    @property
    def onboarding_complete(self) -> bool:
        # The two REQUIRED onboarding steps only — Spotify connect and
        # at least one library location. SoulSeek/Docker setup is
        # deliberately excluded: it's the wizard's third, skippable
        # step ("Set up later"), so its completeness must never gate
        # whether main_ui.py routes to the dashboard vs. the wizard —
        # an unconfigured slskd is handled by soulseek_configured
        # disabling SoulSeek-dependent actions, the same way it already
        # does for the CLI.
        return bool(
            self.spotify_configured and self.library_service.list_locations()
        )
