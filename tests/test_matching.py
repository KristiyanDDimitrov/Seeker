from seeker.matching import artist_matches


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
