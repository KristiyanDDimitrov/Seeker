"""SoulSeek sharing/uploads service — roadmap item 62 (Phase 7).

Real API shapes below were confirmed live (2026-09-01) against a
disposable throwaway slskd container (SLSKD_SWAGGER=true), never the
real production one, per this project's standing "verify live, never
assume" rule (see docs/HISTORY.md item 62 for the full investigation):

  GET /api/v0/shares -> {"local": [share, ...]}  -- NOT a bare array,
    a NEW finding not previously documented anywhere in this codebase.
    Each share: id, alias, isExcluded, localPath (the CONTAINER-side
    path, e.g. "/shared/music"), raw, remotePath, directories, files.
  GET /api/v0/application's "shares" block: ready, scanning,
    scanPending, faulted, cancelled, scanProgress, hosts, directories,
    files -- CLAUDE.md item 53 already documented ready/scanning/
    directories/files; scanPending/faulted/cancelled/scanProgress/hosts
    are new findings from this same live check.
  PUT /api/v0/shares -> real HTTP 200, triggers a rescan. Confirmed via
    a real file added to the shared dir: files count 0 -> 1 after.
  GET /api/v0/transfers/uploads -> a flat array (unlike downloads,
    which is scoped by username in the URL). Returned [] live -- no
    real upload was in flight to observe an actual populated shape, so
    _parse_upload below is deliberately defensive (dict.get everywhere)
    rather than assuming exact field names beyond what the shared
    Transfer schema (state/bytesTransferred/size, see
    soulseek/client.py's TransferStatus) already confirms for
    downloads.
  PATCH /api/v0/options' OptionsOverlay schema has no "shares" key
    anywhere -- share directories genuinely cannot be changed via the
    API. The only way is editing slskd.yml + docker-compose.yml on
    disk and recreating the container, which is what
    add_location_to_share below does.

Real, confirmed-live finding about *this* dev machine's specific
slskd.yml (not a general slskd fact): the shipped docker-compose.yml's
default `${SLSKD_DATA_DIR:-./slskd-data}` template is a fully
commented-out reference block near the top of slskd.yml -- the real,
active `shares:` section slskd itself writes/reads lives further down,
uncommented. Never assume the data-dir/share-path env var defaults
baked into docker-compose.yml reflect what's *actually* mounted right
now (a container could have been brought up with different env values
than the file's own fallback) -- `docker inspect <container>` is the
only live-verified source of truth for real host<->container mount
paths, so every lookup below goes through `_get_live_container_mounts`
rather than text-parsing docker-compose.yml for paths.
"""

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.docker_setup import compose_file_path
from seeker.filename_sanitize import sanitize_path_component
from seeker.models.library_location import LibraryLocation
from seeker.soulseek.client import SoulseekClient

SLSKD_CONTAINER_NAME = "slskd"

# Every share this app adds lives under this container-side root --
# matches the existing default share's own "/shared/music" shape (see
# docker-compose.yml), so a new share reads as a sibling of the
# original rather than an unrelated top-level mount.
SHARE_MOUNT_ROOT = "/shared"

# Untuned constant, same convention as every other threshold in this
# codebase (see CLAUDE.md's "flag untuned constants explicitly" rule)
# -- generous enough to cover a real container recreate + slskd's own
# share rescan of a modestly sized new folder.
SHARE_READY_TIMEOUT_SECONDS = 120.0
SHARE_READY_POLL_INTERVAL_SECONDS = 2.0


class SharingWriteNotAllowedError(RuntimeError):
    pass


class ShareAlreadyExistsError(RuntimeError):
    pass


@dataclass
class ShareEntry:
    id: str
    alias: str
    local_path: str
    is_excluded: bool
    directories: int | None
    files: int | None


@dataclass
class ShareStatus:
    ready: bool
    scanning: bool
    scan_pending: bool
    faulted: bool
    directories: int
    files: int
    shares: list[ShareEntry]


@dataclass
class LocationShareState:
    location: LibraryLocation
    shared: bool
    share: ShareEntry | None


@dataclass
class UploadStatus:
    username: str | None
    filename: str | None
    state: str | None
    bytes_transferred: int | None
    size: int | None


@dataclass
class SharingPlan:
    """A dry-run preview of the exact docker-compose.yml/slskd.yml
    edits add_location_to_share would make -- rendered to the user for
    explicit confirmation before any file is touched, per this
    project's standing "never modify a real file without explicit
    confirmation" rule."""
    location: LibraryLocation
    container_path: str
    compose_volume_line: str
    slskd_share_directory_line: str


@dataclass
class SharingApplyResult:
    location: LibraryLocation
    compose_backup_path: Path
    slskd_yml_backup_path: Path
    directories_before: int
    files_before: int
    directories_after: int
    files_after: int
    became_ready: bool


class SharingService:
    def __init__(
            self,
            soulseek_client: SoulseekClient | None,
            database: Database,
            library_location_repository: LibraryLocationRepository,
            compose_path: Path | None = None,
            container_name: str = SLSKD_CONTAINER_NAME,
    ) -> None:
        self._soulseek_client = soulseek_client
        self.database = database
        self.library_locations = library_location_repository
        self._compose_path = compose_path or compose_file_path()
        # Overridable only for live verification against a disposable
        # throwaway container (see docs/HISTORY.md item 62's real
        # add_location_to_share E2E run) -- a second real container
        # can never itself be named "slskd" without colliding with (or
        # requiring touching) the real production one. Every real call
        # site in Application.sharing_service uses the default.
        self._container_name = container_name

    @property
    def soulseek(self) -> SoulseekClient:
        # Same lazy-raise shape as DownloadService.soulseek (item 28) --
        # a caller that only wants is_self_managed()/preview_add_location
        # must not be forced to have SoulSeek configured at all.
        if self._soulseek_client is None:
            raise RuntimeError("SLSKD is not configured.")

        return self._soulseek_client

    def get_status(self) -> ShareStatus:
        client = self.soulseek

        app_response = httpx.get(
            f"{client.base_url}/api/v0/application",
            headers=client._headers(),
            timeout=10.0,
        )
        app_response.raise_for_status()
        shares_block = app_response.json().get("shares") or {}

        shares_response = httpx.get(
            f"{client.base_url}/api/v0/shares",
            headers=client._headers(),
            timeout=10.0,
        )
        shares_response.raise_for_status()
        raw_shares = (shares_response.json() or {}).get("local") or []

        return ShareStatus(
            ready=bool(shares_block.get("ready")),
            scanning=bool(shares_block.get("scanning")),
            scan_pending=bool(shares_block.get("scanPending")),
            faulted=bool(shares_block.get("faulted")),
            directories=shares_block.get("directories") or 0,
            files=shares_block.get("files") or 0,
            shares=[_parse_share_entry(entry) for entry in raw_shares],
        )

    def get_uploads(self) -> list[UploadStatus]:
        # The real live [] shape and the real slskd.Transfers.Transfer
        # swagger schema (additionalProperties: false) are both
        # confirmed (docs/HISTORY.md item 62 follow-up) -- a real
        # POPULATED transfer object is NOT, since a genuine P2P
        # connectivity limitation blocked producing one live in that
        # investigation. _parse_upload's field names match the schema
        # and are read defensively either way, but this is the same
        # "confirmed against schema, not a real instance, reverify
        # opportunistically" flag CLAUDE.md item 53 already gives
        # placeInQueue -- the next real populated response seen live
        # (e.g. while using the Sharing page for real) is worth a
        # direct diff against this schema.
        client = self.soulseek

        response = httpx.get(
            f"{client.base_url}/api/v0/transfers/uploads",
            headers=client._headers(),
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, list):
            return []

        return [_parse_upload(entry) for entry in data if isinstance(entry, dict)]

    def get_reconciliation(self) -> list[LocationShareState]:
        status = self.get_status()
        mounts = _get_live_container_mounts(self._container_name)

        share_by_host_path: dict[str, ShareEntry] = {}

        for share in status.shares:
            host_path = mounts.get(share.local_path)

            if host_path is not None:
                share_by_host_path[host_path] = share

        with self.database.transaction() as connection:
            locations = self.library_locations.get_all(connection)

        return [
            LocationShareState(
                location=location,
                shared=location.path in share_by_host_path,
                share=share_by_host_path.get(location.path),
            )
            for location in locations
        ]

    def is_self_managed(self) -> bool:
        """True only when the running slskd container was created by
        THIS app's own docker-compose.yml -- never a user's own
        independently-run slskd instance Seeker was merely pointed at.
        Confirmed live (2026-09-01): docker compose stamps every
        container it creates with a
        "com.docker.compose.project.config_files" label naming the
        exact compose file used -- the only live-verified signal for
        this, not assumed. Any failure to determine this (Docker not
        running, container missing, label absent) conservatively
        returns False -- the write path in add_location_to_share must
        never touch infrastructure this app doesn't provably own.
        """
        try:
            result = subprocess.run(
                [
                    "docker", "inspect", self._container_name,
                    "--format",
                    '{{index .Config.Labels "com.docker.compose.project.config_files"}}',
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except (
                FileNotFoundError,
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
        ):
            return False

        label_value = result.stdout.strip()

        if not label_value:
            return False

        try:
            return Path(label_value).resolve() == self._compose_path.resolve()
        except OSError:
            return False

    def preview_add_location(self, location: LibraryLocation) -> SharingPlan:
        alias = sanitize_path_component(location.name)
        container_path = f"{SHARE_MOUNT_ROOT}/{alias}"

        return SharingPlan(
            location=location,
            container_path=container_path,
            compose_volume_line=(
                f'      - "{location.path}:{container_path}:ro"'
            ),
            slskd_share_directory_line=f"    - {container_path}",
        )

    def add_location_to_share(
            self,
            location: LibraryLocation,
            confirm: bool,
    ) -> SharingApplyResult:
        """Add one library location as a new, read-only SoulSeek share.
        Gated end to end: requires explicit confirm=True, requires
        is_self_managed(), backs up both edited files before writing
        either, and never mounts anything but read-only (":ro" is not
        optional/configurable here -- see CLAUDE.md's sharing framing).
        """
        if not confirm:
            raise ValueError(
                "add_location_to_share requires explicit confirm=True."
            )

        if not self.is_self_managed():
            raise SharingWriteNotAllowedError(
                "The running slskd container wasn't created by Seeker's "
                "own docker-compose.yml -- Seeker won't rewrite "
                "infrastructure it doesn't own. Add this folder as a "
                "share yourself, using the preview below as a guide."
            )

        reconciliation = self.get_reconciliation()

        for state in reconciliation:
            if state.location.id == location.id and state.shared:
                raise ShareAlreadyExistsError(
                    f"'{location.name}' is already shared."
                )

        mounts = _get_live_container_mounts(self._container_name)
        data_dir = mounts.get("/app")

        if data_dir is None:
            raise RuntimeError(
                "Could not determine the running slskd container's data "
                "directory -- is it running?"
            )

        slskd_yml_path = Path(data_dir) / "slskd.yml"

        if not slskd_yml_path.exists():
            raise RuntimeError(f"{slskd_yml_path} does not exist.")

        plan = self.preview_add_location(location)
        status_before = self.get_status()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        compose_backup = self._compose_path.with_name(
            f"{self._compose_path.name}.bak-{timestamp}"
        )
        slskd_yml_backup = slskd_yml_path.with_name(
            f"{slskd_yml_path.name}.bak-{timestamp}"
        )

        shutil.copy2(self._compose_path, compose_backup)
        shutil.copy2(slskd_yml_path, slskd_yml_backup)

        compose_text = self._compose_path.read_text()
        updated_compose_text = _insert_compose_volume_line(
            compose_text, plan.compose_volume_line
        )
        self._compose_path.write_text(updated_compose_text)

        slskd_yml_text = slskd_yml_path.read_text()
        updated_slskd_yml_text = _insert_slskd_share_directory(
            slskd_yml_text, plan.slskd_share_directory_line
        )
        slskd_yml_path.write_text(updated_slskd_yml_text)

        # Reuses the CURRENT live-resolved values for the pre-existing
        # env-var-driven mount (data dir + the original share path),
        # not docker-compose.yml's own hardcoded fallback text -- so a
        # recreate is idempotent regardless of how the container was
        # originally brought up (see this module's docstring). The new
        # line just added has its real host path baked in literally,
        # no env var needed.
        original_share_host_path = mounts.get(f"{SHARE_MOUNT_ROOT}/music")
        env = {
            "SLSKD_DATA_DIR": data_dir,
        }

        if original_share_host_path is not None:
            env["SLSKD_SHARE_PATH"] = original_share_host_path

        subprocess.run(
            [
                "docker", "compose", "-f", str(self._compose_path),
                "up", "-d",
            ],
            env={**_inherited_env(), **env},
            cwd=self._compose_path.parent,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )

        deadline = time.monotonic() + SHARE_READY_TIMEOUT_SECONDS
        became_ready = False

        while time.monotonic() < deadline:
            try:
                status_after = self.get_status()
            except httpx.HTTPError:
                time.sleep(SHARE_READY_POLL_INTERVAL_SECONDS)
                continue

            if (
                    status_after.ready
                    and not status_after.scanning
                    and not status_after.scan_pending
            ):
                became_ready = True
                break

            time.sleep(SHARE_READY_POLL_INTERVAL_SECONDS)

        status_after = self.get_status()

        return SharingApplyResult(
            location=location,
            compose_backup_path=compose_backup,
            slskd_yml_backup_path=slskd_yml_backup,
            directories_before=status_before.directories,
            files_before=status_before.files,
            directories_after=status_after.directories,
            files_after=status_after.files,
            became_ready=became_ready,
        )


def _inherited_env() -> dict[str, str]:
    return dict(os.environ)


def _get_live_container_mounts(container_name: str) -> dict[str, str]:
    """{container_path: host_path} for every real mount on the running
    container, read straight from `docker inspect` -- see this
    module's docstring for why this is the only trustworthy source,
    not docker-compose.yml's own text. Empty (not raising) whenever
    Docker/the container isn't reachable -- every caller here already
    treats an empty/missing mapping as "can't determine," not a hard
    error, since get_reconciliation() must keep working (all-unshared)
    even with slskd down.
    """
    try:
        result = subprocess.run(
            [
                "docker", "inspect", container_name,
                "--format", "{{json .Mounts}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (
            FileNotFoundError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
    ):
        return {}

    try:
        mounts = json.loads(result.stdout)
    except ValueError:
        return {}

    if not isinstance(mounts, list):
        return {}

    return {
        mount["Destination"]: mount["Source"]
        for mount in mounts
        if (
                isinstance(mount, dict)
                and mount.get("Destination")
                and mount.get("Source")
        )
    }


def _parse_share_entry(entry: dict[str, object]) -> ShareEntry:
    return ShareEntry(
        id=str(entry.get("id")),
        alias=str(entry.get("alias") or ""),
        local_path=str(entry.get("localPath") or ""),
        is_excluded=bool(entry.get("isExcluded")),
        directories=_as_optional_int(entry.get("directories")),
        files=_as_optional_int(entry.get("files")),
    )


def _parse_upload(entry: dict[str, object]) -> UploadStatus:
    username = entry.get("username")
    filename = entry.get("filename")
    state = entry.get("state")

    return UploadStatus(
        username=str(username) if username is not None else None,
        filename=str(filename) if filename is not None else None,
        state=str(state) if state is not None else None,
        bytes_transferred=_as_optional_int(entry.get("bytesTransferred")),
        size=_as_optional_int(entry.get("size")),
    )


def _as_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    return None


def _insert_compose_volume_line(compose_text: str, new_line: str) -> str:
    lines = compose_text.splitlines()
    volumes_index = None

    for index, line in enumerate(lines):
        if line.strip() == "volumes:":
            volumes_index = index
            break

    if volumes_index is None:
        raise RuntimeError(
            "docker-compose.yml has no 'volumes:' section to add to."
        )

    # Insert after the last existing "      - ..." entry under
    # volumes:, i.e. right before the first line that's no longer more
    # indented than the sibling entries (or end of file).
    insert_at = volumes_index + 1

    for index in range(volumes_index + 1, len(lines)):
        stripped = lines[index].strip()

        if stripped.startswith("- "):
            insert_at = index + 1
            continue

        break

    lines.insert(insert_at, new_line)

    return "\n".join(lines) + "\n"


def _insert_slskd_share_directory(slskd_yml_text: str, new_line: str) -> str:
    lines = slskd_yml_text.splitlines()

    # The REAL, active (uncommented) "shares:" block, not the fully
    # commented default-template reference near the top of the file
    # (see this module's docstring) -- only a line that's exactly
    # "shares:" at column 0, with an uncommented "directories:" child
    # right after it, is the real one.
    directories_index = None

    for index, line in enumerate(lines):
        if line == "shares:" and index + 1 < len(lines):
            next_line = lines[index + 1].strip()

            if next_line == "directories:":
                directories_index = index + 1
                break

    if directories_index is None:
        raise RuntimeError(
            "slskd.yml has no active 'shares: / directories:' section "
            "to add to."
        )

    insert_at = directories_index + 1

    for index in range(directories_index + 1, len(lines)):
        stripped = lines[index].strip()

        if stripped.startswith("- "):
            insert_at = index + 1
            continue

        break

    lines.insert(insert_at, new_line)

    return "\n".join(lines) + "\n"
