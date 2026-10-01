import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from mutagen import File as MutagenFile

from seeker.album_art_cache import AlbumArtCache
from seeker.audio_analysis import analyze_audio as run_audio_analysis
from seeker.config_store import SeekerConfig
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
from seeker.destination_resolution import resolve_playlist_destination
from seeker.errors import PlaylistNotFoundError
from seeker.files.deletion import same_file
from seeker.files.naming import build_track_filename
from seeker.files.placement import resolve_collision
from seeker.metadata import (
    embed_album_art,
    read_embedded_art,
    save_tags,
    write_analysis_tags,
    write_text_tags,
)
from seeker.models.library_location import LibraryLocation
from seeker.models.local_file import LocalFile
from seeker.models.playlist import Playlist
from seeker.models.tag_result import FixArtResult, TagOutcome, TagResult
from seeker.models.track import Track

logger = logging.getLogger(__name__)


# Roadmap item 116 (round 8, §6.4) — album_art_url comes from Spotify's
# own CDN at sync time, so it's trusted in practice, but it's read back
# out of a local SQLite file and _download_album_art streams rather
# than buffering an unbounded response body. A few MB is generous for
# real cover art; untuned, no real track's art has ever come close.
MAX_ALBUM_ART_BYTES = 10 * 1024 * 1024

# Where Spotify serves cover art (every stored URL is i.scdn.co today).
# The URL is read back from the database, so it is checked before it
# becomes an outbound request.
_SPOTIFY_IMAGE_HOST_SUFFIXES = (".scdn.co", ".spotifycdn.com")


def is_spotify_image_url(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()

    return (
        parts.scheme == "https"
        and not parts.username
        and host.endswith(_SPOTIFY_IMAGE_HOST_SUFFIXES)
    )


# Real magic-byte prefixes, checked instead of trusting the response's
# Content-Type header (§6.4.2).
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _sniff_image_mime_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if image_bytes.startswith(_PNG_MAGIC):
        return "image/png"
    raise ValueError(
        "album art response is not a recognized JPEG/PNG image"
    )


@dataclass
class RenamePlan:
    """Roadmap item 67 (Phase 6.3) — one track's rename decision, pure
    planning, zero writes. `current_path`/`proposed_path` are None only
    when `action` is 'not_auto_matched' (nothing to resolve a path for
    at all) or 'no_local_file'/'error' before a path could be computed.
    """
    track_id: str
    local_file_id: int | None
    current_path: Path | None
    proposed_path: Path | None
    # 'rename' / 'already_correct' / 'collision' / 'not_auto_matched' /
    # 'no_local_file' / 'error'
    action: str
    message: str | None = None
    # Roadmap item 93 (B3.2) — current_path/proposed_path are absolute;
    # a preview showing only the basename made an "Already correct" row
    # for a duplicate file elsewhere in the same library location
    # indistinguishable from the file the user was actually looking at
    # (the real bug behind B3's "nothing was renamed" report). None
    # exactly when the matching absolute path is also None.
    current_relative: Path | None = None
    proposed_relative: Path | None = None
    # Roadmap item 93 (B3.4) — set only when plan_renames() was called
    # with a playlist_name (so a real destination can be resolved) AND
    # the matched file's real location/folder disagrees with it. None
    # otherwise, including whenever there's nothing to compare against.
    destination_note: str | None = None


@dataclass
class RenameResult:
    renamed: int = 0
    already_correct: int = 0
    skipped_not_auto_matched: int = 0
    skipped_no_local_file: int = 0
    # A SUBSET of `renamed` (like tagged_without_art is a subset of
    # tagged, item 56 Phase 4.2) — how many of the real renames needed
    # a numbered " (2)" suffix because the target name was already
    # taken by a genuinely different file.
    collisions: int = 0
    failed: int = 0
    details: list[dict[str, str]] = field(default_factory=list)


# Roadmap item 67 (Phase 6.2/6.3) — the real, load-bearing check behind
# both "is this already correct" and "is this a genuine collision or
# just a case-only rename of itself." Shared with duplicate_service.py
# (roadmap item 93/R3.3) via files/deletion.py, not a second copy.
_same_file = same_file


def _describe_track_file(track: Track, local_file: LocalFile) -> str:
    """Roadmap item 93 (B3.3) — a per-track tagging/art-fix outcome
    named only by artist/title made a run against a duplicate file
    elsewhere in the library indistinguishable from the file the user
    actually cared about (the same real B3 story as B3.2's rename
    preview, applied here). `local_file.relative_path` is already
    location-relative — no location object needed to display it."""
    return f"{local_file.relative_path} ({track.artist} - {track.title})"


def _destination_note(
        location: LibraryLocation,
        local_file: LocalFile,
        destination: tuple[LibraryLocation, str | None] | None,
) -> str | None:
    """Roadmap item 93 (B3.4) — the actual B3 story: Seeker was
    renaming/tagging the right file, but a track whose matched file
    lives outside the playlist's own configured destination never said
    so anywhere. `destination` is None when the playlist has no
    resolvable destination at all — nothing to compare against, so no
    note (not an error; plenty of playlists have never had one set)."""
    if destination is None:
        return None

    destination_location, subfolder = destination
    expected_dir = subfolder or ""
    actual_dir = str(Path(local_file.relative_path).parent)

    if actual_dir == ".":
        actual_dir = ""

    if location.id == destination_location.id and actual_dir == expected_dir:
        return None

    actual_display = actual_dir or f"the root of '{location.name}'"
    expected_display = (
        expected_dir or f"the root of '{destination_location.name}'"
    )

    return (
        f"matched file is in {actual_display}, not this playlist's "
        f"configured destination ({expected_display})"
    )


def _rename_via_temp(source: Path, destination: Path) -> None:
    # Roadmap item 67 (Phase 6.2) — macOS's default APFS volume is
    # case-insensitive: a naive Path.rename() between two names
    # differing only by case either no-ops or raises depending on the
    # exact names, because the filesystem already treats them as the
    # same entry. A two-step rename through a unique temporary name in
    # the SAME directory (so it's still on the same filesystem/volume —
    # required for a plain rename rather than a real copy) sidesteps
    # this reliably.
    temp_path = source.with_name(f".{source.name}.seeker-rename-tmp")
    counter = 0

    while temp_path.exists():
        counter += 1
        temp_path = source.with_name(
            f".{source.name}.seeker-rename-tmp{counter}"
        )

    source.rename(temp_path)
    temp_path.rename(destination)


def _mark_within_batch_collisions(
        plans: list[RenamePlan],
) -> list[RenamePlan]:
    """Roadmap item 76 (P2, 2.2) — a real, CONFIRMED gap:
    _plan_one_rename plans every track independently against the
    filesystem as it is BEFORE any rename runs, so two plans can target
    the identical final name (a track duplicated in the playlist, two
    remixes normalizing to the same string, or an already-correct file
    whose name a later plan also targets) with neither individually
    reading as a collision at plan time — the preview showed both as
    clean renames. At apply time the first one wins the name and the
    second silently becomes a numbered suffix. Marking this at PLAN
    time makes the preview honest about it upfront.
    """
    target_counts: dict[Path, int] = {}

    for plan in plans:
        if plan.action == "rename":
            assert plan.proposed_path is not None
            target_counts[plan.proposed_path] = (
                target_counts.get(plan.proposed_path, 0) + 1
            )

    marked = []

    for plan in plans:
        if plan.action == "rename":
            assert plan.proposed_path is not None

            if target_counts[plan.proposed_path] > 1:
                marked.append(replace(
                    plan,
                    action="collision",
                    message=(
                        f"target '{plan.proposed_path.name}' is also "
                        f"the proposed target for another track in "
                        f"this same batch"
                    ),
                ))
                continue

        marked.append(plan)

    return marked


def _rename_sidecar_if_present(current_path: Path, final_path: Path) -> None:
    # Roadmap item 67 (Phase 6.3) — item 2's own AppleDouble filter
    # (`._<name>`, same directory) means the scanner never indexes
    # these, but a real one sitting next to a renamed file would
    # silently become orphaned (pointing nowhere useful) if left
    # behind. Best-effort: a failure here must never fail the real
    # rename it's riding along with. Deliberately NOT handled: .cue,
    # .lrc, or folder art — out of scope, noted rather than half-done.
    sidecar = current_path.parent / f"._{current_path.name}"

    if not sidecar.exists():
        return

    new_sidecar = final_path.parent / f"._{final_path.name}"

    try:
        if _same_file(sidecar, new_sidecar):
            _rename_via_temp(sidecar, new_sidecar)
        else:
            sidecar.rename(new_sidecar)
    except OSError as error:
        logger.warning("Could not rename AppleDouble sidecar: %s", error)


@dataclass(frozen=True)
class _TagNote:
    """One outcome a track adds to a `TagResult`. A `message` becomes a
    detail row, under `reason` when it is more specific than
    `outcome`."""
    outcome: TagOutcome
    message: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class _TagTarget:
    track: Track
    local_file: LocalFile
    file_path: Path

    @property
    def description(self) -> str:
        return _describe_track_file(self.track, self.local_file)


@dataclass(frozen=True)
class _ArtOutcome:
    # "written", "written_wav_rarely_supported", "no_url",
    # "download_failed", "embed_failed" or "format_unsupported".
    outcome: str
    message: str | None = None

    @property
    def written(self) -> bool:
        return self.outcome in ("written", "written_wav_rarely_supported")


def _decide_tag_skips(
        target: _TagTarget,
        analyze_audio: bool,
        force: bool,
) -> tuple[bool, bool, list[_TagNote]]:
    """Whether to skip the tag write, whether to analyse, and the notes
    for what was skipped.

    Tag writing and analysis are skipped independently: a file with
    `tagged_at` set already has its text and art (re-running it would
    re-download the art every time), and one with `bpm` set is already
    analysed. `force` bypasses both.
    """
    local_file = target.local_file
    skip_tag_write = local_file.tagged_at is not None and not force
    skip_analysis = analyze_audio and local_file.bpm is not None and not force
    notes = []

    if skip_tag_write:
        notes.append(_TagNote(
            "skipped_already_tagged",
            f"{target.description}: already tagged at "
            f"{local_file.tagged_at}, skipping text/art write",
        ))

    if skip_analysis:
        notes.append(_TagNote(
            "skipped_already_analyzed",
            f"{target.description}: already analyzed "
            f"(bpm={local_file.bpm}), skipping audio analysis",
        ))

    return skip_tag_write, analyze_audio and not skip_analysis, notes


def _tagged_notes(target: _TagTarget, art: _ArtOutcome) -> list[_TagNote]:
    tagged = _TagNote("tagged")

    if art.outcome == "written_wav_rarely_supported":
        logger.info(
            "Tagged (art embedded, WAV rarely supported): %s",
            target.description,
        )
        return [tagged, _TagNote(
            "tagged_art_rarely_supported_format",
            f"{target.description}: cover art was embedded, but WAV art "
            f"is rarely read by real DJ software — don't rely on it "
            f"being visible",
        )]

    if art.outcome != "written":
        logger.info("Tagged (no cover art): %s", target.description)
        return [tagged, _TagNote(
            "tagged_without_art",
            f"{target.description}: {art.message}",
            reason=f"tagged_without_art_{art.outcome}",
        )]

    logger.info("Tagged: %s", target.description)
    return [tagged]


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
        get_config: Callable[[], SeekerConfig] | None = None,
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
        # Roadmap item R4.2 — same callable-not-snapshot discipline as
        # DownloadService/TrackMatcher/SharingService (item 28) — a
        # Settings toggle change takes effect on the very next tagging
        # run, no restart or service-reconstruction needed.
        self._get_config = get_config or SeekerConfig

    def tag_playlist(
            self,
            playlist_name: str,
            analyze_audio: bool = False,
            expected_bpm_range: tuple[float, float] | None = None,
            force: bool = False,
    ) -> TagResult:
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
    ) -> TagResult:
        result = TagResult()

        for track_id in track_ids:
            # One bad file must not abort the batch. Notes are recorded
            # as they are produced, so a skip already decided still
            # counts when a later step fails.
            try:
                for note in self._tag_one_track(
                        track_id, analyze_audio, expected_bpm_range, force,
                ):
                    result.record(
                        track_id, note.outcome, note.message, note.reason,
                    )
            except Exception as error:
                result.record(track_id, "failed", str(error))
                logger.warning("Failed to tag track %s: %s", track_id, error)

        return result

    def _tag_one_track(
            self,
            track_id: str,
            analyze_audio: bool,
            expected_bpm_range: tuple[float, float] | None,
            force: bool = False,
    ) -> Iterator[_TagNote]:
        target = self._resolve_tag_target(track_id)

        if isinstance(target, _TagNote):
            yield target
            return

        skip_tag_write, needs_analysis, skip_notes = _decide_tag_skips(
            target, analyze_audio, force,
        )
        yield from skip_notes

        if skip_tag_write and not needs_analysis:
            return

        mutagen_file = MutagenFile(target.file_path)

        if mutagen_file is None:
            yield _TagNote(
                "skipped_format_unsupported",
                f"{target.description}: mutagen could not open "
                f"'{target.local_file.filename}'",
            )
            return

        art: _ArtOutcome | None = None

        if not skip_tag_write:
            try:
                write_text_tags(
                    mutagen_file,
                    target.track.artist,
                    target.track.title,
                    target.track.album,
                )
            except ValueError as error:
                yield _TagNote(
                    "skipped_format_unsupported",
                    f"{target.description}: {error}",
                )
                return

            art = self._embed_track_art(mutagen_file, target)

        if needs_analysis:
            self._analyse_track(mutagen_file, target, expected_bpm_range)

        save_tags(mutagen_file)

        if art is None:
            logger.info("Re-analyzed (already tagged): %s", target.description)
            return

        self._mark_tagged(target.local_file)
        yield from _tagged_notes(target, art)

    def _resolve_tag_target(self, track_id: str) -> _TagTarget | _TagNote:
        """The track and the file its match points at, or the note
        explaining why there is nothing to tag."""
        with self.database.transaction() as connection:
            track = self.tracks.get_by_id(track_id, connection)

            if track is None:
                # A stale id or a deleted row: its own message, rather
                # than an AttributeError reported by tag_tracks.
                return _TagNote("failed", f"track {track_id} not found")

            label = f"{track.artist} - {track.title}"
            match = self.track_matches.get_by_track_id(track_id, connection)

            if match is None or match.local_file_id is None:
                return _TagNote(
                    "skipped_no_match", f"{label}: no matched local file",
                )

            local_file = self.local_files.get_by_id(
                match.local_file_id, connection
            )

            if local_file is None:
                return _TagNote(
                    "failed",
                    f"{label}: matched local_file_id "
                    f"{match.local_file_id} not found",
                )

            location = self.locations.get_by_id(
                local_file.location_id, connection
            )

            if location is None:
                return _TagNote(
                    "failed",
                    f"{label}: library location "
                    f"{local_file.location_id} not found",
                )

        return _TagTarget(
            track=track,
            local_file=local_file,
            file_path=Path(location.path) / local_file.relative_path,
        )

    def _embed_track_art(
            self,
            mutagen_file: Any,
            target: _TagTarget,
    ) -> _ArtOutcome:
        """Best effort: a failed art step never sinks the text-tag
        write, but it is reported, never silent (HISTORY §56)."""
        art = self._try_embed_track_art(mutagen_file, target)

        if not art.written:
            logger.warning(
                "Could not embed album art for %s: %s",
                target.description, art.message,
            )

        return art

    def _try_embed_track_art(
            self,
            mutagen_file: Any,
            target: _TagTarget,
    ) -> _ArtOutcome:
        url = target.track.album_art_url

        if not url:
            return _ArtOutcome(
                "no_url",
                "no album art URL stored for this track — re-run "
                "'seeker sync-tracks' for this playlist to populate it",
            )

        try:
            image_bytes, mime_type = self._download_album_art(url)
        except Exception as error:
            return _ArtOutcome("download_failed", str(error))

        try:
            embedded = embed_album_art(mutagen_file, image_bytes, mime_type)
        except Exception as error:
            return _ArtOutcome("embed_failed", str(error))

        if not embedded:
            return _ArtOutcome(
                "format_unsupported",
                "album art isn't supported for this file format",
            )

        if target.local_file.format == "wav":
            # mutagen writes WAV art and reads it back byte-exact, but
            # almost no DJ software reads it: reported separately, so
            # an art the user can never see is not counted as plain
            # success (HISTORY §75).
            return _ArtOutcome("written_wav_rarely_supported")

        return _ArtOutcome("written")

    def _analyse_track(
            self,
            mutagen_file: Any,
            target: _TagTarget,
            expected_bpm_range: tuple[float, float] | None,
    ) -> None:
        """Best effort and independent of the text tags: a failure (or a
        format that cannot hold TBPM/TKEY) logs a warning and never
        undoes or blocks the text-tag write."""
        try:
            analysis = run_audio_analysis(
                target.file_path, expected_bpm_range=expected_bpm_range
            )

            write_analysis_tags(
                mutagen_file, analysis.bpm, analysis.camelot_key
            )

            with self.database.transaction() as connection:
                # Loaded from the DB by _resolve_tag_target, so .id is
                # set.
                assert target.local_file.id is not None

                self.local_files.update_analysis(
                    target.local_file.id,
                    analysis.bpm,
                    analysis.camelot_key,
                    analysis.key_confidence,
                    connection,
                )
        except Exception as error:
            logger.warning(
                "Could not analyze audio for %s: %s",
                target.description, error,
            )

    def _mark_tagged(self, local_file: LocalFile) -> None:
        with self.database.transaction() as connection:
            # Loaded from the DB by _resolve_tag_target, so .id is set.
            assert local_file.id is not None

            self.local_files.mark_tagged(
                local_file.id,
                datetime.now(UTC).isoformat(),
                connection,
            )

    def fix_missing_art_for_playlist(
            self,
            playlist_name: str,
    ) -> FixArtResult:
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

        result = FixArtResult()

        for track in tracks:
            try:
                self._fix_one_track_art(track.id, result)
            except Exception as error:
                result.failed += 1
                result.details.append(
                    {
                        "track_id": track.id,
                        "reason": "failed",
                        "message": str(error),
                    }
                )
                logger.warning(
                    "Failed to fix art for track %s: %s", track.id, error,
                )

        return result

    def _fix_one_track_art(
            self,
            track_id: str,
            result: FixArtResult,
    ) -> None:
        with self.database.transaction() as connection:
            track = self.tracks.get_by_id(track_id, connection)

            if track is None:
                result.failed += 1
                result.details.append(
                    {
                        "track_id": track_id,
                        "reason": "failed",
                        "message": f"track {track_id} not found",
                    }
                )
                return

            match = self.track_matches.get_by_track_id(track_id, connection)

            if match is None or match.local_file_id is None:
                result.skipped_no_match += 1
                result.details.append(
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
                result.failed += 1
                result.details.append(
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
                result.failed += 1
                result.details.append(
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
            result.no_url += 1
            result.details.append(
                {
                    "track_id": track_id,
                    "reason": "no_url",
                    "message": (
                        f"{_describe_track_file(track, local_file)}: no album art "
                        f"URL stored — re-run 'seeker sync-tracks' for "
                        f"this playlist to populate it"
                    ),
                }
            )
            return

        file_path = Path(location.path) / local_file.relative_path
        mutagen_file = MutagenFile(file_path)

        if mutagen_file is None:
            result.format_unsupported += 1
            result.details.append(
                {
                    "track_id": track_id,
                    "reason": "format_unsupported",
                    "message": (
                        f"{_describe_track_file(track, local_file)}: mutagen could "
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
            result.download_failed += 1
            result.details.append(
                {
                    "track_id": track_id,
                    "reason": "download_failed",
                    "message": f"{_describe_track_file(track, local_file)}: {error}",
                }
            )
            return

        # The actual point of this action: skip the write entirely (no
        # file touched at all) if the currently-embedded art already
        # byte-matches the real current CDN bytes — the same
        # authoritative comparison Phase 0.4's own investigation used.
        existing_art = read_embedded_art(mutagen_file)

        if existing_art is not None and existing_art == image_bytes:
            result.already_correct += 1
            return

        try:
            embedded = embed_album_art(mutagen_file, image_bytes, mime_type)
        except Exception as error:
            result.embed_failed += 1
            result.details.append(
                {
                    "track_id": track_id,
                    "reason": "embed_failed",
                    "message": f"{_describe_track_file(track, local_file)}: {error}",
                }
            )
            return

        if not embedded:
            result.format_unsupported += 1
            result.details.append(
                {
                    "track_id": track_id,
                    "reason": "format_unsupported",
                    "message": (
                        f"{_describe_track_file(track, local_file)}: album art "
                        f"isn't supported for this file format"
                    ),
                }
            )
            return

        save_tags(mutagen_file)

        if local_file.format == "wav":
            result.fixed_wav_rarely_supported += 1
            result.details.append(
                {
                    "track_id": track_id,
                    "reason": "fixed_wav_rarely_supported",
                    "message": (
                        f"{_describe_track_file(track, local_file)}: cover art "
                        f"was embedded, but WAV art is rarely read by "
                        f"real DJ software — don't rely on it being "
                        f"visible"
                    ),
                }
            )
            logger.info(
                "Fixed art (WAV, rarely supported): %s",
                _describe_track_file(track, local_file),
            )
        else:
            result.fixed += 1
            logger.info(
                "Fixed art: %s", _describe_track_file(track, local_file),
            )

    def plan_renames(
            self,
            playlist_name: str | None = None,
            track_ids: list[str] | None = None,
    ) -> list[RenamePlan]:
        """Roadmap item 67 (Phase 6.3) — pure planning, zero writes.
        Exactly one of playlist_name/track_ids must be given. Unlike
        tag_playlist/fix_missing_art_for_playlist, this deliberately
        does NOT pre-filter to auto-matched tracks — a needs_review or
        unmatched track still gets a real plan row (action=
        'not_auto_matched'), so the preview the UI/CLI shows accounts
        for every track it was asked about, not just the ones it will
        act on.
        """
        if (playlist_name is None) == (track_ids is None):
            raise ValueError(
                "plan_renames requires exactly one of playlist_name or "
                "track_ids"
            )

        playlist: Playlist | None = None

        with self.database.transaction() as connection:
            if playlist_name is not None:
                playlist = self.playlists.get_by_name(
                    playlist_name, connection
                )

                if playlist is None:
                    raise PlaylistNotFoundError(
                        f"No playlist named '{playlist_name}' has been "
                        f"synced."
                    )

                tracks = self.tracks.get_all_for_playlist(
                    playlist.id, connection
                )
            else:
                assert track_ids is not None
                tracks = [
                    track for track in (
                        self.tracks.get_by_id(track_id, connection)
                        for track_id in track_ids
                    )
                    if track is not None
                ]

        plans = [
            self._plan_one_rename(track, playlist) for track in tracks
        ]
        return _mark_within_batch_collisions(plans)

    def _plan_one_rename(
            self, track: Track, playlist: Playlist | None = None,
    ) -> RenamePlan:
        with self.database.transaction() as connection:
            match = self.track_matches.get_by_track_id(track.id, connection)

            if match is None or match.match_method != "auto":
                return RenamePlan(
                    track.id, None, None, None, "not_auto_matched",
                    f"{track.artist} - {track.title}: not an auto-matched "
                    f"track",
                )

            if match.local_file_id is None:
                return RenamePlan(
                    track.id, None, None, None, "no_local_file",
                    f"{track.artist} - {track.title}: no matched local "
                    f"file",
                )

            local_file = self.local_files.get_by_id(
                match.local_file_id, connection
            )

            if local_file is None:
                return RenamePlan(
                    track.id, match.local_file_id, None, None,
                    "no_local_file",
                    f"{track.artist} - {track.title}: matched "
                    f"local_file_id {match.local_file_id} not found",
                )

            location = self.locations.get_by_id(
                local_file.location_id, connection
            )

            if location is None:
                return RenamePlan(
                    track.id, local_file.id, None, None, "error",
                    f"{track.artist} - {track.title}: library location "
                    f"{local_file.location_id} not found",
                )

            destination = (
                resolve_playlist_destination(
                    playlist, self.locations, self._get_config, connection,
                )
                if playlist is not None else None
            )

        destination_note = _destination_note(location, local_file, destination)
        current_relative = Path(local_file.relative_path)
        current_path = Path(location.path) / local_file.relative_path
        extension = current_path.suffix.lstrip(".")

        proposed_filename = build_track_filename(
            track.artist, track.title, extension,
        )

        if proposed_filename is None:
            return RenamePlan(
                track.id, local_file.id, current_path, None, "error",
                f"{track.artist} - {track.title}: no usable artist/title "
                f"to build a filename from",
                current_relative=current_relative,
                destination_note=destination_note,
            )

        proposed_path = current_path.parent / proposed_filename
        proposed_relative = current_relative.parent / proposed_filename

        if proposed_path == current_path:
            return RenamePlan(
                track.id, local_file.id, current_path, proposed_path,
                "already_correct",
                current_relative=current_relative,
                proposed_relative=proposed_relative,
                destination_note=destination_note,
            )

        if proposed_path.exists() and not _same_file(
                current_path, proposed_path,
        ):
            return RenamePlan(
                track.id, local_file.id, current_path, proposed_path,
                "collision",
                f"target '{proposed_path.name}' already exists as a "
                f"different file",
                current_relative=current_relative,
                proposed_relative=proposed_relative,
                destination_note=destination_note,
            )

        return RenamePlan(
            track.id, local_file.id, current_path, proposed_path, "rename",
            current_relative=current_relative,
            proposed_relative=proposed_relative,
            destination_note=destination_note,
        )

    def apply_renames(self, plans: list[RenamePlan]) -> RenameResult:
        """Roadmap item 67 (Phase 6.3) — 'rename' AND 'collision' plans
        both do real work; every other action is just counted (the plan
        already described it correctly, nothing to act on). 'collision'
        is informational at PLAN time (so a preview can show "this will
        need a suffix" before the user confirms) but is NOT refused at
        apply time — _apply_one_rename resolves it for real, via a
        fresh resolve_collision() call against the real filesystem
        state (which may have changed since planning), appending
        " (2)", " (3)", ... Real user files — never called without the
        caller's own explicit confirmation gate (item 27's "no gate for
        tag-writing" precedent does NOT extend here: renaming moves/
        replaces a file, tag-writing never does).

        Roadmap item 76 (P2, 2.4) — a real, CONFIRMED gap: a modal
        preview dialog's exec() keeps processing timer events, so the
        2s poll timer and the 20s backend-poll timer both keep firing
        while the user is looking at the preview — including a real
        SoulSeek download landing and writing a NEW local_files row
        mid-preview. Re-plans FRESH from the exact same track ids right
        before doing any real work and refuses (as a real per-track
        'failed' outcome, not a silent skip) any track whose fresh plan
        disagrees with what the user actually confirmed — safer than
        merely blocking the timers, since it also closes the "left the
        dialog open for ten minutes" window the brief itself calls out.
        """
        result = RenameResult()

        track_ids = [plan.track_id for plan in plans]
        fresh_plans_by_track_id = {
            plan.track_id: plan
            for plan in self.plan_renames(track_ids=track_ids)
        }

        for plan in plans:
            fresh_plan = fresh_plans_by_track_id.get(plan.track_id)

            if (
                    fresh_plan is None
                    or fresh_plan.action != plan.action
                    or fresh_plan.proposed_path != plan.proposed_path
            ):
                result.failed += 1
                result.details.append(
                    {
                        "track_id": plan.track_id,
                        "reason": "plan_changed_since_confirmed",
                        "message": (
                            "real state changed since this rename was "
                            "confirmed — refused; re-open the preview "
                            "to see the current plan"
                        ),
                    }
                )
                continue

            if plan.action == "already_correct":
                result.already_correct += 1
            elif plan.action == "not_auto_matched":
                result.skipped_not_auto_matched += 1
            elif plan.action in ("no_local_file", "error"):
                result.skipped_no_local_file += 1
            elif plan.action in ("rename", "collision"):
                try:
                    self._apply_one_rename(plan, result)
                except Exception as error:
                    result.failed += 1
                    result.details.append(
                        {
                            "track_id": plan.track_id,
                            "reason": "failed",
                            "message": str(error),
                        }
                    )
                    logger.warning(
                        "Failed to rename track %s: %s",
                        plan.track_id, error,
                    )

        return result

    def _apply_one_rename(
            self, plan: RenamePlan, result: RenameResult,
    ) -> None:
        assert plan.local_file_id is not None
        assert plan.current_path is not None
        assert plan.proposed_path is not None

        # Re-verified at apply time, not trusted from the (possibly
        # stale — plan and apply can be separated by a real user
        # decision pause) plan alone: only ever touches a track that's
        # STILL an auto-matched local file living inside a registered
        # library location. Anything else is refused, counted as a
        # real failure, not silently skipped.
        with self.database.transaction() as connection:
            match = self.track_matches.get_by_track_id(
                plan.track_id, connection,
            )
            local_file = self.local_files.get_by_id(
                plan.local_file_id, connection,
            )
            location = (
                self.locations.get_by_id(local_file.location_id, connection)
                if local_file is not None else None
            )

        if (
                match is None
                or match.match_method != "auto"
                or local_file is None
                or location is None
        ):
            result.failed += 1
            result.details.append(
                {
                    "track_id": plan.track_id,
                    "reason": "failed",
                    "message": (
                        "no longer an auto-matched local file in a "
                        "registered location as of apply time — refused"
                    ),
                }
            )
            return

        current_path = plan.current_path
        if not current_path.exists():
            result.failed += 1
            result.details.append(
                {
                    "track_id": plan.track_id,
                    "reason": "failed",
                    "message": f"'{current_path}' no longer exists",
                }
            )
            return

        # Collision resolved fresh at write time — real filesystem state
        # may have changed since planning.
        final_path = resolve_collision(current_path, plan.proposed_path)

        if _same_file(current_path, final_path):
            # Roadmap item 67 (Phase 6.2) — a case-only rename of the
            # SAME real file (macOS's default APFS volume is case-
            # insensitive) needs the two-step temp-name path; a plain
            # Path.rename() either no-ops or raises depending on the
            # exact names involved.
            _rename_via_temp(current_path, final_path)
        else:
            current_path.rename(final_path)

        _rename_sidecar_if_present(current_path, final_path)

        # Roadmap item 76 (P2, 2.3) — the honest-preview fix: the
        # preview shows plan.proposed_path.name, but this real, fresh
        # resolve_collision() call (real filesystem state at WRITE
        # time, which can differ from the plan's own snapshot) can
        # legitimately return a different name. Silence here is
        # EXACTLY what made "preview said X, disk got Y" invisible —
        # covers both a plan already flagged 'collision' at plan time
        # (almost always resolves to a different, suffixed name) and
        # the more alarming case: a plan previewed as a clean 'rename'
        # that hits a genuinely NEW collision only discovered now.
        if final_path.name != plan.proposed_path.name:
            result.collisions += 1
            result.details.append(
                {
                    "track_id": plan.track_id,
                    "reason": "renamed_with_different_name_than_previewed",
                    "message": (
                        f"renamed to '{final_path.name}', not the "
                        f"previewed '{plan.proposed_path.name}'"
                    ),
                }
            )

        # Loaded from the DB via get_by_id above, so .id is set.
        assert local_file.id is not None

        new_relative_path = str(
            final_path.relative_to(Path(location.path))
        )

        # Roadmap item 67 (Phase 6.3) — deliberately the OPPOSITE
        # ordering from item 40's delete rule (file first there, DB
        # first here would be wrong for the identical reason item 40's
        # own comment already gives, just inverted): a failed rename
        # (caught above, before this point) leaves the DB untouched and
        # consistent; renaming the file FIRST and updating the DB
        # SECOND means the only failure window left is a DB-write
        # failure after a successful rename — handled by renaming back
        # and reporting an error, rather than leaving a local_files row
        # pointing at a path that never existed (which item 40's own
        # ordering exists to avoid on the delete side).
        try:
            with self.database.transaction() as connection:
                self.local_files.update_relative_path(
                    local_file.id, new_relative_path, final_path.name,
                    connection,
                )
        except Exception as db_error:
            try:
                final_path.rename(current_path)
            except OSError:
                logger.exception(
                    "Renamed %s -> %s on disk, the database update then "
                    "failed (%s), and renaming back also failed — the "
                    "file and the database now disagree on its path.",
                    current_path, final_path, db_error,
                )
            result.failed += 1
            result.details.append(
                {
                    "track_id": plan.track_id,
                    "reason": "failed",
                    "message": (
                        f"renamed on disk but the database update "
                        f"failed ({db_error}) — renamed back"
                    ),
                }
            )
            return

        result.renamed += 1
        logger.info(
            "Renamed: %s -> %s", current_path.name, final_path.name,
        )

    def _download_album_art(self, url: str) -> tuple[bytes, str]:
        if not is_spotify_image_url(url):
            logger.warning("Skipped album art at an unexpected URL: %r", url)
            raise ValueError(f"not a Spotify image URL: {url!r}")

        cached = self.album_art_cache.get(url)

        if cached is not None:
            return cached

        # Roadmap item 116 (round 8, §6.4.1) — streamed rather than
        # httpx.get()'s implicit full-body buffering, so a response
        # larger than MAX_ALBUM_ART_BYTES is caught without ever
        # holding the whole thing in memory. httpx doesn't follow
        # redirects by default — deliberately left that way, do not
        # add follow_redirects=True here.
        with httpx.stream("GET", url, timeout=15.0) as response:
            response.raise_for_status()

            chunks = []
            total_bytes = 0

            for chunk in response.iter_bytes():
                total_bytes += len(chunk)
                if total_bytes > MAX_ALBUM_ART_BYTES:
                    raise ValueError(
                        "album art response exceeded "
                        f"{MAX_ALBUM_ART_BYTES} bytes"
                    )
                chunks.append(chunk)

        image_bytes = b"".join(chunks)
        # §6.4.2 — the real image bytes decide the MIME type, not the
        # Content-Type header a response could set to anything.
        mime_type = _sniff_image_mime_type(image_bytes)

        self.album_art_cache.put(url, image_bytes, mime_type)

        return image_bytes, mime_type
