"""Pure-function tests for roadmap item 7's Dashboard "next step" CTA
decision logic — no Qt needed at all, since _decide_next_step() only
ever branches on already-resolved facts (see main_window.py's own
docstring on _NextStepFacts for why the facts/decision split exists).
"""

from seeker.models.track import Track
from seeker.models.track_status import IN_LIBRARY, NOT_FOUND, TrackStatus
from seeker.ui.main_window import _decide_next_step, _NextStepFacts


def _facts(**overrides) -> _NextStepFacts:
    defaults = {
        "spotify_configured": True,
        "has_library_location": True,
        "has_cached_playlists": True,
        "selected_playlist_name": "Test",
        "track_statuses": [],
        "has_scanned_library": True,
        "soulseek_configured": True,
    }
    defaults.update(overrides)
    return _NextStepFacts(**defaults)


def _status(state: str, tagged_at: str | None = None) -> TrackStatus:
    return TrackStatus(
        track=Track(
            id="t1", title="Title", artist="Artist", album="Album",
            duration_ms=200_000,
        ),
        state=state,
        tagged_at=tagged_at,
    )


def test_spotify_not_connected_wins_over_everything_else():
    step = _decide_next_step(_facts(spotify_configured=False))

    assert step is not None
    assert step.action == "settings_connection"
    assert "spotify" in step.message.lower()


def test_no_library_location():
    step = _decide_next_step(
        _facts(spotify_configured=True, has_library_location=False)
    )

    assert step is not None
    assert step.action == "settings_locations"


def test_no_cached_playlists():
    step = _decide_next_step(_facts(has_cached_playlists=False))

    assert step is not None
    assert step.action == "sync"


def test_no_playlist_selected_and_everything_global_fine_is_none():
    step = _decide_next_step(
        _facts(selected_playlist_name=None, track_statuses=None)
    )

    assert step is None


def test_playlist_selected_no_tracks_yet():
    step = _decide_next_step(_facts(track_statuses=[]))

    assert step is not None
    assert step.action == "sync_tracks"


def test_tracks_present_library_never_scanned():
    step = _decide_next_step(
        _facts(
            track_statuses=[_status(NOT_FOUND)],
            has_scanned_library=False,
        )
    )

    assert step is not None
    assert step.action == "scan"


def test_missing_tracks_soulseek_not_configured():
    step = _decide_next_step(
        _facts(
            track_statuses=[_status(NOT_FOUND)],
            soulseek_configured=False,
        )
    )

    assert step is not None
    assert step.action == "settings_connection"
    assert "soulseek" in step.message.lower()


def test_missing_tracks_soulseek_configured_shows_real_count():
    step = _decide_next_step(
        _facts(
            track_statuses=[_status(NOT_FOUND), _status(NOT_FOUND)],
            soulseek_configured=True,
        )
    )

    assert step is not None
    assert step.action == "download"
    assert "2" in step.message
    assert "2" in (step.action_text or "")


def test_downloaded_but_untagged_tracks():
    step = _decide_next_step(
        _facts(
            track_statuses=[
                _status(IN_LIBRARY, tagged_at=None),
                _status(IN_LIBRARY, tagged_at="2026-08-30T12:00:00+00:00"),
            ],
        )
    )

    assert step is not None
    assert step.action == "tag_playlist"
    assert "1" in (step.action_text or "")


def test_nothing_outstanding_is_a_quiet_success_message_with_no_action():
    step = _decide_next_step(
        _facts(
            track_statuses=[_status(IN_LIBRARY, tagged_at="2026-08-30T12:00:00+00:00")],
        )
    )

    assert step is not None
    assert step.action is None
    assert step.action_text is None
    assert step.kind == "success"
    assert "all set" in step.message.lower()


def test_missing_and_untagged_both_present_missing_wins():
    # The table's own ordering: missing tracks come before untagged
    # ones — downloading what's missing is the more urgent gap.
    step = _decide_next_step(
        _facts(
            track_statuses=[
                _status(NOT_FOUND),
                _status(IN_LIBRARY, tagged_at=None),
            ],
        )
    )

    assert step is not None
    assert step.action == "download"
