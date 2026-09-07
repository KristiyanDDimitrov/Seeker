from seeker.ui.help_text import SHARING_FRAMING_BODY


def test_sharing_framing_states_slskd_admin_ui_is_local_only():
    # Roadmap item 116 (round 8, §6.1.4) — someone running a
    # file-sharing daemon deserves to be told plainly what it's
    # exposing and that its admin interface is local-only.
    assert "read-only" in SHARING_FRAMING_BODY
    assert "bound to this machine only" in SHARING_FRAMING_BODY
