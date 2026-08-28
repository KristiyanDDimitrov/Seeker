from dataclasses import replace

from seeker.config_store import SeekerConfig
from seeker.database.connection import Database
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
from seeker.library.matcher import TrackMatcher, find_best_match
from seeker.models.local_file import LocalFile
from seeker.models.playlist import Playlist
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch


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


def test_multi_artist_track_matches_local_file_crediting_only_one():
    # Spotify may credit multiple artists joined with ", " (e.g.
    # "MK, Dom Dolla"); a local file crediting only one of them should
    # still be found as a match.
    track = make_track(artist="MK, Dom Dolla", title="Rhyme Dust")

    candidate = make_local_file(
        tag_artist="MK",
        tag_title="Rhyme Dust",
    )

    match = find_best_match(track, [candidate])

    assert match is not None
    assert match[0] is candidate


# --- Step 8: editable thresholds -------------------------------------

def test_match_all_unchanged_behavior_with_no_config_or_override(tmp_path):
    # Behavior-preservation bar for the refactor itself: a TrackMatcher
    # built the exact same way every existing caller already builds one
    # (make_matcher, no get_config) must classify identically to before.
    matcher = make_matcher(tmp_path)
    track = make_track()
    local_file = make_local_file()

    seed(matcher, track, local_file)

    counts = matcher.match_all()

    assert counts == {"auto": 1, "needs_review": 0, "unmatched": 0}


def test_match_all_explicit_override_reclassifies_a_real_score(tmp_path):
    matcher = make_matcher(tmp_path)
    track = make_track()
    # A real, slightly-off title variant — computed score used directly
    # below rather than guessed, so this test doesn't depend on knowing
    # rapidfuzz's exact ratio in advance.
    local_file = make_local_file(tag_title="Blinding Lights (Radio Edit)")

    match = find_best_match(track, [local_file])
    assert match is not None
    _, real_score = match

    seed(matcher, track, local_file)

    counts_above = matcher.match_all(auto_match_threshold=real_score + 1)
    assert counts_above["auto"] == 0

    counts_at = matcher.match_all(auto_match_threshold=real_score)
    assert counts_at["auto"] == 1


def test_match_all_resolves_threshold_from_config_end_to_end(tmp_path):
    # Not just isolated unit coverage of match_all's own override param
    # — this proves the real wiring: a config value set (mirroring what
    # Settings does via Application._config_store), no explicit
    # override passed, and the classification result actually changes.
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    config_state = SeekerConfig()

    matcher = TrackMatcher(
        database,
        TrackRepository(database),
        LocalFileRepository(database),
        TrackMatchRepository(database),
        get_config=lambda: config_state,
    )

    track = make_track()
    local_file = make_local_file(tag_title="Blinding Lights (Radio Edit)")

    match = find_best_match(track, [local_file])
    assert match is not None
    _, real_score = match

    seed(matcher, track, local_file)

    counts_before = matcher.match_all()
    assert counts_before["auto"] == 0

    # Reassigning the closed-over variable mirrors
    # `self.application._config_store = updated` — the SAME already-
    # constructed matcher must see it on its very next call, no
    # reconstruction, no restart.
    config_state = replace(config_state, auto_match_threshold=real_score)

    counts_after = matcher.match_all()
    assert counts_after["auto"] == 1


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


def _seed_track_with_match(
        matcher: TrackMatcher,
        connection,
        playlist_id: str,
        track_id: str,
        artist: str,
        title: str,
        match_method: str | None,
        score: float | None,
) -> None:
    matcher.tracks.save(
        Track(
            id=track_id,
            title=title,
            artist=artist,
            album="",
            duration_ms=200_000,
        ),
        connection,
    )
    matcher.tracks.save_playlist_track(playlist_id, track_id, connection)
    matcher.track_matches.upsert(
        TrackMatch(
            track_id=track_id,
            local_file_id=None,
            match_method=match_method,
            score=score,
            matched_at="2026-08-27T00:00:00+00:00",
        ),
        connection,
    )


def test_generate_match_report_scopes_to_one_playlist_with_real_data(
        tmp_path,
):
    # Real auto/unmatched split from the actual "240KM/H" and "Test"
    # playlists (2026-08-27) — CLAUDE.md's own "4 of 6" correction found
    # that check's report was silently global across every synced
    # playlist combined, not scoped to whichever playlist a human was
    # actually looking at. Confirms generate_match_report(playlist_id)
    # genuinely isolates one playlist's tracks rather than leaking
    # tracks from the other, using both playlists' real data at once so
    # a scoping bug would show up as real cross-contamination, not just
    # an empty-vs-nonempty difference.
    matcher = make_matcher(tmp_path)
    playlists = PlaylistRepository(matcher.database)

    with matcher.database.transaction() as connection:
        playlists.save(
            Playlist(id="240kmh", name="240KM/H", track_count=3),
            connection,
        )
        playlists.save(
            Playlist(id="test-playlist", name="Test", track_count=10),
            connection,
        )

        # Real 240KM/H tracks: 1 auto, 2 unmatched.
        _seed_track_with_match(
            matcher, connection, "240kmh",
            "3amdisco-track", "3amdisco", "Get Back",
            match_method="auto", score=94.44444444444444,
        )
        _seed_track_with_match(
            matcher, connection, "240kmh",
            "kamaleon-track", "Kamäleon", "Quadrat",
            match_method=None, score=None,
        )
        _seed_track_with_match(
            matcher, connection, "240kmh",
            "zenea-track", "ZENEA", "INFINITE",
            match_method=None, score=None,
        )

        # Real Test tracks: 6 auto, 4 unmatched (Prdk's real score, 24.4,
        # is a genuinely-attempted-but-low match, not just a null score —
        # still lands in "unmatched", below NEEDS_REVIEW_THRESHOLD).
        for track_id, artist, title in [
            ("audio-reebz-track", "Audio, REEBZ", "Tractor Beam"),
            ("eluun-track", "Eluun, The Clamps", "Glassy Star"),
            ("joeford-track", "Joe Ford, Task Horizon", "Ultraviolet"),
            ("prolix-track", "Prolix", "Cannibals"),
            ("qotrilo-track", "Qo, Trilo", "Push It To The Limit"),
            ("skrimor-track", "Skrimor", "Banana Shoes"),
        ]:
            _seed_track_with_match(
                matcher, connection, "test-playlist",
                track_id, artist, title,
                match_method="auto", score=100.0,
            )

        _seed_track_with_match(
            matcher, connection, "test-playlist",
            "balron-track", "Balron, Audio", "Breach",
            match_method=None, score=None,
        )
        _seed_track_with_match(
            matcher, connection, "test-playlist",
            "jadevenom-track", "Jade Venom", "Scared Now? - DIVERGENCE VI",
            match_method=None, score=None,
        )
        _seed_track_with_match(
            matcher, connection, "test-playlist",
            "prdk-track", "Prdk", "ONE MORE NIGHT",
            match_method=None, score=24.390243902439025,
        )
        _seed_track_with_match(
            matcher, connection, "test-playlist",
            "zigisc-track", "Zigi SC, A-Cray", "Bit Perfect",
            match_method=None, score=None,
        )

    kmh_report = matcher.generate_match_report(playlist_id="240kmh")
    assert kmh_report["auto_count"] == 1
    assert len(kmh_report["needs_review"]) == 0
    assert len(kmh_report["unmatched"]) == 2
    kmh_unmatched_artists = {artist for artist, _ in kmh_report["unmatched"]}
    assert kmh_unmatched_artists == {"Kamäleon", "ZENEA"}
    # Test playlist's tracks must never leak into 240KM/H's scoped report.
    assert "Balron, Audio" not in kmh_unmatched_artists

    test_report = matcher.generate_match_report(playlist_id="test-playlist")
    assert test_report["auto_count"] == 6
    assert len(test_report["needs_review"]) == 0
    assert len(test_report["unmatched"]) == 4
    test_unmatched_artists = {
        artist for artist, _ in test_report["unmatched"]
    }
    assert test_unmatched_artists == {
        "Balron, Audio", "Jade Venom", "Prdk", "Zigi SC, A-Cray",
    }
    # 240KM/H's tracks must never leak into Test's scoped report.
    assert "Kamäleon" not in test_unmatched_artists

    # Omitting playlist_id keeps the existing global behavior — the sum
    # of both playlists combined.
    global_report = matcher.generate_match_report()
    assert global_report["auto_count"] == 7
    assert len(global_report["unmatched"]) == 6
