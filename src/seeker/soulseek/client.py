import time
from dataclasses import dataclass
from typing import Any, cast

import httpx

from seeker.models.soulseek_file import SoulseekFile


class SoulseekDownloadError(RuntimeError):
    pass


# Recognized, known-transient slskd rejection reasons — confirmed live
# against real captured responses, not guessed. Matched case-
# insensitively by substring since exact wording may vary slightly
# across peers/slskd versions:
#   "not shared" — the file is genuinely there, but the peer isn't
#     sharing it right now (2026-08-27, "Transfer rejected: File not
#     shared.") — arrives via the ASYNC shape: request_download's own
#     POST succeeds (200, a real transfer_id comes back), and the
#     rejection only shows up moments later via get_download_status
#     ("Completed, Rejected") + get_download_exception.
#   "appears to be offline" — the peer isn't currently reachable at all
#     (2026-08-28, "User long25 appears to be offline") — arrives via a
#     completely different, SYNCHRONOUS shape: slskd refuses the
#     request outright with a 404 straight off the enqueue POST, before
#     any transfer record exists at all. Confirmed live via a direct
#     replay of the exact failing request against the live instance.
# Both are "worth retrying later" in the exact same way — a peer being
# briefly offline or not sharing a file right now isn't permanent — so
# both route through the identical SoulseekDownloadError contract
# every caller already knows how to classify, rather than teaching
# callers about two different exception shapes for one underlying
# concept. Anything NOT matching here (auth failure, malformed
# request, a genuine server error) must keep propagating loudly, not
# get silently absorbed as "retry later" — this is deliberately not
# broadened beyond what's actually been confirmed.
RECOGNIZED_REJECTION_PATTERNS = ("not shared", "appears to be offline")


def is_recognized_rejection(text: str | None) -> bool:
    if not text:
        return False

    lowered = text.lower()

    return any(
        pattern in lowered for pattern in RECOGNIZED_REJECTION_PATTERNS
    )


@dataclass
class TransferStatus:
    state: str
    # Real slskd field names, confirmed live against
    # GET /api/v0/transfers/downloads/{username}/{id} (2026-08-28):
    # "bytesTransferred" and "size" — "size" matches the same convention
    # SoulseekFile already uses for total bytes, so this follows that
    # rather than introducing a "total_bytes" vs "size" inconsistency at
    # this layer. Both None only for a 404 ("NotFound") response, where
    # there's no real transfer body to read them from — a genuine,
    # in-flight transfer always reports both as real integers, 0 being
    # the real, confirmed representation of "hasn't started" (not
    # absent/null).
    bytes_transferred: int | None
    size: int | None


class SoulseekClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key}

    def search(
            self,
            query: str,
            # Empirically, real slskd searches against the live Soulseek
            # network took 20-45s+ to report isComplete in testing — 15s
            # was cutting searches off before most peer responses arrived.
            timeout: float = 45.0,
            poll_interval: float = 2.0,
    ) -> list[SoulseekFile]:
        create_response = httpx.post(
            f"{self.base_url}/api/v0/searches",
            json={"SearchText": query},
            headers=self._headers(),
            timeout=10.0,
        )
        create_response.raise_for_status()

        search_id = create_response.json()["id"]

        deadline = time.monotonic() + timeout

        while True:
            poll_response = httpx.get(
                f"{self.base_url}/api/v0/searches/{search_id}",
                headers=self._headers(),
                timeout=10.0,
            )
            poll_response.raise_for_status()

            if poll_response.json().get("isComplete"):
                break

            if time.monotonic() >= deadline:
                break

            time.sleep(poll_interval)

        # isComplete alone doesn't carry the per-peer file responses —
        # those are only included when explicitly requested, otherwise
        # the search resource always reports an empty "responses" list.
        # Fetch them once at the end (complete or timed out) rather than
        # on every poll, since each peer response can carry many files.
        responses_response = httpx.get(
            f"{self.base_url}/api/v0/searches/{search_id}",
            params={"includeResponses": "true"},
            headers=self._headers(),
            timeout=10.0,
        )
        responses_response.raise_for_status()

        return _parse_search_response(responses_response.json())

    def request_download(
            self,
            username: str,
            filename: str,
            size: int,
            destination: str | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "username": username,
            "files": [{"filename": filename, "size": size}],
        }

        if destination is not None:
            body["options"] = {"destination": destination}

        try:
            response = httpx.post(
                f"{self.base_url}/api/v0/transfers/downloads/batches",
                json=body,
                headers=self._headers(),
                timeout=15.0,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            # A recognized rejection can arrive synchronously as a
            # non-2xx response right here (confirmed live: a 404 with
            # body "User long25 appears to be offline" for an offline
            # peer), not only via the accepted-then-rejected async
            # shape below — see RECOGNIZED_REJECTION_PATTERNS. Wrapped
            # into the same SoulseekDownloadError either shape already
            # raises, so callers have exactly one exception type to
            # classify, not two. Anything unrecognized re-raises as the
            # original httpx.HTTPStatusError — must stay loud.
            try:
                detail = error.response.json()
            except ValueError:
                detail = error.response.text

            message = detail if isinstance(detail, str) else str(detail)

            if is_recognized_rejection(message):
                raise SoulseekDownloadError(
                    f"slskd rejected the download of '{filename}' from "
                    f"'{username}': {message}"
                ) from error

            raise

        data = response.json()
        transfers = (data.get("batch") or {}).get("transfers") or []

        if not transfers:
            failures = data.get("failures") or []
            message = (
                failures[0]["message"] if failures else "unknown error"
            )

            raise SoulseekDownloadError(
                f"slskd rejected the download of '{filename}' from "
                f"'{username}': {message}"
            )

        return cast(str, transfers[0]["id"])

    def get_download_status(
            self,
            username: str,
            transfer_id: str,
    ) -> TransferStatus:
        response = httpx.get(
            f"{self.base_url}/api/v0/transfers/downloads/"
            f"{username}/{transfer_id}",
            headers=self._headers(),
            timeout=10.0,
        )

        if response.status_code == 404:
            return TransferStatus(
                state="NotFound", bytes_transferred=None, size=None,
            )

        response.raise_for_status()
        data = response.json()

        return TransferStatus(
            state=cast(str, data["state"]),
            bytes_transferred=data.get("bytesTransferred"),
            size=data.get("size"),
        )

    def get_download_exception(
            self,
            username: str,
            transfer_id: str,
    ) -> str | None:
        # Confirmed live (2026-08-27): a rejected transfer's real reason
        # ("Transfer rejected: File not shared.") lives in this
        # "exception" field, not in "state" itself — state only says
        # "Completed, Rejected".
        response = httpx.get(
            f"{self.base_url}/api/v0/transfers/downloads/"
            f"{username}/{transfer_id}",
            headers=self._headers(),
            timeout=10.0,
        )

        if response.status_code == 404:
            return None

        response.raise_for_status()

        return cast(str | None, response.json().get("exception"))


def _parse_search_response(data: dict[str, Any]) -> list[SoulseekFile]:
    results = []

    for response in data.get("responses", []):
        username = response.get("username")
        queue_length = response.get("queueLength")
        upload_speed = response.get("uploadSpeed")
        has_free_upload_slot = response.get("hasFreeUploadSlot")

        # A response missing any of these isn't something we can act on
        # at all (no peer to request from, no queue to rank by) — skip
        # it rather than passing None into SoulseekFile's non-optional
        # fields. Every real response carries all four.
        if (
                username is None
                or queue_length is None
                or upload_speed is None
                or has_free_upload_slot is None
        ):
            continue

        for file in response.get("files", []):
            candidate = _build_soulseek_file(
                file,
                username,
                queue_length,
                upload_speed,
                has_free_upload_slot,
                # Defensive: honor a per-file isLocked=true within
                # "files" too, in case it's ever real — but the
                # confirmed-live signal (below) is membership in the
                # separate "lockedFiles" array.
                locked=bool(file.get("isLocked")),
            )

            if candidate is not None:
                results.append(candidate)

        # Real slskd responses carry locked files in a separate
        # "lockedFiles" array, confirmed live (2026-08-27) — a real
        # entry there still reports its own "isLocked" as False, so
        # array membership is the actual signal, not that field.
        # Previously dropped entirely; now included (locked=True) so
        # the Phase 3 retry cycle has something to track.
        for file in response.get("lockedFiles", []):
            candidate = _build_soulseek_file(
                file,
                username,
                queue_length,
                upload_speed,
                has_free_upload_slot,
                locked=True,
            )

            if candidate is not None:
                results.append(candidate)

    return results


def _build_soulseek_file(
        file: dict[str, Any],
        username: str,
        queue_length: int,
        upload_speed: int,
        has_free_upload_slot: bool,
        locked: bool,
) -> SoulseekFile | None:
    filename = file.get("filename")
    size = file.get("size")

    # Both essential — a candidate we can't identify, or can't request a
    # download for (slskd's enqueue API requires size), isn't usable
    # regardless of what else is present.
    if filename is None or size is None:
        return None

    return SoulseekFile(
        username=username,
        filename=filename,
        extension=_derive_extension(filename),
        size=size,
        length=file.get("length"),
        bit_rate=file.get("bitRate"),
        bit_depth=file.get("bitDepth"),
        sample_rate=file.get("sampleRate"),
        is_variable_bitrate=file.get("isVariableBitRate"),
        queue_length=queue_length,
        upload_speed=upload_speed,
        has_free_upload_slot=has_free_upload_slot,
        locked=locked,
    )


def _derive_extension(filename: str) -> str:
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]

    if "." not in basename:
        return ""

    return basename.rsplit(".", 1)[-1].lower()
