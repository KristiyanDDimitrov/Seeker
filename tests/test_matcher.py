from seeker.database.connection import Database
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.library.matcher import TrackMatcher, find_best_match
from seeker.models.local_file import LocalFile
from seeker.models.track import Track


def make_track(**overrides) -> Track:
    defaults = dict(
        id="track1",
        title="Blinding Lights",
        artist="The Weeknd",
        album="After Hours",
        duration_ms=200_000,
    )
    defaults.update(overrides)
    return Track(**defaults)


def make_local_file(**overrides) -> LocalFile:
    defaults = dict(
        location_id=1,
        relative_path="song.mp3",
        filename="song.mp3",
        format="mp3",
        size_bytes=1_000,
        mtime=1.0,
        scanned_at="2026-01-01T00:00:00+00:00",
        tag_artist="The Weeknd",
        tag_title="Blinding Lights",
        duration_ms=200_000,
    )
    defaults.update(overrides)
    return LocalFile(**defaults)


def make_matcher(tmp_path) -> TrackMatcher:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    return TrackMatcher(
        database,
        TrackRepository(database),
        LocalFileRepository(database),
        TrackMatchRepository(database),
    )


def seed(matcher, track: Track, local_file: LocalFile) -> None:
    with matcher.database.transaction() as connection:
        matcher.tracks.save(track, connection)

        location_row = connection.execute(
            "SELECT COUNT(*) FROM library_locations"
        ).fetchone()[0]

        if location_row == 0:
            connection.execute(
                "INSERT INTO library_locations (name, path, added_at) "
                "VALUES (?, ?, ?)",
                ("main", "/music", "2026-01-01T00:00:00+00:00"),
            )

        matcher.local_files.upsert(local_file, connection)


def test_close_match_scores_at_least_90_and_lands_in_auto(tmp_path):
    matcher = make_matcher(tmp_path)

    track = make_track()
    local_file = make_local_file()

    seed(matcher, track, local_file)

    counts = matcher.match_all()

    assert counts == {"auto": 1, "needs_review": 0, "unmatched": 0}

    with matcher.database.transaction() as connection:
        stored = matcher.track_matches.get_by_track_id(track.id, connection)

    assert stored.match_method == "auto"
    assert stored.score >= 90


def test_large_duration_mismatch_is_not_auto_matched(tmp_path):
    matcher = make_matcher(tmp_path)

    track = make_track(duration_ms=200_000)

    # Same artist, same title text (extended mix running ~5 minutes
    # longer than the radio edit Spotify track) — falls outside the
    # ±5s duration tolerance window and must not be pre-filtered in.
    local_file = make_local_file(duration_ms=200_000 + 5 * 60_000)

    seed(matcher, track, local_file)

    counts = matcher.match_all()

    assert counts["auto"] == 0
    assert counts["needs_review"] + counts["unmatched"] == 1


def test_wrong_artist_is_excluded_from_candidacy_despite_title_match():
    track = make_track(artist="The Weeknd", title="Blinding Lights")

    candidate = make_local_file(
        tag_artist="Some Other Artist",
        tag_title="Blinding Lights",
    )

    assert find_best_match(track, [candidate]) is None


def test_untagged_file_matches_via_filename_alone():
    # Real case: a WAV with no tags at all (mutagen extracted nothing),
    # matched purely off its "Artist - Title"-style filename. This used
    # to be a hard rejection — artist_matches() gated on tag_artist
    # specifically with no filename fallback, so a null tag_artist
    # rejected the file outright regardless of filename quality.
    track = make_track(artist="3amdisco", title="Get Back", duration_ms=301_500)

    candidate = make_local_file(
        filename="3AMDISCO - Get Back.wav",
        format="wav",
        tag_artist=None,
        tag_title=None,
        duration_ms=301_500,
    )

    match = find_best_match(track, [candidate])

    assert match is not None
    matched_candidate, score = match
    assert matched_candidate is candidate
    assert score >= 90
