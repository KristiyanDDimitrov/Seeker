import shutil
from dataclasses import replace
from pathlib import Path

import platformdirs

from seeker import config
from seeker.config_store import (
    SeekerConfig,
    load_config,
    migrate_legacy_env_config,
    resolve_config_path,
    save_config,
)
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
from seeker.database.repositories.soulseek_review_candidate_repository import (
    SoulseekReviewCandidateRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.dashboard_service import DashboardService
from seeker.docker_setup import ensure_full_path_environment, slskd_data_dir
from seeker.history_service import HistoryService
from seeker.library.duplicate_service import DuplicateService
from seeker.library.matcher import TrackMatcher
from seeker.library.metadata_service import MetadataService
from seeker.library.service import LibraryService
from seeker.models.data_locations import DataLocations
from seeker.soulseek.client import SoulseekClient
from seeker.soulseek.download_service import DownloadService
from seeker.spotify.auth_manager import SpotifyAuthManager
from seeker.spotify.client import SpotifyClient
from seeker.spotify.callback_server import DEFAULT_REDIRECT_URI
from seeker.spotify.sync_service import SpotifySyncService


# Pre-platformdirs location — a real, non-empty database may still exist
# here from before this migrated to an OS-conventional app-data
# directory. Relative to the current working directory, matching where
# it was always created before.
LEGACY_DATABASE_PATH = Path(".seeker/seeker.db")

# Same pre-platformdirs, CWD-relative story as LEGACY_DATABASE_PATH
# above — this one was originally left CWD-relative on the (wrong)
# assumption it was out of scope for that migration. A launch via
# `uv run seeker-ui` has a writable CWD (the project root), but macOS
# sets a double-clicked .app's CWD to `/` (the read-only Signed System
# Volume), so the `.seeker` mkdir in _save_token() fails there — a
# real bug only a real Finder launch surfaced, never the offscreen
# harness. See LEGACY_SPOTIFY_TOKEN_PATH below.
LEGACY_SPOTIFY_TOKEN_PATH = Path(".seeker/spotify_token.json")


def _resolve_database_path() -> Path:
    data_dir = Path(platformdirs.user_data_dir("Seeker", appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)

    return data_dir / "seeker.db"


def _resolve_spotify_token_path() -> Path:
    # Lives alongside the DB in the same per-user app-data directory —
    # not CWD-relative, so it works identically whether launched via
    # `uv run seeker-ui` or a double-clicked .app (see
    # LEGACY_SPOTIFY_TOKEN_PATH above).
    data_dir = Path(platformdirs.user_data_dir("Seeker", appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)

    return data_dir / "spotify_token.json"


def _migrate_legacy_file(new_path: Path, legacy_path: Path, label: str) -> bool:
    # Only migrate into a genuinely fresh install — never overwrite a
    # file that already exists at the new location (e.g. a second run
    # after the migration already happened once).
    if new_path.exists() or not legacy_path.exists():
        return False

    shutil.move(str(legacy_path), str(new_path))
    print(f"Migrated existing {label} from {legacy_path} to {new_path}.")

    return True


def _migrate_legacy_database(
        new_path: Path,
        legacy_path: Path = LEGACY_DATABASE_PATH,
) -> bool:
    return _migrate_legacy_file(new_path, legacy_path, "database")


def _migrate_legacy_spotify_token(
        new_path: Path,
        legacy_path: Path = LEGACY_SPOTIFY_TOKEN_PATH,
) -> bool:
    return _migrate_legacy_file(new_path, legacy_path, "Spotify token")


class Application:
    def __init__(self) -> None:
        # Must run before anything Docker-related (wizard/Settings'
        # detect_docker_state/bring_up_slskd) — a GUI-launched .app
        # gets launchd's minimal PATH, which doesn't include
        # /usr/local/bin or /opt/homebrew/bin, so `docker` can't be
        # found even when genuinely installed and running. See item 44.
        ensure_full_path_environment()

        db_path = _resolve_database_path()
        _migrate_legacy_database(db_path)

        self.database = Database(db_path)

        self.database.initialize()

        self._spotify_token_path = _resolve_spotify_token_path()
        _migrate_legacy_spotify_token(self._spotify_token_path)

        # Same ordering principle as the DB migration above: run before
        # anything constructs a SoulseekClient, so soulseek_client/
        # soulseek_configured/download_service below always see the
        # post-migration config store state.
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

    @property
    def _spotify_client_id(self) -> str | None:
        # Config store value takes precedence — env is only a fallback
        # for a setup that hasn't gone through migration (or is
        # env-only by choice) — same chain as the SLSKD_* properties
        # below. See config_store.py.
        return self._config_store.spotify_client_id or config.SPOTIFY_CLIENT_ID

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
            or config.SPOTIFY_REDIRECT_URI
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

        if force_reauthorize:
            from seeker.spotify.token_store import TokenStore

            TokenStore(self._spotify_token_path).clear()

        # Triggers the existing OAuth flow via
        # auth_manager.get_valid_token() — opens the system browser and
        # waits for the local callback.
        self.spotify

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

    @property
    def spotify(self) -> SpotifyClient:
        if self._spotify is None:
            token = self.auth_manager.get_valid_token()

            self._spotify = SpotifyClient(
                token.access_token
            )

        return self._spotify

    @property
    def sync_service(self) -> SpotifySyncService:
        if self._sync_service is None:
            self._sync_service = SpotifySyncService(
                self.spotify,
                self.database,
            )

        return self._sync_service

    @property
    def library_service(self) -> LibraryService:
        if self._library_service is None:
            self._library_service = LibraryService(
                self.database,
                LibraryLocationRepository(self.database),
                LocalFileRepository(self.database),
            )

        return self._library_service

    @property
    def track_matcher(self) -> TrackMatcher:
        if self._track_matcher is None:
            self._track_matcher = TrackMatcher(
                self.database,
                TrackRepository(self.database),
                LocalFileRepository(self.database),
                TrackMatchRepository(self.database),
                get_config=lambda: self._config_store,
            )

        return self._track_matcher

    @property
    def _slskd_base_url(self) -> str | None:
        # Config store value takes precedence — env is only a fallback
        # for a setup that hasn't gone through migration (or is
        # env-only by choice). See config_store.py.
        return self._config_store.slskd_base_url or config.SLSKD_BASE_URL

    @property
    def _slskd_api_key(self) -> str | None:
        return self._config_store.slskd_api_key or config.SLSKD_API_KEY

    @property
    def _slskd_download_dir(self) -> str | None:
        return (
            self._config_store.slskd_download_dir
            or config.SLSKD_DOWNLOAD_DIR
        )

    @property
    def soulseek_configured(self) -> bool:
        # Deliberately a cheap config check, not a soulseek_client access
        # — the latter raises when unconfigured, and `check` (unlike the
        # download/status commands) must keep working without slskd set
        # up at all (see config.py). CLI code checks this before calling
        # anything that would otherwise force soulseek_client into
        # existence just to read already-persisted review candidates.
        return bool(self._slskd_base_url and self._slskd_api_key)

    @property
    def soulseek_client(self) -> SoulseekClient:
        if self._soulseek_client is None:
            if not self._slskd_base_url:
                raise RuntimeError("SLSKD_BASE_URL is not configured.")

            if not self._slskd_api_key:
                raise RuntimeError("SLSKD_API_KEY is not configured.")

            self._soulseek_client = SoulseekClient(
                self._slskd_base_url,
                self._slskd_api_key,
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
                PlaylistRepository(self.database),
                TrackRepository(self.database),
                LibraryLocationRepository(self.database),
                DownloadRequestRepository(self.database),
                TrackMatchRepository(self.database),
                LocalFileRepository(self.database),
                SoulseekReviewCandidateRepository(self.database),
                self._slskd_download_dir,
                get_config=lambda: self._config_store,
            )

        return self._download_service

    @property
    def metadata_service(self) -> MetadataService:
        if self._metadata_service is None:
            self._metadata_service = MetadataService(
                self.database,
                TrackRepository(self.database),
                TrackMatchRepository(self.database),
                LocalFileRepository(self.database),
                LibraryLocationRepository(self.database),
                PlaylistRepository(self.database),
            )

        return self._metadata_service

    @property
    def dashboard_service(self) -> DashboardService:
        if self._dashboard_service is None:
            self._dashboard_service = DashboardService(
                self.database,
                PlaylistRepository(self.database),
                TrackRepository(self.database),
                TrackMatchRepository(self.database),
                DownloadRequestRepository(self.database),
                SoulseekReviewCandidateRepository(self.database),
                LocalFileRepository(self.database),
            )

        return self._dashboard_service

    @property
    def duplicate_service(self) -> DuplicateService:
        if self._duplicate_service is None:
            self._duplicate_service = DuplicateService(
                self.database,
                LibraryLocationRepository(self.database),
                LocalFileRepository(self.database),
                TrackMatchRepository(self.database),
            )

        return self._duplicate_service

    @property
    def history_service(self) -> HistoryService:
        if self._history_service is None:
            self._history_service = HistoryService(
                self.database,
                DownloadRequestRepository(self.database),
                LocalFileRepository(self.database),
                TrackMatchRepository(self.database),
                TrackRepository(self.database),
                PlaylistRepository(self.database),
            )

        return self._history_service

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
