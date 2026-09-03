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
from seeker.models.needs_review_match import NeedsReviewMatch
from seeker.models.playlist import Playlist
from seeker.models.soulseek_file import SoulseekFile
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch
from seeker.soulseek.download_service import NoDestinationConfiguredError
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
            duplicate_service=None,
            history_service=None,
            library_service=None,
            sharing_service=None,
    ):
        self.track_matcher = track_matcher
        self.soulseek_configured = soulseek_configured
        self.download_service = download_service
        self.sync_service = sync_service
        self.duplicate_service = duplicate_service
        self.history_service = history_service
        self.library_service = library_service
        self.sharing_service = sharing_service


class FakeLibraryServiceForCli:
    def __init__(self, needs_review_matches: list | None = None):
        self.scan_all_calls = 0
        self.scan_and_match_calls = 0
        self._needs_review_matches = needs_review_matches or []
        self.get_needs_review_matches_calls: list[str | None] = []
        self.confirm_match_calls: list[str] = []
        self.reject_match_calls: list[str] = []

    def scan_all(self) -> dict:
        self.scan_all_calls += 1
        return {"added": 0, "updated": 0, "removed": 0, "unchanged": 0}

    def scan_and_match(self) -> dict:
        self.scan_and_match_calls += 1
        return {
            "added": 1, "updated": 0, "removed": 0, "unchanged": 0,
            "auto": 1, "needs_review": 0, "unmatched": 0,
        }

    def get_needs_review_matches(
            self, playlist_name: str | None = None,
    ) -> list:
        self.get_needs_review_matches_calls.append(playlist_name)
        return self._needs_review_matches

    def confirm_match(self, track_id: str) -> None:
        self.confirm_match_calls.append(track_id)

    def reject_match(self, track_id: str) -> None:
        self.reject_match_calls.append(track_id)


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


class FakeDownloadServiceForBulkReview:
    # Roadmap item R3.1/R3.4 — CLI parity for "Replace all."
    def __init__(self, pending_upgrades, batch_result=None):
        self._pending_upgrades = pending_upgrades
        self._batch_result = batch_result
        self.apply_upgrade_decisions_batch_calls: list[
            tuple[list[int], bool]
        ] = []

    def get_pending_upgrade_reviews(self):
        return self._pending_upgrades

    def apply_upgrade_decisions_batch(self, request_ids, delete_old):
        self.apply_upgrade_decisions_batch_calls.append(
            (request_ids, delete_old)
        )
        return self._batch_result


class FakeDownloadServiceForSearch:
    def __init__(self, files=None, download_result=None, download_error=None):
        self._files = files or []
        self._download_result = download_result or {
            "requested": False, "settled": False,
            "reason": "no_candidate_found",
        }
        self._download_error = download_error
        self.search_manual_calls: list[tuple[str, str]] = []
        self.download_manual_calls: list[tuple[str, str]] = []

    def search_manual(self, artist: str, title: str):
        self.search_manual_calls.append((artist, title))
        return self._files

    def download_manual(self, artist: str, title: str):
        self.download_manual_calls.append((artist, title))
        if self._download_error is not None:
            raise self._download_error
        return self._download_result


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


class FakeDuplicateService:
    def __init__(self, fingerprint_result=None, groups=None, cleanup_totals=(0, 0)):
        self._fingerprint_result = fingerprint_result or {
            "computed": 0, "skipped_already_computed": 0, "failed": 0,
            "details": [],
        }
        self._groups = groups or []
        self._cleanup_totals = cleanup_totals
        self.compute_fingerprints_calls = []
        self.find_duplicate_groups_calls = []

    def compute_fingerprints(
            self, location_name, force=False, folders=None, progress=None,
    ):
        self.compute_fingerprints_calls.append((location_name, force, folders))
        return self._fingerprint_result

    def find_duplicate_groups(self, location_name, folders=None, progress=None):
        self.find_duplicate_groups_calls.append((location_name, folders))
        return self._groups

    def get_cleanup_totals(self):
        return self._cleanup_totals


def test_library_fingerprint_calls_compute_fingerprints_and_reports_counts(
        tmp_path, capsys,
):
    matcher = make_matcher(tmp_path)
    duplicate_service = FakeDuplicateService(
        fingerprint_result={
            "computed": 2, "skipped_already_computed": 1, "failed": 0,
            "details": [],
        },
    )

    cli.run(
        FakeApplication(matcher, duplicate_service=duplicate_service),
        ["library", "fingerprint", "Main"],
    )

    assert duplicate_service.compute_fingerprints_calls == [("Main", False, None)]
    output = capsys.readouterr().out
    assert "Fingerprinted: 2" in output
    assert "Skipped (already computed): 1" in output


def test_library_fingerprint_force_flag_is_passed_through(tmp_path):
    matcher = make_matcher(tmp_path)
    duplicate_service = FakeDuplicateService()

    cli.run(
        FakeApplication(matcher, duplicate_service=duplicate_service),
        ["library", "fingerprint", "Main", "--force"],
    )

    assert duplicate_service.compute_fingerprints_calls == [("Main", True, None)]


def test_library_fingerprint_reports_failure_details(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    duplicate_service = FakeDuplicateService(
        fingerprint_result={
            "computed": 0, "skipped_already_computed": 0, "failed": 1,
            "details": [
                {
                    "local_file_id": "1",
                    "reason": "failed",
                    "message": "a.mp3: real decode error",
                },
            ],
        },
    )

    cli.run(
        FakeApplication(matcher, duplicate_service=duplicate_service),
        ["library", "fingerprint", "Main"],
    )

    output = capsys.readouterr().out
    assert "real decode error" in output


def test_library_duplicates_reports_no_duplicates(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    duplicate_service = FakeDuplicateService(groups=[])

    cli.run(
        FakeApplication(matcher, duplicate_service=duplicate_service),
        ["library", "duplicates", "Main"],
    )

    assert duplicate_service.find_duplicate_groups_calls == [("Main", None)]
    output = capsys.readouterr().out
    assert "No duplicates found" in output


def test_library_duplicates_shows_reclaimed_space_milestone(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    duplicate_service = FakeDuplicateService(
        groups=[], cleanup_totals=(312, 15_254_112_614),
    )

    cli.run(
        FakeApplication(matcher, duplicate_service=duplicate_service),
        ["library", "duplicates", "Main"],
    )

    output = capsys.readouterr().out
    assert "reclaimed" in output
    assert "312 files" in output


def test_library_duplicates_hides_milestone_when_nothing_reclaimed_yet(
        tmp_path, capsys,
):
    matcher = make_matcher(tmp_path)
    duplicate_service = FakeDuplicateService(groups=[], cleanup_totals=(0, 0))

    cli.run(
        FakeApplication(matcher, duplicate_service=duplicate_service),
        ["library", "duplicates", "Main"],
    )

    output = capsys.readouterr().out
    assert "reclaimed" not in output


def test_library_duplicates_reports_real_group_shape(tmp_path, capsys):
    from seeker.library.duplicate_service import DuplicateFile, DuplicateGroup
    from seeker.soulseek.quality import LocalFileQuality

    matcher = make_matcher(tmp_path)
    group = DuplicateGroup(
        files=[
            DuplicateFile(
                local_file=LocalFile(
                    location_id=1, relative_path="a.flac", filename="a.flac",
                    format="flac", size_bytes=1, mtime=0.0,
                    scanned_at="2026-01-01T00:00:00+00:00",
                ),
                quality=LocalFileQuality(
                    tier=2, bitrate_kbps=1000, bit_depth=16,
                    sample_rate=44_100, clipping_ratio=0.0,
                    integrated_loudness_lufs=None,
                ),
            ),
            DuplicateFile(
                local_file=LocalFile(
                    location_id=1, relative_path="a.mp3", filename="a.mp3",
                    format="mp3", size_bytes=1, mtime=0.0,
                    scanned_at="2026-01-01T00:00:00+00:00",
                ),
                quality=LocalFileQuality(
                    tier=1, bitrate_kbps=320, bit_depth=None,
                    sample_rate=44_100, clipping_ratio=0.0,
                    integrated_loudness_lufs=None,
                ),
            ),
        ],
        similarity=0.987,
    )
    duplicate_service = FakeDuplicateService(groups=[group])

    cli.run(
        FakeApplication(matcher, duplicate_service=duplicate_service),
        ["library", "duplicates", "Main"],
    )

    output = capsys.readouterr().out
    assert "Found 1 duplicate group" in output
    assert "98.7%" in output
    assert "a.flac" in output
    assert "a.mp3" in output


def test_library_fingerprint_unknown_location_exits_nonzero(tmp_path, capsys):
    from seeker.library.duplicate_service import LibraryLocationNotFoundError

    matcher = make_matcher(tmp_path)

    class RaisingDuplicateService:
        def compute_fingerprints(
                self, location_name, force=False, folders=None, progress=None,
        ):
            raise LibraryLocationNotFoundError(
                f"No library location named '{location_name}' is registered."
            )

    try:
        cli.run(
            FakeApplication(
                matcher, duplicate_service=RaisingDuplicateService(),
            ),
            ["library", "fingerprint", "Nonexistent"],
        )
        assert False, "expected SystemExit"
    except SystemExit as exit_info:
        assert exit_info.code == 1

    output = capsys.readouterr().out
    assert "Nonexistent" in output


class FakeHistoryServiceForCli:
    def __init__(self, events):
        self._events = events
        self.get_recent_events_calls: list[int] = []

    def get_recent_events(self, limit):
        self.get_recent_events_calls.append(limit)
        return self._events


def test_history_prints_each_event(tmp_path, capsys):
    from seeker.models.history_event import DOWNLOADED, TAGGED, HistoryEvent

    matcher = make_matcher(tmp_path)
    events = [
        HistoryEvent(
            occurred_at="2026-01-02T00:00:00+00:00",
            event_type=DOWNLOADED,
            track_artist="ZENEA",
            track_title="INFINITE",
            playlist_name="240KM/H",
            detail="FLAC from peer1",
        ),
        HistoryEvent(
            occurred_at="2026-01-01T00:00:00+00:00",
            event_type=TAGGED,
            track_artist="Kamäleon",
            track_title="Quadrat",
            playlist_name="Test",
            detail="Tagged with Spotify metadata",
        ),
    ]
    history_service = FakeHistoryServiceForCli(events)

    cli.run(
        FakeApplication(matcher, history_service=history_service),
        ["history"],
    )

    output = capsys.readouterr().out
    assert "ZENEA - INFINITE" in output
    assert "Downloaded" in output
    assert "Kamäleon - Quadrat" in output
    assert "Tagged" in output
    assert history_service.get_recent_events_calls == [50]


def test_history_default_limit_used_when_flag_omitted(tmp_path, capsys):
    from seeker.history_service import DEFAULT_LIMIT

    matcher = make_matcher(tmp_path)
    history_service = FakeHistoryServiceForCli([])

    cli.run(
        FakeApplication(matcher, history_service=history_service),
        ["history"],
    )

    assert history_service.get_recent_events_calls == [DEFAULT_LIMIT]


def test_history_limit_flag_overrides_default(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    history_service = FakeHistoryServiceForCli([])

    cli.run(
        FakeApplication(matcher, history_service=history_service),
        ["history", "--limit", "5"],
    )

    assert history_service.get_recent_events_calls == [5]


def test_history_empty_prints_a_clear_message(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    history_service = FakeHistoryServiceForCli([])

    cli.run(
        FakeApplication(matcher, history_service=history_service),
        ["history"],
    )

    output = capsys.readouterr().out
    assert "No downloaded or tagged tracks yet." in output


# --- Roadmap item 56: `library scan --match` ----------------------------

def test_library_scan_without_match_flag_calls_scan_all_only(tmp_path):
    matcher = make_matcher(tmp_path)
    library_service = FakeLibraryServiceForCli()

    cli.run(
        FakeApplication(matcher, library_service=library_service),
        ["library", "scan"],
    )

    assert library_service.scan_all_calls == 1
    assert library_service.scan_and_match_calls == 0


def test_library_scan_with_match_flag_calls_scan_and_match(tmp_path):
    matcher = make_matcher(tmp_path)
    library_service = FakeLibraryServiceForCli()

    cli.run(
        FakeApplication(matcher, library_service=library_service),
        ["library", "scan", "--match"],
    )

    assert library_service.scan_and_match_calls == 1
    assert library_service.scan_all_calls == 0


# --- Roadmap item 56 Phase 2: `seeker review` ----------------------------

def test_review_lists_needs_review_matches_across_all_playlists(
        tmp_path, capsys,
):
    matcher = make_matcher(tmp_path)
    match = NeedsReviewMatch(
        track_id="track1",
        track_artist="The Weeknd",
        track_title="Blinding Lights",
        local_file_id=1,
        local_file_path="song.mp3",
        location_name="Main",
        score=85.71,
        tag_artist="The Weeknd",
        tag_title="Blinding Lights Edit",
    )
    library_service = FakeLibraryServiceForCli(needs_review_matches=[match])

    cli.run(
        FakeApplication(matcher, library_service=library_service),
        ["review"],
    )

    assert library_service.get_needs_review_matches_calls == [None]
    output = capsys.readouterr().out
    assert "[track1]" in output
    assert "The Weeknd - Blinding Lights" in output
    assert "score: 85.7" in output
    assert "song.mp3" in output


def test_review_empty_prints_a_clear_message(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    library_service = FakeLibraryServiceForCli(needs_review_matches=[])

    cli.run(
        FakeApplication(matcher, library_service=library_service),
        ["review"],
    )

    output = capsys.readouterr().out
    assert "None." in output


def test_review_scoped_to_playlist_resolves_the_name_first(
        tmp_path, capsys,
):
    matcher = make_matcher(tmp_path)
    library_service = FakeLibraryServiceForCli()
    sync_service = FakeSyncService(
        [Playlist(id="p1", name="My Playlist", track_count=1)]
    )

    cli.run(
        FakeApplication(
            matcher,
            library_service=library_service,
            sync_service=sync_service,
        ),
        ["review", "My Playlist"],
    )

    assert library_service.get_needs_review_matches_calls == ["My Playlist"]


def test_review_confirm_calls_confirm_match(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    library_service = FakeLibraryServiceForCli()

    cli.run(
        FakeApplication(matcher, library_service=library_service),
        ["review", "--confirm", "track1"],
    )

    assert library_service.confirm_match_calls == ["track1"]
    assert library_service.reject_match_calls == []
    assert library_service.get_needs_review_matches_calls == []
    assert "Confirmed" in capsys.readouterr().out


def test_review_reject_calls_reject_match(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    library_service = FakeLibraryServiceForCli()

    cli.run(
        FakeApplication(matcher, library_service=library_service),
        ["review", "--reject", "track1"],
    )

    assert library_service.reject_match_calls == ["track1"]
    assert library_service.confirm_match_calls == []
    assert "Rejected" in capsys.readouterr().out


# --- Roadmap item 82 (P13.6): `seeker search` -------------------------------

def test_search_without_download_flag_lists_results(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    files = [
        SoulseekFile(
            username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
            extension="flac", size=25_000_000, queue_length=0,
            upload_speed=1_000_000, has_free_upload_slot=True,
            bit_rate=None,
        ),
        SoulseekFile(
            username="peer2", filename="Dom Dolla - Rhyme Dust.mp3",
            extension="mp3", size=8_000_000, queue_length=3,
            upload_speed=500_000, has_free_upload_slot=True,
            bit_rate=320,
        ),
    ]
    download_service = FakeDownloadServiceForSearch(files=files)

    cli.run(
        FakeApplication(matcher, download_service=download_service),
        ["search", "Dom Dolla", "Rhyme Dust"],
    )

    assert download_service.search_manual_calls == [
        ("Dom Dolla", "Rhyme Dust")
    ]
    assert download_service.download_manual_calls == []

    output = capsys.readouterr().out
    assert "peer1" in output
    assert "Dom Dolla - Rhyme Dust.flac" in output
    assert "peer2" in output
    assert "320kbps" in output
    # flac (lossless) ranks above mp3 (lossy) — real ranking, not list order.
    assert output.index("peer1") < output.index("peer2")


def test_search_without_results_prints_a_clear_message(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    download_service = FakeDownloadServiceForSearch(files=[])

    cli.run(
        FakeApplication(matcher, download_service=download_service),
        ["search", "Nobody", "Nothing"],
    )

    assert "No results" in capsys.readouterr().out


def test_search_download_flag_requests_the_best_candidate(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    download_service = FakeDownloadServiceForSearch(
        download_result={
            "requested": True, "settled": True,
            "username": "peer1", "filename": "Dom Dolla - Rhyme Dust.flac",
        },
    )

    cli.run(
        FakeApplication(matcher, download_service=download_service),
        ["search", "Dom Dolla", "Rhyme Dust", "--download"],
    )

    assert download_service.download_manual_calls == [
        ("Dom Dolla", "Rhyme Dust")
    ]
    assert download_service.search_manual_calls == []

    output = capsys.readouterr().out
    assert "Requested from peer1" in output
    assert "Dom Dolla - Rhyme Dust.flac" in output


def test_search_download_flag_with_no_candidates_reports_it(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    download_service = FakeDownloadServiceForSearch(
        download_result={
            "requested": False, "settled": False,
            "reason": "no_candidate_found",
        },
    )

    cli.run(
        FakeApplication(matcher, download_service=download_service),
        ["search", "Nobody", "Nothing", "--download"],
    )

    assert "No candidates found" in capsys.readouterr().out


def test_search_download_flag_with_no_destination_gives_settings_guidance(
        tmp_path, capsys,
):
    # Roadmap item 82 — a manual search has no playlist to set a
    # per-playlist destination for; guidance must point at Settings,
    # not the ordinary 'seeker playlists set-destination' hint.
    matcher = make_matcher(tmp_path)
    download_service = FakeDownloadServiceForSearch(
        download_error=NoDestinationConfiguredError(
            "No download destination is configured yet."
        ),
    )

    try:
        cli.run(
            FakeApplication(matcher, download_service=download_service),
            ["search", "Dom Dolla", "Rhyme Dust", "--download"],
        )
        assert False, "expected SystemExit"
    except SystemExit as exit_info:
        assert exit_info.code == 1

    output = capsys.readouterr().out
    assert "Settings" in output
    assert "playlists set-destination" not in output


class FakeSharingServiceForCli:
    def __init__(self, status, self_managed, reconciliation):
        self._status = status
        self._self_managed = self_managed
        self._reconciliation = reconciliation

    def get_status(self):
        return self._status

    def is_self_managed(self) -> bool:
        return self._self_managed

    def get_reconciliation(self):
        return self._reconciliation


class FakeShareStatus:
    def __init__(self, ready, scanning, directories, files):
        self.ready = ready
        self.scanning = scanning
        self.directories = directories
        self.files = files


class FakeShareEntry:
    def __init__(self, local_path, directories, files):
        self.local_path = local_path
        self.directories = directories
        self.files = files


class FakeLocationShareState:
    def __init__(self, location_name, shared, share=None):
        class Location:
            def __init__(self, name):
                self.name = name

        self.location = Location(location_name)
        self.shared = shared
        self.share = share


def test_sharing_status_reports_when_not_configured(tmp_path, capsys):
    matcher = make_matcher(tmp_path)

    cli.run(
        FakeApplication(matcher, soulseek_configured=False),
        ["sharing", "status"],
    )

    output = capsys.readouterr().out
    assert "isn't configured" in output


def test_sharing_status_reports_self_managed_and_reconciliation(
        tmp_path, capsys,
):
    matcher = make_matcher(tmp_path)
    sharing_service = FakeSharingServiceForCli(
        status=FakeShareStatus(
            ready=True, scanning=False, directories=2, files=10,
        ),
        self_managed=True,
        reconciliation=[
            FakeLocationShareState(
                "Music", True,
                FakeShareEntry("/shared/music", 2, 10),
            ),
            FakeLocationShareState("Other", False),
        ],
    )

    cli.run(
        FakeApplication(
            matcher,
            soulseek_configured=True,
            sharing_service=sharing_service,
        ),
        ["sharing", "status"],
    )

    output = capsys.readouterr().out
    assert "managed by Seeker's own docker-compose.yml" in output
    assert "Music: shared as /shared/music" in output
    assert "Other: not shared" in output


def test_downloads_review_all_replaces_every_pending_upgrade(
        tmp_path, capsys, monkeypatch,
):
    from seeker.models.track import Track
    from seeker.models.upgrade_review import UpgradeReviewDetails
    from seeker.soulseek.download_service import BulkUpgradeReplaceResult

    track = Track(
        id="t1", title="Title", artist="Artist", album="Album",
        duration_ms=200_000,
    )
    upgrades = [
        UpgradeReviewDetails(
            request_id=1, track=track, quality_descriptor="flac 1000kbps",
            current_description="mp3", old_file_path="/music/old.mp3",
        ),
    ]
    download_service = FakeDownloadServiceForBulkReview(
        upgrades,
        batch_result=BulkUpgradeReplaceResult(
            replaced=1, failed=0, details=["Artist - Title: Replaced with x"],
        ),
    )
    matcher = make_matcher(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")

    cli.run(
        FakeApplication(matcher, download_service=download_service),
        ["downloads", "review", "--all"],
    )

    assert download_service.apply_upgrade_decisions_batch_calls == [([1], True)]
    output = capsys.readouterr().out
    assert "Replaced: 1, Failed: 0" in output


def test_downloads_review_all_declined_at_first_prompt_calls_nothing(
        tmp_path, capsys, monkeypatch,
):
    from seeker.models.track import Track
    from seeker.models.upgrade_review import UpgradeReviewDetails

    track = Track(
        id="t1", title="Title", artist="Artist", album="Album",
        duration_ms=200_000,
    )
    upgrades = [
        UpgradeReviewDetails(
            request_id=1, track=track, quality_descriptor="flac",
            current_description="mp3", old_file_path=None,
        ),
    ]
    download_service = FakeDownloadServiceForBulkReview(upgrades)
    matcher = make_matcher(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    cli.run(
        FakeApplication(matcher, download_service=download_service),
        ["downloads", "review", "--all"],
    )

    assert download_service.apply_upgrade_decisions_batch_calls == []
    assert "Cancelled" in capsys.readouterr().out


def test_downloads_review_all_empty_prints_nothing_to_review(
        tmp_path, capsys, monkeypatch,
):
    download_service = FakeDownloadServiceForBulkReview([])
    matcher = make_matcher(tmp_path)
    monkeypatch.setattr(
        "builtins.input", lambda prompt="": (_ for _ in ()).throw(
            AssertionError("input() must not be called with nothing to review")
        )
    )

    cli.run(
        FakeApplication(matcher, download_service=download_service),
        ["downloads", "review", "--all"],
    )

    assert download_service.apply_upgrade_decisions_batch_calls == []
    assert "Nothing to review." in capsys.readouterr().out


def test_sharing_status_reports_not_self_managed(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    sharing_service = FakeSharingServiceForCli(
        status=FakeShareStatus(
            ready=True, scanning=False, directories=0, files=0,
        ),
        self_managed=False,
        reconciliation=[],
    )

    cli.run(
        FakeApplication(
            matcher,
            soulseek_configured=True,
            sharing_service=sharing_service,
        ),
        ["sharing", "status"],
    )

    output = capsys.readouterr().out
    assert "NOT managed by Seeker" in output
