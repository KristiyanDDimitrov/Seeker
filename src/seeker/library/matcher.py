import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from seeker.config_store import SeekerConfig
from seeker.database.connection import Database
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.matching import (
    AUTO_MATCH_THRESHOLD,
    NEEDS_REVIEW_THRESHOLD,
    artist_matches,
    evaluate_match,
    resolve_text_source,
)
from seeker.models.local_file import LocalFile
from seeker.models.track import Track, is_manual_track_id
from seeker.models.track_match import TrackMatch

logger = logging.getLogger(__name__)

# Duration pre-filter window. Starting at ±5 seconds — tune this once real
# match data shows how tight/loose it needs to be.
DURATION_TOLERANCE_MS = 5_000


def _resolve_artist_evidence(
        spotify_artist: str,
        candidate: LocalFile,
) -> tuple[str, bool]:
    """Returns (local_artist_source, came_from_a_real_tag).

    When tag_artist is populated, it's the only source tried — a real
    tag that doesn't name the artist is genuine negative evidence
    (evaluate_match's hard-reject branch), not something a path/filename
    fallback should be allowed to override.

    When tag_artist is null, tries filename stem -> parent directory
    name -> grandparent directory name in order (roadmap item 56): a
    real Artist/Album/Track.ext library layout puts the artist name in
    the path, not just the filename, and this used to be ignored
    entirely. The first source that actually contains the artist name
    wins; evaluate_match() re-confirms it and treats it as confirmed
    (a folder name is real, human-curated evidence, same as a tag).
    If nothing matches, the filename stem is still returned as the
    nominal source (for evaluate_match's "not confirmed, not a tag"
    capped-score branch), not as any evidence in itself.
    """
    if candidate.tag_artist:
        return candidate.tag_artist, True

    # filename.stem, not relative_path's own stem — relative_path is
    # only consulted below for its PARENT components (real, extra
    # information filename alone can't give); its basename is the same
    # file this candidate's own .filename already names, and the two can
    # legitimately differ in a test fixture or an inconsistent caller.
    fallback_sources = [Path(candidate.filename).stem]

    path = Path(candidate.relative_path)
    parent_name = path.parent.name
    if parent_name:
        fallback_sources.append(parent_name)

    grandparent_name = path.parent.parent.name
    if grandparent_name and grandparent_name != parent_name:
        fallback_sources.append(grandparent_name)

    for source in fallback_sources:
        if artist_matches(spotify_artist, source, aggressive=True):
            return source, False

    return fallback_sources[0], False


def find_best_match(
        track: Track,
        candidates: list[LocalFile],
) -> tuple[LocalFile, float] | None:
    best: tuple[LocalFile, float] | None = None

    for candidate in candidates:
        local_artist_source, from_tag = _resolve_artist_evidence(
            track.artist, candidate
        )

        local_title_source = resolve_text_source(
            candidate.tag_title, candidate.filename
        )

        evaluation = evaluate_match(
            track.artist,
            track.title,
            local_artist_source,
            from_tag,
            local_title_source,
        )

        if evaluation.score is None:
            continue

        if best is None or evaluation.score > best[1]:
            best = (candidate, evaluation.score)

    return best


class TrackMatcher:
    def __init__(
        self,
        database: Database,
        track_repository: TrackRepository,
        local_file_repository: LocalFileRepository,
        track_match_repository: TrackMatchRepository,
        get_config: Callable[[], SeekerConfig] | None = None,
    ):
        self.database = database
        self.tracks = track_repository
        self.local_files = local_file_repository
        self.track_matches = track_match_repository
        # A callable, not a snapshot SeekerConfig — TrackMatcher itself
        # is constructed once and cached for the app's lifetime
        # (Application.track_matcher), so a plain dataclass value passed
        # in at construction time would go stale the moment Settings
        # saves a threshold change. Application supplies
        # `lambda: self._config_store`, which always reads its own
        # current attribute; defaulting here to an always-empty config
        # keeps every existing caller (tests included) byte-for-byte
        # unchanged, since SeekerConfig()'s threshold fields are None.
        self._get_config = get_config or SeekerConfig

    def match_all(
            self,
            auto_match_threshold: float | None = None,
            needs_review_threshold: float | None = None,
    ) -> dict[str, int]:
        # Resolved once per call, not cached — a threshold changed via
        # Settings takes effect on the very next match_all() run, no
        # restart needed. An explicit argument (if a caller ever passes
        # one — e.g. a future "preview before saving" UI, or a test)
        # wins over config; config wins over matching.py's hardcoded
        # default.
        config = self._get_config()
        resolved_auto_threshold = (
            auto_match_threshold
            if auto_match_threshold is not None
            else config.auto_match_threshold or AUTO_MATCH_THRESHOLD
        )
        resolved_needs_review_threshold = (
            needs_review_threshold
            if needs_review_threshold is not None
            else config.needs_review_threshold or NEEDS_REVIEW_THRESHOLD
        )

        counts = {"auto": 0, "needs_review": 0, "unmatched": 0}

        with self.database.transaction() as connection:
            tracks = self.tracks.get_all(connection)
            local_files = self.local_files.get_all(connection)
            existing_matches = {
                match.track_id: match
                for match in self.track_matches.get_all(connection)
            }

            for track in tracks:
                # A human-confirmed match (roadmap item 56 Phase 2) must
                # survive a re-match untouched — this is what closes item
                # 45's pre-existing demotion bug (match_all() used to
                # recompute every row from scratch with no concept of
                # "already confirmed," so a later run could silently
                # demote a just-confirmed match back to needs_review).
                existing = existing_matches.get(track.id)

                if existing is not None and existing.confirmed_at is not None:
                    counts["auto"] += 1
                    continue

                candidates = [
                    local_file
                    for local_file in local_files
                    if local_file.duration_ms is None
                    or abs(
                        local_file.duration_ms - track.duration_ms
                    ) <= DURATION_TOLERANCE_MS
                ]

                match = find_best_match(track, candidates)

                match_method = None
                local_file_id = None
                score = None

                if match is not None:
                    candidate, score = match

                    if score >= resolved_auto_threshold:
                        match_method = "auto"
                        local_file_id = candidate.id
                    elif score >= resolved_needs_review_threshold:
                        match_method = "needs_review"
                        local_file_id = candidate.id

                if match_method == "auto":
                    counts["auto"] += 1
                elif match_method == "needs_review":
                    counts["needs_review"] += 1
                else:
                    counts["unmatched"] += 1

                self.track_matches.upsert(
                    TrackMatch(
                        track_id=track.id,
                        local_file_id=local_file_id,
                        match_method=match_method,
                        score=score,
                        matched_at=datetime.now(UTC).isoformat(),
                    ),
                    connection,
                )

        logger.info(
            "Matching complete. Auto: %d, Needs review: %d, Unmatched: %d.",
            counts["auto"], counts["needs_review"], counts["unmatched"],
        )

        return counts

    def generate_match_report(
            self,
            playlist_id: str | None = None,
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            if playlist_id is not None:
                tracks = self.tracks.get_all_for_playlist(
                    playlist_id, connection
                )
            else:
                # Roadmap item 82 (P13.7) — a manual (not-from-Spotify)
                # search-and-download track belongs to no playlist at
                # all, so it can never appear in a playlist-scoped
                # report above — but the GLOBAL report reads every
                # `tracks` row, and would otherwise show a manual
                # track sitting in "unmatched" the moment a routine
                # match run gives it a track_matches row, muddying a
                # report whose whole point is "how much of my Spotify
                # library is present locally."
                tracks = [
                    track for track in self.tracks.get_all(connection)
                    if not is_manual_track_id(track.id)
                ]

            tracks_by_id = {track.id: track for track in tracks}
            matches = self.track_matches.get_all(connection)
            local_files_by_id = {
                local_file.id: local_file
                for local_file in self.local_files.get_all(connection)
            }

        auto_matched = []
        needs_review = []
        unmatched = []

        for match in matches:
            track = tracks_by_id.get(match.track_id)

            if track is None:
                continue

            if match.match_method == "auto":
                local_file = local_files_by_id.get(match.local_file_id)
                filename = (
                    local_file.filename if local_file is not None else "?"
                )
                auto_matched.append(
                    (track.artist, track.title, match.score, filename)
                )
            elif match.match_method == "needs_review":
                needs_review.append(
                    (track.artist, track.title, match.score)
                )
            else:
                unmatched.append((track.artist, track.title))

        auto_matched.sort(key=lambda item: (item[0], item[1]))
        # match.score is float | None in general, but a needs_review-
        # classified match always has a real numeric score (that's what
        # put it in this bucket) — the `or 0.0` is just satisfying the
        # type, not a real fallback path.
        needs_review.sort(key=lambda item: item[2] or 0.0, reverse=True)
        unmatched.sort(key=lambda item: (item[0], item[1]))

        return {
            "auto_count": len(auto_matched),
            "auto_matched": auto_matched,
            "needs_review": needs_review,
            "unmatched": unmatched,
        }
