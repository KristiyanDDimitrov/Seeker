from dataclasses import dataclass

# Roadmap item 82 (P13) — a manual (not-from-Spotify) search-and-
# download track is a real `tracks` row belonging to no playlist, id
# `manual:<uuid4>`. Prefix-checked rather than a separate boolean
# column — no schema change, and every existing `tracks`/
# `download_requests` query already works unchanged since the id is
# still a plain string primary key with no format constraint.
MANUAL_TRACK_ID_PREFIX = "manual:"


def is_manual_track_id(track_id: str) -> bool:
    return track_id.startswith(MANUAL_TRACK_ID_PREFIX)


def resolve_playlist_label(track_id: str, playlist_names: list[str]) -> str:
    """Shared by DashboardService.get_active_downloads and both
    HistoryService event kinds — the same "which playlist is this
    track from" display label, so a future third call site can't drift
    into a fourth, differently-worded copy the way matching.py's own
    history warns against (see CLAUDE.md). A manual track always
    resolves to "Manual" (a real, expected state, not a data-integrity
    concern) rather than falling through to "Unknown", which exists
    for the genuinely-unexpected case of a real Spotify track with no
    playlist_tracks row at all.
    """
    if is_manual_track_id(track_id):
        return "Manual"

    return ", ".join(playlist_names) or "Unknown"


@dataclass
class Track:
    id: str
    title: str
    artist: str
    album: str
    duration_ms: int
    album_art_url: str | None = None