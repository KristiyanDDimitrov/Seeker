from PySide6.QtCore import QObject, Signal

from seeker.models.playlist import Playlist


class PlaylistSelection(QObject):
    """The playlist/track selection Dashboard and Library both act on
    (round9 §7.1). Owned by the shell (one instance, `MainWindow.
    playlist_selection`), handed to every page via `PageContext.
    playlist_selection` — replaces the prior arrangement where
    `LibraryHost`/`TaggingPanelHost` reached into DashboardPage's own
    attributes through read-only callables, which could not support a
    second writer (§7.2 needs Library to change the playlist too).

    Dashboard is the sole writer today; Library becomes a second
    writer in §7.2. Both are readers, and both are meant to re-render
    on `changed` — Dashboard already does, by construction, since its
    own selection UI is what drives a write.
    """

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._playlist: Playlist | None = None
        self._track_ids: list[str] = []

    @property
    def playlist(self) -> Playlist | None:
        return self._playlist

    @property
    def track_ids(self) -> list[str]:
        return list(self._track_ids)

    def set_playlist(self, playlist: Playlist | None) -> None:
        if playlist == self._playlist:
            return

        self._playlist = playlist
        self._track_ids = []
        self.changed.emit()

    def set_track_ids(self, track_ids: list[str]) -> None:
        if track_ids == self._track_ids:
            return

        self._track_ids = list(track_ids)
        self.changed.emit()
