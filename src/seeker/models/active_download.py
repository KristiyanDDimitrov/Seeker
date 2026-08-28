from dataclasses import dataclass

from seeker.models.download_request import DownloadRequest
from seeker.models.track import Track


@dataclass
class ActiveDownload:
    request: DownloadRequest
    track: Track
    # Joined-for-display playlist name(s) this track belongs to — usually
    # one, but a track can legitimately be synced into more than one
    # playlist, so this is a comma-joined string rather than a single
    # name. "Unknown" only if a track is somehow no longer linked to any
    # playlist (playlist deleted after the request was made).
    playlist_name: str
