import time

import httpx

from seeker.models.soulseek_file import SoulseekFile


class SoulseekClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict:
        return {"X-API-Key": self.api_key}

    def search(
            self,
            query: str,
            timeout: float = 15.0,
            poll_interval: float = 1.0,
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
        data = {}

        while True:
            poll_response = httpx.get(
                f"{self.base_url}/api/v0/searches/{search_id}",
                headers=self._headers(),
                timeout=10.0,
            )
            poll_response.raise_for_status()

            data = poll_response.json()

            if data.get("isComplete"):
                break

            if time.monotonic() >= deadline:
                break

            time.sleep(poll_interval)

        return _parse_search_response(data)


def _parse_search_response(data: dict) -> list[SoulseekFile]:
    results = []

    for response in data.get("responses", []):
        username = response.get("username")
        queue_length = response.get("queueLength")
        upload_speed = response.get("uploadSpeed")
        has_free_upload_slot = response.get("hasFreeUploadSlot")

        for file in response.get("files", []):
            if file.get("isLocked"):
                continue

            filename = file["filename"]

            results.append(
                SoulseekFile(
                    username=username,
                    filename=filename,
                    extension=_derive_extension(filename),
                    size=file.get("size"),
                    length=file.get("length"),
                    bit_rate=file.get("bitRate"),
                    bit_depth=file.get("bitDepth"),
                    sample_rate=file.get("sampleRate"),
                    queue_length=queue_length,
                    upload_speed=upload_speed,
                    has_free_upload_slot=has_free_upload_slot,
                )
            )

    return results


def _derive_extension(filename: str) -> str:
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]

    if "." not in basename:
        return ""

    return basename.rsplit(".", 1)[-1].lower()
