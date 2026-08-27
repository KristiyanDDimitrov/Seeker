import time
from typing import Any, cast

import httpx

from seeker.models.soulseek_file import SoulseekFile


class SoulseekDownloadError(RuntimeError):
    pass


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

        response = httpx.post(
            f"{self.base_url}/api/v0/transfers/downloads/batches",
            json=body,
            headers=self._headers(),
            timeout=15.0,
        )
        response.raise_for_status()

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

    def get_download_status(self, username: str, transfer_id: str) -> str:
        response = httpx.get(
            f"{self.base_url}/api/v0/transfers/downloads/"
            f"{username}/{transfer_id}",
            headers=self._headers(),
            timeout=10.0,
        )

        if response.status_code == 404:
            return "NotFound"

        response.raise_for_status()

        return cast(str, response.json()["state"])

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
