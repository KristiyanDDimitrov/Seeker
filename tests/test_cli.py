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
from seeker.models.playlist import Playlist
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch
from seeker.spotify.sync_service import (
    PlaylistNotFoundError as SyncPlaylistNotFoundError,
)


class FakeSyncService:
    def __init__(self, playlists: list[Playlist]):
        self._playlists = playlists

    def get_playlist_by_name(self, name: str) -> Playlist:
        for playlist in self._playlists:
            if playlist.name.lower() == name.lower():
                return playlist

        raise SyncPlaylistNotFoundError(
            f"No playlist named '{name}' found locally."
        )

    def list_playlists(self) -> list[Playlist]:
        return self._playlists


class FakeApplication:
    def __init__(
            self,
            track_matcher: TrackMatcher,
            soulseek_configured: bool = False,
            download_service=None,
            sync_service=None,
    ):
        self.track_matcher = track_matcher
        self.soulseek_configured = soulseek_configured
        self.download_service = download_service
        self.sync_service = sync_service


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

            local_file = matcher.local_files.get_by_location_and_relative_path(
                location_id, relative_path, connection
            )

            matcher.track_matches.upsert(
                TrackMatch(
                    track_id=track.id,
                    local_file_id=local_file.id,
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


class FakeDownloadServiceForReview:
    def __init__(self, review_candidates):
        self._review_candidates = review_candidates
        self.get_review_candidates_calls = []

    def get_review_candidates(self, playlist_id=None):
        self.get_review_candidates_calls.append(playlist_id)
        return self._review_candidates


def test_check_omits_soulseek_review_section_when_not_configured(
        tmp_path, capsys,
):
    # `check` must keep working without slskd configured at all (see
    # config.py) — the new section should be silently absent, not
    # attempted and errored.
    matcher = make_matcher(tmp_path)

    cli.run(
        FakeApplication(matcher, soulseek_configured=False),
        ["check"],
    )

    output = capsys.readouterr().out

    assert "SoulSeek candidate found" not in output


def test_check_lists_soulseek_review_candidates_distinct_from_unmatched(
        tmp_path, capsys,
):
    # Real data captured live (2026-08-27) — same candidate used in
    # test_quality.py/test_download_service.py's needs_review tests.
    matcher = make_matcher(tmp_path)

    track = Track(
        id="prdk-track",
        title="ONE MORE NIGHT",
        artist="Prdk",
        album="",
        duration_ms=227_000,
    )
    candidate = SoulseekReviewCandidate(
        track_id="prdk-track",
        username="musicmasterrdjpool",
        filename=(
            "DJPOOLS\\2026\\MONTHS\\FEB\\20\\The Mash Up 20 FEB\\"
            "Prdk - One More Night (Clean) 4A 87.mp3"
        ),
        score=70.37,
        quality_descriptor="mp3 320kbps",
        found_at="2026-08-27T00:00:00+00:00",
    )

    download_service = FakeDownloadServiceForReview([(track, candidate)])

    cli.run(
        FakeApplication(
            matcher,
            soulseek_configured=True,
            download_service=download_service,
        ),
        ["check"],
    )

    output = capsys.readouterr().out

    assert "Needs review (SoulSeek candidate found) (1):" in output
    assert "Prdk - ONE MORE NIGHT" in output
    assert "score: 70.4" in output
    assert "musicmasterrdjpool" in output

    # Distinct section from "Unmatched" — the candidate must not also
    # appear listed there.
    unmatched_section = output.split("Unmatched")[-1]
    assert "musicmasterrdjpool" not in unmatched_section


def test_check_without_playlist_name_labels_scope_as_global(
        tmp_path, capsys,
):
    matcher = make_matcher(tmp_path)
    seed_auto_matched_tracks(matcher, count=2)

    cli.run(FakeApplication(matcher), ["check"])

    output = capsys.readouterr().out

    assert "Across all synced playlists:" in output


def test_check_playlist_scoped_reports_only_that_playlists_tracks(
        tmp_path, capsys,
):
    matcher = make_matcher(tmp_path)

    # 3 tracks total: 2 in PlaylistA, 1 in PlaylistB — scoping to
    # PlaylistA must report only its 2, not the combined 3.
    seed_auto_matched_tracks(matcher, count=3)

    with matcher.database.transaction() as connection:
        connection.execute(
            "INSERT INTO playlists (id, name, track_count) "
            "VALUES (?, ?, ?)",
            ("pA", "PlaylistA", 2),
        )
        connection.execute(
            "INSERT INTO playlists (id, name, track_count) "
            "VALUES (?, ?, ?)",
            ("pB", "PlaylistB", 1),
        )
        connection.executemany(
            "INSERT INTO playlist_tracks (playlist_id, track_id) "
            "VALUES (?, ?)",
            [("pA", "track0"), ("pA", "track1"), ("pB", "track2")],
        )

    sync_service = FakeSyncService([
        Playlist(id="pA", name="PlaylistA", track_count=2),
        Playlist(id="pB", name="PlaylistB", track_count=1),
    ])

    cli.run(
        FakeApplication(matcher, sync_service=sync_service),
        ["check", "PlaylistA"],
    )

    output = capsys.readouterr().out

    assert "For playlist 'PlaylistA':" in output
    assert "Auto-matched: 2" in output


def test_check_playlist_scoped_passes_playlist_id_to_review_candidates(
        tmp_path,
):
    matcher = make_matcher(tmp_path)

    with matcher.database.transaction() as connection:
        connection.execute(
            "INSERT INTO playlists (id, name, track_count) "
            "VALUES (?, ?, ?)",
            ("pA", "PlaylistA", 0),
        )

    sync_service = FakeSyncService(
        [Playlist(id="pA", name="PlaylistA", track_count=0)]
    )
    download_service = FakeDownloadServiceForReview([])

    cli.run(
        FakeApplication(
            matcher,
            soulseek_configured=True,
            download_service=download_service,
            sync_service=sync_service,
        ),
        ["check", "PlaylistA"],
    )

    assert download_service.get_review_candidates_calls == ["pA"]
