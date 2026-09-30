"""A track match never outlives the file it points at.

`track_matches.local_file_id` is `ON DELETE SET NULL`, which on its own
leaves `match_method`/`score`/`confirmed_at` behind on a row that no
longer points anywhere ("limbo"): shown missing on the Dashboard, never
downloaded, never re-matched (HISTORY §139).
"""
import pytest

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
from seeker.errors import LibraryLocationNotFoundError
from seeker.library.matcher import TrackMatcher
from seeker.library.service import (
    LibraryService,
)
from seeker.models.library_result import MatchResult
from seeker.models.location_removal import LocationRemovalSummary
from seeker.models.playlist import Playlist
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch

MATCHING_NAME = "3AMDISCO - Get Back.wav"


def make_scenario(tmp_path) -> tuple[LibraryService, TrackMatcher]:
    """Location `Lib` holding one file that auto-matches track `t1`,
    which is in playlist `p1`. Nothing scanned yet.
    """
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    library_root = tmp_path / "lib"
    (library_root / "A").mkdir(parents=True)
    (library_root / "A" / MATCHING_NAME).write_bytes(b"not real audio")

    matcher = TrackMatcher(
        database,
        TrackRepository(database),
        LocalFileRepository(database),
        TrackMatchRepository(database),
    )
    service = LibraryService(
        database,
        LibraryLocationRepository(database),
        LocalFileRepository(database),
        track_matcher=matcher,
        playlist_repo=PlaylistRepository(database),
    )
    service.add_location("Lib", str(library_root))

    with database.transaction() as connection:
        PlaylistRepository(database).save(
            Playlist(id="p1", name="P", track_count=1), connection,
        )
        matcher.tracks.save(
            Track(
                id="t1",
                title="Get Back",
                artist="3amdisco",
                album="Get Back EP",
                duration_ms=200_000,
            ),
            connection,
        )
        matcher.tracks.replace_playlist_tracks("p1", ["t1"], connection)

    return service, matcher


def match_row(matcher: TrackMatcher) -> tuple[object, ...] | None:
    with matcher.database.transaction() as connection:
        match = matcher.track_matches.get_by_track_id("t1", connection)

    if match is None:
        return None

    return (
        match.local_file_id,
        match.match_method,
        match.score,
        match.confirmed_at,
    )


def unmatched_ids(matcher: TrackMatcher) -> list[str]:
    with matcher.database.transaction() as connection:
        tracks = matcher.tracks.get_unmatched_for_playlist("p1", connection)

    return [track.id for track in tracks]


def local_file_ids(matcher: TrackMatcher) -> list[int | None]:
    with matcher.database.transaction() as connection:
        return [f.id for f in matcher.local_files.get_all(connection)]


# --- §4.2: deleting a local_files row releases its matches ------------

def test_a_confirmed_match_whose_file_moved_away_becomes_unmatched(
        tmp_path,
):
    # Probe A.3: confirm a match, rename the file in Finder, rescan.
    service, matcher = make_scenario(tmp_path)
    service.scan_and_match()
    service.confirm_match("t1")

    (tmp_path / "lib" / "A" / MATCHING_NAME).rename(
        tmp_path / "lib" / "A" / "Moved in Finder.wav",
    )
    result = service.scan_and_match()
    row = match_row(matcher)

    # The rescan's own below-threshold score is kept, as for any
    # unmatched track.
    assert row is not None
    assert (row[0], row[1], row[3]) == (None, None, None)
    assert result.match.auto == 0
    assert result.match.unmatched == 1
    assert unmatched_ids(matcher) == ["t1"]


def test_a_confirmed_match_whose_file_moved_is_relinked_at_its_new_path(
        tmp_path,
):
    service, matcher = make_scenario(tmp_path)
    service.scan_and_match()
    service.confirm_match("t1")

    (tmp_path / "lib" / "B").mkdir()
    (tmp_path / "lib" / "A" / MATCHING_NAME).rename(
        tmp_path / "lib" / "B" / MATCHING_NAME,
    )
    service.scan_and_match()

    [new_file_id] = local_file_ids(matcher)
    row = match_row(matcher)

    assert row is not None
    assert row[:2] == (new_file_id, "auto")
    assert unmatched_ids(matcher) == []


def test_delete_by_id_resets_every_match_pointing_at_the_file(tmp_path):
    service, matcher = make_scenario(tmp_path)
    service.scan_and_match()
    service.confirm_match("t1")
    [file_id] = local_file_ids(matcher)
    assert file_id is not None

    with matcher.database.transaction() as connection:
        matcher.local_files.delete_by_id(file_id, connection)

    assert match_row(matcher) == (None, None, None, None)
    assert unmatched_ids(matcher) == ["t1"]


def test_delete_by_id_leaves_matches_to_other_files_alone(tmp_path):
    service, matcher = make_scenario(tmp_path)
    (tmp_path / "lib" / "other.wav").write_bytes(b"x")
    service.scan_and_match()
    before = match_row(matcher)

    with matcher.database.transaction() as connection:
        other = matcher.local_files.get_by_location_and_relative_path(
            1, "other.wav", connection,
        )
        assert other is not None and other.id is not None
        matcher.local_files.delete_by_id(other.id, connection)

    assert before is not None and before[1] == "auto"
    assert match_row(matcher) == before


# --- §4.3: a limbo row already in the database is tolerated ------------

def seed_limbo_row(matcher: TrackMatcher) -> None:
    """The exact shape the old cascade left behind: no file, but a
    method, a score and a human confirmation still set.
    """
    with matcher.database.transaction() as connection:
        matcher.track_matches.upsert(
            TrackMatch(
                track_id="t1",
                matched_at="2026-09-01T00:00:00+00:00",
                local_file_id=None,
                match_method="auto",
                score=95.0,
                confirmed_at="2026-09-01T00:00:00+00:00",
            ),
            connection,
        )


def test_a_limbo_row_counts_as_unmatched_for_download(tmp_path):
    _, matcher = make_scenario(tmp_path)
    seed_limbo_row(matcher)

    assert unmatched_ids(matcher) == ["t1"]


def test_match_all_re_evaluates_a_confirmed_row_that_lost_its_file(
        tmp_path,
):
    service, matcher = make_scenario(tmp_path)
    service.scan_all()
    seed_limbo_row(matcher)

    counts = matcher.match_all()

    [file_id] = local_file_ids(matcher)
    row = match_row(matcher)
    assert counts == MatchResult(auto=1, needs_review=0, unmatched=0)
    assert row is not None
    assert (row[0], row[1], row[3]) == (file_id, "auto", None)


def test_match_all_keeps_a_confirmed_row_whose_file_is_still_there(
        tmp_path,
):
    service, matcher = make_scenario(tmp_path)
    service.scan_and_match()
    service.confirm_match("t1")
    before = match_row(matcher)

    matcher.match_all()

    assert before is not None and before[3] is not None
    assert match_row(matcher) == before


def test_a_limbo_row_is_not_offered_as_auto_matched(tmp_path):
    _, matcher = make_scenario(tmp_path)
    seed_limbo_row(matcher)

    with matcher.database.transaction() as connection:
        auto = matcher.tracks.get_auto_matched_for_playlist("p1", connection)

    assert auto == []


# --- §4.4: removing a location -----------------------------------------

def set_destination(matcher: TrackMatcher, playlist_id: str) -> None:
    playlists = PlaylistRepository(matcher.database)

    with matcher.database.transaction() as connection:
        if playlists.get_by_id(playlist_id, connection) is None:
            playlists.save(
                Playlist(id=playlist_id, name=playlist_id, track_count=0),
                connection,
            )
        playlists.set_destination(playlist_id, 1, "P", connection)


def test_removing_a_location_a_playlist_downloads_into_succeeds(tmp_path):
    # Probe A.4: this raised IntegrityError (FOREIGN KEY constraint).
    service, matcher = make_scenario(tmp_path)
    set_destination(matcher, "p1")

    service.remove_location("Lib")

    with matcher.database.transaction() as connection:
        playlist = PlaylistRepository(matcher.database).get_by_id(
            "p1", connection,
        )

    assert service.list_locations() == []
    assert playlist is not None
    assert (playlist.download_location_id, playlist.download_subfolder) == (
        None, None,
    )


def test_removing_a_location_unmatches_its_files_and_reports_counts(
        tmp_path,
):
    service, matcher = make_scenario(tmp_path)
    (tmp_path / "lib" / "other.wav").write_bytes(b"x")
    service.scan_and_match()
    service.confirm_match("t1")
    set_destination(matcher, "p1")
    set_destination(matcher, "p2")

    summary = service.remove_location("Lib", default_location_id=1)

    assert summary == LocationRemovalSummary(
        location_name="Lib",
        files_forgotten=2,
        matches_cleared=1,
        confirmed_matches_cleared=1,
        playlists_affected=2,
        was_default=True,
    )
    assert local_file_ids(matcher) == []
    assert match_row(matcher) == (None, None, None, None)
    assert unmatched_ids(matcher) == ["t1"]


def test_removing_a_location_that_is_not_the_default_says_so(tmp_path):
    service, _ = make_scenario(tmp_path)

    summary = service.remove_location("Lib", default_location_id=99)

    assert summary.was_default is False


def test_removing_an_unknown_location_raises(tmp_path):
    service, _ = make_scenario(tmp_path)

    with pytest.raises(LibraryLocationNotFoundError, match="Nope"):
        service.remove_location("Nope")

    assert len(service.list_locations()) == 1


# --- §4.5: preview before removal ------------------------------------

def test_preview_reports_the_removal_counts_and_changes_nothing(tmp_path):
    service, matcher = make_scenario(tmp_path)
    service.scan_and_match()
    service.confirm_match("t1")
    set_destination(matcher, "p1")
    before = match_row(matcher)

    preview = service.preview_remove_location("Lib", default_location_id=1)

    assert preview == LocationRemovalSummary(
        location_name="Lib",
        files_forgotten=1,
        matches_cleared=1,
        confirmed_matches_cleared=1,
        playlists_affected=1,
        was_default=True,
    )
    assert len(service.list_locations()) == 1
    assert match_row(matcher) == before
    assert service.remove_location("Lib", default_location_id=1) == preview


def test_preview_of_an_unknown_location_raises(tmp_path):
    service, _ = make_scenario(tmp_path)

    with pytest.raises(LibraryLocationNotFoundError):
        service.preview_remove_location("Nope")
