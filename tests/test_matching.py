from seeker.matching import artist_matches


def test_artist_matches_single_artist_unchanged():
    assert artist_matches("3amdisco", "3AMDISCO - Get Back") is True
    assert artist_matches("3amdisco", "Some Other Artist - Get Back") is False


def test_artist_matches_none_local_artist_returns_false():
    assert artist_matches("3amdisco", None) is False
