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
from seeker.library.matcher import TrackMatcher
from seeker.library.scanner import LibraryUnavailableError
from seeker.library.service import (
    LibraryLocationPathAlreadyRegisteredError,
    LibraryService,
    PlaylistNotFoundError,
)
from seeker.models.local_file import LocalFile
from seeker.models.playlist import Playlist
from seeker.models.track import Track


def make_service(tmp_path) -> LibraryService:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    return LibraryService(
        database,
        LibraryLocationRepository(database),
        LocalFileRepository(database),
    )


def make_service_with_matcher(tmp_path) -> LibraryService:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    track_matcher = TrackMatcher(
        database,
        TrackRepository(database),
        LocalFileRepository(database),
        TrackMatchRepository(database),
    )

    return LibraryService(
        database,
        LibraryLocationRepository(database),
        LocalFileRepository(database),
        track_matcher=track_matcher,
        playlist_repo=PlaylistRepository(database),
    )


def seed_needs_review_track_and_file(service: LibraryService) -> None:
    """A track/local_file pair whose real fuzzy score (85.71, confirmed
    directly via find_best_match before writing this fixture, not
    guessed) lands in the needs_review band (70-89 by default
    thresholds) — "Blinding Lights" vs. a locally-tagged "Blinding
    Lights Edit".
    """
    track_matcher = service.track_matcher
    assert track_matcher is not None

    with service.database.transaction() as connection:
        connection.execute(
            "INSERT INTO library_locations (name, path, added_at) "
            "VALUES (?, ?, ?)",
            ("Main", "/music", "2026-01-01T00:00:00+00:00"),
        )
        location_id = connection.execute(
            "SELECT id FROM library_locations WHERE name = 'Main'"
        ).fetchone()[0]

        track_matcher.tracks.save(
            Track(
                id="track1",
                title="Blinding Lights",
                artist="The Weeknd",
                album="After Hours",
                duration_ms=200_000,
            ),
            connection,
        )
        track_matcher.local_files.upsert(
            LocalFile(
                location_id=location_id,
                relative_path="song.mp3",
                filename="song.mp3",
                format="mp3",
                size_bytes=1_000,
                mtime=1.0,
                scanned_at="2026-01-01T00:00:00+00:00",
                tag_artist="The Weeknd",
                tag_title="Blinding Lights Edit",
                duration_ms=200_000,
            ),
            connection,
        )


def test_add_location_raises_for_nonexistent_path(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(LibraryUnavailableError):
        service.add_location("main", str(tmp_path / "does-not-exist"))


def test_add_location_raises_clear_error_for_duplicate_name(tmp_path):
    service = make_service(tmp_path)

    first_root = tmp_path / "music1"
    second_root = tmp_path / "music2"
    first_root.mkdir()
    second_root.mkdir()

    service.add_location("main", str(first_root))

    with pytest.raises(RuntimeError, match="named 'main' already exists"):
        service.add_location("main", str(second_root))


def test_add_location_raises_clear_error_for_duplicate_path(tmp_path):
    service = make_service(tmp_path)

    library_root = tmp_path / "music"
    library_root.mkdir()

    service.add_location("main", str(library_root))

    with pytest.raises(RuntimeError, match="already registered"):
        service.add_location("other", str(library_root))


def test_add_location_from_path_uses_folder_basename_as_the_name(tmp_path):
    service = make_service(tmp_path)
    library_root = tmp_path / "Music"
    library_root.mkdir()

    location = service.add_location_from_path(str(library_root))

    assert location.name == "Music"
    assert location.path == str(library_root)


def test_add_location_from_path_auto_suffixes_on_name_collision(tmp_path):
    service = make_service(tmp_path)
    first_root = tmp_path / "Music"
    first_root.mkdir()
    (tmp_path / "nested").mkdir()
    second_root = tmp_path / "nested" / "Music"
    second_root.mkdir()

    first = service.add_location_from_path(str(first_root))
    second = service.add_location_from_path(str(second_root))

    assert first.name == "Music"
    assert second.name == "Music (2)"


def test_add_location_from_path_raises_a_clear_error_naming_the_existing_location(
        tmp_path,
):
    service = make_service(tmp_path)
    library_root = tmp_path / "Music"
    library_root.mkdir()

    first = service.add_location_from_path(str(library_root))

    with pytest.raises(LibraryLocationPathAlreadyRegisteredError) as excinfo:
        service.add_location_from_path(str(library_root))

    assert excinfo.value.existing.name == first.name
    assert first.name in str(excinfo.value)


def test_add_location_from_path_raises_for_nonexistent_path(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(LibraryUnavailableError):
        service.add_location_from_path(str(tmp_path / "does-not-exist"))


def test_rename_location_updates_the_name(tmp_path):
    service = make_service(tmp_path)
    library_root = tmp_path / "Music"
    library_root.mkdir()
    location = service.add_location_from_path(str(library_root))

    renamed = service.rename_location(location.id, "My Music")

    assert renamed.name == "My Music"
    with service.database.transaction() as connection:
        assert service.locations.get_by_name(
                "My Music",
                connection,
        ) is not None
        assert service.locations.get_by_name("Music", connection) is None


def test_rename_location_raises_a_clear_error_on_name_collision(tmp_path):
    service = make_service(tmp_path)
    first_root = tmp_path / "Music"
    first_root.mkdir()
    second_root = tmp_path / "Podcasts"
    second_root.mkdir()
    service.add_location_from_path(str(first_root))
    second = service.add_location_from_path(str(second_root))

    with pytest.raises(RuntimeError, match="named 'Music' already exists"):
        service.rename_location(second.id, "Music")


def test_has_scanned_library_false_with_no_local_files(tmp_path):
    service = make_service(tmp_path)

    assert service.has_scanned_library() is False


def test_has_scanned_library_true_after_a_real_scan_finds_files(tmp_path):
    library_root = tmp_path / "music"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"not real audio")

    service = make_service(tmp_path)
    service.add_location("Main", str(library_root))
    service.scan_all()

    assert service.has_scanned_library() is True


def test_scan_all_skips_unreachable_location_without_touching_its_rows(
        tmp_path,
):
    library_root = tmp_path / "music"
    library_root.mkdir()

    service = make_service(tmp_path)
    service.add_location("main", str(library_root))

    with service.database.transaction() as connection:
        location = service.locations.get_by_name("main", connection)

        service.local_files.upsert(
            LocalFile(
                location_id=location.id,
                relative_path="song.mp3",
                filename="song.mp3",
                format="mp3",
                size_bytes=123,
                mtime=111.0,
                scanned_at="2026-01-01T00:00:00+00:00",
            ),
            connection,
        )

    # Simulate the drive going offline after the location was registered
    # and an earlier scan had already recorded a row for it.
    library_root.rmdir()

    service.scan_all()

    with service.database.transaction() as connection:
        remaining = service.local_files.get_all(connection)

    assert len(remaining) == 1
    assert remaining[0].relative_path == "song.mp3"


def test_scan_all_returns_aggregated_totals_across_locations(tmp_path):
    root_a = tmp_path / "music-a"
    root_b = tmp_path / "music-b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "one.mp3").write_bytes(b"not real audio")
    (root_b / "two.mp3").write_bytes(b"not real audio")
    (root_b / "three.mp3").write_bytes(b"not real audio")

    service = make_service(tmp_path)
    service.add_location("a", str(root_a))
    service.add_location("b", str(root_b))

    totals = service.scan_all()

    assert totals == {"added": 3, "updated": 0, "removed": 0, "unchanged": 0}

    # A second scan with nothing changed on disk reports everything as
    # unchanged, still aggregated across both locations.
    totals_again = service.scan_all()
    assert totals_again == {
        "added": 0, "updated": 0, "removed": 0, "unchanged": 3,
    }


def test_scan_and_match_requires_a_track_matcher(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(RuntimeError, match="track_matcher"):
        service.scan_and_match()


def test_scan_and_match_chains_scan_then_match_in_one_call(tmp_path):
    library_root = tmp_path / "music"
    library_root.mkdir()
    (library_root / "3AMDISCO - Get Back.wav").write_bytes(b"not real audio")

    service = make_service_with_matcher(tmp_path)
    service.add_location("main", str(library_root))

    with service.database.transaction() as connection:
        service.track_matcher.tracks.save(
            Track(
                id="track1",
                title="Get Back",
                artist="3amdisco",
                album="Get Back EP",
                duration_ms=200_000,
            ),
            connection,
        )

    # Before scan_and_match, nothing has been scanned or matched at all.
    assert service.has_scanned_library() is False

    result = service.scan_and_match()

    # scan_all()'s keys and match_all()'s keys, combined in one dict —
    # this is the real regression this chaining fixes: a plain scan_all()
    # alone would leave "auto"/"needs_review"/"unmatched" entirely absent
    # (and the track unmatched) until a separate match_all() call.
    assert result["added"] == 1
    assert result["auto"] == 1
    assert result["needs_review"] == 0
    assert result["unmatched"] == 0

    with service.database.transaction() as connection:
        stored = service.track_matcher.track_matches.get_by_track_id(
            "track1", connection
        )

    assert stored is not None
    assert stored.match_method == "auto"


# --- Roadmap item 56 Phase 2: local-file needs-review flow --------------

def test_get_needs_review_matches_requires_a_track_matcher(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(RuntimeError, match="track_matcher"):
        service.get_needs_review_matches()


def test_get_needs_review_matches_returns_real_pairing_context(tmp_path):
    service = make_service_with_matcher(tmp_path)
    seed_needs_review_track_and_file(service)

    counts = service.track_matcher.match_all()
    assert counts["needs_review"] == 1

    results = service.get_needs_review_matches()

    assert len(results) == 1
    result = results[0]
    assert result.track_id == "track1"
    assert result.track_artist == "The Weeknd"
    assert result.track_title == "Blinding Lights"
    assert result.location_name == "Main"
    assert result.local_file_path == "song.mp3"
    assert result.tag_artist == "The Weeknd"
    assert result.tag_title == "Blinding Lights Edit"
    assert 70.0 <= result.score < 90.0


def test_get_needs_review_matches_scoped_to_playlist_excludes_others(
        tmp_path,
):
    service = make_service_with_matcher(tmp_path)
    seed_needs_review_track_and_file(service)
    service.track_matcher.match_all()

    with service.database.transaction() as connection:
        service.playlists.save(
            Playlist(id="p1", name="My Playlist", track_count=1),
            connection,
        )
        service.track_matcher.tracks.save_playlist_track(
            "p1", "track1", connection
        )
        service.playlists.save(
            Playlist(id="p2", name="Other Playlist", track_count=0),
            connection,
        )

    assert len(service.get_needs_review_matches("My Playlist")) == 1
    assert service.get_needs_review_matches("Other Playlist") == []


def test_get_needs_review_matches_unknown_playlist_raises(tmp_path):
    service = make_service_with_matcher(tmp_path)

    with pytest.raises(PlaylistNotFoundError):
        service.get_needs_review_matches("Does Not Exist")


def test_confirm_match_stamps_confirmed_at_without_a_100_score_sentinel(
        tmp_path,
):
    service = make_service_with_matcher(tmp_path)
    seed_needs_review_track_and_file(service)
    service.track_matcher.match_all()

    with service.database.transaction() as connection:
        before = service.track_matcher.track_matches.get_by_track_id(
            "track1", connection
        )

    service.confirm_match("track1")

    with service.database.transaction() as connection:
        after = service.track_matcher.track_matches.get_by_track_id(
            "track1", connection
        )

    assert after.match_method == "auto"
    assert after.confirmed_at is not None
    # The real computed score stays visible — never overwritten with a
    # 100.0 sentinel (item 45's precedent).
    assert after.score == before.score
    assert after.local_file_id == before.local_file_id

    # And it now genuinely survives a re-match, end to end.
    counts = service.track_matcher.match_all()
    assert counts == {"auto": 1, "needs_review": 0, "unmatched": 0}


def test_reject_match_deletes_the_row_no_blacklist(tmp_path):
    service = make_service_with_matcher(tmp_path)
    seed_needs_review_track_and_file(service)
    service.track_matcher.match_all()

    service.reject_match("track1")

    with service.database.transaction() as connection:
        stored = service.track_matcher.track_matches.get_by_track_id(
            "track1", connection
        )

    assert stored is None

    # No blacklist — the same candidate can resurface on a later match
    # run (item 26's deliberate non-feature, mirrored here).
    counts = service.track_matcher.match_all()
    assert counts["needs_review"] == 1
