import argparse
import re
from pathlib import Path

import pytest

from seeker import cli
from seeker.database.connection import Database
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.errors import LibraryLocationNotFoundError, PlaylistNotFoundError
from seeker.library.matcher import TrackMatcher
from seeker.library.metadata_service import RenamePlan, RenameResult
from seeker.models.download_result import ManualDownloadResult
from seeker.models.fingerprint_result import FingerprintResult
from seeker.models.library_location import LibraryLocation
from seeker.models.library_result import (
    MatchResult,
    ScanAndMatchResult,
    ScanResult,
)
from seeker.models.local_file import LocalFile
from seeker.models.location_merge import LocationMergeSummary
from seeker.models.location_removal import LocationRemovalSummary
from seeker.models.needs_review_match import NeedsReviewMatch
from seeker.models.nested_location import NestedLocation
from seeker.models.playlist import Playlist
from seeker.models.soulseek_file import SoulseekFile
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.spotify_sync import PlaylistRefreshResult, TrackSyncResult
from seeker.models.tag_result import FixArtResult, TagResult
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch
from seeker.soulseek.download_service import NoDestinationConfiguredError


class FakeSyncService:
    def __init__(self, playlists: list[Playlist]):
        self._playlists = playlists
        self.track_sync_result = TrackSyncResult(tracks_saved=0)
        self.refresh_result = PlaylistRefreshResult(
            playlist_count=len(playlists), updated_playlist_names=[],
        )

    def get_playlist_by_name(self, name: str) -> Playlist:
        for playlist in self._playlists:
            if playlist.name.lower() == name.lower():
                return playlist

        raise PlaylistNotFoundError(
            f"No playlist named '{name}' found locally."
        )

    def list_playlists(self) -> list[Playlist]:
        return self._playlists

    def sync_playlist_tracks(self, playlist: Playlist) -> TrackSyncResult:
        return self.track_sync_result

    def refresh_playlists(self) -> PlaylistRefreshResult:
        return self.refresh_result


class FakeApplication:
    def __init__(
            self,
            track_matcher: TrackMatcher,
            soulseek_configured: bool = False,
            download_service=None,
            review_service=None,
            sync_service=None,
            duplicate_service=None,
            history_service=None,
            library_service=None,
            sharing_service=None,
    ):
        self.track_matcher = track_matcher
        self.soulseek_configured = soulseek_configured
        self.download_service = download_service
        self.review_service = review_service
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

    def scan_all(self) -> ScanResult:
        self.scan_all_calls += 1
        return ScanResult()

    def scan_and_match(self) -> ScanAndMatchResult:
        self.scan_and_match_calls += 1
        return ScanAndMatchResult(
            scan=ScanResult(added=1), match=MatchResult(auto=1),
        )

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
        TrackRepository(),
        LocalFileRepository(),
        TrackMatchRepository(),
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


class FakeReviewServiceForCheck:
    def __init__(self, review_candidates):
        self._review_candidates = review_candidates
        self.get_review_candidates_calls = []

    def get_review_candidates(self, playlist_id=None):
        self.get_review_candidates_calls.append(playlist_id)
        return self._review_candidates


class FakeReviewServiceForBulkReview:
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
        self._download_result = download_result or ManualDownloadResult(
            track_id="manual:fake", requested=False, settled=False,
            reason="no_candidate_found",
        )
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

    review_service = FakeReviewServiceForCheck([(track, candidate)])

    cli.run(
        FakeApplication(
            matcher,
            soulseek_configured=True,
            review_service=review_service,
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
    review_service = FakeReviewServiceForCheck([])

    cli.run(
        FakeApplication(
            matcher,
            soulseek_configured=True,
            review_service=review_service,
            sync_service=sync_service,
        ),
        ["check", "PlaylistA"],
    )

    assert review_service.get_review_candidates_calls == ["pA"]


class FakeDuplicateService:
    def __init__(
            self,
            fingerprint_result=None,
            groups=None,
            cleanup_totals=(0, 0),
    ):
        self._fingerprint_result = fingerprint_result or FingerprintResult(
            computed=0, skipped_already_computed=0, failed=0,
            details=[],
        )
        self._groups = groups or []
        self._cleanup_totals = cleanup_totals
        self.compute_fingerprints_calls = []
        self.find_duplicate_groups_calls = []

    def compute_fingerprints(
            self, location_name, force=False, folders=None, progress=None,
    ):
        self.compute_fingerprints_calls.append((location_name, force, folders))
        return self._fingerprint_result

    def find_duplicate_groups(
            self,
            location_name,
            folders=None,
            progress=None,
    ):
        self.find_duplicate_groups_calls.append((location_name, folders))
        return self._groups

    def get_cleanup_totals(self):
        return self._cleanup_totals


def test_library_fingerprint_calls_compute_fingerprints_and_reports_counts(
        tmp_path, capsys,
):
    matcher = make_matcher(tmp_path)
    duplicate_service = FakeDuplicateService(
        fingerprint_result=FingerprintResult(
            computed=2, skipped_already_computed=1, failed=0,
            details=[],
        ),
    )

    cli.run(
        FakeApplication(matcher, duplicate_service=duplicate_service),
        ["library", "fingerprint", "Main"],
    )

    assert duplicate_service.compute_fingerprints_calls == [
            ("Main", False, None)
    ]
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

    assert duplicate_service.compute_fingerprints_calls == [
            ("Main", True, None)
    ]


def test_library_fingerprint_reports_failure_details(tmp_path, capsys):
    matcher = make_matcher(tmp_path)
    duplicate_service = FakeDuplicateService(
        fingerprint_result=FingerprintResult(
            computed=0, skipped_already_computed=0, failed=1,
            details=[
                {
                    "local_file_id": "1",
                    "reason": "failed",
                    "message": "a.mp3: real decode error",
                },
            ],
        ),
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
    from seeker.audio.quality import LocalFileQuality
    from seeker.library.duplicate_service import DuplicateFile, DuplicateGroup

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
        raise AssertionError("expected SystemExit")
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


def test_search_output_strips_terminal_control_from_peer_strings(
        tmp_path, capsys,
):
    matcher = make_matcher(tmp_path)
    files = [
        SoulseekFile(
            username="peer\x1b[2J\x9b31m",
            filename="\x1b]8;;https://evil.example\x07Rhyme Dust.flac",
            extension="flac", size=25_000_000, queue_length=0,
            upload_speed=1_000_000, has_free_upload_slot=True,
            bit_rate=None,
        ),
    ]
    download_service = FakeDownloadServiceForSearch(files=files)

    cli.run(
        FakeApplication(matcher, download_service=download_service),
        ["search", "Dom Dolla", "Rhyme Dust"],
    )

    output = capsys.readouterr().out
    assert "\x1b" not in output
    assert "\x07" not in output
    assert "\x9b" not in output
    assert "Rhyme Dust.flac" in output


def test_printable_keeps_tabs_and_text_and_drops_control_characters():
    assert cli.printable("a\tb\x00c\x1bd\x7fe\x85f\nñ") == "a\tbcdefñ"


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
        download_result=ManualDownloadResult(
            track_id="manual:fake", requested=True, settled=True,
            username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
        ),
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
        download_result=ManualDownloadResult(
            track_id="manual:fake", requested=False, settled=False,
            reason="no_candidate_found",
        ),
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
        raise AssertionError("expected SystemExit")
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

    def get_reconciliation(self, status):
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
    from seeker.soulseek.review_service import BulkUpgradeReplaceResult

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
    review_service = FakeReviewServiceForBulkReview(
        upgrades,
        batch_result=BulkUpgradeReplaceResult(
            replaced=1, failed=0, details=["Artist - Title: Replaced with x"],
        ),
    )
    matcher = make_matcher(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")

    cli.run(
        FakeApplication(matcher, review_service=review_service),
        ["downloads", "review", "--all"],
    )

    assert review_service.apply_upgrade_decisions_batch_calls == [
            ([1], True)
    ]
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
    review_service = FakeReviewServiceForBulkReview(upgrades)
    matcher = make_matcher(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    cli.run(
        FakeApplication(matcher, review_service=review_service),
        ["downloads", "review", "--all"],
    )

    assert review_service.apply_upgrade_decisions_batch_calls == []
    assert "Cancelled" in capsys.readouterr().out


def test_downloads_review_all_empty_prints_nothing_to_review(
        tmp_path, capsys, monkeypatch,
):
    review_service = FakeReviewServiceForBulkReview([])
    matcher = make_matcher(tmp_path)
    monkeypatch.setattr(
        "builtins.input", lambda prompt="": (_ for _ in ()).throw(
            AssertionError("input() must not be called with nothing to review")
        )
    )

    cli.run(
        FakeApplication(matcher, review_service=review_service),
        ["downloads", "review", "--all"],
    )

    assert review_service.apply_upgrade_decisions_batch_calls == []
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


# --- library remove ------------------------------------------------------

class FakeApplicationRemovingLocations(FakeApplication):
    def __init__(self, matcher, summary=None, error=None):
        super().__init__(matcher)
        self._summary = summary
        self._error = error
        self.remove_location_calls: list[str] = []

    def remove_location(self, name):
        self.remove_location_calls.append(name)
        if self._error is not None:
            raise self._error
        return self._summary


def test_library_remove_prints_what_was_forgotten(tmp_path, capsys):
    application = FakeApplicationRemovingLocations(
        make_matcher(tmp_path),
        summary=LocationRemovalSummary(
            location_name="Music",
            files_forgotten=3454,
            matches_cleared=12,
            confirmed_matches_cleared=3,
            playlists_affected=2,
            was_default=True,
        ),
    )

    cli.run(application, ["library", "remove", "Music"])

    assert application.remove_location_calls == ["Music"]
    output = capsys.readouterr().out
    assert "Removed 'Music'" in output
    assert "3,454 indexed files" in output
    assert "12 matches (3 you confirmed)" in output
    assert "2 playlists" in output
    assert "default download location" in output
    assert "Files on disk were not touched." in output


def test_library_remove_unknown_name_exits_with_the_error(tmp_path, capsys):
    application = FakeApplicationRemovingLocations(
        make_matcher(tmp_path),
        error=LibraryLocationNotFoundError(
            "No library location named 'Nope' is registered."
        ),
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.run(application, ["library", "remove", "Nope"])

    assert exit_info.value.code == 1
    assert "No library location named 'Nope'" in capsys.readouterr().out


class FakeLibraryServiceCheckingNesting:
    def __init__(self, nested: list[NestedLocation]):
        self._nested = nested

    def find_nested_locations(self) -> list[NestedLocation]:
        return self._nested


def test_library_check_lists_every_nested_pair(tmp_path, capsys):
    drive = LibraryLocation("x9-pro", "/Volumes/X9 Pro", "t", id=1)
    music = LibraryLocation("Music", "/Volumes/X9 Pro/Music", "t", id=2)
    application = FakeApplication(
        make_matcher(tmp_path),
        library_service=FakeLibraryServiceCheckingNesting(
            [NestedLocation(inner=music, outer=drive)],
        ),
    )

    cli.run(application, ["library", "check"])

    output = capsys.readouterr().out
    assert "indexed twice" in output
    assert (
        "'Music' (/Volumes/X9 Pro/Music) is inside "
        "'x9-pro' (/Volumes/X9 Pro)"
    ) in output


def test_library_check_says_when_nothing_is_nested(tmp_path, capsys):
    application = FakeApplication(
        make_matcher(tmp_path),
        library_service=FakeLibraryServiceCheckingNesting([]),
    )

    cli.run(application, ["library", "check"])

    assert "No library location is inside another." in (
        capsys.readouterr().out
    )


class FakeApplicationMergingLocations(FakeApplication):
    def __init__(self, matcher, summary):
        super().__init__(matcher)
        self._summary = summary
        self.merge_location_calls: list[tuple[str, str]] = []

    def merge_location(self, name, keep):
        self.merge_location_calls.append((name, keep))
        return self._summary


def test_library_merge_prints_what_moved_and_what_was_forgotten(
        tmp_path, capsys,
):
    application = FakeApplicationMergingLocations(
        make_matcher(tmp_path),
        LocationMergeSummary(
            merged_name="x9-pro",
            kept_name="Music",
            files_merged=3452,
            files_forgotten=5,
            matches_moved=37,
            matches_cleared=1,
            analyses_kept=2663,
            playlists_moved=1,
            playlists_cleared=2,
            was_default=True,
        ),
    )

    cli.run(application, ["library", "merge", "x9-pro", "Music"])

    assert application.merge_location_calls == [("x9-pro", "Music")]
    output = capsys.readouterr().out
    assert "Merged 'x9-pro' into 'Music'." in output
    assert "Moved 37 matches" in output
    assert "kept analysis for 2,663 files" in output
    assert "Forgot 5 indexed files and 1 matches" in output
    assert "1 playlists download into the same folder" in output
    assert "2 playlists need a new destination" in output
    assert "default download location, now unset" in output
    assert "Files on disk were not touched." in output


def test_sync_tracks_reports_skipped_local_files_and_duplicates(
        tmp_path, capsys,
):
    playlist = Playlist(id="p1", name="Bootlegs", track_count=6)
    sync_service = FakeSyncService([playlist])
    sync_service.track_sync_result = TrackSyncResult(
        tracks_saved=3, local_files_skipped=2, duplicates_collapsed=1,
    )
    application = FakeApplication(
        make_matcher(tmp_path),
        sync_service=sync_service,
    )

    cli.handle_sync_tracks(
        application, cli.build_parser().parse_args(
            ["sync-tracks", "Bootlegs"],
        ),
    )

    output = capsys.readouterr().out
    assert "Saved 3 tracks for 'Bootlegs'." in output
    assert "1 repeated listing(s)" in output
    assert "Skipped 2 Spotify local file(s)" in output


def test_sync_reports_playlists_whose_tracks_were_updated(tmp_path, capsys):
    playlists = [
        Playlist(id="p1", name="Warmup", track_count=1),
        Playlist(id="p2", name="Peak", track_count=1),
    ]
    sync_service = FakeSyncService(playlists)
    sync_service.refresh_result = PlaylistRefreshResult(
        playlist_count=2, updated_playlist_names=["Peak"],
    )
    application = FakeApplication(
        make_matcher(tmp_path), sync_service=sync_service,
    )

    cli.handle_sync(application, cli.build_parser().parse_args(["sync"]))

    output = capsys.readouterr().out
    assert "Refreshed 2 playlists." in output
    assert "Updated tracks for 1 that changed on Spotify: Peak" in output


def _run_sync_raising(monkeypatch, error):
    def handle_sync(application, parsed):
        raise error

    monkeypatch.setattr(cli, "handle_sync", handle_sync)
    cli.run(object(), ["sync"])


def test_unreachable_slskd_prints_readable_text_not_a_traceback(
        monkeypatch, capsys,
):
    import httpx

    error = httpx.ConnectError(
        "[Errno 61] Connection refused",
        request=httpx.Request("GET", "http://127.0.0.1:5030/api/v0/x"),
    )

    with pytest.raises(SystemExit) as exit_info:
        _run_sync_raising(monkeypatch, error)

    assert exit_info.value.code == 1
    output = capsys.readouterr().out
    assert "slskd" in output
    assert "Docker" in output


def test_a_locked_database_prints_readable_text(monkeypatch, capsys):
    import sqlite3

    with pytest.raises(SystemExit) as exit_info:
        _run_sync_raising(
            monkeypatch, sqlite3.OperationalError("database is locked"),
        )

    assert exit_info.value.code == 1
    assert "busy" in capsys.readouterr().out


def test_other_database_errors_print_their_details(monkeypatch, capsys):
    import sqlite3

    with pytest.raises(SystemExit):
        _run_sync_raising(
            monkeypatch, sqlite3.OperationalError("disk I/O error"),
        )

    output = capsys.readouterr().out
    assert "database" in output
    assert "disk I/O error" in output
    assert "Open Log Folder" not in output


def test_any_seeker_error_prints_its_sentence_not_a_traceback(
        monkeypatch, capsys,
):
    from seeker.spotify.client import SpotifyAuthenticationError

    with pytest.raises(SystemExit) as exit_info:
        _run_sync_raising(monkeypatch, SpotifyAuthenticationError())

    assert exit_info.value.code == 1
    assert capsys.readouterr().out == (
        "Spotify rejected Seeker's authorization. Re-authorize in "
        "Settings.\n"
    )


def test_an_unexpected_error_still_tracebacks(monkeypatch):
    # A bug report needs the traceback; only known failure kinds are
    # turned into a sentence.
    with pytest.raises(KeyError):
        _run_sync_raising(monkeypatch, KeyError("track_id"))


def test_downloads_status_with_slskd_down_prints_the_outage_and_fails(
        capsys,
):
    from types import SimpleNamespace

    from seeker.soulseek.client import SlskdUnreachableError

    def poll_downloads():
        raise SlskdUnreachableError("http://127.0.0.1:5030")

    application = SimpleNamespace(
        download_service=SimpleNamespace(poll_downloads=poll_downloads),
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.run(application, ["downloads", "status"])

    assert exit_info.value.code == 1
    assert capsys.readouterr().out == (
        "SoulSeek isn't reachable — downloads are paused until slskd is "
        "running.\n"
    )


@pytest.mark.parametrize(
    ("command", "subcommands"),
    [
        (
            "library",
            "{add,list,remove,check,merge,scan,match,tag,fix-art,fingerprint,"
            "duplicates,rename}",
        ),
        ("downloads", "{status,review}"),
        ("sharing", "{status}"),
    ],
)
def test_a_command_group_without_its_subcommand_is_a_usage_error(
        command, subcommands, capsys,
):
    with pytest.raises(SystemExit) as exit_info:
        cli.run(object(), [command])

    assert exit_info.value.code == 2
    error = " ".join(capsys.readouterr().err.split())
    assert f"seeker {command} [-h] {subcommands}" in error
    assert "the following arguments are required" in error


class FakeMetadataServiceForCli:
    def __init__(self, plans=None):
        self.plans = plans or []
        self.tag_calls: list[dict] = []
        self.applied: list = []

    def tag_playlist(self, playlist_name, **kwargs):
        self.tag_calls.append({"playlist_name": playlist_name, **kwargs})
        return TagResult(
            tagged=2, tagged_without_art=1, failed=1,
            details=[{"track_id": "t1", "reason": "failed",
                      "message": "Boom."}],
        )

    def fix_missing_art_for_playlist(self, playlist_name):
        return FixArtResult(
            fixed=1, already_correct=3,
            details=[{"track_id": "t2", "reason": "no_url",
                      "message": "No art."}],
        )

    def plan_renames(self, playlist_name=None):
        return self.plans

    def apply_renames(self, plans):
        self.applied.append(plans)
        return RenameResult(renamed=2, collisions=1, already_correct=1)


def _rename_plans() -> list[RenamePlan]:
    def plan(action, current=None, proposed=None, note=None):
        return RenamePlan(
            track_id=action, local_file_id=None, current_path=None,
            proposed_path=None, action=action,
            current_relative=Path(current) if current else None,
            proposed_relative=Path(proposed) if proposed else None,
            destination_note=note,
        )

    return [
        plan("rename", "a.mp3", "A - Song.mp3", note="Not in Warmup."),
        plan("collision", "b.mp3", "B - Song.mp3"),
        plan("already_correct"),
        plan("not_auto_matched"),
        plan("no_local_file"),
        plan("error"),
    ]


def _metadata_application(tmp_path, metadata_service):
    application = FakeApplication(
        make_matcher(tmp_path),
        sync_service=FakeSyncService(
            [Playlist(id="p1", name="Warmup", track_count=6)],
        ),
    )
    application.metadata_service = metadata_service
    return application


def test_library_rename_dry_run_prints_the_plan_and_changes_nothing(
        tmp_path, capsys,
):
    metadata_service = FakeMetadataServiceForCli(_rename_plans())

    cli.run(
        _metadata_application(tmp_path, metadata_service),
        ["library", "rename", "warmup"],
    )

    assert capsys.readouterr().out == (
        "Rename plan for 'Warmup':\n\n"
        "  a.mp3 -> A - Song.mp3\n"
        "    warning: Not in Warmup.\n"
        "  b.mp3 -> B - Song.mp3 (needs a numbered suffix)\n"
        "\n2 to rename (1 with a collision), 1 already correct, "
        "1 not auto-matched, 2 no local file.\n"
        "\nDry run only — pass --apply to actually rename.\n"
    )
    assert metadata_service.applied == []


def test_library_rename_apply_confirms_then_renames(
        tmp_path, capsys, monkeypatch,
):
    metadata_service = FakeMetadataServiceForCli(_rename_plans())
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    cli.run(
        _metadata_application(tmp_path, metadata_service),
        ["library", "rename", "Warmup", "--apply"],
    )

    assert metadata_service.applied == [metadata_service.plans]
    assert capsys.readouterr().out.endswith(
        "\nRenamed: 2 (1 with a collision), Already correct: 1, "
        "Not auto-matched: 0, No local file: 0, Failed: 0.\n"
    )


def test_library_rename_apply_with_nothing_to_rename_asks_nothing(
        tmp_path, capsys,
):
    metadata_service = FakeMetadataServiceForCli([])

    cli.run(
        _metadata_application(tmp_path, metadata_service),
        ["library", "rename", "Warmup", "--apply"],
    )

    assert capsys.readouterr().out.endswith("\nNothing to rename.\n")


def test_library_tag_prints_counts_and_details(tmp_path, capsys):
    metadata_service = FakeMetadataServiceForCli()

    cli.run(
        _metadata_application(tmp_path, metadata_service),
        ["library", "tag", "Warmup", "--analyze-audio",
         "--bpm-range", "160", "180"],
    )

    assert metadata_service.tag_calls == [{
        "playlist_name": "Warmup", "analyze_audio": True,
        "expected_bpm_range": (160.0, 180.0), "force": False,
    }]
    assert capsys.readouterr().out == (
        "Tagged: 2 (1 without cover art), Skipped (no match): 0, "
        "Skipped (unsupported format): 0, Skipped (already tagged): 0, "
        "Skipped (already analyzed): 0, Failed: 1.\n"
        "\nDetails (skipped, failed, or tagged without art):\n"
        "  [failed] Boom.\n"
    )


def test_library_tag_bpm_range_needs_analyze_audio(tmp_path, capsys):
    metadata_service = FakeMetadataServiceForCli()

    cli.run(
        _metadata_application(tmp_path, metadata_service),
        ["library", "tag", "Warmup", "--bpm-range", "160", "180"],
    )

    assert metadata_service.tag_calls == []
    assert capsys.readouterr().out == (
        "--bpm-range requires --analyze-audio.\n"
    )


def test_library_fix_art_prints_counts_and_details(tmp_path, capsys):
    cli.run(
        _metadata_application(tmp_path, FakeMetadataServiceForCli()),
        ["library", "fix-art", "Warmup"],
    )

    assert capsys.readouterr().out == (
        "Fixed: 1, Already correct: 3, No art URL: 0, "
        "Download failed: 0, Embed failed: 0, Unsupported format: 0, "
        "Skipped (no match): 0, Failed: 0.\n"
        "\nDetails:\n"
        "  [no_url] No art.\n"
    )


class FakeServiceForCliRouting:
    def __init__(self):
        self.calls: list[tuple] = []

    def set_destination(self, playlist_name, location_name, subfolder):
        self.calls.append(
            ("set_destination", playlist_name, location_name, subfolder),
        )

    def get_pending_upgrade_reviews(self):
        self.calls.append(("get_pending_upgrade_reviews",))
        return []


def test_playlists_without_a_subcommand_lists_playlists(tmp_path, capsys):
    application = _metadata_application(tmp_path, None)

    cli.run(application, ["playlists"])

    assert capsys.readouterr().out == "Warmup (6 tracks)\n"


def test_playlists_set_destination_resolves_the_playlist(tmp_path):
    application = _metadata_application(tmp_path, None)
    application.download_service = FakeServiceForCliRouting()

    cli.run(
        application,
        ["playlists", "set-destination", "warmup", "Music", "Sets"],
    )

    assert application.download_service.calls == [
        ("set_destination", "Warmup", "Music", "Sets"),
    ]


def test_downloads_review_without_all_runs_the_interactive_review(
        tmp_path, capsys,
):
    application = _metadata_application(tmp_path, None)
    application.review_service = FakeServiceForCliRouting()

    cli.run(application, ["downloads", "review"])

    assert application.review_service.calls == [
        ("get_pending_upgrade_reviews",),
    ]
    assert capsys.readouterr().out == "Nothing to review.\n"


# --- Playlist-name resolution: the refresh offer ----------------------


class FakeSyncServiceThatCanRefresh(FakeSyncService):
    """`sync_playlists` makes `appears_after_refresh` known, as a
    metadata refresh would for a playlist created on Spotify since."""

    def __init__(self, playlists, appears_after_refresh=None):
        super().__init__(playlists)
        self._appears_after_refresh = appears_after_refresh
        self.sync_playlists_calls = 0

    def sync_playlists(self) -> None:
        self.sync_playlists_calls += 1
        if self._appears_after_refresh is not None:
            self._playlists.append(self._appears_after_refresh)


def _refreshing_application(tmp_path, sync_service):
    return FakeApplication(make_matcher(tmp_path), sync_service=sync_service)


def _answer(monkeypatch, *answers: str) -> list[str]:
    prompts: list[str] = []
    remaining = list(answers)

    def fake_input(prompt=""):
        prompts.append(prompt)
        return remaining.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)
    return prompts


def test_a_close_playlist_name_fails_without_offering_a_refresh(
        tmp_path, capsys, monkeypatch,
):
    sync_service = FakeSyncServiceThatCanRefresh(
        [Playlist(id="p1", name="Warmup", track_count=6)],
    )
    prompts = _answer(monkeypatch)

    with pytest.raises(SystemExit) as exit_info:
        cli.run(
            _refreshing_application(tmp_path, sync_service),
            ["sync-tracks", "Warmp"],
        )

    assert exit_info.value.code == 1
    assert prompts == []
    assert sync_service.sync_playlists_calls == 0
    assert "Warmp" in capsys.readouterr().out


def test_declining_the_refresh_offer_reports_the_missing_playlist(
        tmp_path, capsys, monkeypatch,
):
    sync_service = FakeSyncServiceThatCanRefresh([])
    prompts = _answer(monkeypatch, "n")

    with pytest.raises(SystemExit):
        cli.run(
            _refreshing_application(tmp_path, sync_service),
            ["sync-tracks", "Brand New"],
        )

    assert len(prompts) == 1
    assert sync_service.sync_playlists_calls == 0
    assert (
        "No playlist named 'Brand New' found locally."
        in capsys.readouterr().out
    )


def test_accepting_the_refresh_offer_finds_a_new_playlist(
        tmp_path, capsys, monkeypatch,
):
    sync_service = FakeSyncServiceThatCanRefresh(
        [], appears_after_refresh=Playlist(
            id="p9", name="Brand New", track_count=4,
        ),
    )
    sync_service.track_sync_result = TrackSyncResult(tracks_saved=4)
    _answer(monkeypatch, "y")

    cli.run(
        _refreshing_application(tmp_path, sync_service),
        ["sync-tracks", "brand new"],
    )

    assert sync_service.sync_playlists_calls == 1
    assert (
        capsys.readouterr().out == "Saved 4 tracks for 'Brand New'.\n"
    )


def test_a_playlist_missing_even_after_refreshing_says_so(
        tmp_path, capsys, monkeypatch,
):
    sync_service = FakeSyncServiceThatCanRefresh([])
    _answer(monkeypatch, "y")

    with pytest.raises(SystemExit):
        cli.run(
            _refreshing_application(tmp_path, sync_service),
            ["sync-tracks", "Brand New"],
        )

    assert "even after refreshing from Spotify" in capsys.readouterr().out


# --- download --------------------------------------------------------


class FakeDownloadServiceForPlaylist:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.download_playlist_calls: list[str] = []

    def download_playlist(self, playlist_name):
        self.download_playlist_calls.append(playlist_name)
        if self._error is not None:
            raise self._error
        return self._result


def _download_application(tmp_path, download_service):
    application = _metadata_application(tmp_path, None)
    application.download_service = download_service
    return application


def test_download_names_every_kind_of_skip(tmp_path, capsys):
    from seeker.models.download_result import (
        PlaylistDownloadResult,
        TrackFailure,
    )

    download_service = FakeDownloadServiceForPlaylist(
        PlaylistDownloadResult(
            requested=2, skipped=4, total=7,
            already_in_progress=["A - One"],
            needs_review=["B - Two", "C - Three"],
            failures=[TrackFailure(track="D - Four", reason="search failed")],
        ),
    )

    cli.run(
        _download_application(tmp_path, download_service),
        ["download", "warmup"],
    )

    assert download_service.download_playlist_calls == ["Warmup"]
    assert capsys.readouterr().out == (
        "Requested 2 download(s), skipped 4 (2 sent to review, "
        "1 already in progress, 1 no candidate found), failed 1 "
        "(of 7 unmatched tracks).\n"
        "  Run 'seeker review' to see the new candidates.\n"
    )


def test_download_without_a_destination_points_at_set_destination(
        tmp_path, capsys,
):
    download_service = FakeDownloadServiceForPlaylist(
        error=NoDestinationConfiguredError("Warmup"),
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.run(
            _download_application(tmp_path, download_service),
            ["download", "Warmup"],
        )

    assert exit_info.value.code == 1
    assert capsys.readouterr().out.rstrip().endswith(
        "Run 'seeker playlists set-destination' first."
    )


# --- downloads status ------------------------------------------------


class FakeDownloadServiceForPoll:
    def __init__(self, result):
        self._result = result

    def poll_downloads(self):
        return self._result


def test_downloads_status_prints_every_count(tmp_path, capsys):
    from seeker.models.download_result import PollResult

    application = FakeApplication(
        make_matcher(tmp_path),
        download_service=FakeDownloadServiceForPoll(
            PollResult(
                queued=1, downloading=2, completed=3, failed=4,
                ready_for_review=5, locked=6, shortlisted=7,
                superseded=8, unavailable=9,
            ),
        ),
    )

    cli.run(application, ["downloads", "status"])

    assert capsys.readouterr().out == (
        "Queued: 1, Downloading: 2, Completed: 3, Failed: 4, "
        "Ready for review: 5, Locked (retrying): 6, "
        "Shortlisted (pending): 7, Superseded: 8, Unavailable: 9.\n"
    )


# --- downloads review, one at a time ---------------------------------


class FakeReviewServiceForOneByOne:
    def __init__(self, details_by_id, message="Replaced."):
        self._details_by_id = details_by_id
        self._message = message
        self.decisions: list[tuple[int, bool, bool]] = []

    def get_pending_upgrade_reviews(self):
        return [
            details for details in self._details_by_id.values()
            if details is not None
        ] + [
            self._listed_only(request_id)
            for request_id, details in self._details_by_id.items()
            if details is None
        ]

    def _listed_only(self, request_id):
        from seeker.models.upgrade_review import UpgradeReviewDetails

        return UpgradeReviewDetails(
            request_id=request_id,
            track=Track(
                id="gone", title="Gone", artist="Gone", album="",
                duration_ms=0,
            ),
            quality_descriptor=None, current_description="",
            old_file_path=None,
        )

    def get_upgrade_review_details(self, request_id):
        return self._details_by_id[request_id]

    def apply_upgrade_decision(self, request_id, replace, delete_old):
        self.decisions.append((request_id, replace, delete_old))
        return self._message if replace else None


def _upgrade(request_id, old_file_path="/music/old.mp3"):
    from seeker.models.upgrade_review import UpgradeReviewDetails

    return UpgradeReviewDetails(
        request_id=request_id,
        track=Track(
            id=f"t{request_id}", title=f"Title {request_id}",
            artist="Artist", album="Album", duration_ms=200_000,
        ),
        quality_descriptor="flac 1000kbps", current_description="mp3",
        old_file_path=old_file_path,
    )


def test_downloads_review_asks_per_upgrade_and_applies_each_answer(
        tmp_path, capsys, monkeypatch,
):
    review_service = FakeReviewServiceForOneByOne(
        {1: _upgrade(1), 2: _upgrade(2), 3: _upgrade(3, old_file_path=None)},
    )
    # 1: replace, delete the old file. 2: decline. 3: replace; no old
    # file, so no delete question.
    prompts = _answer(monkeypatch, "y", "y", "n", "y")

    cli.run(
        FakeApplication(make_matcher(tmp_path), review_service=review_service),
        ["downloads", "review"],
    )

    assert review_service.decisions == [
        (1, True, True), (2, False, False), (3, True, False),
    ]
    assert len(prompts) == 4
    assert "Delete old file at /music/old.mp3?" in prompts[1]
    assert capsys.readouterr().out == "  Replaced.\n  Replaced.\n"


def test_downloads_review_skips_an_upgrade_resolved_meanwhile(
        tmp_path, monkeypatch,
):
    review_service = FakeReviewServiceForOneByOne({7: None})
    prompts = _answer(monkeypatch)

    cli.run(
        FakeApplication(make_matcher(tmp_path), review_service=review_service),
        ["downloads", "review"],
    )

    assert prompts == []
    assert review_service.decisions == []


# --- library add, list, match ----------------------------------------


class FakeLibraryServiceForLocations:
    def __init__(self, locations=None, add_error=None):
        self._locations = locations or []
        self._add_error = add_error
        self.add_location_calls: list[tuple[str, str]] = []

    def add_location(self, name, path):
        self.add_location_calls.append((name, path))
        if self._add_error is not None:
            raise self._add_error

    def list_locations(self):
        return self._locations


def test_library_add_registers_the_location(tmp_path):
    library_service = FakeLibraryServiceForLocations()

    cli.run(
        FakeApplication(
            make_matcher(tmp_path), library_service=library_service,
        ),
        ["library", "add", "Music", "/music"],
    )

    assert library_service.add_location_calls == [("Music", "/music")]


def test_library_add_of_a_missing_path_exits_with_the_reason(
        tmp_path, capsys,
):
    from seeker.library.scanner import LibraryUnavailableError

    library_service = FakeLibraryServiceForLocations(
        add_error=LibraryUnavailableError(Path("/Volumes/Gone/Music")),
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.run(
            FakeApplication(
                make_matcher(tmp_path), library_service=library_service,
            ),
            ["library", "add", "Music", "/Volumes/Gone/Music"],
        )

    assert exit_info.value.code == 1
    assert "may not be connected" in capsys.readouterr().out


def test_library_list_shows_each_location_and_whether_it_is_reachable(
        tmp_path, capsys,
):
    from seeker.models.library_location import LibraryLocation

    library_service = FakeLibraryServiceForLocations([
        (LibraryLocation("Music", "/music", "2026-01-01", id=1), True),
        (LibraryLocation("X9", "/Volumes/X9", "2026-01-01", id=2), False),
    ])

    cli.run(
        FakeApplication(
            make_matcher(tmp_path), library_service=library_service,
        ),
        ["library", "list"],
    )

    assert capsys.readouterr().out == (
        "Music: /music (reachable)\n"
        "X9: /Volumes/X9 (unreachable)\n"
    )


def test_library_list_with_no_locations_says_so(tmp_path, capsys):
    cli.run(
        FakeApplication(
            make_matcher(tmp_path),
            library_service=FakeLibraryServiceForLocations(),
        ),
        ["library", "list"],
    )

    assert capsys.readouterr().out == "No library locations registered.\n"


def test_library_match_runs_the_matcher(tmp_path):
    class RecordingMatcher:
        match_all_calls = 0

        def match_all(self):
            self.match_all_calls += 1

    matcher = RecordingMatcher()

    cli.run(FakeApplication(matcher), ["library", "match"])

    assert matcher.match_all_calls == 1


# --- no command ------------------------------------------------------


def test_no_command_prints_help_and_exits_cleanly(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.parse_args([])

    assert exit_info.value.code == 0
    assert "usage:" in capsys.readouterr().out


def _every_parser(parser: argparse.ArgumentParser):
    yield parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for subparser in action.choices.values():
                yield from _every_parser(subparser)


def test_no_help_text_carries_development_history():
    # --help is user-facing copy; a roadmap or round number means
    # nothing to the person reading it.
    history = re.compile(r"[Rr]oadmap item|[Rr]ound [0-9]|item [0-9]|§[0-9]")

    leaks = [
        f"{parser.prog}: {match.group(0)}"
        for parser in _every_parser(cli.build_parser())
        for match in [history.search(parser.format_help())]
        if match
    ]

    assert leaks == []
