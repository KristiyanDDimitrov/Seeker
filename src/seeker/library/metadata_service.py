from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
from seeker.filename_format import build_track_filename
from seeker.metadata import (
    embed_album_art,
    read_embedded_art,
    save_tags,
    write_analysis_tags,
    write_text_tags,
)
from seeker.models.track import Track


class PlaylistNotFoundError(RuntimeError):
    pass


def _write_cover_jpg_sidecar(file_path: Path, image_bytes: bytes) -> bool:
    """Roadmap item R4.2 — the one thing Seeker can usefully do about
    embedded art not showing in every real DJ/media app for every
    format it writes to (see R4's own diagnosis: macOS Finder never
    reads embedded art from FLAC or WAV at all). Written next to the
    track's own file — this app has no notion of a dedicated per-album
    folder structure, so "one per album/track folder" means one per
    directory a track's file lives in; several tracks sharing a real
    album folder all resolve to the same path and only the first write
    creates it. Never overwrites an existing cover.jpg, even a
    stale/wrong one — the near-universal convention assumes exactly
    one cover per folder, and this app has no way to know whether a
    file already there was placed deliberately. Returns whether it
    actually wrote a new file, purely for the caller's own honest
    counts — never raises, since this is a bonus best-effort write on
    top of an already-successful art download, not something that
    should be able to fail a tagging run.
    """
    cover_path = file_path.parent / "cover.jpg"

    if cover_path.exists():
        return False

    try:
        cover_path.write_bytes(image_bytes)
    except OSError:
        return False

    return True


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


def _same_file(path_a: Path, path_b: Path) -> bool:
    # Roadmap item 67 (Phase 6.2/6.3) — the real, load-bearing check
    # behind both "is this already correct" and "is this a genuine
    # collision or just a case-only rename of itself." A plain string/
    # Path equality check would say two differently-cased paths are
    # different even when the filesystem (macOS's default APFS volume,
    # case-insensitive) considers them the identical file.
    if not path_b.exists():
        return False
    try:
        return path_a.samefile(path_b)
    except OSError:
        return False


def _resolve_collision(current_path: Path, proposed_path: Path) -> Path:
    # Real filesystem state at WRITE time, not the plan's own possibly-
    # stale snapshot. A case-only rename of the same file is never a
    # real collision (handled by the caller via _same_file); a
    # genuinely different file at the target gets " (2)", " (3)", ...
    if not proposed_path.exists() or _same_file(current_path, proposed_path):
        return proposed_path

    stem = proposed_path.stem
    suffix = proposed_path.suffix
    counter = 2

    while True:
        candidate = proposed_path.with_name(f"{stem} ({counter}){suffix}")

        if not candidate.exists() or _same_file(current_path, candidate):
            return candidate

        counter += 1


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
        print(f"  Warning: could not rename AppleDouble sidecar: {error}")


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
        self._get_config = get_config or (lambda: SeekerConfig())

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
            # Roadmap item 75 (P6, 6.4) — art WAS embedded, but the
            # format (WAV) means essentially no real DJ software will
            # ever show it — a distinct, honest bucket, not folded into
            # either "tagged" plain success or "tagged_without_art".
            "tagged_art_rarely_supported_format": 0,
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
                    if self._get_config().write_cover_jpg_sidecars:
                        _write_cover_jpg_sidecar(file_path, image_bytes)

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
                        elif local_file.format == "wav":
                            # Roadmap item 75 (P6, 6.4) — mutagen writes
                            # a real APIC into the RIFF container and
                            # reads it back byte-exact (embed_album_
                            # art's own docstring), but essentially
                            # nothing else in a DJ's real toolchain
                            # reads embedded art from WAV. A count of
                            # "written" the user can never actually see
                            # is exactly the dishonest reporting Phase
                            # 4.2 (item 56) was built to end — this
                            # gets its own outcome instead of silently
                            # joining the same bucket as a real,
                            # visible MP3/FLAC/M4A embed.
                            art_outcome = "written_wav_rarely_supported"

            if art_outcome not in ("written", "written_wav_rarely_supported"):
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

        save_tags(mutagen_file)

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

        if art_outcome == "written_wav_rarely_supported":
            # Roadmap item 75 (P6, 6.4) — art WAS written (not the same
            # thing as "no art" below), but honestly, not as "tagged"
            # plain success either — see the outcome's own comment
            # above for why.
            counts["tagged_art_rarely_supported_format"] += 1
            details.append(
                {
                    "track_id": track_id,
                    "reason": "tagged_art_rarely_supported_format",
                    "message": (
                        f"{track.artist} - {track.title}: cover art "
                        f"was embedded, but WAV art is rarely read by "
                        f"real DJ software — don't rely on it being "
                        f"visible"
                    ),
                }
            )
            print(
                f"  Tagged (art embedded, WAV rarely supported): "
                f"{track.artist} - {track.title}"
            )
        elif art_outcome != "written":
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
            # Roadmap item 75 (P6, 6.4) — same honest distinction as
            # tag_tracks' own "tagged_art_rarely_supported_format": art
            # WAS embedded, but essentially no real DJ software reads
            # embedded art from WAV.
            "fixed_wav_rarely_supported": 0,
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

        if self._get_config().write_cover_jpg_sidecars:
            _write_cover_jpg_sidecar(file_path, image_bytes)

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

        save_tags(mutagen_file)

        if local_file.format == "wav":
            counts["fixed_wav_rarely_supported"] += 1
            details.append(
                {
                    "track_id": track_id,
                    "reason": "fixed_wav_rarely_supported",
                    "message": (
                        f"{track.artist} - {track.title}: cover art "
                        f"was embedded, but WAV art is rarely read by "
                        f"real DJ software — don't rely on it being "
                        f"visible"
                    ),
                }
            )
            print(
                f"  Fixed art (WAV, rarely supported): "
                f"{track.artist} - {track.title}"
            )
        else:
            counts["fixed"] += 1
            print(f"  Fixed art: {track.artist} - {track.title}")

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

        plans = [self._plan_one_rename(track) for track in tracks]
        return _mark_within_batch_collisions(plans)

    def _plan_one_rename(self, track: Track) -> RenamePlan:
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
            )

        proposed_path = current_path.parent / proposed_filename

        if proposed_path == current_path:
            return RenamePlan(
                track.id, local_file.id, current_path, proposed_path,
                "already_correct",
            )

        if proposed_path.exists() and not _same_file(
                current_path, proposed_path,
        ):
            return RenamePlan(
                track.id, local_file.id, current_path, proposed_path,
                "collision",
                f"target '{proposed_path.name}' already exists as a "
                f"different file",
            )

        return RenamePlan(
            track.id, local_file.id, current_path, proposed_path, "rename",
        )

    def apply_renames(self, plans: list[RenamePlan]) -> RenameResult:
        """Roadmap item 67 (Phase 6.3) — 'rename' AND 'collision' plans
        both do real work; every other action is just counted (the plan
        already described it correctly, nothing to act on). 'collision'
        is informational at PLAN time (so a preview can show "this will
        need a suffix" before the user confirms) but is NOT refused at
        apply time — _apply_one_rename resolves it for real, via a
        fresh _resolve_collision() call against the real filesystem
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
                    print(
                        f"  Failed to rename track {plan.track_id}: {error}"
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
        final_path = _resolve_collision(current_path, plan.proposed_path)

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
        # _resolve_collision() call (real filesystem state at WRITE
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
                pass
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
        print(f"  Renamed: {current_path.name} -> {final_path.name}")

    def _download_album_art(self, url: str) -> tuple[bytes, str]:
        cached = self.album_art_cache.get(url)

        if cached is not None:
            return cached

        response = httpx.get(url, timeout=15.0)
        response.raise_for_status()

        mime_type = response.headers.get("content-type", "image/jpeg")

        self.album_art_cache.put(url, response.content, mime_type)

        return response.content, mime_type
