import json

import httpx
import pytest

from seeker.soulseek.client import SoulseekClient, SoulseekDownloadError


class FakeResponse:
    def __init__(self, data: dict):
        self._data = data
        self.status_code = 200

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeErrorResponse:
    # Mimics enough of a real httpx.Response for raise_for_status() to
    # raise a genuine httpx.HTTPStatusError carrying this object as
    # .response, exactly like the real client sees.
    def __init__(self, status_code: int, json_body):
        self.status_code = status_code
        self.text = json.dumps(json_body)
        self._json_body = json_body

    def json(self):
        return self._json_body

    def raise_for_status(self):
        raise httpx.HTTPStatusError(
            f"{self.status_code} error",
            request=httpx.Request(
                "POST",
                "http://localhost:5030/api/v0/transfers/downloads/batches",
            ),
            response=self,  # type: ignore[arg-type]
        )


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
    results = client.search(
            "Dom Dolla Rhyme Dust",
            timeout=5.0,
            poll_interval=0.01,
    )

    assert len(results) == 1
    assert results[0].locked is True
    assert results[0].username == "another_seeder"
    assert results[0].size == 34279790


# request_download / get_download_status / get_download_exception were
# previously only exercised indirectly, through FakeSoulseekClient in
# download_service tests — the real client methods (the same ones with
# real, previously-found bugs: the endpoint/field-name saga, the locked-
# file investigation) had no direct httpx-mocked coverage of their own.


def test_request_download_returns_transfer_id_on_success(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        assert (
            url
            == "http://localhost:5030/api/v0/transfers/downloads/batches"
        )
        assert json == {
            "username": "peer1",
            "files": [{"filename": "song.flac", "size": 12345}],
        }
        return FakeResponse({"batch": {"transfers": [{"id": "transfer-abc"}]}})

    monkeypatch.setattr(httpx, "post", fake_post)

    client = SoulseekClient("http://localhost:5030", "test-api-key")
    transfer_id = client.request_download("peer1", "song.flac", 12345)

    assert transfer_id == "transfer-abc"


def test_request_download_includes_destination_when_given(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        return FakeResponse({"batch": {"transfers": [{"id": "t1"}]}})

    monkeypatch.setattr(httpx, "post", fake_post)

    client = SoulseekClient("http://localhost:5030", "test-api-key")
    client.request_download(
        "peer1", "song.flac", 12345, destination="sub/dir"
    )

    assert captured["json"]["options"] == {"destination": "sub/dir"}


def test_request_download_raises_with_slskd_failure_message(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return FakeResponse({"failures": [{"message": "File not shared."}]})

    monkeypatch.setattr(httpx, "post", fake_post)

    client = SoulseekClient("http://localhost:5030", "test-api-key")

    with pytest.raises(SoulseekDownloadError, match="File not shared."):
        client.request_download("peer1", "song.flac", 12345)


def test_request_download_wraps_real_peer_offline_404(monkeypatch):
    # Real, captured response (2026-08-28): a direct replay of the exact
    # failing request against the live instance for a peer that wasn't
    # currently online returned this precise body — a synchronous 404
    # straight off the enqueue POST, a genuinely different shape from
    # the accepted-then-rejected-later flow the other tests exercise.
    def fake_post(url, json=None, headers=None, timeout=None):
        return FakeErrorResponse(404, "User long25 appears to be offline")

    monkeypatch.setattr(httpx, "post", fake_post)

    client = SoulseekClient("http://localhost:5030", "test-api-key")

    with pytest.raises(
        SoulseekDownloadError, match="appears to be offline",
    ):
        client.request_download(
            "long25", "NeuroFunk26\\Balron, Audio - Breach.flac", 37691256,
        )


@pytest.mark.parametrize("status_code", [401, 500])
def test_request_download_does_not_wrap_unrecognized_error(
        monkeypatch, status_code,
):
    # An unrecognized 4xx/5xx (auth failure, server error — anything
    # that isn't a confirmed, known-transient rejection reason) must
    # keep propagating loudly as the original httpx.HTTPStatusError,
    # not get silently absorbed into "retry later." Guardrail against
    # RECOGNIZED_REJECTION_PATTERNS ever being broadened past what's
    # actually been confirmed.
    def fake_post(url, json=None, headers=None, timeout=None):
        return FakeErrorResponse(status_code, "Internal Server Error")

    monkeypatch.setattr(httpx, "post", fake_post)

    client = SoulseekClient("http://localhost:5030", "test-api-key")

    with pytest.raises(httpx.HTTPStatusError):
        client.request_download("peer1", "song.flac", 12345)


def test_get_download_status_returns_real_state(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        assert url == (
            "http://localhost:5030/api/v0/transfers/downloads/"
            "peer1/transfer-abc"
        )
        return FakeResponse({"state": "Completed, Succeeded"})

    monkeypatch.setattr(httpx, "get", fake_get)

    client = SoulseekClient("http://localhost:5030", "test-api-key")
    status = client.get_download_status("peer1", "transfer-abc")

    assert status.state == "Completed, Succeeded"


def test_get_download_status_returns_notfound_on_404(monkeypatch):
    class NotFoundResponse:
        status_code = 404

    monkeypatch.setattr(httpx, "get", lambda *a, **k: NotFoundResponse())

    client = SoulseekClient("http://localhost:5030", "test-api-key")
    status = client.get_download_status("peer1", "transfer-abc")

    assert status.state == "NotFound"
    assert status.bytes_transferred is None
    assert status.size is None


def test_get_download_status_parses_real_progress_fields_on_completion(
        monkeypatch,
):
    # Real transfer record shape confirmed live (2026-08-28) against a
    # genuinely completed transfer (kingdomcum, 3AMDISCO - Get Back.wav):
    # bytesTransferred == size once a transfer has genuinely finished.
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(
            {
                "state": "Completed, Succeeded",
                "size": 79776980,
                "bytesTransferred": 79776980,
            }
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    client = SoulseekClient("http://localhost:5030", "test-api-key")
    status = client.get_download_status("peer1", "transfer-abc")

    assert status.bytes_transferred == 79776980
    assert status.size == 79776980
    assert status.bytes_transferred == status.size


def test_get_download_status_parses_real_progress_fields_before_rejection(
        monkeypatch,
):
    # Real transfer record shape confirmed live (2026-08-28) for a
    # locked file rejected before any bytes moved: bytesTransferred is
    # genuinely 0 in the real payload, not absent — the caller (not this
    # parsing layer) decides whether to persist that or leave progress
    # unset for a rejection.
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(
            {
                "state": "Completed, Rejected",
                "size": 55144573,
                "bytesTransferred": 0,
            }
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    client = SoulseekClient("http://localhost:5030", "test-api-key")
    status = client.get_download_status("peer1", "transfer-abc")

    assert status.bytes_transferred == 0
    assert status.size == 55144573


def test_get_download_exception_returns_real_reason(monkeypatch):
    # Exact real string confirmed live (2026-08-27 locked-file
    # investigation).
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(
            {
                "state": "Completed, Rejected",
                "exception": "Transfer rejected: File not shared.",
            }
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    client = SoulseekClient("http://localhost:5030", "test-api-key")
    exception_text = client.get_download_exception("peer1", "transfer-abc")

    assert exception_text == "Transfer rejected: File not shared."


def test_get_download_exception_returns_none_when_absent(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse({"state": "Completed, Succeeded"})

    monkeypatch.setattr(httpx, "get", fake_get)

    client = SoulseekClient("http://localhost:5030", "test-api-key")
    exception_text = client.get_download_exception("peer1", "transfer-abc")

    assert exception_text is None


def test_get_download_exception_returns_none_on_404(monkeypatch):
    class NotFoundResponse:
        status_code = 404

    monkeypatch.setattr(httpx, "get", lambda *a, **k: NotFoundResponse())

    client = SoulseekClient("http://localhost:5030", "test-api-key")
    exception_text = client.get_download_exception("peer1", "transfer-abc")

    assert exception_text is None
