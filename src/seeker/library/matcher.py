import re
from datetime import datetime, timezone
from pathlib import Path

from rapidfuzz import fuzz

from seeker.database.connection import Database
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.models.local_file import LocalFile
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch


# Duration pre-filter window. Starting at ±5 seconds — tune this once real
# match data shows how tight/loose it needs to be.
DURATION_TOLERANCE_MS = 5_000

AUTO_MATCH_THRESHOLD = 90.0
NEEDS_REVIEW_THRESHOLD = 70.0

TRACK_NUMBER_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s*[-.]\s*")
TRAILING_SEPARATOR_RE = re.compile(r"[\s\-–—.]+$")
WHITESPACE_RE = re.compile(r"\s+")
WATERMARK_SUBSTRINGS = (".com", ".org", ".net")


def normalize_filename_text(text: str) -> str:
    text = TRACK_NUMBER_PREFIX_RE.sub("", text)

    tokens = text.split()

    if tokens and any(
            substring in tokens[-1].lower()
            for substring in WATERMARK_SUBSTRINGS
    ):
        tokens = tokens[:-1]

    text = " ".join(tokens).lower()
    text = TRAILING_SEPARATOR_RE.sub("", text)
    text = WHITESPACE_RE.sub(" ", text)

    return text.strip()


def artist_matches(spotify_artist: str, local_artist: str | None) -> bool:
    if local_artist is None:
        return False

    normalized_spotify_artist = normalize_filename_text(spotify_artist)
    normalized_local_artist = normalize_filename_text(local_artist)

    return normalized_spotify_artist in normalized_local_artist


def score_title(spotify_title: str, local_file: LocalFile) -> float:
    if local_file.tag_title:
        local_title_source = local_file.tag_title
    else:
        local_title_source = Path(local_file.filename).stem

    normalized_spotify_title = normalize_filename_text(spotify_title)
    normalized_local_title = normalize_filename_text(local_title_source)

    return fuzz.token_sort_ratio(
        normalized_spotify_title,
        normalized_local_title,
    )


def find_best_match(
        track: Track,
        candidates: list[LocalFile],
) -> tuple[LocalFile, float] | None:
    best: tuple[LocalFile, float] | None = None

    for candidate in candidates:
        if not artist_matches(track.artist, candidate.tag_artist):
            continue

        score = score_title(track.title, candidate)

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

    def generate_match_report(self) -> dict:
        with self.database.transaction() as connection:
            tracks_by_id = {
                track.id: track
                for track in self.tracks.get_all(connection)
            }
            matches = self.track_matches.get_all(connection)

        auto_count = 0
        needs_review = []
        unmatched = []

        for match in matches:
            track = tracks_by_id.get(match.track_id)

            if track is None:
                continue

            if match.match_method == "auto":
                auto_count += 1
            elif match.match_method == "needs_review":
                needs_review.append(
                    (track.artist, track.title, match.score)
                )
            else:
                unmatched.append((track.artist, track.title))

        needs_review.sort(key=lambda item: item[2], reverse=True)
        unmatched.sort(key=lambda item: (item[0], item[1]))

        return {
            "auto_count": auto_count,
            "needs_review": needs_review,
            "unmatched": unmatched,
        }
