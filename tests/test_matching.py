from seeker.matching import (
    ARTIST_UNCONFIRMED_SCORE_CAP,
    AUTO_MATCH_THRESHOLD,
    artist_matches,
    evaluate_match,
    normalize_filename_text,
    score_title,
)


def test_artist_matches_single_artist_unchanged():
    assert artist_matches("3amdisco", "3AMDISCO - Get Back") is True
    assert artist_matches("3amdisco", "Some Other Artist - Get Back") is False


def test_artist_matches_none_local_artist_returns_false():
    assert artist_matches("3amdisco", None) is False


def test_artist_matches_multi_artist_matches_when_local_credits_only_one():
    # Spotify may credit multiple artists joined with ", " (e.g.
    # "MK, Dom Dolla"). A local tag or filename crediting only one of
    # them should still count as a match.
    assert artist_matches("MK, Dom Dolla", "MK") is True
    assert artist_matches("MK, Dom Dolla", "Dom Dolla") is True


def test_artist_matches_multi_artist_fails_when_local_credits_neither():
    assert artist_matches("MK, Dom Dolla", "Some Other Artist") is False


# --- Roadmap item 56: aggressive normalization + evaluate_match --------

def test_normalize_filename_text_default_is_unchanged_by_aggressive_mode():
    # quality.py always calls with the default (aggressive=False) — this
    # is the exact behavior-preservation bar for that module.
    text = "07. a bulleT w- my namE On [ost] p.u.s.s.-e"
    assert normalize_filename_text(text) == normalize_filename_text(
        text, aggressive=False
    )


def test_normalize_filename_text_aggressive_maps_fs_substitution_to_space():
    # Real case: a Spotify title's literal "/" survives locally only as
    # "-" once written to a filename/tag.
    assert normalize_filename_text(
        "a bullet w/ my name on", aggressive=True
    ) == normalize_filename_text("a bullet w- my name on", aggressive=True)


def test_normalize_filename_text_aggressive_strips_dots():
    # Real case: Spotify's own letter-spacing stylization ("R.i.p.")
    # dropped entirely by the local rip's own tag ("Rip").
    assert normalize_filename_text(
        "R.i.p.", aggressive=True
    ) == normalize_filename_text("Rip", aggressive=True)


def test_score_title_aggressive_tries_feat_clause_stripped_as_extra_variant():
    # Real case: a Spotify title's "(feat. X)" clause entirely absent
    # from the local tag. Aggressive mode must score at least as well as
    # non-aggressive (the stripped variant is additive, never a
    # replacement) and clear the auto-match threshold.
    spotify_title = "a bulleT w/ my namE On (feat. Underoath)"
    local_title = "a bulleT w- my namE On"

    non_aggressive = score_title(
        "Bring Me The Horizon, Underoath", spotify_title, local_title,
    )
    aggressive = score_title(
        "Bring Me The Horizon, Underoath", spotify_title, local_title,
        aggressive=True,
    )

    assert aggressive >= non_aggressive
    assert aggressive >= AUTO_MATCH_THRESHOLD


def test_score_title_aggressive_does_not_penalize_a_title_that_really_has_feat():
    # The feat-stripped variant is additive — a local title that
    # genuinely DOES carry the "(feat. ...)" text must still score its
    # normal high match, not get penalized by the extra variant existing.
    spotify_title = "a bulleT w/ my namE On (feat. Underoath)"
    local_title = "a bulleT w/ my namE On (feat. Underoath)"

    assert score_title(
        "Bring Me The Horizon, Underoath", spotify_title, local_title,
        aggressive=True,
    ) == 100.0


def test_evaluate_match_artist_confirmed_scores_normally():
    evaluation = evaluate_match(
        "Bring Me The Horizon",
        "R.i.p. (duskCOre RemIx)",
        "Bring Me The Horizon",
        True,
        "Rip (duskCOre RemIx)",
    )

    assert evaluation.artist_confirmed is True
    assert evaluation.score is not None
    assert evaluation.score >= AUTO_MATCH_THRESHOLD


def test_evaluate_match_contradicting_real_tag_hard_rejects():
    evaluation = evaluate_match(
        "The Weeknd", "Blinding Lights",
        "Some Other Artist", True,
        "Blinding Lights",
    )

    assert evaluation.artist_confirmed is False
    assert evaluation.score is None


def test_evaluate_match_unconfirmed_fallback_source_is_capped_not_rejected():
    # No tag existed (from_tag=False) and the fallback source doesn't
    # name the artist either — still gets a real score, capped below
    # AUTO_MATCH_THRESHOLD rather than discarded outright.
    evaluation = evaluate_match(
        "3amdisco", "Get Back",
        "unrelated filename text", False,
        "Get Back",
    )

    assert evaluation.artist_confirmed is False
    assert evaluation.score is not None
    assert evaluation.score <= ARTIST_UNCONFIRMED_SCORE_CAP
