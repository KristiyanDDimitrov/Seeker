from pathlib import Path

from seeker import config
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
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.library.matcher import TrackMatcher
from seeker.library.metadata_service import MetadataService
from seeker.library.service import LibraryService
from seeker.soulseek.client import SoulseekClient
from seeker.soulseek.download_service import DownloadService
from seeker.spotify.auth_manager import SpotifyAuthManager
from seeker.spotify.client import SpotifyClient
from seeker.spotify.sync_service import SpotifySyncService


class Application:
    def __init__(
        self,
        spotify_client_id: str,
        spotify_redirect_uri: str,
    ):
        self.database = Database(
            Path(".seeker/seeker.db")
        )

        self.database.initialize()

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
    def soulseek_client(self) -> SoulseekClient:
        if self._soulseek_client is None:
            if not config.SLSKD_BASE_URL:
                raise RuntimeError("SLSKD_BASE_URL is not configured.")

            if not config.SLSKD_API_KEY:
                raise RuntimeError("SLSKD_API_KEY is not configured.")

            self._soulseek_client = SoulseekClient(
                config.SLSKD_BASE_URL,
                config.SLSKD_API_KEY,
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
                config.SLSKD_DOWNLOAD_DIR,
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
