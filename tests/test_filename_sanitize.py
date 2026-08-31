from seeker.filename_sanitize import MAX_LENGTH, sanitize_path_component


def test_leaves_an_ordinary_name_untouched():
    assert sanitize_path_component("Pop") == "Pop"


# Real playlist names from this project's own production database
# (checked live, per the task's own instruction) — not synthetic
# edge cases guessed in the abstract.

def test_real_playlist_name_with_a_slash():
    assert sanitize_path_component("240KM/H") == "240KM-H"


def test_real_playlist_name_with_a_colon():
    assert sanitize_path_component("Node: Reloaded") == "Node- Reloaded"


def test_real_playlist_name_with_a_colon_no_space():
    assert sanitize_path_component("GO:OD AM") == "GO-OD AM"


def test_real_playlist_name_with_double_slash():
    assert sanitize_path_component("Lotus // Trap") == "Lotus -- Trap"


def test_real_playlist_name_with_a_leading_number_slash():
    assert (
        sanitize_path_component("4/20 Secret Location Party")
        == "4-20 Secret Location Party"
    )


def test_backslash_is_replaced_too_not_just_forward_slash():
    assert sanitize_path_component(r"A\B") == "A-B"


def test_control_characters_are_replaced():
    assert sanitize_path_component("Mix\x00Tape\x1f") == "Mix-Tape-"


def test_trailing_dots_and_spaces_are_stripped():
    # A real, confirmed Windows failure mode, not cosmetic: Windows
    # itself silently strips trailing dots/spaces from a folder name
    # at creation time — and it strips ALL of them, not just the last
    # character, which is exactly what str.rstrip(" .") does too.
    assert sanitize_path_component("My Playlist. . ") == "My Playlist"


def test_windows_reserved_punctuation_is_replaced():
    for char in '<>:"|?*':
        assert char not in sanitize_path_component(f"Name{char}Here")


def test_invalid_characters_replaced_not_dropped():
    assert sanitize_path_component("////") == "----"


def test_entirely_invalid_name_falls_back_to_a_real_name():
    # Nothing but trailing dots/spaces to strip — the result would
    # otherwise be a real, silent empty string.
    assert sanitize_path_component("...") == "Untitled"
    assert sanitize_path_component("") == "Untitled"
    assert sanitize_path_component("   ") == "Untitled"


def test_very_long_name_is_truncated():
    result = sanitize_path_component("x" * 500)
    assert len(result) <= MAX_LENGTH
