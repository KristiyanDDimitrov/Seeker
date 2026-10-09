"""Where a finished download lands, and what it may never destroy.

The five invariants these tests pin (HISTORY §138):

1. No file that existed before the operation is destroyed, except the
   current file of an upgrade confirmed with "Delete old file".
2. After a successful move, the track's match points at a
   `local_files` row whose file exists and holds the downloaded
   content.
3. The delete-old step never deletes the file the match now points at.
4. A settled download never replaces an existing file: it gets the
   shared collision suffix.
5. A request whose file cannot be located unambiguously is left for
   the next poll, never guessed, and the condition is logged once.
"""
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from db_seed import add_playlist_track
from seeker.database.connection import Database
from seeker.database.repositories.download_request_repository import (
    DownloadRequestRepository,
)
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.playlist_repository import (
    PlaylistRepository,
)
from seeker.database.repositories.soulseek_review_candidate_repository import (
    SoulseekReviewCandidateRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.library.scanner import index_single_file
from seeker.models.download_request import DownloadRequest
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch
from seeker.soulseek.download_service import DownloadService
from service_seams import review_service_for
from test_download_service import FakeSoulseekClient


@dataclass
class Scenario:
    service: DownloadService
    location: LibraryLocation
    destination: Path
    slskd: Path

    def request_id(self) -> int:
        with self.service.database.transaction() as connection:
            row = connection.execute(
                "SELECT id FROM download_requests",
            ).fetchone()
        return int(row["id"])

    def status(self) -> str:
        with self.service.database.transaction() as connection:
            row = connection.execute(
                "SELECT status FROM download_requests",
            ).fetchone()
        return str(row["status"])

    def matched_path(self) -> Path | None:
        """The file the track's match points at, or None."""
        with self.service.database.transaction() as connection:
            match = self.service.track_matches.get_by_track_id(
                "t1", connection,
            )
            if match is None or match.local_file_id is None:
                return None
            local_file = self.service.local_files.get_by_id(
                match.local_file_id, connection,
            )
            assert local_file is not None
            location = self.service.locations.get_by_id(
                local_file.location_id, connection,
            )
        assert location is not None
        return Path(location.path) / local_file.relative_path

    def local_file_paths(self) -> list[str]:
        with self.service.database.transaction() as connection:
            rows = connection.execute(
                "SELECT relative_path FROM local_files ORDER BY id",
            ).fetchall()
        return [row["relative_path"] for row in rows]


def make_scenario(
        tmp_path: Path,
        states: dict[str, str] | None = None,
) -> Scenario:
    """Location `Lib` at `lib/`, playlist `p1` with destination
    (`Lib`, `"P"`), track `t1` on it, and an empty slskd download
    directory — probe A.1's setup (BRIEF Appendix A)."""
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    lib_root = tmp_path / "lib"
    lib_root.mkdir()
    slskd = tmp_path / "slskd"
    slskd.mkdir()

    locations = LibraryLocationRepository()
    playlists = PlaylistRepository()
    tracks = TrackRepository()

    with database.transaction() as connection:
        locations.add(
            LibraryLocation(name="Lib", path=str(lib_root), added_at="x"),
            connection,
        )
        location = locations.get_by_name("Lib", connection)
        assert location is not None
        playlists.save(Playlist(id="p1", name="P", track_count=1), connection)
        playlists.set_destination("p1", location.id, "P", connection)
        tracks.save(
            Track(
                id="t1", title="Song", artist="Artist", album="Album",
                duration_ms=1000,
            ),
            connection,
        )
        add_playlist_track("p1", "t1", connection)

    service = DownloadService(
        database,
        FakeSoulseekClient(states or {}),
        playlists,
        tracks,
        locations,
        DownloadRequestRepository(),
        TrackMatchRepository(),
        LocalFileRepository(),
        SoulseekReviewCandidateRepository(),
        str(slskd),
    )

    return Scenario(service, location, lib_root / "P", slskd)


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def add_request(
        scenario: Scenario,
        filename: str,
        size: int | None,
        role: str = "settled",
        status: str = "downloading",
        transfer_id: str | None = "tx-1",
) -> None:
    with scenario.service.database.transaction() as connection:
        scenario.service.download_requests.add(
            DownloadRequest(
                track_id="t1",
                username="peer",
                filename=filename,
                format=Path(filename.replace("\\", "/")).suffix[1:],
                role=role,
                status=status,
                transfer_id=transfer_id,
                size=size,
                requested_at="x",
            ),
            connection,
        )


def match_existing_file(scenario: Scenario, relative_path: str) -> int:
    """Indexes `lib/<relative_path>` and auto-matches `t1` to it."""
    with scenario.service.database.transaction() as connection:
        local_file = index_single_file(
            scenario.location, relative_path,
            scenario.service.local_files, connection,
        )
        assert local_file.id is not None
        scenario.service.track_matches.upsert(
            TrackMatch(
                track_id="t1", matched_at="x",
                local_file_id=local_file.id, match_method="auto", score=90.0,
            ),
            connection,
        )
    return local_file.id


def seed_upgrade(
        tmp_path: Path,
        old_name: str,
        new_name: str,
) -> tuple[Scenario, Path, Path]:
    scenario = make_scenario(tmp_path)
    old = write(scenario.destination / old_name, "OLD")
    new = write(scenario.slskd / "Music" / new_name, "NEW upgrade")
    match_existing_file(scenario, f"P/{old_name}")
    add_request(
        scenario,
        f"@@peer\\Music\\{new_name}",
        size=len("NEW upgrade"),
        role="upgrade",
        status="ready_for_review",
    )
    return scenario, old, new


# --- Upgrades (probe A.1) ---------------------------------------------


def test_same_name_upgrade_with_delete_old_keeps_the_new_file(tmp_path):
    scenario, old, _ = seed_upgrade(
        tmp_path, "Artist - Song.mp3", "Artist - Song.mp3",
    )
    with scenario.service.database.transaction() as connection:
        old_row_id = scenario.service.local_files.get_by_location_and_relative_path(
            scenario.location.id, "P/Artist - Song.mp3", connection,
        ).id

    message = review_service_for(scenario.service).apply_upgrade_decision(
        scenario.request_id(), replace=True, delete_old=True,
    )

    # Invariants 2 and 3: the track's file exists and is the upgrade.
    assert old.read_text() == "NEW upgrade"
    assert scenario.matched_path() == old
    assert scenario.local_file_paths() == ["P/Artist - Song.mp3"]
    assert scenario.status() == "completed"
    assert message is not None
    assert "Deleted" not in message
    # The swap keeps the row; nothing measured on the old content
    # survives onto the new content.
    with scenario.service.database.transaction() as connection:
        row = scenario.service.local_files.get_by_location_and_relative_path(
            scenario.location.id, "P/Artist - Song.mp3", connection,
        )
    assert row.id == old_row_id
    assert row.size_bytes == len("NEW upgrade")


def test_same_name_swap_clears_analysis_measured_on_the_old_content(
        tmp_path,
):
    scenario, _, _ = seed_upgrade(
        tmp_path, "Artist - Song.mp3", "Artist - Song.mp3",
    )
    with scenario.service.database.transaction() as connection:
        row = scenario.service.local_files.get_by_location_and_relative_path(
            scenario.location.id, "P/Artist - Song.mp3", connection,
        )
        scenario.service.local_files.update_analysis(
            row.id, 128.0, "8A", 0.9, connection,
        )
        scenario.service.local_files.update_fingerprint(
            row.id, "AQAA", 1.0, "x", connection,
        )
        scenario.service.local_files.mark_tagged(row.id, "x", connection)

    review_service_for(scenario.service).apply_upgrade_decision(
        scenario.request_id(), replace=True, delete_old=True,
    )

    with scenario.service.database.transaction() as connection:
        (after,) = [
            local_file
            for local_file in (
                scenario.service.local_files
                .get_all_for_location_with_fingerprints(
                    scenario.location.id, connection,
                )
            )
            if local_file.id == row.id
        ]
    assert after.bpm is None
    assert after.camelot_key is None
    assert after.fingerprint is None
    assert after.tagged_at is None


def test_same_name_upgrade_without_delete_old_keeps_both_files(tmp_path):
    scenario, old, _ = seed_upgrade(
        tmp_path, "Artist - Song.mp3", "Artist - Song.mp3",
    )

    message = review_service_for(scenario.service).apply_upgrade_decision(
        scenario.request_id(), replace=True, delete_old=False,
    )

    # Invariant 1: the old file is untouched.
    assert old.read_text() == "OLD"
    new = scenario.destination / "Artist - Song (2).mp3"
    assert new.read_text() == "NEW upgrade"
    assert scenario.matched_path() == new
    assert message is not None
    assert "Leaving" in message


def test_differently_named_upgrade_with_delete_old_removes_row_then_file(
        tmp_path,
):
    scenario, old, _ = seed_upgrade(
        tmp_path, "old.mp3", "Artist - Song.flac",
    )

    message = review_service_for(scenario.service).apply_upgrade_decision(
        scenario.request_id(), replace=True, delete_old=True,
    )

    new = scenario.destination / "Artist - Song.flac"
    assert not old.exists()
    assert new.read_text() == "NEW upgrade"
    assert scenario.matched_path() == new
    # No row left behind for a file that no longer exists.
    assert scenario.local_file_paths() == ["P/Artist - Song.flac"]
    assert message is not None
    assert "Deleted" in message


def test_upgrade_never_overwrites_an_unrelated_same_named_file(tmp_path):
    # The current file is old.mp3; an unrelated file already holds the
    # upgrade's name. With delete-old checked, only old.mp3 may go.
    scenario, old, _ = seed_upgrade(
        tmp_path, "old.mp3", "Artist - Song.flac",
    )
    unrelated = write(scenario.destination / "Artist - Song.flac", "OTHER")

    review_service_for(scenario.service).apply_upgrade_decision(
        scenario.request_id(), replace=True, delete_old=True,
    )

    assert unrelated.read_text() == "OTHER"
    assert not old.exists()
    new = scenario.destination / "Artist - Song (2).flac"
    assert new.read_text() == "NEW upgrade"
    assert scenario.matched_path() == new


# --- Settled downloads (probe A.2) ------------------------------------


def test_settled_download_never_overwrites_a_different_same_named_file(
        tmp_path,
):
    scenario = make_scenario(tmp_path, {"tx-1": "Completed, Succeeded"})
    existing = write(
        scenario.destination / "01 - Intro.mp3",
        "USER'S EXISTING FILE (different song)",
    )
    write(scenario.slskd / "AlbumA" / "01 - Intro.mp3", "download for A")
    add_request(scenario, "@@peer\\AlbumA\\01 - Intro.mp3", size=14)

    scenario.service.poll_downloads()

    assert existing.read_text() == "USER'S EXISTING FILE (different song)"
    new = scenario.destination / "01 - Intro (2).mp3"
    assert new.read_text() == "download for A"
    assert scenario.matched_path() == new
    assert scenario.status() == "completed"


def test_same_named_downloads_resolve_by_remote_parent_folder(tmp_path):
    # Same name AND same size: only the remote parent folder tells them
    # apart. A whole-tree search's order would decide otherwise.
    scenario = make_scenario(tmp_path, {"tx-1": "Completed, Succeeded"})
    write(scenario.slskd / "AlbumA" / "01 - Intro.mp3", "download for A")
    write(scenario.slskd / "AlbumB" / "01 - Intro.mp3", "download for B")
    add_request(scenario, "@@peer\\Music\\AlbumA\\01 - Intro.mp3", size=14)

    scenario.service.poll_downloads()

    assert (scenario.destination / "01 - Intro.mp3").read_text() == (
        "download for A"
    )
    assert (scenario.slskd / "AlbumB" / "01 - Intro.mp3").exists()


def test_same_named_downloads_resolve_by_exact_size_in_the_fallback(
        tmp_path,
):
    # Neither file sits under the remote parent's name, so the
    # whole-tree fallback runs; the exact byte size picks the file.
    scenario = make_scenario(tmp_path, {"tx-1": "Completed, Succeeded"})
    write(scenario.slskd / "X" / "01 - Intro.mp3", "download for A")
    write(scenario.slskd / "Y" / "01 - Intro.mp3", "download for B, longer")
    add_request(scenario, "@@peer\\Music\\01 - Intro.mp3", size=22)

    scenario.service.poll_downloads()

    assert (scenario.destination / "01 - Intro.mp3").read_text() == (
        "download for B, longer"
    )


def test_slskd_tick_suffixed_copy_is_found_by_size(tmp_path):
    # slskd appends _<UtcNow.Ticks> on a name clash (FileService.MoveFile).
    scenario = make_scenario(tmp_path, {"tx-1": "Completed, Succeeded"})
    write(scenario.slskd / "LOGIC" / "05 - Buried Alive.flac", "earlier")
    write(
        scenario.slskd / "LOGIC" / "05 - Buried Alive_639239396236841232.flac",
        "the requested download",
    )
    add_request(scenario, "@@peer\\LOGIC\\05 - Buried Alive.flac", size=22)

    scenario.service.poll_downloads()

    assert (scenario.destination / "05 - Buried Alive.flac").read_text() == (
        "the requested download"
    )
    assert (scenario.slskd / "LOGIC" / "05 - Buried Alive.flac").exists()


def test_several_same_size_candidates_take_the_newest(tmp_path):
    scenario = make_scenario(tmp_path, {"tx-1": "Completed, Succeeded"})
    older = write(scenario.slskd / "A" / "Song.mp3", "same bytes 1")
    newer = write(scenario.slskd / "A" / "Song_638000000000000000.mp3",
                  "same bytes 2")
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))
    add_request(scenario, "@@peer\\A\\Song.mp3", size=12)

    scenario.service.poll_downloads()

    assert (scenario.destination / "Song.mp3").read_text() == "same bytes 2"


def test_ambiguous_download_is_left_for_the_next_poll_and_logged_once(
        tmp_path, caplog,
):
    # Size unknown and two candidates: refuse to guess (invariant 5).
    scenario = make_scenario(tmp_path, {"tx-1": "Completed, Succeeded"})
    write(scenario.slskd / "X" / "01 - Intro.mp3", "download for A")
    write(scenario.slskd / "Y" / "01 - Intro.mp3", "download for B")
    add_request(scenario, "@@peer\\Music\\01 - Intro.mp3", size=None)

    with caplog.at_level(logging.WARNING, logger="seeker"):
        scenario.service.poll_downloads()
        scenario.service.poll_downloads()

    assert not scenario.destination.exists()
    assert scenario.status() == "downloading"
    assert scenario.matched_path() is None
    ambiguous = [
        record for record in caplog.records
        if "01 - Intro.mp3" in record.getMessage()
    ]
    assert len(ambiguous) == 1


def test_no_candidate_of_the_requested_size_is_never_guessed(tmp_path):
    scenario = make_scenario(tmp_path, {"tx-1": "Completed, Succeeded"})
    stray = write(scenario.slskd / "A" / "Song.mp3", "a different file")
    add_request(scenario, "@@peer\\A\\Song.mp3", size=999)

    scenario.service.poll_downloads()

    assert stray.exists()
    assert scenario.status() == "downloading"


def test_a_dot_dot_basename_is_unlocatable(tmp_path):
    scenario = make_scenario(tmp_path, {"tx-1": "Completed, Succeeded"})
    write(scenario.slskd / "A" / "Song.mp3", "x")
    add_request(scenario, "@@peer\\A\\..", size=None)

    scenario.service.poll_downloads()

    assert scenario.status() == "downloading"
    assert (scenario.slskd / "A" / "Song.mp3").exists()


@pytest.mark.parametrize(
    ("peer_name", "placed_name"),
    [
        # Finder hides a dot-led name.
        (".hidden.mp3", "_hidden.mp3"),
        # U+202E reverses what follows: Finder shows "cover3pm.jpg".
        ("cover\u202egpj.mp3", "covergpj.mp3"),
        # 284 UTF-8 bytes: APFS takes it (its limit counts characters),
        # ext4 and ExFAT library drives refuse it. The extension stays.
        ("é" * 140 + ".mp3", "é" * 125 + ".mp3"),
    ],
)
def test_a_peers_basename_is_cleaned_before_it_is_placed(
        tmp_path, peer_name, placed_name,
):
    scenario = make_scenario(tmp_path, {"tx-1": "Completed, Succeeded"})
    source = write(scenario.slskd / "Album" / peer_name, "download")
    add_request(scenario, f"@@peer\\Music\\Album\\{peer_name}", size=8)

    scenario.service.poll_downloads()

    assert scenario.status() == "completed"
    assert not source.exists()
    assert scenario.matched_path() == scenario.destination / placed_name
    assert (scenario.destination / placed_name).read_text() == "download"
