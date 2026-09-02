from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from mutagen import File as MutagenFile

from seeker.album_art_cache import AlbumArtCache
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
    read_embedded_art,
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
        album_art_cache: AlbumArtCache | None = None,
    ):
        self.database = database
        self.tracks = track_repository
        self.track_matches = track_match_repository
        self.local_files = local_file_repository
        self.locations = library_location_repository
        self.playlists = playlist_repository
        # Roadmap item 56 Phase 4.3 — MetadataService is a cached
        # singleton for the app's whole lifetime (Application.
        # metadata_service, same pattern as track_matcher/dashboard_
        # service — item 33), so the default instance here persists
        # across tagging runs too, not just within one.
        self.album_art_cache = album_art_cache or AlbumArtCache()

    def tag_playlist(
            self,
            playlist_name: str,
            analyze_audio: bool = False,
            expected_bpm_range: tuple[float, float] | None = None,
            force: bool = False,
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
            force=force,
        )

    def tag_tracks(
            self,
            track_ids: list[str],
            analyze_audio: bool = False,
            expected_bpm_range: tuple[float, float] | None = None,
            force: bool = False,
    ) -> dict[str, Any]:
        counts: dict[str, int] = {
            "tagged": 0,
            # Roadmap item 56 Phase 4.2 — a subset of "tagged" (text
            # tags DID get written), broken out because art is
            # currently a silent best-effort best-case: without this,
            # a CDN hiccup or a never-synced album_art_url makes the
            # UI report unqualified success with no way to tell.
            "tagged_without_art": 0,
            "skipped_no_match": 0,
            "skipped_format_unsupported": 0,
            "skipped_already_tagged": 0,
            "skipped_already_analyzed": 0,
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
                    force,
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
            force: bool = False,
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

        # Two independently-skippable operations, per the ask: a
        # deterministic tag write (text+art) has already happened once
        # tagged_at is set — re-running it is a pure waste (most
        # visibly, a redundant album art re-download every run); an
        # analysis has already happened once bpm is set. --force
        # bypasses both checks independently, e.g. for Spotify metadata
        # having changed or wanting to redo analysis.
        skip_tag_write = local_file.tagged_at is not None and not force
        skip_analysis = (
            analyze_audio
            and local_file.bpm is not None
            and not force
        )
        needs_analysis = analyze_audio and not skip_analysis

        if skip_tag_write:
            counts["skipped_already_tagged"] += 1
            details.append(
                {
                    "track_id": track_id,
                    "reason": "skipped_already_tagged",
                    "message": (
                        f"{track.artist} - {track.title}: already "
                        f"tagged at {local_file.tagged_at}, skipping "
                        f"text/art write"
                    ),
                }
            )

        if skip_analysis:
            counts["skipped_already_analyzed"] += 1
            details.append(
                {
                    "track_id": track_id,
                    "reason": "skipped_already_analyzed",
                    "message": (
                        f"{track.artist} - {track.title}: already "
                        f"analyzed (bpm={local_file.bpm}), skipping "
                        f"audio analysis"
                    ),
                }
            )

        if skip_tag_write and not needs_analysis:
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

        art_outcome = "written"
        art_message: str | None = None

        if not skip_tag_write:
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
                        "message": (
                            f"{track.artist} - {track.title}: {error}"
                        ),
                    }
                )
                return

            # Art is best-effort — a download/embed failure shouldn't
            # sink an otherwise-successful text-tag write — but a
            # silent one is exactly what made this whole thing
            # invisible to the UI before (roadmap item 56 Phase 0.4/
            # 4.2): the track still counted as plain "tagged" with no
            # record anywhere of what actually happened to the art.
            if not track.album_art_url:
                art_outcome = "no_url"
                art_message = (
                    "no album art URL stored for this track — re-run "
                    "'seeker sync-tracks' for this playlist to "
                    "populate it"
                )
            else:
                try:
                    image_bytes, mime_type = self._download_album_art(
                        track.album_art_url
                    )
                except Exception as error:
                    art_outcome = "download_failed"
                    art_message = str(error)
                else:
                    try:
                        embedded = embed_album_art(
                            mutagen_file, image_bytes, mime_type
                        )
                    except Exception as error:
                        art_outcome = "embed_failed"
                        art_message = str(error)
                    else:
                        if not embedded:
                            art_outcome = "format_unsupported"
                            art_message = (
                                "album art isn't supported for this "
                                "file format"
                            )

            if art_outcome != "written":
                print(
                    f"  Warning: could not embed album art for "
                    f"{track.artist} - {track.title}: {art_message}"
                )

        if needs_analysis:
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

        if skip_tag_write:
            print(
                f"  Re-analyzed (already tagged): "
                f"{track.artist} - {track.title}"
            )
            return

        with self.database.transaction() as connection:
            # Loaded from the DB via get_by_id above, so .id is set.
            assert local_file.id is not None

            self.local_files.mark_tagged(
                local_file.id,
                datetime.now(timezone.utc).isoformat(),
                connection,
            )

        counts["tagged"] += 1

        if art_outcome != "written":
            counts["tagged_without_art"] += 1
            details.append(
                {
                    "track_id": track_id,
                    "reason": f"tagged_without_art_{art_outcome}",
                    "message": (
                        f"{track.artist} - {track.title}: {art_message}"
                    ),
                }
            )
            print(
                f"  Tagged (no cover art): {track.artist} - {track.title}"
            )
        else:
            print(f"  Tagged: {track.artist} - {track.title}")

    def fix_missing_art_for_playlist(self, playlist_name: str) -> dict[str, Any]:
        """Roadmap item 66 (Phase 5.2) — a narrower, safer repair action
        than a forced full re-tag: re-embeds art ONLY, never touches
        text tags, for auto-matched tracks whose embedded art is
        missing or doesn't match the real current album_art_url. Built
        for exactly the scenario Phase 0.4's investigation found: a
        track already tagged (tagged_at set) before Phase 4's own art
        fixes landed, whose text tags are already correct and don't
        need rewriting, but whose art was never fixed retroactively.
        """
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

        counts: dict[str, int] = {
            "fixed": 0,
            "already_correct": 0,
            "no_url": 0,
            "download_failed": 0,
            "embed_failed": 0,
            "format_unsupported": 0,
            "skipped_no_match": 0,
            "failed": 0,
        }
        details: list[dict[str, str]] = []

        for track in tracks:
            try:
                self._fix_one_track_art(track.id, counts, details)
            except Exception as error:
                counts["failed"] += 1
                details.append(
                    {
                        "track_id": track.id,
                        "reason": "failed",
                        "message": str(error),
                    }
                )
                print(f"  Failed to fix art for track {track.id}: {error}")

        return {**counts, "details": details}

    def _fix_one_track_art(
            self,
            track_id: str,
            counts: dict[str, int],
            details: list[dict[str, str]],
    ) -> None:
        with self.database.transaction() as connection:
            track = self.tracks.get_by_id(track_id, connection)

            if track is None:
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

        if not track.album_art_url:
            counts["no_url"] += 1
            details.append(
                {
                    "track_id": track_id,
                    "reason": "no_url",
                    "message": (
                        f"{track.artist} - {track.title}: no album art "
                        f"URL stored — re-run 'seeker sync-tracks' for "
                        f"this playlist to populate it"
                    ),
                }
            )
            return

        file_path = Path(location.path) / local_file.relative_path
        mutagen_file = MutagenFile(file_path)

        if mutagen_file is None:
            counts["format_unsupported"] += 1
            details.append(
                {
                    "track_id": track_id,
                    "reason": "format_unsupported",
                    "message": (
                        f"{track.artist} - {track.title}: mutagen could "
                        f"not open '{local_file.filename}'"
                    ),
                }
            )
            return

        # Matches write_text_tags' own guard — a fresh WAV/etc. mutagen
        # object has tags=None until this is called once; without it,
        # the isinstance(mutagen_file.tags, ID3) checks inside
        # read_embedded_art/embed_album_art never match at all.
        if mutagen_file.tags is None:
            mutagen_file.add_tags()

        try:
            image_bytes, mime_type = self._download_album_art(
                track.album_art_url
            )
        except Exception as error:
            counts["download_failed"] += 1
            details.append(
                {
                    "track_id": track_id,
                    "reason": "download_failed",
                    "message": f"{track.artist} - {track.title}: {error}",
                }
            )
            return

        # The actual point of this action: skip the write entirely (no
        # file touched at all) if the currently-embedded art already
        # byte-matches the real current CDN bytes — the same
        # authoritative comparison Phase 0.4's own investigation used.
        existing_art = read_embedded_art(mutagen_file)

        if existing_art is not None and existing_art == image_bytes:
            counts["already_correct"] += 1
            return

        try:
            embedded = embed_album_art(mutagen_file, image_bytes, mime_type)
        except Exception as error:
            counts["embed_failed"] += 1
            details.append(
                {
                    "track_id": track_id,
                    "reason": "embed_failed",
                    "message": f"{track.artist} - {track.title}: {error}",
                }
            )
            return

        if not embedded:
            counts["format_unsupported"] += 1
            details.append(
                {
                    "track_id": track_id,
                    "reason": "format_unsupported",
                    "message": (
                        f"{track.artist} - {track.title}: album art "
                        f"isn't supported for this file format"
                    ),
                }
            )
            return

        mutagen_file.save()
        counts["fixed"] += 1
        print(f"  Fixed art: {track.artist} - {track.title}")

    def _download_album_art(self, url: str) -> tuple[bytes, str]:
        cached = self.album_art_cache.get(url)

        if cached is not None:
            return cached

        response = httpx.get(url, timeout=15.0)
        response.raise_for_status()

        mime_type = response.headers.get("content-type", "image/jpeg")

        self.album_art_cache.put(url, response.content, mime_type)

        return response.content, mime_type
