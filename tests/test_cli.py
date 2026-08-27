from seeker import cli
from seeker.database.connection import Database
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.library.matcher import TrackMatcher
from seeker.models.local_file import LocalFile
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch


class FakeApplication:
    def __init__(self, track_matcher: TrackMatcher):
        self.track_matcher = track_matcher


def make_matcher(tmp_path) -> TrackMatcher:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    return TrackMatcher(
        database,
        TrackRepository(database),
        LocalFileRepository(database),
        TrackMatchRepository(database),
    )


def seed_auto_matched_tracks(matcher: TrackMatcher, count: int) -> None:
    with matcher.database.transaction() as connection:
        connection.execute(
            "INSERT INTO library_locations (name, path, added_at) "
            "VALUES (?, ?, ?)",
            ("main", "/music", "2026-01-01T00:00:00+00:00"),
        )
        location_id = connection.execute(
            "SELECT id FROM library_locations WHERE name = 'main'"
        ).fetchone()[0]

        for i in range(count):
            track = Track(
                id=f"track{i}",
                title=f"Title {i}",
                artist=f"Artist {i}",
                album="Album",
                duration_ms=200_000,
            )
            matcher.tracks.save(track, connection)

            relative_path = f"song{i}.mp3"

            matcher.local_files.upsert(
                LocalFile(
                    location_id=location_id,
                    relative_path=relative_path,
                    filename=relative_path,
                    format="mp3",
                    size_bytes=1_000,
                    mtime=1.0,
                    scanned_at="2026-01-01T00:00:00+00:00",
                    tag_artist=f"Artist {i}",
                    tag_title=f"Title {i}",
                    duration_ms=200_000,
                ),
                connection,
            )

            local_file_id = connection.execute(
                "SELECT id FROM local_files "
                "WHERE location_id = ? AND relative_path = ?",
                (location_id, relative_path),
            ).fetchone()[0]

            matcher.track_matches.upsert(
                TrackMatch(
                    track_id=track.id,
                    local_file_id=local_file_id,
                    match_method="auto",
                    score=95.0,
                    matched_at="2026-01-01T00:00:00+00:00",
                ),
                connection,
            )


def test_check_default_output_has_no_per_track_auto_matched_lines(
        tmp_path, capsys,
):
    matcher = make_matcher(tmp_path)
    seed_auto_matched_tracks(matcher, count=3)

    cli.run(FakeApplication(matcher), ["check"])

    output = capsys.readouterr().out

    assert "Auto-matched: 3" in output
    # The verbose per-track line format is
    # "{artist} - {title} (score: ...) -> {filename}" — its "->" arrow
    # never appears anywhere else in default output.
    assert "->" not in output


def test_check_verbose_lists_each_auto_matched_track(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    seed_auto_matched_tracks(matcher, count=2)

    cli.run(FakeApplication(matcher), ["check", "--verbose"])

    output = capsys.readouterr().out
    auto_lines = [line for line in output.splitlines() if "->" in line]

    assert len(auto_lines) == 2

    for line in auto_lines:
        assert "score:" in line
        assert ".mp3" in line
