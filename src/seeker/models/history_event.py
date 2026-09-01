from dataclasses import dataclass

# The only two kinds HistoryService derives — matches the History page's
# own subtitle ("Recently downloaded and tagged tracks, in one place").
# Deliberately excludes a "download failed" kind: download_requests has
# no persisted failure-reason column (the real slskd exception text is
# only ever seen live, at poll time, never written to the DB), so a
# failed-download event could show a status but never an honest detail
# — left to the Downloads page, which already surfaces live failures.
DOWNLOADED = "downloaded"
TAGGED = "tagged"


@dataclass
class HistoryEvent:
    # ISO 8601 UTC string, same convention as every other stored
    # timestamp in this codebase — formatting (local time) is the
    # caller's job via ui/formatting.format_timestamp, not baked in here.
    occurred_at: str
    event_type: str  # DOWNLOADED or TAGGED
    track_title: str
    track_artist: str
    # "Unknown" if the track is no longer linked to any playlist —
    # mirrors ActiveDownload.playlist_name's own precedent.
    playlist_name: str
    detail: str
