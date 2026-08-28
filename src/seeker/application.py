import shutil
from pathlib import Path

import platformdirs

from seeker import config
from seeker.config_store import (
    SeekerConfig,
    migrate_legacy_slskd_env_config,
    resolve_config_path,
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
from seeker.library.matcher import TrackMatcher
from seeker.library.metadata_service import MetadataService
from seeker.library.service import LibraryService
from seeker.soulseek.client import SoulseekClient
from seeker.soulseek.download_service import DownloadService
from seeker.spotify.auth_manager import SpotifyAuthManager
from seeker.spotify.client import SpotifyClient
from seeker.spotify.sync_service import SpotifySyncService


# Pre-platformdirs location — a real, non-empty database may still exist
# here from before this migrated to an OS-conventional app-data
# directory. Relative to the current working directory, matching where
# it was always created before.
LEGACY_DATABASE_PATH = Path(".seeker/seeker.db")


def _resolve_database_path() -> Path:
    data_dir = Path(platformdirs.user_data_dir("Seeker", appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)

    return data_dir / "seeker.db"


def _migrate_legacy_database(
        new_path: Path,
        legacy_path: Path = LEGACY_DATABASE_PATH,
) -> bool:
    # Only migrate into a genuinely fresh install — never overwrite a
    # database that already exists at the new location (e.g. a second
    # run after the migration already happened once).
    if new_path.exists() or not legacy_path.exists():
        return False

    shutil.move(str(legacy_path), str(new_path))
    print(f"Migrated existing database from {legacy_path} to {new_path}.")

    return True


class Application:
    def __init__(
        self,
        spotify_client_id: str,
        spotify_redirect_uri: str,
    ):
        db_path = _resolve_database_path()
        _migrate_legacy_database(db_path)

        self.database = Database(db_path)

        self.database.initialize()

        # Same ordering principle as the DB migration above: run before
        # anything constructs a SoulseekClient, so soulseek_client/
        # soulseek_configured/download_service below always see the
        # post-migration config store state.
        self._config_store: SeekerConfig = migrate_legacy_slskd_env_config(
            resolve_config_path()
        )

        self.auth_manager = SpotifyAuthManager(
            client_id=spotify_client_id,
            redirect_uri=spotify_redirect_uri,
            token_path=Path(
                ".seeker/spotify_token.json"
            ),
        )

        self._spotify: SpotifyClient | None = None
        self._sync_service: SpotifySyncService | None = None
        self._library_service: LibraryService | None = None
        self._track_matcher: TrackMatcher | None = None
        self._soulseek_client: SoulseekClient | None = None
        self._download_service: DownloadService | None = None
        self._metadata_service: MetadataService | None = None
        self._dashboard_service: DashboardService | None = None

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
            self._download_service = DownloadService(
                self.database,
                self.soulseek_client,
                PlaylistRepository(self.database),
                TrackRepository(self.database),
                LibraryLocationRepository(self.database),
                DownloadRequestRepository(self.database),
                TrackMatchRepository(self.database),
                LocalFileRepository(self.database),
                SoulseekReviewCandidateRepository(self.database),
                self._slskd_download_dir,
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
