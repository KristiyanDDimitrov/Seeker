
import httpx
import pytest

from db_seed import add_playlist_track
from seeker.config_store import SeekerConfig
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
from seeker.models.download_result import TrackFailure
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.models.soulseek_file import SoulseekFile
from seeker.models.track import Track
from seeker.soulseek.client import SlskdUnreachableError
from seeker.soulseek.download_service import DownloadService
from seeker.soulseek.sweep import SweepService


class FakeSlskd:
    """slskd's search and enqueue: a query's candidates, or the error
    its search raises."""

    base_url = "http://localhost:5030"

    def __init__(self, results: dict[str, list[SoulseekFile] | Exception]):
        self.results = results
        self.searches: list[str] = []
        self.requested: list[str] = []

    def search(self, query: str) -> list[SoulseekFile]:
        self.searches.append(query)
        result = self.results.get(query, [])

        if isinstance(result, Exception):
            raise result

        return result

    def request_download(self, username: str, filename: str, size: int) -> str:
        self.requested.append(filename)
        return f"transfer-{filename}"


class Sweep:
    """A SweepService over a real database, with the stamps it made."""

    def __init__(self, tmp_path, slskd: FakeSlskd, config: SeekerConfig):
        self.database = Database(tmp_path / "seeker.db")
        self.database.initialize()
        self.slskd = slskd
        self.config = config
        self.stamps: list[str] = []
        self.library = tmp_path / "music"
        self.library.mkdir()
        self.downloads = DownloadService(
            self.database,
            slskd,  # type: ignore[arg-type]
            PlaylistRepository(),
            TrackRepository(),
            LibraryLocationRepository(),
            DownloadRequestRepository(),
            TrackMatchRepository(),
            LocalFileRepository(),
            SoulseekReviewCandidateRepository(),
            slskd_download_dir=None,
            get_config=lambda: self.config,
        )

    def service(self, max_searches: int = 50) -> SweepService:
        return SweepService(
            self.database,
            lambda: self.downloads,
            PlaylistRepository(),
            TrackRepository(),
            get_config=lambda: self.config,
            record_sweep=self.stamps.append,
            max_searches=max_searches,
        )

    def add_playlist(
            self,
            name: str,
            track_ids: list[str],
            loaded: bool = True,
            destination: bool = True,
    ) -> None:
        with self.database.transaction() as connection:
            locations = LibraryLocationRepository()
            location = locations.get_by_name("Main", connection)
            if location is None:
                locations.add(
                    LibraryLocation(
                        name="Main", path=str(self.library),
                        added_at="2026-01-01",
                    ),
                    connection,
                )
                location = locations.get_by_name("Main", connection)
            playlists = PlaylistRepository()
            playlists.save(
                Playlist(
                    id=name, name=name, track_count=len(track_ids),
                    snapshot_id="s1",
                ),
                connection,
            )
            if loaded:
                playlists.mark_tracks_loaded(name, "s1", connection)
            if destination:
                playlists.set_destination(name, location.id, None, connection)
            for track_id in track_ids:
                TrackRepository().save(
                    Track(
                        id=track_id, title=f"Title {track_id}",
                        artist="Dom Dolla", album="Album",
                        duration_ms=200_000,
                    ),
                    connection,
                )
                add_playlist_track(name, track_id, connection)


def candidate(track_id: str) -> SoulseekFile:
    return SoulseekFile(
        username="peer", filename=f"Dom Dolla - Title {track_id}.flac",
        extension="flac", size=1_000_000, queue_length=0,
        upload_speed=1_000_000, has_free_upload_slot=True,
    )


def query(track_id: str) -> str:
    return f"Dom Dolla Title {track_id}"


def test_sweep_searches_the_missing_tracks_of_loaded_playlists_only(tmp_path):
    sweep = Sweep(
        tmp_path, FakeSlskd({query("t1"): [candidate("t1")]}), SeekerConfig(),
    )
    sweep.add_playlist("Loaded", ["t1", "t2"])
    sweep.add_playlist("Never opened", ["t3"], loaded=False)

    result = sweep.service().run_sweep()

    assert sorted(sweep.slskd.searches) == [query("t1"), query("t2")]
    assert sweep.slskd.requested == ["Dom Dolla - Title t1.flac"]
    assert result.requested == ["Dom Dolla - Title t1"]
    assert result.still_missing == ["Dom Dolla - Title t2"]
    assert result.searched == 2
    assert len(sweep.stamps) == 1


def test_sweep_names_a_loaded_playlist_it_cannot_download_into(tmp_path):
    sweep = Sweep(tmp_path, FakeSlskd({}), SeekerConfig())
    sweep.add_playlist("No destination", ["t1"], destination=False)

    result = sweep.service().run_sweep()

    assert sweep.slskd.searches == []
    assert result.playlists_without_destination == ["No destination"]


def test_a_capped_sweep_leaves_the_rest_for_the_next_one_oldest_first(
        tmp_path,
):
    sweep = Sweep(tmp_path, FakeSlskd({}), SeekerConfig())
    sweep.add_playlist("Loaded", ["t1", "t2", "t3"])

    first = sweep.service(max_searches=2).run_sweep()
    sweep.slskd.searches.clear()
    second = sweep.service(max_searches=2).run_sweep()

    assert first.deferred == ["Dom Dolla - Title t3"]
    # t3 was never searched; t1 was searched before t2.
    assert sweep.slskd.searches == [query("t3"), query("t1")]
    assert second.deferred == ["Dom Dolla - Title t2"]


def test_a_track_already_downloading_does_not_spend_the_cap(tmp_path):
    sweep = Sweep(
        tmp_path, FakeSlskd({query("t1"): [candidate("t1")]}), SeekerConfig(),
    )
    sweep.add_playlist("Loaded", ["t1", "t2", "t3"])
    sweep.downloads.download_playlist("Loaded")
    sweep.slskd.searches.clear()

    result = sweep.service(max_searches=2).run_sweep()

    assert result.already_in_progress == ["Dom Dolla - Title t1"]
    assert sorted(sweep.slskd.searches) == [query("t2"), query("t3")]
    assert result.deferred == []


def test_an_outage_stops_the_sweep_at_once_and_records_no_sweep(tmp_path):
    sweep = Sweep(
        tmp_path,
        FakeSlskd({query("t1"): httpx.ConnectError("connection refused")}),
        SeekerConfig(),
    )
    sweep.add_playlist("Loaded", ["t1", "t2"])

    with pytest.raises(SlskdUnreachableError):
        sweep.service().run_sweep()

    assert sweep.slskd.searches == [query("t1")]
    assert sweep.stamps == []


def test_one_tracks_failure_is_counted_and_the_sweep_goes_on(tmp_path):
    sweep = Sweep(
        tmp_path,
        FakeSlskd({query("t1"): RuntimeError("malformed response")}),
        SeekerConfig(),
    )
    sweep.add_playlist("Loaded", ["t1", "t2"])

    result = sweep.service().run_sweep()

    assert result.failures == [
        TrackFailure("Dom Dolla - Title t1", "malformed response"),
    ]
    assert result.still_missing == ["Dom Dolla - Title t2"]
    assert len(sweep.stamps) == 1


def test_a_paused_sweep_searches_nothing_and_records_no_sweep(tmp_path):
    sweep = Sweep(tmp_path, FakeSlskd({}), SeekerConfig(downloads_paused=True))
    sweep.add_playlist("Loaded", ["t1"])

    result = sweep.service().run_sweep()

    assert result.paused is True
    assert sweep.slskd.searches == []
    assert sweep.stamps == []


def test_pausing_mid_sweep_stops_before_the_next_search(tmp_path):
    sweep = Sweep(tmp_path, FakeSlskd({}), SeekerConfig())
    sweep.add_playlist("Loaded", ["t1", "t2"])
    search = sweep.slskd.search

    def search_then_pause(text: str) -> list[SoulseekFile]:
        sweep.config = SeekerConfig(downloads_paused=True)
        return search(text)

    sweep.slskd.search = search_then_pause  # type: ignore[method-assign]

    result = sweep.service().run_sweep()

    assert result.paused is True
    assert sweep.slskd.searches == [query("t1")]
    assert result.still_missing == ["Dom Dolla - Title t1"]
    assert sweep.stamps == []
