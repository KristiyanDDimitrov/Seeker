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

    def fake_get(url, headers=None, timeout=None):
        assert url == "http://localhost:5030/api/v0/searches/search-1"
        return FakeResponse(SEARCH_RESPONSE)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    return SoulseekClient("http://localhost:5030", "test-api-key")


def _search(client) -> list:
    return client.search(
        "Dom Dolla Rhyme Dust",
        timeout=5.0,
        poll_interval=0.01,
    )


def test_search_excludes_locked_files(searching_client):
    results = _search(searching_client)

    assert len(results) == 2
    assert all("Extended Mix" not in r.filename for r in results)


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
