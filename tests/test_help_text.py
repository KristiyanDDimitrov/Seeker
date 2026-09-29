from seeker.models.location_removal import LocationRemovalSummary
from seeker.ui import help_text
from seeker.ui.help_text import SHARING_FRAMING_BODY


def test_sharing_framing_states_slskd_admin_ui_is_local_only():
    # Roadmap item 116 (round 8, §6.1.4) — someone running a
    # file-sharing daemon deserves to be told plainly what it's
    # exposing and that its admin interface is local-only.
    assert "read-only" in SHARING_FRAMING_BODY
    assert "bound to this machine only" in SHARING_FRAMING_BODY


def test_remove_location_confirm_body_names_everything_it_forgets():
    summary = LocationRemovalSummary(
        location_name="Music",
        files_forgotten=3454,
        matches_cleared=12,
        confirmed_matches_cleared=3,
        playlists_affected=2,
        was_default=False,
    )

    assert help_text.format_remove_location_confirm_body(summary) == (
        "Remove 'Music'? Seeker forgets 3,454 indexed files and 12 "
        "matches (3 you confirmed). 2 playlists download here and will "
        "need a new destination. Files on disk are not touched."
    )
