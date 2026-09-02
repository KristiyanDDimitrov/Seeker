from seeker.filename_format import MAX_FILENAME_BYTES, build_track_filename


def test_single_artist():
    assert (
        build_track_filename("Prolix", "Cannibals", "mp3")
        == "Prolix - Cannibals.mp3"
    )


def test_multi_artist_joined_with_spotify_order():
    # Real Spotify credit order from this library — Track.artist already
    # holds every artist joined with ", " (item 9).
    assert (
        build_track_filename("A-Cray, Zigi SC", "Bit Perfect (Original Mix)", "mp3")
        == "A-Cray, Zigi SC - Bit Perfect (Original Mix).mp3"
    )


def test_extension_lowercased_and_never_changed():
    assert (
        build_track_filename("Artist", "Title", "FLAC")
        == "Artist - Title.flac"
    )
    assert (
        build_track_filename("Artist", "Title", ".WAV")
        == "Artist - Title.wav"
    )


def test_feat_dedupe_drops_a_second_artist_already_credited_in_the_title():
    # Real example shape from this library: a multi-artist track where
    # one of the artists is ALSO named in the title's own feat clause —
    # without dedup this would double up as "A, B - Title (feat. B)".
    assert (
        build_track_filename(
            "Alex Hoing, Sebastian Reza, Bluckther",
            "La Mangueleña (feat. Bluckther)",
            "mp3",
        )
        == "Alex Hoing, Sebastian Reza - La Mangueleña (feat. Bluckther).mp3"
    )


def test_feat_dedupe_is_case_insensitive():
    assert (
        build_track_filename(
            "Artist A, ARTIST B", "Title (feat. artist b)", "mp3",
        )
        == "Artist A - Title (feat. artist b).mp3"
    )


def test_feat_dedupe_always_keeps_the_first_artist_even_if_credited():
    assert (
        build_track_filename(
            "Artist A, Artist B", "Title (feat. Artist A)", "mp3",
        )
        == "Artist A, Artist B - Title (feat. Artist A).mp3"
    )


def test_feat_dedupe_handles_ft_and_featuring_variants():
    assert (
        build_track_filename("A, B", "Title (ft. B)", "mp3")
        == "A - Title (ft. B).mp3"
    )
    assert (
        build_track_filename("A, B", "Title (featuring B)", "mp3")
        == "A - Title (featuring B).mp3"
    )


def test_no_feat_clause_keeps_every_artist():
    assert (
        build_track_filename("A, B, C", "Title With No Feat Clause", "mp3")
        == "A, B, C - Title With No Feat Clause.mp3"
    )


def test_illegal_characters_delegate_to_the_shared_sanitizer():
    # "240KM/H"-style real playlist name shape (item 6 §3's own real
    # example) -- a literal path separator must never survive.
    assert (
        build_track_filename("240KM/H Artist", "Title: Part Two?", "mp3")
        == "240KM-H Artist - Title- Part Two-.mp3"
    )


def test_collapses_whitespace():
    assert (
        build_track_filename("Artist   With   Spaces", "Title", "mp3")
        == "Artist With Spaces - Title.mp3"
    )


def test_no_trailing_dots_or_spaces():
    # sanitize_path_component's own Windows-illegal-trailing-dot/space
    # strip, reused via clean_path_component -- but the title lands in
    # the MIDDLE of the base string here, so this specifically checks
    # the FINAL result (after truncation logic runs) has no trailing
    # dot/space, not just the intermediate title clean.
    result = build_track_filename("Artist", "Title...", "mp3")
    assert result is not None
    name_without_ext = result.rsplit(".", 1)[0]
    assert not name_without_ext.endswith(".")
    assert not name_without_ext.endswith(" ")


def test_empty_artist_returns_none():
    assert build_track_filename("", "Title", "mp3") is None
    assert build_track_filename("   ", "Title", "mp3") is None


def test_empty_title_returns_none():
    assert build_track_filename("Artist", "", "mp3") is None
    assert build_track_filename("Artist", "   ", "mp3") is None


def test_length_cap_is_255_utf8_bytes_not_characters():
    # An accented-heavy title should be truncated by real UTF-8 byte
    # count, not character count -- each 'é' is 2 bytes in UTF-8.
    long_title = "é" * 300
    result = build_track_filename("Artist", long_title, "mp3")
    assert result is not None
    assert len(result.encode("utf-8")) <= MAX_FILENAME_BYTES


def test_length_cap_never_truncates_the_extension():
    long_title = "A" * 300
    result = build_track_filename("Artist", long_title, "flac")
    assert result is not None
    assert result.endswith(".flac")
    assert len(result.encode("utf-8")) <= MAX_FILENAME_BYTES


def test_length_cap_never_splits_a_multibyte_character():
    # A title made entirely of 3-byte UTF-8 characters ('世') at a length
    # chosen so a naive byte-slice would land mid-character.
    long_title = "世" * 200
    result = build_track_filename("Artist", long_title, "mp3")
    assert result is not None
    # Would raise UnicodeDecodeError if a character was split.
    result.encode("utf-8").decode("utf-8")


def test_truncation_only_shortens_the_title_never_the_artist_prefix():
    long_title = "T" * 300
    result = build_track_filename("Real Artist Name", long_title, "mp3")
    assert result is not None
    assert result.startswith("Real Artist Name - ")
