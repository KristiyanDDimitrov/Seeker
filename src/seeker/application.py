from pathlib import Path

from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.library.service import LibraryService
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

        self._spotify = None
        self._sync_service = None
        self._library_service = None

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
