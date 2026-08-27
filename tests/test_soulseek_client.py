import httpx
import pytest

from seeker.soulseek.client import SoulseekClient


class FakeResponse:
    def __init__(self, data: dict):
        self._data = data
        self.status_code = 200

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


# Trimmed real slskd search response shape for "Dom Dolla Rhyme Dust" — one
# peer offering the real audio file (API's own "extension" field left
# blank, as observed in real responses), a cover-art jpg alongside it, and
# a locked file that must never surface.
SEARCH_RESPONSE = {
    "id": "search-1",
    "isComplete": True,
    "responses": [
        {
            "username": "some_seeder",
            "queueLength": 2,
            "uploadSpeed": 1048576,
            "hasFreeUploadSlot": True,
            "files": [
                {
                    "filename": (
                        "@@1a2b3c\\Music\\Dom Dolla\\Rhyme Dust\\"
                        "Dom Dolla - Rhyme Dust.flac"
                    ),
                    "size": 34567890,
                    "extension": "",
                    "bitRate": None,
                    "sampleRate": 44100,
                    "bitDepth": 16,
                    "length": 215,
                    "isLocked": False,
                },
                {
                    "filename": (
                        "@@1a2b3c\\Music\\Dom Dolla\\Rhyme Dust\\cover.jpg"
                    ),
                    "size": 204800,
                    "extension": "jpg",
                    "bitRate": None,
                    "sampleRate": None,
                    "bitDepth": None,
                    "length": None,
                    "isLocked": False,
                },
                {
                    "filename": (
                        "@@1a2b3c\\Private\\"
                        "Dom Dolla - Rhyme Dust (Extended Mix).mp3"
                    ),
                    "size": 12345678,
                    "extension": "mp3",
                    "bitRate": 320,
                    "sampleRate": 44100,
                    "bitDepth": None,
                    "length": 402,
                    "isLocked": True,
                },
            ],
        }
    ],
}


@pytest.fixture
def searching_client(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        assert url == "http://localhost:5030/api/v0/searches"
        assert json == {"SearchText": "Dom Dolla Rhyme Dust"}
        return FakeResponse({"id": "search-1"})

    def fake_get(url, params=None, headers=None, timeout=None):
        assert url == "http://localhost:5030/api/v0/searches/search-1"

        # Real slskd only inlines the per-peer file responses when asked
        # via ?includeResponses=true — a plain poll reports isComplete
        # with an empty "responses" list even once results exist.
        if params and params.get("includeResponses") == "true":
            return FakeResponse(SEARCH_RESPONSE)

        return FakeResponse(
            {"id": "search-1", "isComplete": True, "responses": []}
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    return SoulseekClient("http://localhost:5030", "test-api-key")


def _search(client) -> list:
    return client.search(
        "Dom Dolla Rhyme Dust",
        timeout=5.0,
        poll_interval=0.01,
    )


def test_search_includes_locked_files_marked_locked(searching_client):
    # Previously dropped entirely; now included with locked=True so the
    # Phase 3 retry cycle has something to track.
    results = _search(searching_client)

    assert len(results) == 3

    locked_result = next(r for r in results if "Extended Mix" in r.filename)
    assert locked_result.locked is True

    unlocked_results = [r for r in results if "Extended Mix" not in r.filename]
    assert all(r.locked is False for r in unlocked_results)


def test_search_derives_extension_from_filename_not_api_field(
        searching_client,
):
    results = _search(searching_client)

    flac_result = next(r for r in results if r.filename.endswith(".flac"))

    # The API's own "extension" field was blank for this file.
    assert flac_result.extension == "flac"
    assert flac_result.username == "some_seeder"
    assert flac_result.queue_length == 2
    assert flac_result.upload_speed == 1048576
    assert flac_result.has_free_upload_slot is True
    assert flac_result.length == 215
    assert flac_result.bit_depth == 16
    assert flac_result.sample_rate == 44100


def test_search_includes_non_audio_files_unfiltered(searching_client):
    results = _search(searching_client)

    jpg_result = next(r for r in results if r.extension == "jpg")

    assert jpg_result.filename.endswith("cover.jpg")
    assert jpg_result.username == "some_seeder"


# Real response shape confirmed live (2026-08-27): locked files actually
# arrive in a separate top-level "lockedFiles" array per response, not
# via isLocked=true within "files" — and the real entry's own "isLocked"
# field was itself False, confirming array membership is the real signal.
LOCKED_FILES_RESPONSE = {
    "id": "search-2",
    "isComplete": True,
    "responses": [
        {
            "username": "another_seeder",
            "queueLength": 0,
            "uploadSpeed": 500000,
            "hasFreeUploadSlot": True,
            "files": [],
            "lockedFileCount": 1,
            "lockedFiles": [
                {
                    "filename": (
                        "Colección\\Beatport\\Beatport 2023\\"
                        "MK, Dom Dolla - Rhyme Dust (Extended).flac"
                    ),
                    "size": 34279790,
                    "extension": "",
                    "bitRate": None,
                    "sampleRate": 44100,
                    "bitDepth": 16,
                    "length": 330,
                    "isLocked": False,
                },
            ],
        },
    ],
}


def test_search_includes_real_lockedfiles_array_shape(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return FakeResponse({"id": "search-2"})

    def fake_get(url, params=None, headers=None, timeout=None):
        if params and params.get("includeResponses") == "true":
            return FakeResponse(LOCKED_FILES_RESPONSE)

        return FakeResponse(
            {"id": "search-2", "isComplete": True, "responses": []}
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    client = SoulseekClient("http://localhost:5030", "test-api-key")
    results = client.search("Dom Dolla Rhyme Dust", timeout=5.0, poll_interval=0.01)

    assert len(results) == 1
    assert results[0].locked is True
    assert results[0].username == "another_seeder"
    assert results[0].size == 34279790
