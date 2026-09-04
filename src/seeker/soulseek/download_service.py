import glob
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from seeker.audio_formats import is_downloadable_extension
from seeker.config_store import SeekerConfig
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
from seeker.database.repositories.soulseek_review_candidate_repository import (
    SoulseekReviewCandidateRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.destination_resolution import resolve_playlist_destination
from seeker.download_dedup import candidate_key, most_recent_per_candidate
from seeker.file_deletion import delete_file
from seeker.library.matcher import find_best_match
from seeker.library.scanner import index_single_file
from seeker.matching import AUTO_MATCH_THRESHOLD, NEEDS_REVIEW_THRESHOLD
from seeker.models.download_request import DownloadRequest
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.models.soulseek_file import SoulseekFile
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import MANUAL_TRACK_ID_PREFIX, Track, is_manual_track_id
from seeker.models.track_match import TrackMatch
from seeker.models.upgrade_review import UpgradeReviewDetails
from seeker.soulseek.client import (
    SoulseekClient,
    SoulseekDownloadError,
    derive_extension,
    is_recognized_rejection,
)
from seeker.soulseek.quality import select_downloads


def _debug_poll(message: str) -> None:
    # Roadmap item 66 (Phase 4.3) — item 63's temporary, unconditional
    # print() converted to a gated log, per that item's own explicit
    # instruction to keep the diagnostic capability without the console
    # noise: the root cause of the real production retry-frequency storm
    # is still unknown, and with Phase 4.3's backoff now in place, a
    # recurrence would show up as a violated next_retry_at — a much
    # sharper signal than raw call timing — so this stays available for
    # that, opt-in via SEEKER_DEBUG_POLL=1, rather than deleted outright.
    if os.environ.get("SEEKER_DEBUG_POLL") == "1":
        print(message)


# Roadmap item 66 (Phase 4.3) — bounds the previously-unbounded locked
# retry loop (items 13/14/25/63; item 63's own real production storm:
# 300+ retries of one row in ~18 minutes, root cause still unknown but
# now structurally capped regardless). All three untuned — real numbers
# to revisit once real usage data exists, same convention as every other
# threshold in this codebase.
LOCKED_RETRY_BASE_SECONDS = 60
LOCKED_RETRY_MAX_SECONDS = 3600
LOCKED_RETRY_MAX_ATTEMPTS = 8

# Soulseek.TransferStates is a [Flags] enum — slskd reports it as a
# comma-joined string (e.g. "Completed, Succeeded"). Check failure markers
# first since a transfer can be "Completed" without having succeeded.
FAILED_STATE_MARKERS = (
    "Cancelled",
    "TimedOut",
    "Errored",
    "Rejected",
    "Aborted",
)



class PlaylistNotFoundError(RuntimeError):
    pass


class NoDestinationConfiguredError(RuntimeError):
    pass


class UnsupportedDownloadFormatError(RuntimeError):
    """Roadmap item 94 (B5.4) — an explicit per-row 'Download this one'
    pick (download_manual's chosen=) bypasses select_downloads'
    ranking/threshold entirely (item 82), which is also where the
    DOWNLOADABLE_EXTENSIONS gate normally lives — so this is the final
    guard at request time. A refused click must say so loudly, not do
    nothing: same "explicit action, honest outcome" standard as item 56
    Phase 4.2."""

    def __init__(self, extension: str):
        # Fixed, readable order (mp3/flac/wav/aiff/aif/m4a) rather than
        # DOWNLOADABLE_EXTENSIONS' own set-iteration order.
        downloadable = "mp3, flac, wav, aiff and m4a"
        super().__init__(
            f"Seeker only downloads {downloadable} — this one is "
            f".{extension.lower().lstrip('.')}."
        )


class LibraryLocationNotFoundError(RuntimeError):
    pass


class ReviewCandidateNotFoundError(RuntimeError):
    pass


class ReviewCandidateMissingSizeError(RuntimeError):
    pass


@dataclass
class BulkUpgradeReplaceResult:
    """Roadmap item R3.1 — the real per-row outcome of a "Replace all"
    batch, same honest-reporting shape as `format_rename_result_message`
    (item 67/76): a count for the UI's headline, plus one detail line
    per row so a partial failure is never just a bare number."""
    replaced: int
    failed: int
    details: list[str]


def _build_search_query(artist: str, title: str) -> str:
    # artist may credit multiple artists joined with ", " (e.g.
    # "MK, Dom Dolla") — strip the comma for the actual search string
    # rather than sending it literally. Soulseek search matching isn't
    # guaranteed to ignore stray punctuation, so a literal "MK," glued to
    # the first name risks not matching filenames that don't happen to
    # have that exact comma placement.
    #
    # Roadmap item 82 (P13.3) — takes plain artist/title strings now,
    # not a Track, so a manual (not-from-Spotify) search shares this
    # EXACT construction with download_playlist rather than a second,
    # drifting copy.
    artist_query = artist.replace(",", " ")

    return " ".join(f"{artist_query} {title}".split())


def _quality_descriptor(file: SoulseekFile) -> str:
    descriptor = file.extension

    if file.bit_rate:
        descriptor += f" {file.bit_rate}kbps"

    return descriptor


class DownloadService:
    def __init__(
        self,
        database: Database,
        soulseek_client: SoulseekClient | None,
        playlist_repository: PlaylistRepository,
        track_repository: TrackRepository,
        library_location_repository: LibraryLocationRepository,
        download_request_repository: DownloadRequestRepository,
        track_match_repository: TrackMatchRepository,
        local_file_repository: LocalFileRepository,
        soulseek_review_candidate_repository: SoulseekReviewCandidateRepository,
        slskd_download_dir: str | None,
        get_config: Callable[[], SeekerConfig] | None = None,
    ):
        self.database = database
        # None only when SoulSeek genuinely isn't configured — Step 8's
        # Settings screen needs to construct a real, usable
        # DownloadService for set_destination()/get_review_candidates()/
        # get_pending_upgrade_reviews() (none of which ever touch
        # SoulSeek at all) without a working slskd connection. A method
        # that DOES need it (download_playlist, poll_downloads, ...)
        # raises a clear error via the `soulseek` property below,
        # rather than making construction itself impossible the way
        # Application.soulseek_client's own eager raise already does
        # for anything that goes through it directly.
        self._soulseek_client = soulseek_client
        self.playlists = playlist_repository
        self.tracks = track_repository
        self.locations = library_location_repository
        self.download_requests = download_request_repository
        self.track_matches = track_match_repository
        self.local_files = local_file_repository
        self.soulseek_review_candidates = soulseek_review_candidate_repository
        # See matcher.py's identical get_config comment — a callable,
        # not a snapshot, so a Settings-driven threshold change is
        # visible on the very next download_playlist() call without
        # needing DownloadService itself reconstructed.
        self._get_config = get_config or (lambda: SeekerConfig())
        self.slskd_download_dir = slskd_download_dir

    @property
    def soulseek(self) -> SoulseekClient:
        if self._soulseek_client is None:
            raise RuntimeError(
                "SoulSeek is not configured (SLSKD_BASE_URL/SLSKD_API_KEY)."
            )

        return self._soulseek_client

    def set_destination(
        self,
        playlist_name: str,
        location_name: str,
        subfolder: str | None = None,
    ) -> None:
        with self.database.transaction() as connection:
            playlist = self.playlists.get_by_name(playlist_name, connection)

            if playlist is None:
                raise PlaylistNotFoundError(
                    f"No playlist named '{playlist_name}' has been "
                    f"synced."
                )

            location = self.locations.get_by_name(location_name, connection)

            if location is None:
                raise LibraryLocationNotFoundError(
                    f"No library location named '{location_name}' is "
                    f"registered."
                )

            # Loaded from the DB via get_by_name above, so .id is set.
            assert location.id is not None

            self.playlists.set_destination(
                playlist.id,
                location.id,
                subfolder,
                connection,
            )

        suffix = f"/{subfolder}" if subfolder else ""
        print(
            f"'{playlist_name}' will download to "
            f"'{location_name}'{suffix}"
        )

    def get_resolved_destination(
            self,
            playlist_name: str,
    ) -> tuple[LibraryLocation, str | None] | None:
        """Read-only — the UI's own check before ever calling
        download_playlist() (roadmap item 6 §3): resolvable now (a
        playlist-specific destination, or the configured default) means
        proceed straight to the real download; None means show the
        "set a destination" dialog first rather than letting
        download_playlist() raise NoDestinationConfiguredError and dead-
        end the user. Shares _resolve_destination with the real move
        step, so this is never a second, drifting notion of
        "resolvable."
        """
        with self.database.transaction() as connection:
            playlist = self.playlists.get_by_name(playlist_name, connection)

            if playlist is None:
                raise PlaylistNotFoundError(
                    f"No playlist named '{playlist_name}' has been "
                    f"synced."
                )

        return self._resolve_destination(playlist)

    def download_playlist(self, playlist_name: str) -> dict[str, Any]:
        with self.database.transaction() as connection:
            playlist = self.playlists.get_by_name(playlist_name, connection)

            if playlist is None:
                raise PlaylistNotFoundError(
                    f"No playlist named '{playlist_name}' has been "
                    f"synced."
                )

            if self._resolve_destination(playlist) is None:
                # Interface-neutral wording, deliberately — this
                # exception is shared by both the CLI and the UI
                # (roadmap item 6 §2: a GUI-facing message must never
                # tell someone to run a shell command). The CLI's own
                # handler appends its own command-line guidance when it
                # catches this; the UI instead proactively resolves the
                # destination via a real dialog before ever calling
                # download_playlist() with none configured (§3), so it
                # should only ever see this in a genuine race.
                raise NoDestinationConfiguredError(
                    f"'{playlist_name}' has no download destination "
                    f"configured yet."
                )

            unmatched_tracks = self.tracks.get_unmatched_for_playlist(
                playlist.id,
                connection,
            )

        # Resolved once for the whole run, not per track — thresholds
        # don't change mid-run, and re-reading config per track would
        # just be wasted work. Still re-resolved on every
        # download_playlist() call, so a Settings-driven change takes
        # effect on the next run with no restart needed.
        config = self._get_config()
        auto_match_threshold = (
            config.auto_match_threshold or AUTO_MATCH_THRESHOLD
        )
        needs_review_threshold = (
            config.needs_review_threshold or NEEDS_REVIEW_THRESHOLD
        )

        requested = 0
        skipped = 0
        failed = 0
        # Roadmap item 56 Phase 5.1 — distinct from the generic
        # `skipped` count so the UI can tell "already downloading/
        # downloaded" apart from "no real candidate found" (the two
        # skip reasons below are otherwise indistinguishable from the
        # return value alone).
        already_in_progress: list[str] = []
        # Roadmap item 66 (Phase 4.2) — same reasoning, for a THIRD
        # skip reason folded into the same generic `skipped` counter:
        # "sent to Review" (a real needs-review candidate was found and
        # recorded) reads identically to "no candidate found at all"
        # without this. `skipped` itself is left as their combined total
        # (backward-compatible with any existing consumer summing it),
        # this list is what lets a caller subtract the two apart honestly.
        needs_review_tracks: list[str] = []

        for track in unmatched_tracks:
            # One bad track (search timeout, malformed response, a
            # transient network error — anything) must not silently
            # abort every track after it in the batch. Every track ends
            # up in exactly one bucket: requested, skipped (no real
            # candidates), or failed (with a printed reason) — never
            # dropped without being counted anywhere.
            try:
                with self.database.transaction() as connection:
                    blocking = (
                        self.download_requests
                        .get_requests_blocking_redownload(
                            track.id, connection,
                        )
                    )

                if blocking:
                    # A request for this exact track is already in
                    # flight (queued/downloading/locked/shortlisted/
                    # ready_for_review) OR already completed —
                    # re-running download_playlist must not pile on a
                    # duplicate, otherwise-identical row for the same
                    # candidate, and must not re-download a track
                    # that's already sitting in the library. Confirmed
                    # live, both cases: two runs against a still-
                    # 'locked' upgrade created two rows before the
                    # original (narrower) guard existed (item 16); two
                    # differently-named files landed for the same real
                    # track (Kamäleon - Quadrat) because a completed
                    # row wasn't "active" under that narrower guard.
                    statuses = ", ".join(
                        sorted({request.status for request in blocking})
                    )
                    print(
                        f"  Already in progress for {track.artist} - "
                        f"{track.title} ({statuses}) — skipping."
                    )
                    skipped += 1
                    already_in_progress.append(
                        f"{track.artist} - {track.title}"
                    )
                    continue

                print(f"Searching: {track.artist} - {track.title}")

                files = self.soulseek.search(
                    _build_search_query(track.artist, track.title)
                )
                settled, upgrade_shortlist, needs_review = select_downloads(
                    track, files, auto_match_threshold, needs_review_threshold,
                )

                if settled is not None or upgrade_shortlist:
                    # Something real and auto-tier exists for this track
                    # now (downloaded, or locked but chased via the
                    # upgrade cascade) — any needs_review row from an
                    # earlier, worse run is stale information and must
                    # not keep being surfaced by `seeker check`.
                    self._clear_review_candidate(track.id)

                if settled is None:
                    if upgrade_shortlist:
                        # Nothing practical/unlocked, but select_downloads
                        # still found a real, above-threshold candidate —
                        # e.g. every filtered match is locked. Request it
                        # the same way an upgrade is normally requested
                        # (role='upgrade') so it lands in poll_downloads'
                        # existing locked-retry cascade instead of being
                        # silently discarded. Counted as requested, not
                        # skipped — a real download WAS requested, just
                        # not a settled one.
                        print(
                            "  No practical candidate — requesting "
                            "locked/upgrade-only candidate(s)."
                        )
                        self._request_upgrade_shortlist(
                            track, upgrade_shortlist
                        )
                        requested += 1
                    elif needs_review is not None:
                        # No auto-tier candidate at all, but a real,
                        # plausible one exists (70-89) — record it for
                        # `seeker check` to surface, rather than letting
                        # it silently vanish. Never requested from slskd
                        # on its own; a human confirms manually.
                        review_file, review_score = needs_review
                        self._record_review_candidate(
                            track, review_file, review_score
                        )
                        print(
                            f"  No auto-match candidate — needs-review "
                            f"candidate found (score {review_score:.1f}): "
                            f"{review_file.username}: "
                            f"{review_file.filename}"
                        )
                        skipped += 1
                        needs_review_tracks.append(
                            f"{track.artist} - {track.title}"
                        )
                    else:
                        print("  No candidates found.")
                        skipped += 1
                    continue

                self._request_and_record(track, settled, role="settled")
                print(
                    f"  Requested from {settled.username}: "
                    f"{settled.filename}"
                )
                requested += 1

                if upgrade_shortlist:
                    self._request_upgrade_shortlist(track, upgrade_shortlist)
            except Exception as error:
                failed += 1
                print(
                    f"  Failed: {track.artist} - {track.title}: {error}"
                )

        return {
            "requested": requested,
            "skipped": skipped,
            "failed": failed,
            "total": len(unmatched_tracks),
            "already_in_progress": already_in_progress,
            "needs_review": needs_review_tracks,
        }

    def search_manual(self, artist: str, title: str) -> list[SoulseekFile]:
        """Roadmap item 82 (P13.3) — a real SoulSeek search for a track
        that isn't in any Spotify playlist, using the EXACT SAME query
        construction download_playlist uses (_build_search_query) —
        never a second, drifting copy. Read-only: no track row, no
        download_requests row, nothing persisted. A real search takes
        20-45s (client.py's own documented real-world timing) — the
        caller (UI/CLI) is responsible for showing that it's busy.
        """
        return self.soulseek.search(_build_search_query(artist, title))

    def download_manual(
            self,
            artist: str,
            title: str,
            chosen: SoulseekFile | None = None,
            files: list[SoulseekFile] | None = None,
    ) -> dict[str, Any]:
        """Roadmap item 82 (P13.1/13.3) — search for and download a
        track that isn't in any Spotify playlist, reusing the same
        "best quality available, fall back until something actually
        downloads" behavior as a playlist download (select_downloads),
        no new ranking logic. Creates a real `tracks` row (id
        `manual:<uuid4>`, album="", duration_ms=0 — see
        _index_and_match_settled_download's own comment on why a
        placeholder duration doesn't affect the immediate post-download
        match) belonging to no playlist.

        `chosen`, when given (an explicit per-row "Download this one"
        pick — P13.5), bypasses select_downloads' ranking/threshold
        entirely and requests exactly that file as role='settled': the
        user's own explicit choice is a stronger signal than any
        threshold, the same reasoning item 26 already applies to a
        human-confirmed needs-review candidate.

        `files`, when given, skips a second real 20-45s network search
        — the UI's own results table (already populated via
        search_manual()) is reused rather than searched again for the
        headline "Download best" action. Omit it (e.g. the CLI's
        `--download`, which never has a prior search in hand) to search
        fresh.
        """
        if self._resolve_destination(None) is None:
            # Checked BEFORE creating a track row or running a real
            # 20-45s search — same "no destination configured" contract
            # as download_playlist (the CLI appends its own guidance;
            # the UI reuses this exact exception to route to Settings).
            raise NoDestinationConfiguredError(
                "No download destination is configured yet."
            )

        if chosen is not None and not is_downloadable_extension(
                chosen.extension,
        ):
            # Roadmap item 94 (B5.3/B5.4) — chosen bypasses
            # select_downloads (and its own DOWNLOADABLE_EXTENSIONS
            # gate) entirely, so this is the final check at request
            # time — checked here, before a track row is even created,
            # matching the destination check just above. A refused
            # explicit click gets a real, readable error, not a silent
            # no-op — same standard as item 56 Phase 4.2.
            raise UnsupportedDownloadFormatError(chosen.extension)

        track = Track(
            id=f"{MANUAL_TRACK_ID_PREFIX}{uuid4()}",
            title=title,
            artist=artist,
            album="",
            duration_ms=0,
        )
        with self.database.transaction() as connection:
            self.tracks.save(track, connection)

        if chosen is not None:
            self._request_and_record(track, chosen, role="settled")
            print(f"  Requested from {chosen.username}: {chosen.filename}")
            return {
                "track_id": track.id,
                "requested": True,
                "settled": True,
                "username": chosen.username,
                "filename": chosen.filename,
            }

        config = self._get_config()
        auto_match_threshold = (
            config.auto_match_threshold or AUTO_MATCH_THRESHOLD
        )
        needs_review_threshold = (
            config.needs_review_threshold or NEEDS_REVIEW_THRESHOLD
        )

        search_results = (
            files if files is not None
            else self.soulseek.search(_build_search_query(artist, title))
        )

        settled, upgrade_shortlist, _needs_review = select_downloads(
            track, search_results, auto_match_threshold, needs_review_threshold,
        )

        if settled is None and not upgrade_shortlist:
            return {
                "track_id": track.id,
                "requested": False,
                "settled": False,
                "reason": "no_candidate_found",
            }

        if settled is not None:
            self._request_and_record(track, settled, role="settled")
            print(f"  Requested from {settled.username}: {settled.filename}")

            if upgrade_shortlist:
                self._request_upgrade_shortlist(track, upgrade_shortlist)

            return {
                "track_id": track.id,
                "requested": True,
                "settled": True,
                "username": settled.username,
                "filename": settled.filename,
            }

        # Nothing practical/unlocked, but select_downloads still found
        # real above-threshold candidate(s) — every one of them locked.
        # Requested the same way a locked-only playlist track is (see
        # download_playlist above): lands in poll_downloads' existing
        # locked-retry cascade instead of being silently discarded.
        print("  No practical candidate — requesting locked/upgrade-only candidate(s).")
        self._request_upgrade_shortlist(track, upgrade_shortlist)
        return {
            "track_id": track.id,
            "requested": True,
            "settled": False,
            "reason": "locked_only",
        }

    def _request_upgrade_shortlist(
            self,
            track: Track,
            upgrade_shortlist: list[SoulseekFile],
    ) -> None:
        # Shared by both call sites: the normal "settled found, plus a
        # better upgrade exists" path, and the "nothing settled, but a
        # real (possibly locked-only) candidate exists" path. Rank 1 is
        # requested immediately; the rest are persisted but not sent to
        # slskd until poll_downloads' cascade needs them.
        top = upgrade_shortlist[0]
        self._request_and_record(track, top, role="upgrade", rank=1)
        print(
            f"  Requested upgrade from {top.username}: "
            f"{top.filename} (rank 1)"
        )

        for rank, candidate in enumerate(upgrade_shortlist[1:], start=2):
            self._record_shortlisted(track, candidate, rank=rank)
            print(
                f"  Shortlisted upgrade candidate from "
                f"{candidate.username}: {candidate.filename} "
                f"(rank {rank})"
            )

    def _request_and_record(
            self,
            track: Track,
            file: SoulseekFile,
            role: str,
            rank: int | None = None,
    ) -> None:
        # No destination is passed here for either role — the file lands
        # in slskd's own download dir and is moved out by seeker, whether
        # immediately (settled) or on user confirmation (upgrade).
        transfer_id = self.soulseek.request_download(
            file.username,
            file.filename,
            file.size,
        )

        with self.database.transaction() as connection:
            self.download_requests.add(
                DownloadRequest(
                    track_id=track.id,
                    username=file.username,
                    filename=file.filename,
                    format=file.extension,
                    quality_descriptor=_quality_descriptor(file),
                    role=role,
                    rank=rank,
                    transfer_id=transfer_id,
                    size=file.size,
                    requested_at=datetime.now(timezone.utc).isoformat(),
                ),
                connection,
            )

    def _record_shortlisted(
            self,
            track: Track,
            file: SoulseekFile,
            rank: int,
    ) -> None:
        # Known and persisted, but not yet sent to slskd — request_download
        # only happens once a higher-ranked entry for this track is
        # rejected (see the poll_downloads cascade below).
        with self.database.transaction() as connection:
            self.download_requests.add(
                DownloadRequest(
                    track_id=track.id,
                    username=file.username,
                    filename=file.filename,
                    format=file.extension,
                    quality_descriptor=_quality_descriptor(file),
                    role="upgrade",
                    status="shortlisted",
                    rank=rank,
                    size=file.size,
                    requested_at=datetime.now(timezone.utc).isoformat(),
                ),
                connection,
            )

    def _record_review_candidate(
            self,
            track: Track,
            file: SoulseekFile,
            score: float,
    ) -> None:
        with self.database.transaction() as connection:
            self.soulseek_review_candidates.upsert(
                SoulseekReviewCandidate(
                    track_id=track.id,
                    username=file.username,
                    filename=file.filename,
                    score=score,
                    quality_descriptor=_quality_descriptor(file),
                    found_at=datetime.now(timezone.utc).isoformat(),
                    size=file.size,
                ),
                connection,
            )

    def _clear_review_candidate(self, track_id: str) -> None:
        with self.database.transaction() as connection:
            self.soulseek_review_candidates.delete(track_id, connection)

    def get_review_candidates(
            self,
            playlist_id: str | None = None,
    ) -> list[tuple[Track, SoulseekReviewCandidate]]:
        # Read-only listing — the actual confirm/reject actions are
        # confirm_review_candidate()/reject_review_candidate() below
        # (item 26, the Review screen), not here. Originally this
        # method's own docstring deferred that entirely to "a future UI,
        # not another CLI prompt loop" (mirroring the local matcher's
        # identical open item) — that future UI is what item 26 builds.
        with self.database.transaction() as connection:
            candidates = self.soulseek_review_candidates.get_all(connection)

            if playlist_id is not None:
                tracks = self.tracks.get_all_for_playlist(
                    playlist_id, connection
                )
            else:
                tracks = self.tracks.get_all(connection)

            tracks_by_id = {track.id: track for track in tracks}

        results = []

        for candidate in candidates:
            track = tracks_by_id.get(candidate.track_id)

            if track is not None:
                results.append((track, candidate))

        results.sort(key=lambda item: (item[0].artist, item[0].title))

        return results

    def confirm_review_candidate(self, track_id: str) -> None:
        # Item 26 — the Review screen's SoulSeek-candidate confirm
        # action. role='settled', deliberately: a human just manually
        # confirmed this specific candidate is correct, a stronger
        # signal than an algorithmic top-rank pick, so it auto-moves
        # into the library on success rather than demanding a SECOND
        # confirmation via ready_for_review. This required a real,
        # audited change to poll_downloads()'s rejection handling (see
        # CLAUDE.md item 26) — find_best_needs_review_candidate never
        # filters on lock status, so this candidate genuinely can be
        # locked, and a locked settled-role request now correctly
        # retries via the same Phase 3 cascade an upgrade would, rather
        # than failing permanently the moment it's requested.
        with self.database.transaction() as connection:
            candidate = self.soulseek_review_candidates.get_by_track_id(
                track_id, connection,
            )

        if candidate is None:
            raise ReviewCandidateNotFoundError(
                f"No SoulSeek review candidate found for track "
                f"{track_id}."
            )

        if candidate.size is None:
            # A legacy row persisted before `size` existed on this
            # table (item 26) — can't call request_download without it.
            # Downloading the track's playlist again refreshes this row
            # with a real size the normal way, rather than this method
            # guessing or defaulting one. UI-first wording (roadmap
            # item 6 §2) — this reaches the GUI directly via the
            # Review tab's Confirm action, so it must describe the fix
            # in UI terms, not a CLI command.
            raise ReviewCandidateMissingSizeError(
                f"Review candidate for track {track_id} predates size "
                f"tracking — download its playlist again (Dashboard → "
                f"select the playlist → Download) to refresh it before "
                f"confirming."
            )

        transfer_id = self.soulseek.request_download(
            candidate.username, candidate.filename, candidate.size,
        )

        with self.database.transaction() as connection:
            self.download_requests.add(
                DownloadRequest(
                    track_id=track_id,
                    username=candidate.username,
                    filename=candidate.filename,
                    format=derive_extension(candidate.filename),
                    quality_descriptor=candidate.quality_descriptor,
                    role="settled",
                    transfer_id=transfer_id,
                    size=candidate.size,
                    requested_at=datetime.now(timezone.utc).isoformat(),
                ),
                connection,
            )

        # Cleared immediately once the request is made, not once it
        # completes — the exact same clearing trigger item 17 already
        # established ("something real now exists for this track"), so
        # `seeker check` never surfaces this candidate as still awaiting
        # a decision once a decision has, in fact, been made.
        self._clear_review_candidate(track_id)

    def reject_review_candidate(self, track_id: str) -> None:
        # No request made — just removes the candidate from view. Note,
        # not built: nothing stops the same or a similar candidate from
        # resurfacing on a later `download` run if it's still the
        # best-scoring real match (no blacklist concept exists here);
        # that's out of scope for this action.
        self._clear_review_candidate(track_id)

    def poll_downloads(self) -> dict[str, int]:
        # Diagnostic (roadmap item 63/66) — a real, timestamped call-
        # frequency log for the still-open locked-retry burst
        # investigation, gated behind SEEKER_DEBUG_POLL=1 (Phase 4.3
        # converted this from an unconditional print — see _debug_poll's
        # own docstring for why it stays rather than being deleted
        # outright). `_trigger_backend_poll`'s own overlap guard should
        # make this fire at most once per real 20s BACKEND_POLL_INTERVAL_MS
        # tick; a real attended run once showed a genuinely bursty
        # pattern no isolated repro has reproduced since (see
        # docs/HISTORY.md item 63).
        _debug_poll(
            f"[poll_downloads] {datetime.now(timezone.utc).isoformat()} "
            f"called"
        )

        # Roadmap item R7.4 — checked here, not just in the UI's own
        # timer, so pausing is authoritative regardless of caller: no
        # real slskd network call (status poll, locked-retry, upgrade
        # cascade) happens at all while paused. Read fresh via
        # self._get_config() (the same not-a-snapshot discipline every
        # other config read in this class already uses), never cached,
        # so a resume takes effect on the very next call.
        if self._get_config().downloads_paused:
            # Same full key set the CLI's `seeker downloads status`
            # print reads from a real run (queued/downloading/
            # completed/failed plus the four counts normally appended
            # at the end of this method) — a paused run must report
            # honestly "nothing happened," not raise a KeyError on a
            # key a real run would have added.
            return {
                "queued": 0, "downloading": 0, "completed": 0, "failed": 0,
                "ready_for_review": 0, "locked": 0, "shortlisted": 0,
                "superseded": 0, "unavailable": 0,
            }

        with self.database.transaction() as connection:
            pending = self.download_requests.get_pending(connection)
            locked = self.download_requests.get_locked(connection)

        _debug_poll(
            f"[poll_downloads] pending={len(pending)} locked={len(locked)}"
        )

        counts = {
            "queued": 0,
            "downloading": 0,
            "completed": 0,
            "failed": 0,
        }

        for request in pending:
            # Loaded from the DB via get_pending() above, so .id is set —
            # only a not-yet-persisted DownloadRequest has id=None, and
            # nothing here ever is one.
            assert request.id is not None

            # Same principle as download_playlist(): one bad request (a
            # network blip talking to slskd, anything) must not silently
            # stop every request after it in this run from being polled.
            try:
                if request.transfer_id is None:
                    counts[request.status] += 1
                    continue

                transfer_status = self.soulseek.get_download_status(
                    request.username,
                    request.transfer_id,
                )
                state = transfer_status.state

                if any(marker in state for marker in FAILED_STATE_MARKERS):
                    # A rejection isn't progress — progress fields stay
                    # unset here rather than zeroed, whether or not any
                    # bytes happened to move before the rejection (real,
                    # confirmed data: a rejected-before-any-bytes-moved
                    # transfer reports bytesTransferred=0, but recording
                    # that would misleadingly imply a real 0%-complete
                    # attempt rather than "never really started").
                    #
                    # Lock-pattern classification applies regardless of
                    # role (item 26 correction — see CLAUDE.md item 13's
                    # updated note): this used to be scoped to
                    # role=='upgrade' only, on the premise that
                    # select_downloads() never assigns a locked candidate
                    # to 'settled', so a settled-role rejection was
                    # "never expected to be lock-related". That premise
                    # was already only ever approximately true even for
                    # the ordinary search pipeline (a candidate confirmed
                    # unlocked at search time can go offline by the time
                    # the real request lands), and confirm_review_candidate
                    # (item 26) makes it concretely false: a needs-review
                    # candidate is never filtered on lock status at all,
                    # so a human-confirmed one can be a genuinely locked
                    # file requested as role='settled'. Retry-worthiness
                    # is a property of the REJECTION, not of why the
                    # download was requested, so the classification
                    # itself is now unconditional; only the Phase 4
                    # cascade below stays role-specific, since the
                    # shortlist/cascade mechanism is an upgrade-only
                    # concept.
                    status = self._resolve_rejection_status(
                        state, request.username, request.transfer_id,
                    )
                    self._update_status(request.id, status)

                    if status == "failed":
                        counts["failed"] += 1

                    if request.role == "upgrade":
                        # Phase 4 cascade: try the next shortlisted
                        # candidate for this track immediately, in this
                        # same run, regardless of why this one was
                        # rejected (locked-pattern or otherwise) — the
                        # exact same candidate has already failed either
                        # way, so there's no reason to wait a day before
                        # trying the next best one. Scoped to
                        # role=='upgrade' only — 'settled' has no
                        # shortlist concept, and get_next_shortlisted()
                        # isn't itself role-scoped, so calling this for a
                        # 'settled' rejection could incorrectly activate
                        # an unrelated upgrade-role shortlist entry for
                        # the same track.
                        self._cascade_upgrade(request.track_id, counts)

                    continue

                # Genuinely in progress or just succeeded — real
                # bytes-so-far/total are available either way (on a
                # completed transfer, confirmed live: bytes_transferred
                # == size). Every request reaching this point came from
                # `pending` (queued/downloading only) at the top of this
                # run, so this never fires for a locked/shortlisted/
                # superseded row.
                self._update_progress(
                    request.id,
                    transfer_status.bytes_transferred,
                    transfer_status.size,
                )

                if "Succeeded" not in state:
                    new_status = (
                        "downloading" if state != "Requested" else "queued"
                    )

                    if new_status != request.status:
                        self._update_status(request.id, new_status)

                    counts[new_status] += 1
                    continue

                if request.role == "upgrade":
                    # Leave the file in slskd's own download dir — it
                    # only moves once the user confirms the replacement
                    # below.
                    self._update_status(request.id, "ready_for_review")
                    self._supersede_others_for_track(
                        request.track_id, request.id,
                    )
                    continue

                if self._track_already_has_a_matched_file(request.track_id):
                    # Roadmap item 56 Phase 5.3 — a real safety net,
                    # not a hypothetical: this is what closes the gap
                    # 5.2's dedup guard alone couldn't (a candidate
                    # requested before that guard existed, or matched
                    # by some other path in the meantime). By
                    # definition this settled download is now an
                    # upgrade candidate.
                    self._update_status(request.id, "ready_for_review")
                    self._supersede_others_for_track(
                        request.track_id, request.id,
                    )
                    continue

                move_result = self._move_completed_file(request)

                if move_result is not None:
                    self._update_status(request.id, "completed")
                    counts["completed"] += 1
                    self._index_and_match_settled_download(
                        request, move_result, counts,
                    )
                else:
                    counts[request.status] += 1
            except Exception as error:
                counts["failed"] += 1
                print(
                    f"  Failed to poll '{request.filename}': {error}"
                )

        # Phase 3 retry, now covering the whole shortlist rather than a
        # single row per track: re-issue request_download for every
        # request that was ALREADY 'locked' before this run started (not
        # ones that just became locked above, or via the cascade below —
        # those wait for the next run, matching the "daily cadence"
        # design). Same exact username+filename each time — retrying
        # access to the same candidate, not a fresh search.
        for request in locked:
            # Same principle as above — one bad retry must not stop the
            # rest of the locked shortlist from being retried this run.
            try:
                self._retry_locked_request(request, counts)
            except Exception as error:
                print(
                    f"  Failed to retry locked '{request.filename}': "
                    f"{error}"
                )

        counts["ready_for_review"] = len(self._get_ready_for_review())
        counts["locked"] = len(self._get_locked())
        counts["shortlisted"] = len(self._get_shortlisted())
        counts["superseded"] = len(self._get_superseded())
        counts["unavailable"] = len(self._get_unavailable())

        return counts

    def _resolve_rejection_status(
            self,
            state: str,
            username: str,
            transfer_id: str,
    ) -> str:
        if "Rejected" in state:
            exception_text = self.soulseek.get_download_exception(
                username, transfer_id,
            )

            if is_recognized_rejection(exception_text):
                return "locked"

        return "failed"

    def _cascade_upgrade(self, track_id: str, counts: dict[str, int]) -> None:
        # Sequential, not simultaneous: try one candidate, and only move
        # to the next once this one is confirmed unavailable — never
        # multiple in-flight requests for the same track at once. See
        # CLAUDE.md for why (the Soulseek protocol doesn't swarm-download
        # the way BitTorrent does, and firing every shortlisted candidate
        # at once would just be needless load on multiple peers for a
        # track that only needs one to succeed).
        while True:
            with self.database.transaction() as connection:
                next_entry = self.download_requests.get_next_shortlisted(
                    track_id, connection,
                )

            if next_entry is None:
                return

            # Loaded from the DB via get_next_shortlisted() above.
            assert next_entry.id is not None

            status = self._activate_shortlisted_entry(next_entry)

            if status == "failed":
                counts["failed"] += 1
                continue

            if status == "locked":
                continue

            if status in ("queued", "downloading"):
                counts[status] += 1
                return

            if status == "ready_for_review":
                self._supersede_others_for_track(track_id, next_entry.id)
                return

    def _activate_shortlisted_entry(self, request: DownloadRequest) -> str:
        # Phase 4 cascade — submit a fresh request_download for a NEW
        # candidate (never tried before), so a rejection's reason still
        # matters: it gets properly classified locked-vs-failed, exactly
        # like a first-time request in the main poll_downloads loop.
        #
        # Both loaded from the DB by every real caller (_cascade_upgrade
        # fetches via get_next_shortlisted, which only returns persisted
        # rows; size is always set at creation time in
        # _request_and_record/_record_shortlisted).
        assert request.id is not None
        assert request.size is not None

        try:
            transfer_id = self.soulseek.request_download(
                request.username,
                request.filename,
                request.size,
            )
        except SoulseekDownloadError as error:
            # request_download itself now raises this for BOTH
            # rejection shapes — the synchronous one (e.g. peer
            # offline, a 404 straight off the enqueue POST) as well as
            # the asynchronous one (e.g. file not shared, which instead
            # raises nothing here and only shows up via the status
            # check below) — see client.py's RECOGNIZED_REJECTION_PATTERNS.
            status = (
                "locked" if is_recognized_rejection(str(error)) else "failed"
            )
            self._update_status(request.id, status)
            return status

        # An ASYNC-shape rejection doesn't raise from request_download
        # itself (confirmed live, 2026-08-27) — it shows up almost
        # immediately via the status endpoint instead, so check right
        # away rather than waiting a full poll cycle to find out it
        # failed again. A SYNC-shape rejection (peer offline) never
        # reaches this point at all — it's already handled above.
        state = self.soulseek.get_download_status(
            request.username, transfer_id,
        ).state

        if any(marker in state for marker in FAILED_STATE_MARKERS):
            status = self._resolve_rejection_status(
                state, request.username, transfer_id,
            )
        elif "Succeeded" in state:
            status = "ready_for_review"
        else:
            status = "downloading" if state != "Requested" else "queued"

        with self.database.transaction() as connection:
            self.download_requests.update_transfer_id_and_status(
                request.id, transfer_id, status, connection,
            )

        return status

    def _supersede_others_for_track(
            self,
            track_id: str,
            keep_id: int,
    ) -> None:
        with self.database.transaction() as connection:
            self.download_requests.supersede_other_active_for_track(
                track_id, keep_id, connection,
            )

    def _track_already_has_a_matched_file(self, track_id: str) -> bool:
        """Roadmap item 56 Phase 5.3 — a safety net for the same class
        of bug 5.2 targets: before an automatic completion moves a
        settled download into place, check whether track_matches
        already points at a real local file for this track. By
        definition, a settled download landing after that is now an
        upgrade candidate, not a first arrival — §8's own design
        already says an upgrade is never auto-moved, so this reuses
        that same rule for a settled download that turns out to be
        redundant. Deliberately NOT applied to apply_upgrade_decision's
        own replace action — a human explicitly clicking "Replace" is
        the one place overwriting an existing match is exactly the
        point, not a bug to prevent.
        """
        with self.database.transaction() as connection:
            existing_match = self.track_matches.get_by_track_id(
                track_id, connection,
            )

        return (
            existing_match is not None
            and existing_match.local_file_id is not None
        )

    def _retry_locked_request(
            self, request: DownloadRequest, counts: dict[str, int],
    ) -> None:
        # Phase 3 retry — reactivate an ALREADY-'locked' request. Unlike
        # _activate_shortlisted_entry above, a rejection's specific
        # reason doesn't matter here: this candidate is already
        # confirmed locked, so ANY rejection on the retry (any reason)
        # just means stay 'locked' and try again next run — only a real
        # success or in-progress state moves it out of the retry cycle.
        #
        # `locked` (the list this is called over) is fetched once at the
        # start of poll_downloads(), before the main loop runs — if a
        # DIFFERENT entry for the same track succeeds during that loop
        # and supersedes this one, this row is no longer really 'locked'
        # by the time we get here. Re-check its current status first
        # rather than blindly reactivating (and potentially overwriting
        # 'superseded' back to 'locked'/'queued') a stale snapshot.
        assert request.id is not None
        assert request.size is not None

        with self.database.transaction() as connection:
            current = self.download_requests.get_by_id(request.id, connection)

        if current is None or current.status != "locked":
            return

        if self._supersede_stale_duplicates(current):
            # A more recent row for the exact same candidate already
            # exists and just absorbed this one's spot — no point
            # issuing a real, redundant request_download for a stale
            # duplicate against the same real peer.
            return

        # Roadmap item 66 (Phase 4.3) — the retry cadence is now
        # independent of the poll cadence: a row isn't due for another
        # real attempt until its own next_retry_at (exponential backoff)
        # has passed, however often poll_downloads() itself runs. This
        # is the actual fix for item 63's storm regardless of whatever
        # its real trigger turns out to be — a violated next_retry_at
        # would now be a visible, checkable signal if it recurs.
        now = datetime.now(timezone.utc)
        if current.next_retry_at is not None:
            next_retry_at = datetime.fromisoformat(current.next_retry_at)
            if now < next_retry_at:
                return

        if current.retry_count >= LOCKED_RETRY_MAX_ATTEMPTS:
            # Exhausted every real attempt — the file exists but this
            # peer won't give it up. Terminal, distinct from 'failed'
            # (the candidate itself was real), and deliberately excluded
            # from get_requests_blocking_redownload() so a later
            # download_playlist() run can look for the same track from a
            # different peer.
            with self.database.transaction() as connection:
                self.download_requests.mark_status(
                    request.id, "unavailable", connection,
                )
            return

        try:
            transfer_id = self.soulseek.request_download(
                request.username,
                request.filename,
                request.size,
            )
        except SoulseekDownloadError:
            # Covers both recognized rejection shapes now that
            # request_download wraps the synchronous one too (see
            # client.py's RECOGNIZED_REJECTION_PATTERNS) — a peer that's
            # offline right now hits this branch exactly the same way a
            # file-not-shared rejection always did.
            self._advance_locked_retry(request, current.retry_count)
            return  # Rejected again at the batch level — stays locked.
        except Exception:
            # Roadmap item 66 (Phase 4.3) — live-caught, not
            # theoretical: an UNRECOGNIZED error (client.py's own
            # request_download deliberately re-raises anything that
            # isn't a known rejection pattern "loud," as its own comment
            # says — confirmed live 2026-09-02 against real production
            # slskd, a genuine `500 Internal Server Error` on
            # /api/v0/transfers/downloads/batches, the exact endpoint/
            # error text item 63's storm investigation already flagged
            # as its one concrete lead) must STILL advance the retry
            # budget — otherwise this exact failure shape retries
            # forever with no bound, which is precisely the bug this
            # phase exists to close, regardless of the failure's cause.
            # Re-raised unchanged so poll_downloads()'s own outer
            # per-request try/except still prints its diagnostic; this
            # is additive bookkeeping, not a change to what's reported.
            self._advance_locked_retry(request, current.retry_count)
            raise

        try:
            state = self.soulseek.get_download_status(
                request.username, transfer_id,
            ).state
        except Exception:
            # Same reasoning as the request_download branch above —
            # get_download_status (client.py) has no exception wrapping
            # of its own at all, so any real failure here (a timeout, a
            # non-404 HTTP error) must still count against the retry
            # budget rather than silently never advancing it.
            self._advance_locked_retry(request, current.retry_count)
            raise

        if any(marker in state for marker in FAILED_STATE_MARKERS):
            status = "locked"
        elif "Succeeded" in state:
            # role='upgrade' still needs a human's confirmation via
            # ready_for_review, exactly as before. role='settled' is
            # only reachable here at all via a human-confirmed
            # needs-review candidate that turned out to be locked
            # (find_best_needs_review_candidate never filters on lock
            # status — item 26) — that candidate was ALREADY
            # human-confirmed once, so it auto-moves into the library
            # like an ordinary settled success, not a second
            # confirmation via ready_for_review.
            status = "ready_for_review" if request.role == "upgrade" else "completed"
        else:
            status = "downloading" if state != "Requested" else "queued"

        if (
                status == "completed"
                and self._track_already_has_a_matched_file(request.track_id)
        ):
            # Roadmap item 56 Phase 5.3 — same safety net as the main
            # poll_downloads() loop: even a role='settled' row that's
            # already human-confirmed once (item 26's own reasoning
            # just above) must not silently create a second file for a
            # track something else already matched in the meantime.
            status = "ready_for_review"
        elif status == "completed":
            # Mirror poll_downloads()'s own main-loop pattern: only
            # persist 'completed' if the file is genuinely found and
            # moved. If not, fall back to 'downloading' — the real
            # transfer stays reported as Succeeded by slskd on every
            # future poll, so the next run's main pending loop retries
            # the move instead of this row silently claiming a
            # completion that never actually happened.
            move_result = self._move_completed_file(request)

            if move_result is not None:
                counts["completed"] += 1
                # Same indexing gap as poll_downloads()'s main loop
                # (see _index_and_match_settled_download's own
                # docstring) — this branch reaches 'completed' for a
                # role='settled' row too (a human-confirmed needs-review
                # candidate that turned out to be locked), so it needs
                # the identical fix, not a second copy of it.
                self._index_and_match_settled_download(
                    request, move_result, counts,
                )
            else:
                status = "downloading"

        with self.database.transaction() as connection:
            self.download_requests.update_transfer_id_and_status(
                request.id, transfer_id, status, connection,
            )

        if status == "locked":
            # Real attempt made, still locked — advance the backoff
            # schedule. Left alone (not reset) when status moves on to
            # anything else: those rows leave the retry cycle entirely,
            # so their retry_count/next_retry_at stop being consulted.
            self._advance_locked_retry(request, current.retry_count)

        if status == "ready_for_review":
            self._supersede_others_for_track(request.track_id, request.id)

    def _advance_locked_retry(
            self, request: DownloadRequest, current_retry_count: int,
    ) -> None:
        # Roadmap item 66 (Phase 4.3) — called once per real retry
        # attempt that ends up staying 'locked' (whether rejected at the
        # batch level or via the async status check), regardless of
        # which of the two call sites made the attempt. current_retry_count
        # is the count BEFORE this attempt — used as the exponent so the
        # first attempt (0) backs off LOCKED_RETRY_BASE_SECONDS, matching
        # the brief's own worked example (60s, then 120s, then 240s).
        assert request.id is not None

        new_retry_count = current_retry_count + 1
        backoff_seconds = min(
            LOCKED_RETRY_BASE_SECONDS * (2 ** current_retry_count),
            LOCKED_RETRY_MAX_SECONDS,
        )
        next_retry_at = (
            datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
        ).isoformat()

        with self.database.transaction() as connection:
            self.download_requests.update_retry_state(
                request.id, new_retry_count, next_retry_at, connection,
            )

    def _supersede_stale_duplicates(self, request: DownloadRequest) -> bool:
        # item 16's creation-time dedup guard (get_active_for_track,
        # checked inside download_playlist()) only prevents NEW
        # duplicate rows going forward — it does nothing for rows
        # already created before it was fully effective. Confirmed live
        # (2026-08-28): get_locked() has no per-track/per-candidate
        # collapsing by its own documented design, so without this
        # check the retry loop below would re-issue a real
        # request_download for every stale duplicate independently,
        # every poll cycle, against the same real peer — real, ongoing,
        # low-value network traffic against a live third party.
        #
        # Mirrors seeker.download_dedup.most_recent_per_candidate's
        # exact grouping/tiebreak rule rather than reinventing one — the
        # same rule DashboardService.get_active_downloads() already
        # uses on the read side, so display and mutation never drift
        # onto two different notions of "duplicate" (the same
        # consolidation reasoning already applied to matching.py and
        # AUDIO_EXTENSIONS elsewhere in this codebase).
        #
        # Returns True if `request` itself lost to a more recent sibling
        # (and was just marked 'superseded' — the caller must not retry
        # it). Returns False if `request` IS the most recent (or the
        # only) row for its candidate — in which case every OTHER
        # sibling in the group gets marked 'superseded' here, so a
        # group of duplicates converges to one survivor within a single
        # poll_downloads() run regardless of which row this method
        # happens to be called for first (get_by_id-guarded siblings
        # already marked 'superseded' on an earlier call this same run
        # simply won't be in the group query's result on a later one).
        assert request.id is not None

        with self.database.transaction() as connection:
            group = self.download_requests.get_active_candidates(
                request.track_id, request.role, request.username,
                request.filename, connection,
            )

        winner = most_recent_per_candidate(group).get(
            candidate_key(request)
        )

        if winner is not None and winner.id != request.id:
            self._update_status(request.id, "superseded")
            return True

        for sibling in group:
            if sibling.id != request.id:
                assert sibling.id is not None
                self._update_status(sibling.id, "superseded")

        return False

    def review_pending_upgrades(self) -> None:
        requests = self._get_ready_for_review()

        if not requests:
            print("Nothing to review.")
            return

        for request in requests:
            self._confirm_upgrade(request)

    def _get_ready_for_review(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_ready_for_review(connection)

    def _get_locked(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_locked(connection)

    def _get_shortlisted(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_shortlisted(connection)

    def _get_superseded(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_superseded(connection)

    def _get_unavailable(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_unavailable(connection)

    def _update_status(self, request_id: int, status: str) -> None:
        with self.database.transaction() as connection:
            self.download_requests.mark_status(request_id, status, connection)

    def _update_progress(
            self,
            request_id: int,
            bytes_transferred: int | None,
            total_bytes: int | None,
    ) -> None:
        with self.database.transaction() as connection:
            self.download_requests.update_progress(
                request_id, bytes_transferred, total_bytes, connection,
            )

    def _resolve_destination(
            self,
            playlist: Playlist | None,
    ) -> tuple[LibraryLocation, str | None] | None:
        """A playlist-specific download_location_id/download_subfolder
        always wins when set. Otherwise falls back to the configured
        default destination (roadmap item 6) — resolved through
        _get_config(), not a snapshot, so a Settings-driven change
        takes effect on the very next call, matching this project's
        standing rule for every other config-backed threshold. The
        playlist's own name becomes the subfolder (sanitized — a real
        playlist name, "240KM/H", contains a literal path separator)
        only when default_download_subfolder_per_playlist is on.
        Returns None when neither resolves to a real, still-registered
        location — the caller's job to report that clearly.

        Roadmap item 82 (P13.2) — `playlist=None` is a manual (not-
        from-Spotify) search-and-download track, which has no playlist
        at all: always resolves via the configured default (never a
        playlist-specific override, since there's no playlist), with a
        fixed "Manual" subfolder — never the per-playlist subfolder
        rule, which has no meaning here.

        The actual precedence logic lives in destination_resolution.py
        (roadmap item 93/B3.4) — shared with MetadataService's rename
        preview, which needs to know a track's configured destination
        without a second, drifting copy of this rule.
        """
        with self.database.transaction() as connection:
            return resolve_playlist_destination(
                playlist, self.locations, self._get_config, connection,
            )

    def _move_completed_file(
            self,
            request: DownloadRequest,
    ) -> tuple[LibraryLocation, str] | None:
        if not self.slskd_download_dir:
            print(
                f"  Warning: SLSKD_DOWNLOAD_DIR is not configured; "
                f"cannot move '{request.filename}'."
            )
            return None

        with self.database.transaction() as connection:
            playlists = self.playlists.get_by_track_id(
                request.track_id,
                connection,
            )

        resolved = None

        for playlist in playlists:
            resolved = self._resolve_destination(playlist)

            if resolved is not None:
                break

        if not playlists:
            # Roadmap item 82 (P13.2) — a manual (not-from-Spotify)
            # track belongs to no playlist at all, so the loop above
            # never runs and `resolved` would otherwise stay None
            # unconditionally, leaving every completed manual download
            # stuck in slskd's own download dir forever. Falls back to
            # the same default-destination resolution _resolve_
            # destination(None) now supports. Deliberately scoped to
            # "genuinely no playlist" only — an ordinary playlist track
            # with no resolvable destination keeps its existing,
            # unchanged "leave it in place" behavior.
            resolved = self._resolve_destination(None)

        if resolved is None:
            print(
                f"  Warning: no configured destination found for "
                f"track {request.track_id}; leaving "
                f"'{request.filename}' in place."
            )
            return None

        location, subfolder = resolved

        basename = Path(request.filename.replace("\\", "/")).name
        # rglob() treats its argument as a glob PATTERN, not a literal
        # name — real Soulseek filenames routinely contain '[', ']'
        # (release tags like "[www.dj-promo.org]", "[FLAC]"), which
        # fnmatch interprets as a character class. Unescaped, a real
        # completed download with such a filename silently never
        # matches here (an empty `matches` list, not an error) and
        # stays stuck in 'downloading' forever, never moved or indexed
        # — found live while verifying the Phase 1 indexing fix against
        # a real completed transfer whose filename contained exactly
        # this pattern. glob.escape() makes the lookup literal again.
        matches = list(
            Path(self.slskd_download_dir).rglob(glob.escape(basename))
        )

        if not matches:
            return None

        destination_dir = Path(location.path)

        if subfolder:
            destination_dir = destination_dir / subfolder

        destination_dir.mkdir(parents=True, exist_ok=True)

        destination_path = destination_dir / basename
        shutil.move(str(matches[0]), str(destination_path))

        print(f"  Moved '{basename}' to {destination_dir}")

        relative_path = str(
            destination_path.relative_to(Path(location.path))
        )

        return (location, relative_path)

    def _index_and_match_settled_download(
            self,
            request: DownloadRequest,
            move_result: tuple[LibraryLocation, str],
            counts: dict[str, int],
    ) -> None:
        # An ordinary settled download previously left the file moved
        # into place but otherwise invisible to the rest of the app:
        # index_single_file() only ever ran on the confirmed-upgrade
        # path (apply_upgrade_decision, below), never here. So the file
        # never got a local_files row, never got a track_matches row,
        # and the track stayed NOT_FOUND on the Dashboard forever —
        # DashboardService._compute_status requires BOTH an 'auto'
        # track_matches row AND a resolvable local_file_id for
        # IN_LIBRARY — with no ordinary Match run able to fix it either,
        # since match_all() only ever considers local_files rows that
        # already exist. It also left get_unmatched_for_playlist()
        # (which filters on track_matches.match_method IS NULL)
        # thinking the track was still unmatched, so a second
        # `download`/Download-click run would genuinely re-search and
        # re-request a file already sitting on disk — get_active_for_
        # track's creation-time dedup guard only covers ACTIVE requests
        # (excludes 'completed'), so it did nothing to prevent this.
        #
        # Fixed by mirroring apply_upgrade_decision's own index+match
        # tail. match_method='auto' is set unconditionally, regardless
        # of the computed fuzzy score: this exact file was searched,
        # filtered by quality.py, and downloaded FOR this exact track —
        # that provenance is a stronger signal than filename fuzzy-
        # matching, the same reasoning item 26 used when a human-
        # confirmed needs-review candidate is requested as
        # role='settled'. Unlike apply_upgrade_decision's hardcoded
        # score=100.0 sentinel, the real find_best_match() score is
        # computed and stored here so a genuinely bad pairing stays
        # visible in the data instead of being hidden behind a fake
        # perfect score.
        #
        # Wrapped in its own try/except, per this codebase's standing
        # per-item batch rule: an indexing/matching failure must not
        # undo the 'completed' status the caller already set (the file
        # really did download successfully), and must not abort the
        # rest of this poll_downloads() run.
        try:
            location, relative_path = move_result

            with self.database.transaction() as connection:
                local_file = index_single_file(
                    location, relative_path, self.local_files, connection,
                )

                track = self.tracks.get_by_id(request.track_id, connection)
                score = None

                if track is not None:
                    match = find_best_match(track, [local_file])
                    if match is not None:
                        score = match[1]

                    # Roadmap item 82 (P13.1) — a manual (not-from-
                    # Spotify) track is created with a placeholder
                    # duration_ms=0 (there's no real Spotify duration
                    # to record). find_best_match() above never reads
                    # duration at all (matching.py's scoring is
                    # artist+title only), so this doesn't affect THIS
                    # match — but a LATER match_all() re-run applies
                    # its own duration pre-filter (DURATION_TOLERANCE_MS,
                    # matcher.py) against every candidate local file,
                    # which a real duration_ms=0 would fail against
                    # almost any real file and could demote this match
                    # back to unmatched (item 45's own documented
                    # demotion-risk class). Backfilled here, once, from
                    # the real just-downloaded file's own read duration
                    # — never touches a real Spotify track's authoritative
                    # duration_ms.
                    if (
                            is_manual_track_id(track.id)
                            and local_file.duration_ms is not None
                    ):
                        self.tracks.save(
                            replace(
                                track, duration_ms=local_file.duration_ms,
                            ),
                            connection,
                        )

                self.track_matches.upsert(
                    TrackMatch(
                        track_id=request.track_id,
                        local_file_id=local_file.id,
                        match_method="auto",
                        score=score,
                        matched_at=datetime.now(timezone.utc).isoformat(),
                    ),
                    connection,
                )

            counts["indexed"] = counts.get("indexed", 0) + 1
        except Exception as error:
            counts["index_failed"] = counts.get("index_failed", 0) + 1
            print(
                f"  Warning: downloaded '{request.filename}' but failed "
                f"to index/match it into the library: {error}"
            )

    def get_upgrade_review_details(
            self,
            request_id: int,
    ) -> UpgradeReviewDetails | None:
        # Read-only — no input() anywhere, so both the CLI's interactive
        # loop and the Review screen's UI can build their prompts/labels
        # from the identical resolved info. None only when the request
        # or its track can no longer be found (matches the CLI's own
        # original early-return-on-missing-track guard).
        with self.database.transaction() as connection:
            request = self.download_requests.get_by_id(request_id, connection)

            if request is None:
                return None

            track = self.tracks.get_by_id(request.track_id, connection)
            current_match = self.track_matches.get_by_track_id(
                request.track_id,
                connection,
            )

            current_local_file = None
            if current_match is not None and current_match.local_file_id:
                current_local_file = self.local_files.get_by_id(
                    current_match.local_file_id,
                    connection,
                )

            old_location = None
            if current_local_file is not None:
                old_location = self.locations.get_by_id(
                    current_local_file.location_id,
                    connection,
                )

        if track is None:
            return None

        current_description = (
            current_local_file.format
            if current_local_file is not None
            else "no current file"
        )

        old_file_path = None
        if current_local_file is not None and old_location is not None:
            old_file_path = str(
                Path(old_location.path) / current_local_file.relative_path
            )

        return UpgradeReviewDetails(
            request_id=request_id,
            track=track,
            quality_descriptor=request.quality_descriptor,
            current_description=current_description,
            old_file_path=old_file_path,
        )

    def get_pending_upgrade_reviews(self) -> list[UpgradeReviewDetails]:
        # The Review screen's listing call for its upgrade-confirmation
        # section — same read-only resolution get_upgrade_review_details
        # already does per-row, just fetching every ready_for_review row
        # up front rather than requiring the caller to already know a
        # request_id (mirrors get_review_candidates()'s own shape for
        # the needs-review section). A row whose details can no longer
        # be resolved (track deleted, etc.) is silently skipped rather
        # than surfaced as a broken row — the same "None means gone"
        # contract get_upgrade_review_details already documents.
        requests = self._get_ready_for_review()

        results = []

        for request in requests:
            assert request.id is not None
            details = self.get_upgrade_review_details(request.id)

            if details is not None:
                results.append(details)

        return results

    def apply_upgrade_decision(
            self,
            request_id: int,
            replace: bool,
            delete_old: bool = False,
    ) -> str | None:
        """Explicit-decision version of the Phase 2 replace/delete-old-
        file action — pure mutation, no input() anywhere, so the CLI's
        interactive loop and a UI can call the identical logic with
        already-resolved booleans instead of blocking on stdin. Returns
        a short, human-readable status message (the exact text
        review_pending_upgrades() used to print inline) for the caller
        to surface, or None for `replace=False` (a no-op — the row
        stays ready_for_review, offered again later, same as declining
        in the CLI).
        """
        if not replace:
            return None

        with self.database.transaction() as connection:
            request = self.download_requests.get_by_id(request_id, connection)

        if request is None:
            return "Request not found."

        with self.database.transaction() as connection:
            current_match = self.track_matches.get_by_track_id(
                request.track_id,
                connection,
            )

            current_local_file = None
            if current_match is not None and current_match.local_file_id:
                current_local_file = self.local_files.get_by_id(
                    current_match.local_file_id,
                    connection,
                )

        result = self._move_completed_file(request)

        if result is None:
            return "Could not locate the downloaded file; leaving for review."

        location, relative_path = result

        with self.database.transaction() as connection:
            new_local_file = index_single_file(
                location,
                relative_path,
                self.local_files,
                connection,
            )

            self.track_matches.upsert(
                TrackMatch(
                    track_id=request.track_id,
                    local_file_id=new_local_file.id,
                    match_method="auto",
                    score=100.0,
                    matched_at=datetime.now(timezone.utc).isoformat(),
                ),
                connection,
            )

            # request_id, not request.id — this is the caller-supplied
            # id (always set for any real caller: get_ready_for_review()
            # rows always have one), avoiding a redundant assert on the
            # freshly-refetched `request` above.
            self.download_requests.mark_status(
                request_id,
                "completed",
                connection,
            )

        message = f"Replaced with {location.path}/{relative_path}"

        if current_local_file is None:
            return message

        with self.database.transaction() as connection:
            old_location = self.locations.get_by_id(
                current_local_file.location_id,
                connection,
            )

        if old_location is None:
            return message

        old_path = Path(old_location.path) / current_local_file.relative_path

        if not delete_old:
            return f"{message}\n  Leaving {old_path} in place."

        error = delete_file(old_path)

        if error is None:
            return f"{message}\n  Deleted {old_path}"

        return f"{message}\n  Could not delete {old_path}: {error}"

    def apply_upgrade_decisions_batch(
            self,
            request_ids: list[int],
            delete_old: bool,
    ) -> BulkUpgradeReplaceResult:
        """Roadmap item R3.1 — "Replace all" pending upgrades. Applies
        `apply_upgrade_decision(request_id, True, delete_old)` per row
        through the exact same explicit-decision method the CLI and
        the single-row UI action already use — no second mutation
        path. Per-row try/except (CLAUDE.md's standing batch-loop
        pattern, item 15) so one bad row can't abort the rest.

        Success is checked by re-reading the request's own status
        AFTER the call, not by parsing the returned message string —
        `apply_upgrade_decision`'s own contract only advances a
        request to `"completed"` on a real success; every failure path
        (not found, file not locatable) returns early with the status
        untouched, so a failed row is naturally still
        `ready_for_review` afterward and will be offered again on the
        next Review poll (the brief's own "partial failure must leave
        failed rows visible and pending" requirement, satisfied
        structurally rather than by extra bookkeeping here).
        """
        replaced = 0
        failed = 0
        details: list[str] = []

        for request_id in request_ids:
            review_details = self.get_upgrade_review_details(request_id)
            label = (
                f"{review_details.track.artist} - {review_details.track.title}"
                if review_details is not None
                else f"request {request_id}"
            )

            try:
                message = self.apply_upgrade_decision(
                    request_id, True, delete_old,
                )
            except Exception as error:
                failed += 1
                details.append(f"{label}: Failed — {error}")
                continue

            with self.database.transaction() as connection:
                updated_request = self.download_requests.get_by_id(
                    request_id, connection,
                )

            succeeded = (
                updated_request is not None
                and updated_request.status == "completed"
            )

            if succeeded:
                replaced += 1
            else:
                failed += 1

            details.append(f"{label}: {message or 'No change made.'}")

        return BulkUpgradeReplaceResult(
            replaced=replaced, failed=failed, details=details,
        )

    def _confirm_upgrade(self, request: DownloadRequest) -> None:
        # Thin, interactive wrapper over the two explicit-decision
        # methods above — CLI-only input() sequencing lives here now;
        # the actual mutation is identical to what apply_upgrade_decision
        # does for the UI. Always called over rows from
        # get_ready_for_review(), so .id is set.
        assert request.id is not None

        details = self.get_upgrade_review_details(request.id)

        if details is None:
            return

        answer = input(
            f"Higher quality version of {details.track.artist} - "
            f"{details.track.title} ready ({details.quality_descriptor} "
            f"vs current {details.current_description}). Replace? [y/n] "
        ).strip().lower()

        replace = answer == "y"
        delete_old = False

        if replace and details.old_file_path is not None:
            delete_answer = input(
                f"Delete old file at {details.old_file_path}? [y/n] "
            ).strip().lower()
            delete_old = delete_answer == "y"

        message = self.apply_upgrade_decision(request.id, replace, delete_old)

        if message is not None:
            print(f"  {message}")
