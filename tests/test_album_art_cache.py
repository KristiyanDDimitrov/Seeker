from seeker.album_art_cache import AlbumArtCache


def test_get_returns_none_for_a_cold_cache(tmp_path):
    cache = AlbumArtCache(tmp_path / "art")

    assert cache.get("https://i.scdn.co/image/fake") is None


def test_put_then_get_round_trips_within_one_instance(tmp_path):
    cache = AlbumArtCache(tmp_path / "art")

    cache.put(
            "https://i.scdn.co/image/fake",
            b"\xff\xd8fakejpeg",
            "image/jpeg",
    )

    assert cache.get("https://i.scdn.co/image/fake") == (
        b"\xff\xd8fakejpeg", "image/jpeg",
    )


def test_put_persists_to_disk_and_survives_a_fresh_instance(tmp_path):
    # The real point of the disk layer (roadmap item 56 Phase 4.3) — a
    # brand new process/MetadataService must still hit the cache, not
    # just the in-memory dict within one already-running instance.
    cache_dir = tmp_path / "art"
    first = AlbumArtCache(cache_dir)
    first.put("https://i.scdn.co/image/fake", b"real bytes here", "image/png")

    second = AlbumArtCache(cache_dir)

    assert second.get("https://i.scdn.co/image/fake") == (
        b"real bytes here", "image/png",
    )


def test_different_urls_do_not_collide(tmp_path):
    cache = AlbumArtCache(tmp_path / "art")

    cache.put("https://i.scdn.co/image/one", b"one", "image/jpeg")
    cache.put("https://i.scdn.co/image/two", b"two", "image/jpeg")

    assert cache.get("https://i.scdn.co/image/one") == (b"one", "image/jpeg")
    assert cache.get("https://i.scdn.co/image/two") == (b"two", "image/jpeg")


def test_get_ignores_a_corrupt_cache_entry_instead_of_raising(tmp_path):
    cache_dir = tmp_path / "art"
    cache_dir.mkdir()
    cache = AlbumArtCache(cache_dir)
    key = cache._key_for("https://i.scdn.co/image/fake")

    # A real .bin file with no matching .json (a plausible partial-write
    # shape, e.g. interrupted mid-put) — must be a clean miss, not an
    # exception a real tagging run would then have to handle.
    (cache_dir / f"{key}.bin").write_bytes(b"orphaned data")

    assert cache.get("https://i.scdn.co/image/fake") is None


def test_default_cache_dir_is_under_platformdirs_user_cache_not_data():
    from seeker.album_art_cache import default_cache_dir

    path = default_cache_dir()

    assert "Seeker" in str(path)
    assert "album_art" in str(path)
