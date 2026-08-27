from pathlib import Path
from typing import Any

import httpx
from mutagen import File as MutagenFile

from seeker.audio_analysis import analyze_audio as run_audio_analysis
from seeker.database.connection import Database
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
from seeker.metadata import (
    embed_album_art,
    write_analysis_tags,
    write_text_tags,
)


class PlaylistNotFoundError(RuntimeError):
    pass


class MetadataService:
    def __init__(
        self,
        database: Database,
        track_repository: TrackRepository,
        track_match_repository: TrackMatchRepository,
        local_file_repository: LocalFileRepository,
        library_location_repository: LibraryLocationRepository,
        playlist_repository: PlaylistRepository,
    ):
        self.database = database
        self.tracks = track_repository
        self.track_matches = track_match_repository
        self.local_files = local_file_repository
        self.locations = library_location_repository
        self.playlists = playlist_repository

    def tag_playlist(
            self,
            playlist_name: str,
            analyze_audio: bool = False,
            expected_bpm_range: tuple[float, float] | None = None,
    ) -> dict[str, Any]:
        # Only auto-matched tracks — a needs_review match hasn't been
        # confirmed by a human yet, and writing Spotify's canonical
        # metadata onto a possibly-wrong file would be actively harmful.
        # Same caution as the existing download_playlist/review split.
        with self.database.transaction() as connection:
            playlist = self.playlists.get_by_name(playlist_name, connection)

            if playlist is None:
                raise PlaylistNotFoundError(
                    f"No playlist named '{playlist_name}' has been "
                    f"synced."
                )

            tracks = self.tracks.get_auto_matched_for_playlist(
                playlist.id, connection
            )

        return self.tag_tracks(
            [track.id for track in tracks],
            analyze_audio=analyze_audio,
            expected_bpm_range=expected_bpm_range,
        )

    def tag_tracks(
            self,
            track_ids: list[str],
            analyze_audio: bool = False,
            expected_bpm_range: tuple[float, float] | None = None,
    ) -> dict[str, Any]:
        counts: dict[str, int] = {
            "tagged": 0,
            "skipped_no_match": 0,
            "skipped_format_unsupported": 0,
            "failed": 0,
        }
        details: list[dict[str, str]] = []

        for track_id in track_ids:
            # One bad file must not abort the batch.
            try:
                self._tag_one_track(
                    track_id,
                    counts,
                    details,
                    analyze_audio,
                    expected_bpm_range,
                )
            except Exception as error:
                counts["failed"] += 1
                details.append(
                    {
                        "track_id": track_id,
                        "reason": "failed",
                        "message": str(error),
                    }
                )
                print(f"  Failed to tag track {track_id}: {error}")

        return {**counts, "details": details}

    def _tag_one_track(
            self,
            track_id: str,
            counts: dict[str, int],
            details: list[dict[str, str]],
            analyze_audio: bool,
            expected_bpm_range: tuple[float, float] | None,
    ) -> None:
        with self.database.transaction() as connection:
            track = self.tracks.get_by_id(track_id, connection)

            if track is None:
                # Genuinely possible (stale track_id, deleted row) —
                # not just a type-checker formality, so it gets its own
                # clear message rather than falling into the generic
                # "failed" handler in tag_tracks() with a raw
                # AttributeError.
                counts["failed"] += 1
                details.append(
                    {
                        "track_id": track_id,
                        "reason": "failed",
                        "message": f"track {track_id} not found",
                    }
                )
                return

            match = self.track_matches.get_by_track_id(track_id, connection)

            if match is None or match.local_file_id is None:
                counts["skipped_no_match"] += 1
                details.append(
                    {
                        "track_id": track_id,
                        "reason": "skipped_no_match",
                        "message": (
                            f"{track.artist} - {track.title}: no "
                            f"matched local file"
                        ),
                    }
                )
                return

            local_file = self.local_files.get_by_id(
                match.local_file_id, connection
            )

            if local_file is None:
                counts["failed"] += 1
                details.append(
                    {
                        "track_id": track_id,
                        "reason": "failed",
                        "message": (
                            f"{track.artist} - {track.title}: matched "
                            f"local_file_id {match.local_file_id} not "
                            f"found"
                        ),
                    }
                )
                return

            location = self.locations.get_by_id(
                local_file.location_id, connection
            )

            if location is None:
                counts["failed"] += 1
                details.append(
                    {
                        "track_id": track_id,
                        "reason": "failed",
                        "message": (
                            f"{track.artist} - {track.title}: library "
                            f"location {local_file.location_id} not "
                            f"found"
                        ),
                    }
                )
                return

        file_path = Path(location.path) / local_file.relative_path
        mutagen_file = MutagenFile(file_path)

        if mutagen_file is None:
            counts["skipped_format_unsupported"] += 1
            details.append(
                {
                    "track_id": track_id,
                    "reason": "skipped_format_unsupported",
                    "message": (
                        f"{track.artist} - {track.title}: mutagen could "
                        f"not open '{local_file.filename}'"
                    ),
                }
            )
            return

        try:
            write_text_tags(
                mutagen_file, track.artist, track.title, track.album
            )
        except ValueError as error:
            counts["skipped_format_unsupported"] += 1
            details.append(
                {
                    "track_id": track_id,
                    "reason": "skipped_format_unsupported",
                    "message": f"{track.artist} - {track.title}: {error}",
                }
            )
            return

        if track.album_art_url:
            try:
                image_bytes, mime_type = self._download_album_art(
                    track.album_art_url
                )
                embed_album_art(mutagen_file, image_bytes, mime_type)
            except Exception as error:
                # Art is best-effort — a download/embed failure shouldn't
                # sink an otherwise-successful text-tag write.
                print(
                    f"  Warning: could not embed album art for "
                    f"{track.artist} - {track.title}: {error}"
                )

        if analyze_audio:
            # Fully independent of the text/art tagging above — an
            # analysis failure (or an unsupported format for the
            # TBPM/TKEY write specifically) must not undo or block the
            # text-tag write that already happened; it only prints a
            # warning and skips the analysis fields, same best-effort
            # treatment as album art.
            try:
                analysis = run_audio_analysis(
                    file_path, expected_bpm_range=expected_bpm_range
                )

                write_analysis_tags(
                    mutagen_file, analysis.bpm, analysis.camelot_key
                )

                with self.database.transaction() as connection:
                    # Loaded from the DB via get_by_id above, so .id is
                    # set.
                    assert local_file.id is not None

                    self.local_files.update_analysis(
                        local_file.id,
                        analysis.bpm,
                        analysis.camelot_key,
                        analysis.key_confidence,
                        connection,
                    )
            except Exception as error:
                print(
                    f"  Warning: could not analyze audio for "
                    f"{track.artist} - {track.title}: {error}"
                )

        mutagen_file.save()

        counts["tagged"] += 1
        print(f"  Tagged: {track.artist} - {track.title}")

    def _download_album_art(self, url: str) -> tuple[bytes, str]:
        response = httpx.get(url, timeout=15.0)
        response.raise_for_status()

        mime_type = response.headers.get("content-type", "image/jpeg")

        return response.content, mime_type
