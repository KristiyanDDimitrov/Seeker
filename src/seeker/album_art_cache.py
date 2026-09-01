import hashlib
import json
from pathlib import Path

import platformdirs


def default_cache_dir() -> Path:
    return (
        Path(platformdirs.user_cache_dir("Seeker", appauthor=False))
        / "album_art"
    )


class AlbumArtCache:
    """Caches downloaded album art bytes by URL — roadmap item 56 Phase
    4.3. A playlist drawn from a handful of albums re-downloads the
    same image once per track without this; this is purely a
    bandwidth/latency win, not a Spotify API quota one — the URL comes
    from `tracks.album_art_url`, already captured at sync time
    (item 9), and the fetch itself goes to Spotify's CDN, not the Web
    API.

    Two layers: an in-memory dict (covers "the duration of a tagging
    run" even with no disk access) backed by an on-disk cache under the
    platformdirs user CACHE directory — deliberately not the user DATA
    directory (see `application.py`'s `platformdirs.user_data_dir`
    calls for that one): this is disposable, safe to clear at any time,
    and never contains anything the app couldn't re-fetch from
    Spotify's CDN. Keyed by a SHA-256 hash of the URL, not the URL text
    itself, to keep filenames filesystem-safe with no sanitization
    logic needed.
    """

    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or default_cache_dir()
        self._memory: dict[str, tuple[bytes, str]] = {}

    def get(self, url: str) -> tuple[bytes, str] | None:
        if url in self._memory:
            return self._memory[url]

        key = self._key_for(url)
        data_path = self.cache_dir / f"{key}.bin"
        meta_path = self.cache_dir / f"{key}.json"

        if not data_path.is_file() or not meta_path.is_file():
            return None

        try:
            meta = json.loads(meta_path.read_text())
            image_bytes = data_path.read_bytes()
            mime_type = str(meta["mime_type"])
        except (OSError, ValueError, KeyError):
            # A corrupt/partial cache entry is treated as a miss, never
            # an error — this cache is purely an optimization.
            return None

        result = (image_bytes, mime_type)
        self._memory[url] = result

        return result

    def put(self, url: str, image_bytes: bytes, mime_type: str) -> None:
        self._memory[url] = (image_bytes, mime_type)

        key = self._key_for(url)

        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{key}.bin").write_bytes(image_bytes)
            (self.cache_dir / f"{key}.json").write_text(
                json.dumps({"url": url, "mime_type": mime_type})
            )
        except OSError:
            # Disk cache is purely an optimization — a write failure
            # (disk full, permissions) must never break tagging itself;
            # the in-memory entry above still covers this run.
            pass

    @staticmethod
    def _key_for(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()
