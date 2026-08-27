from datetime import datetime, timezone
from typing import Any

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
    resolve_text_source,
    score_title,
)
from seeker.models.local_file import LocalFile
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch


# Duration pre-filter window. Starting at ±5 seconds — tune this once real
# match data shows how tight/loose it needs to be.
DURATION_TOLERANCE_MS = 5_000


def find_best_match(
        track: Track,
        candidates: list[LocalFile],
) -> tuple[LocalFile, float] | None:
    best: tuple[LocalFile, float] | None = None

    for candidate in candidates:
        local_artist_source = resolve_text_source(
            candidate.tag_artist, candidate.filename
        )

        if not artist_matches(track.artist, local_artist_source):
            continue

        local_title_source = resolve_text_source(
            candidate.tag_title, candidate.filename
        )

        score = score_title(track.artist, track.title, local_title_source)

        if best is None or score > best[1]:
            best = (candidate, score)

    return best


class TrackMatcher:
    def __init__(
        self,
        database: Database,
        track_repository: TrackRepository,
        local_file_repository: LocalFileRepository,
        track_match_repository: TrackMatchRepository,
    ):
        self.database = database
        self.tracks = track_repository
        self.local_files = local_file_repository
        self.track_matches = track_match_repository

    def match_all(self) -> dict[str, int]:
        counts = {"auto": 0, "needs_review": 0, "unmatched": 0}

        with self.database.transaction() as connection:
            tracks = self.tracks.get_all(connection)
            local_files = self.local_files.get_all(connection)

            for track in tracks:
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

                    if score >= AUTO_MATCH_THRESHOLD:
                        match_method = "auto"
                        local_file_id = candidate.id
                    elif score >= NEEDS_REVIEW_THRESHOLD:
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
                        matched_at=datetime.now(timezone.utc).isoformat(),
                    ),
                    connection,
                )

        print(
            f"Matching complete. "
            f"Auto: {counts['auto']}, "
            f"Needs review: {counts['needs_review']}, "
            f"Unmatched: {counts['unmatched']}."
        )

        return counts

    def generate_match_report(self) -> dict[str, Any]:
        with self.database.transaction() as connection:
            tracks_by_id = {
                track.id: track
                for track in self.tracks.get_all(connection)
            }
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
