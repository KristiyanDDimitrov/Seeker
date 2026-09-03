from pathlib import Path

import pytest

from seeker.library.metadata_service import PlaylistNotFoundError
from seeker.models.local_file import LocalFile
from seeker.models.playlist import Playlist
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch

from test_metadata_service import make_service, seed_location, seed_matched_track


def _seed_playlist_with_track(service, track_id: str) -> None:
    with service.database.transaction() as connection:
        service.playlists.save(
            Playlist(id="p1", name="Test Playlist", track_count=1),
            connection,
        )
        service.tracks.save_playlist_track("p1", track_id, connection)


def _write_real_file(path: Path, content: bytes = b"fake-audio-bytes") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


# --- plan_renames -----------------------------------------------------

def test_plan_renames_raises_when_playlist_not_synced(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(PlaylistNotFoundError, match="never-synced"):
        service.plan_renames(playlist_name="never-synced")


def test_plan_renames_requires_exactly_one_of_playlist_or_track_ids(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(ValueError):
        service.plan_renames()

    with pytest.raises(ValueError):
        service.plan_renames(playlist_name="x", track_ids=["t1"])


def test_plan_renames_flags_needs_review_track_as_not_auto_matched(tmp_path):
    root = tmp_path / "music"
    _write_real_file(root / "song.mp3")

    service = make_service(tmp_path)
    location = seed_location(service, root)

    with service.database.transaction() as connection:
        service.tracks.save(
            Track(
                id="t1", title="Title", artist="Artist", album="Album",
                duration_ms=1000,
            ),
            connection,
        )
        service.local_files.upsert(
            LocalFile(
                location_id=location.id, relative_path="song.mp3",
                filename="song.mp3", format="mp3", size_bytes=1,
                mtime=1.0, scanned_at="2026-01-01",
            ),
            connection,
        )
        local_file = service.local_files.get_by_location_and_relative_path(
            location.id, "song.mp3", connection
        )
        service.track_matches.upsert(
            TrackMatch(
                track_id="t1", local_file_id=local_file.id,
                match_method="needs_review", score=75.0,
                matched_at="2026-01-01",
            ),
            connection,
        )

    _seed_playlist_with_track(service, "t1")

    plans = service.plan_renames(playlist_name="Test Playlist")

    assert len(plans) == 1
    assert plans[0].action == "not_auto_matched"
    assert plans[0].current_path is None


def test_plan_renames_flags_missing_local_file_as_no_local_file(tmp_path):
    # An 'auto' match with no local_file_id at all -- the schema's own
    # FK (local_file_id REFERENCES local_files(id) ON DELETE SET NULL)
    # means this, not a dangling id pointing nowhere, is the real
    # reachable shape of "no local file."
    service = make_service(tmp_path)

    with service.database.transaction() as connection:
        service.tracks.save(
            Track(
                id="t1", title="Title", artist="Artist", album="Album",
                duration_ms=1000,
            ),
            connection,
        )
        service.track_matches.upsert(
            TrackMatch(
                track_id="t1", local_file_id=None,
                match_method="auto", score=100.0, matched_at="2026-01-01",
            ),
            connection,
        )

    _seed_playlist_with_track(service, "t1")

    plans = service.plan_renames(playlist_name="Test Playlist")

    assert plans[0].action == "no_local_file"


def test_plan_renames_already_correct_when_filename_already_matches(tmp_path):
    root = tmp_path / "music"
    dest = root / "Test Artist - Test Title.mp3"
    _write_real_file(dest)

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "Test Artist - Test Title.mp3",
        artist="Test Artist", title="Test Title",
    )
    _seed_playlist_with_track(service, "t1")

    plans = service.plan_renames(playlist_name="Test Playlist")

    assert plans[0].action == "already_correct"
    assert plans[0].current_path == dest
    assert plans[0].proposed_path == dest


def test_plan_renames_proposes_a_real_rename(tmp_path):
    root = tmp_path / "music"
    dest = root / "wrong_name.mp3"
    _write_real_file(dest)

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "wrong_name.mp3",
        artist="Real Artist", title="Real Title",
    )
    _seed_playlist_with_track(service, "t1")

    plans = service.plan_renames(playlist_name="Test Playlist")

    assert plans[0].action == "rename"
    assert plans[0].proposed_path == root / "Real Artist - Real Title.mp3"


def test_plan_renames_via_explicit_track_ids(tmp_path):
    root = tmp_path / "music"
    _write_real_file(root / "wrong_name.mp3")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "wrong_name.mp3",
        artist="Real Artist", title="Real Title",
    )

    plans = service.plan_renames(track_ids=["t1"])

    assert len(plans) == 1
    assert plans[0].track_id == "t1"
    assert plans[0].action == "rename"


# --- apply_renames ------------------------------------------------------

def test_apply_renames_moves_the_real_file_and_updates_the_db(tmp_path):
    root = tmp_path / "music"
    dest = root / "wrong_name.mp3"
    _write_real_file(dest, b"real-audio-content")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "wrong_name.mp3",
        artist="Real Artist", title="Real Title",
    )
    _seed_playlist_with_track(service, "t1")

    plans = service.plan_renames(playlist_name="Test Playlist")
    result = service.apply_renames(plans)

    assert result.renamed == 1
    assert result.failed == 0

    new_path = root / "Real Artist - Real Title.mp3"
    assert new_path.exists()
    assert new_path.read_bytes() == b"real-audio-content"
    assert not dest.exists()

    with service.database.transaction() as connection:
        local_file = service.local_files.get_by_id(
            plans[0].local_file_id, connection,
        )
        # track_matches still resolves to the SAME local_file_id -- never
        # delete-and-reinsert.
        match = service.track_matches.get_by_track_id("t1", connection)

    assert local_file.relative_path == "Real Artist - Real Title.mp3"
    assert local_file.filename == "Real Artist - Real Title.mp3"
    assert match.local_file_id == local_file.id


def test_apply_renames_case_only_change_on_a_real_filesystem(tmp_path):
    # tmp_path is on the same (default, case-insensitive) APFS volume
    # as the rest of this machine's real filesystem on macOS -- a real,
    # not simulated, exercise of the two-step rename path (item 67
    # Phase 6.2).
    root = tmp_path / "music"
    dest = root / "artist - title.mp3"
    _write_real_file(dest, b"case-only-rename-content")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "artist - title.mp3",
        artist="Artist", title="Title",
    )
    _seed_playlist_with_track(service, "t1")

    plans = service.plan_renames(playlist_name="Test Playlist")
    assert plans[0].action == "rename"

    result = service.apply_renames(plans)

    assert result.renamed == 1
    new_path = root / "Artist - Title.mp3"
    assert new_path.exists()
    assert new_path.read_bytes() == b"case-only-rename-content"
    # Exactly one real file on disk, not two.
    assert len(list(root.iterdir())) == 1


def test_apply_renames_resolves_a_real_collision_with_a_numbered_suffix(
        tmp_path,
):
    root = tmp_path / "music"
    dest = root / "wrong_name.mp3"
    _write_real_file(dest, b"track-being-renamed")
    # A genuinely different, pre-existing file already at the target name.
    _write_real_file(root / "Real Artist - Real Title.mp3", b"unrelated-file")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "wrong_name.mp3",
        artist="Real Artist", title="Real Title",
    )
    _seed_playlist_with_track(service, "t1")

    plans = service.plan_renames(playlist_name="Test Playlist")
    assert plans[0].action == "collision"

    result = service.apply_renames(plans)

    assert result.renamed == 1
    assert (root / "Real Artist - Real Title (2).mp3").exists()
    assert (root / "Real Artist - Real Title (2).mp3").read_bytes() == (
        b"track-being-renamed"
    )
    # The pre-existing, unrelated file is untouched.
    assert (root / "Real Artist - Real Title.mp3").read_bytes() == (
        b"unrelated-file"
    )


def test_apply_renames_renames_the_appledouble_sidecar_alongside(tmp_path):
    root = tmp_path / "music"
    dest = root / "wrong_name.mp3"
    _write_real_file(dest, b"real-content")
    _write_real_file(root / "._wrong_name.mp3", b"sidecar-content")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "wrong_name.mp3",
        artist="Real Artist", title="Real Title",
    )
    _seed_playlist_with_track(service, "t1")

    plans = service.plan_renames(playlist_name="Test Playlist")
    service.apply_renames(plans)

    new_sidecar = root / "._Real Artist - Real Title.mp3"
    assert new_sidecar.exists()
    assert new_sidecar.read_bytes() == b"sidecar-content"
    assert not (root / "._wrong_name.mp3").exists()


def test_apply_renames_refuses_a_track_no_longer_auto_matched_at_apply_time(
        tmp_path,
):
    root = tmp_path / "music"
    dest = root / "wrong_name.mp3"
    _write_real_file(dest)

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "wrong_name.mp3",
        artist="Real Artist", title="Real Title",
    )
    _seed_playlist_with_track(service, "t1")

    plans = service.plan_renames(playlist_name="Test Playlist")

    # Simulate the match changing between plan and apply (a later
    # match_all() run demoting it, say).
    with service.database.transaction() as connection:
        service.track_matches.upsert(
            TrackMatch(
                track_id="t1", local_file_id=plans[0].local_file_id,
                match_method="needs_review", score=60.0,
                matched_at="2026-01-01",
            ),
            connection,
        )

    result = service.apply_renames(plans)

    assert result.renamed == 0
    assert result.failed == 1
    assert dest.exists()  # untouched
    assert "refused" in result.details[0]["message"]


def test_apply_renames_rolls_back_the_file_when_the_db_update_fails(
        tmp_path, monkeypatch,
):
    root = tmp_path / "music"
    dest = root / "wrong_name.mp3"
    _write_real_file(dest, b"content")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "wrong_name.mp3",
        artist="Real Artist", title="Real Title",
    )
    _seed_playlist_with_track(service, "t1")

    plans = service.plan_renames(playlist_name="Test Playlist")

    def failing_update(*args, **kwargs):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(
        service.local_files, "update_relative_path", failing_update,
    )

    result = service.apply_renames(plans)

    assert result.renamed == 0
    assert result.failed == 1
    # Renamed back -- the original file is exactly where it was.
    assert dest.exists()
    assert dest.read_bytes() == b"content"
    assert not (root / "Real Artist - Real Title.mp3").exists()


def test_apply_renames_end_to_end_multi_artist_feat_accented_and_byte_cap(
        tmp_path,
):
    # Roadmap item 67 (Phase 6.5) -- one real round-trip covering every
    # explicitly-required case at once: multi-artist, a (feat. X) title
    # where X is also a credited artist, an accented name, and a title
    # long enough to hit the byte cap.
    root = tmp_path / "music"
    long_title = "Título con acentos " + ("é" * 100) + " (feat. B)"
    dest = root / "original_download_name.flac"
    _write_real_file(dest, b"multi-artist-content")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "original_download_name.flac",
        artist="A, B", title=long_title,
    )
    _seed_playlist_with_track(service, "t1")

    plans = service.plan_renames(playlist_name="Test Playlist")
    assert plans[0].action == "rename"

    result = service.apply_renames(plans)

    assert result.renamed == 1
    proposed_name = plans[0].proposed_path.name
    assert proposed_name.startswith("A - Título con acentos")  # B deduped
    assert proposed_name.endswith(".flac")
    assert len(proposed_name.encode("utf-8")) <= 255

    real_path = root / proposed_name
    assert real_path.exists()
    assert real_path.read_bytes() == b"multi-artist-content"

    with service.database.transaction() as connection:
        match = service.track_matches.get_by_track_id("t1", connection)
        local_file = service.local_files.get_by_id(
            match.local_file_id, connection,
        )

    # The DB row follows the file, and track_matches still resolves.
    assert local_file.relative_path == proposed_name
    assert local_file.id == plans[0].local_file_id


# --- Roadmap item 76 (P2): within-batch collisions, honest preview
# mismatches, refusing a stale confirmed plan -----------------------------

def test_plan_renames_flags_within_batch_collision_at_plan_time(tmp_path):
    # Roadmap item 76 (P2, 2.2) — the real, CONFIRMED defect: two
    # tracks whose canonical filenames land on the SAME target. Neither
    # target exists on disk yet at plan time, so the OLD per-track-only
    # collision check would show both as clean 'rename' plans -- this
    # must catch it before either file is touched.
    root = tmp_path / "music"
    _write_real_file(root / "download1.mp3")
    _write_real_file(root / "download2.mp3")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "download1.mp3",
        artist="Real Artist", title="Real Title",
    )
    seed_matched_track(
        service, location, "t2", "download2.mp3",
        artist="Real Artist", title="Real Title",
    )
    _seed_playlist_with_track(service, "t1")
    _seed_playlist_with_track(service, "t2")

    plans = service.plan_renames(playlist_name="Test Playlist")

    assert len(plans) == 2
    assert {plan.action for plan in plans} == {"collision"}
    assert all(
        "another track in this same batch" in (plan.message or "")
        for plan in plans
    )


def test_apply_renames_within_batch_collision_resolves_with_suffix_for_one(
        tmp_path,
):
    root = tmp_path / "music"
    _write_real_file(root / "download1.mp3", b"content-1")
    _write_real_file(root / "download2.mp3", b"content-2")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "download1.mp3",
        artist="Real Artist", title="Real Title",
    )
    seed_matched_track(
        service, location, "t2", "download2.mp3",
        artist="Real Artist", title="Real Title",
    )
    _seed_playlist_with_track(service, "t1")
    _seed_playlist_with_track(service, "t2")

    plans = service.plan_renames(playlist_name="Test Playlist")
    result = service.apply_renames(plans)

    assert result.renamed == 2
    assert result.failed == 0
    # Exactly one plain name and one " (2)" suffixed name -- both files
    # survive, neither overwrites the other.
    assert (root / "Real Artist - Real Title.mp3").exists()
    assert (root / "Real Artist - Real Title (2).mp3").exists()
    # Roadmap item 76 (P2, 2.3) -- both plans were previewed as
    # 'collision', but only ONE of them actually ends up with a
    # different real name than previewed (whichever is processed
    # second — the first to reach the target still lands on its own
    # exact previewed name). Reporting the REAL outcome, not the
    # plan-time guess, is the honest behavior.
    assert result.collisions == 1
    mismatch_details = [
        d for d in result.details
        if d["reason"] == "renamed_with_different_name_than_previewed"
    ]
    assert len(mismatch_details) == 1
    assert "Real Artist - Real Title (2).mp3" in mismatch_details[0]["message"]


def test_apply_renames_records_honest_detail_when_resolved_name_differs(
        tmp_path,
):
    # Roadmap item 76 (P2, 2.3) — the exact "preview said X, disk got
    # Y" symptom: a real, different, pre-existing file already at the
    # target name (a genuine filesystem collision, known at plan time).
    root = tmp_path / "music"
    _write_real_file(root / "wrong_name.mp3", b"track-being-renamed")
    _write_real_file(root / "Real Artist - Real Title.mp3", b"unrelated")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "wrong_name.mp3",
        artist="Real Artist", title="Real Title",
    )
    _seed_playlist_with_track(service, "t1")

    plans = service.plan_renames(playlist_name="Test Playlist")
    result = service.apply_renames(plans)

    assert result.renamed == 1
    assert result.collisions == 1
    detail = next(
        d for d in result.details
        if d["reason"] == "renamed_with_different_name_than_previewed"
    )
    assert "Real Artist - Real Title (2).mp3" in detail["message"]
    assert "Real Artist - Real Title.mp3" in detail["message"]


def test_apply_renames_refuses_when_a_new_collision_appears_after_confirm(
        tmp_path,
):
    # Roadmap item 76 (P2, 2.4) — the real, CONFIRMED defect: a modal
    # preview dialog's exec() keeps processing timer events, so a real
    # download landing (or anything else touching this track) between
    # confirm and apply must not silently proceed against a stale plan.
    root = tmp_path / "music"
    _write_real_file(root / "wrong_name.mp3", b"content")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "wrong_name.mp3",
        artist="Real Artist", title="Real Title",
    )
    _seed_playlist_with_track(service, "t1")

    plans = service.plan_renames(playlist_name="Test Playlist")
    assert plans[0].action == "rename"

    # Simulate a real download landing at the target path while the
    # preview dialog was still open, mid-preview.
    _write_real_file(
        root / "Real Artist - Real Title.mp3", b"landed-mid-preview",
    )

    result = service.apply_renames(plans)

    assert result.renamed == 0
    assert result.failed == 1
    assert "plan_changed_since_confirmed" == result.details[0]["reason"]
    # Neither file was touched.
    assert (root / "wrong_name.mp3").read_bytes() == b"content"
    assert (root / "Real Artist - Real Title.mp3").read_bytes() == (
        b"landed-mid-preview"
    )


def test_plan_renames_stale_db_row_after_a_completed_rename_reads_as_collision(
        tmp_path,
):
    # Roadmap item 76 (P2, 2.6) — the REAL failing shape found live in
    # Phase 0.2 against the real production "Test" playlist: a
    # previous rename batch successfully renamed a file on disk, but
    # local_files.relative_path was never reconciled with the new real
    # name (root cause not conclusively identified — see docs/
    # HISTORY.md #71). Reproduces the exact real symptom: local_files
    # still holds the OLD name (which no longer exists on disk), while
    # the file ALREADY sitting at the canonical new name is mistaken
    # for a competing collision rather than recognized as this same
    # track's own already-completed rename. This is a real, understood
    # consequence of DB/disk drift, not a crash or silent data loss —
    # scan_and_match (already this project's designed self-healing
    # path, see item 40) is the real fix for the drift itself; this
    # test documents the mechanism, not a code change to plan_renames.
    root = tmp_path / "music"
    old_path = root / "old_stale_name.mp3"
    _write_real_file(old_path)

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "old_stale_name.mp3",
        artist="Real Artist", title="Real Title",
    )
    _seed_playlist_with_track(service, "t1")

    # Simulate the real Phase 0.2 shape: the file was already renamed
    # on disk (old name gone, new canonical name now sitting there
    # instead), but local_files.relative_path was never reconciled.
    old_path.unlink()
    _write_real_file(root / "Real Artist - Real Title.mp3", b"already-renamed")

    plans = service.plan_renames(playlist_name="Test Playlist")

    assert plans[0].action == "collision"
    assert plans[0].current_path == root / "old_stale_name.mp3"
    assert plans[0].proposed_path == root / "Real Artist - Real Title.mp3"


def test_apply_renames_refuses_when_match_changed_after_confirm(tmp_path):
    # A different, real shape of the same 2.4 defect: the track's own
    # match_method changed (e.g. a background match_all() demoting it)
    # between confirm and apply -- the fresh re-plan now reads
    # 'not_auto_matched' where the confirmed plan said 'rename'.
    root = tmp_path / "music"
    _write_real_file(root / "wrong_name.mp3", b"content")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "wrong_name.mp3",
        artist="Real Artist", title="Real Title",
    )
    _seed_playlist_with_track(service, "t1")

    plans = service.plan_renames(playlist_name="Test Playlist")
    assert plans[0].action == "rename"

    with service.database.transaction() as connection:
        service.track_matches.upsert(
            TrackMatch(
                track_id="t1", local_file_id=plans[0].local_file_id,
                match_method="needs_review", score=60.0,
                matched_at="2026-01-01",
            ),
            connection,
        )

    result = service.apply_renames(plans)

    assert result.renamed == 0
    assert result.failed == 1
    assert "plan_changed_since_confirmed" == result.details[0]["reason"]
    assert (root / "wrong_name.mp3").exists()
