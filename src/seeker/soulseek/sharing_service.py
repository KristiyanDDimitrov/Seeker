"""SoulSeek sharing/uploads service.

Real API shapes below were confirmed live against a disposable
throwaway slskd container (SLSKD_SWAGGER=true), never the real
production one (see HISTORY §56's Phase 7 and HISTORY §62):

  GET /api/v0/shares -> {"local": [share, ...]}  -- NOT a bare array.
    Each share: id, alias, isExcluded, localPath (the CONTAINER-side
    path, e.g. "/shared/music"), raw, remotePath, directories, files.
  GET /api/v0/application's "shares" block: ready, scanning,
    scanPending, faulted, cancelled, scanProgress, hosts, directories,
    files.
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

A finding about one real slskd.yml (not a general slskd fact): the
shipped docker-compose.yml's default `${SLSKD_DATA_DIR:-./slskd-data}`
template is a fully commented-out reference block near the top of
slskd.yml -- the real, active `shares:` section slskd itself
writes/reads lives further down, uncommented. Never assume the
data-dir/share-path env var defaults baked into docker-compose.yml
reflect what's *actually* mounted right now (a container could have been
brought up with different env values than the file's own fallback) --
`docker inspect <container>` is the only live-verified source of truth
for real host<->container mount paths, so every lookup below goes
through `_get_live_container_mounts` rather than text-parsing
docker-compose.yml for paths.
"""

import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from seeker.config_store import SeekerConfig
from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.errors import SeekerError
from seeker.files.atomic import write_text_atomic
from seeker.files.sanitize import sanitize_path_component
from seeker.models.library_location import LibraryLocation
from seeker.soulseek.client import SoulseekClient
from seeker.soulseek.docker_setup import (
    SlskdBringUpError,
    bring_up_slskd,
    compose_file_path,
)

SLSKD_CONTAINER_NAME = "slskd"

# Every share this app adds lives under this container-side root --
# matches the existing default share's own "/shared/music" shape (see
# docker-compose.yml), so a new share reads as a sibling of the
# original rather than an unrelated top-level mount.
SHARE_MOUNT_ROOT = "/shared"

# Untuned, same convention as every other threshold in this codebase
# -- generous enough to cover a real container recreate + slskd's own
# share rescan of a modestly sized new folder.
SHARE_READY_TIMEOUT_SECONDS = 120.0
SHARE_READY_POLL_INTERVAL_SECONDS = 2.0

# `.bak-<timestamp>` copies kept per edited file; older ones are pruned
# each time a share is added.
BACKUPS_KEPT = 5


class SharingWriteNotAllowedError(SeekerError):
    pass


class ShareAlreadyExistsError(SeekerError):
    pass


class SlskdCredentialsMissingError(SeekerError):
    """Raised instead of recreating the slskd container with a blank
    credential: a recreate that silently de-authenticates the container
    (either from Seeker, or from the real SoulSeek network) is worse
    than refusing to recreate. An older install's wizard run, or any
    bring-up whose result was never routed through
    Application.persist_soulseek_config, leaves these fields None in the
    config store forever. See HISTORY §84."""


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


@dataclass
class _RecreateContext:
    """What add_location_to_share's preconditions established, for the
    phases after them."""
    config: SeekerConfig
    status_before: ShareStatus
    data_dir: str
    share_host_path: str
    slskd_yml_path: Path


@dataclass
class _OriginalTexts:
    compose: str
    slskd_yml: str


class SharingService:
    def __init__(
            self,
            soulseek_client: SoulseekClient | None,
            database: Database,
            library_location_repository: LibraryLocationRepository,
            compose_path: Path | None = None,
            container_name: str = SLSKD_CONTAINER_NAME,
            get_config: Callable[[], SeekerConfig] | None = None,
            record_bring_up: Callable[[str, str], None] | None = None,
    ) -> None:
        self._soulseek_client = soulseek_client
        self.database = database
        self.library_locations = library_location_repository
        self._compose_path = compose_path or compose_file_path()
        # Overridable only for live verification against a disposable
        # throwaway container (HISTORY §62) -- a second real container
        # can never itself be named "slskd" without colliding with (or
        # requiring touching) the real production one. Every real call
        # site in Application.sharing_service uses the default.
        self._container_name = container_name
        # Same callable-not-snapshot discipline as DownloadService/
        # TrackMatcher -- a Settings credential update takes
        # effect on the very next add_location_to_share call, no
        # restart or service-reconstruction needed.
        self._get_config = get_config or SeekerConfig
        # Saves (share path, data dir) after a successful recreate, so a
        # later one can work without a container to read them from.
        self._record_bring_up = record_bring_up or (lambda share, data: None)

    @property
    def soulseek(self) -> SoulseekClient:
        # Same lazy-raise shape as DownloadService.soulseek --
        # a caller that only wants is_self_managed()/preview_add_location
        # must not be forced to have SoulSeek configured at all.
        if self._soulseek_client is None:
            raise RuntimeError("SLSKD is not configured.")

        return self._soulseek_client

    def get_status(self) -> ShareStatus:
        client = self.soulseek
        shares_block = client.get_application().get("shares") or {}
        raw_shares = (client.get_shares() or {}).get("local") or []

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
        # The live [] shape and the slskd.Transfers.Transfer swagger
        # schema (additionalProperties: false) are both confirmed
        # (HISTORY §62) -- a POPULATED transfer object is NOT, since a
        # P2P connectivity limitation blocked producing one live.
        # _parse_upload's field names match the schema and are read
        # defensively either way: confirmed against the schema, not a
        # real instance -- the next real populated response seen live
        # (e.g. while using the Sharing page for real) is worth a
        # direct diff against this schema.
        data = self.soulseek.get_uploads()

        if not isinstance(data, list):
            return []

        return [_parse_upload(entry) for entry in data if isinstance(entry, dict)]

    def get_reconciliation(
            self,
            status: ShareStatus,
    ) -> list[LocationShareState]:
        """Which library locations `status`'s shares cover. Takes the
        status its caller already fetched, so a refresh asks slskd
        once."""
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

    def current_share_path(self) -> str | None:
        """The host folder the running container shares as
        /shared/music, or None when there is no container (or Docker
        can't be reached). A recreate passes this back unchanged so it
        never alters what is shared."""
        mounts = _get_live_container_mounts(self._container_name)
        return mounts.get(f"{SHARE_MOUNT_ROOT}/music")

    def current_data_dir(self) -> str | None:
        """The host folder the running container mounts as /app (its
        slskd.yml, state and downloads), or None when there is no
        container. A recreate reuses it so slskd keeps its state."""
        mounts = _get_live_container_mounts(self._container_name)
        return mounts.get("/app")

    def is_self_managed(self) -> bool:
        """True only when the running slskd container was created by
        THIS app's own docker-compose.yml -- never a user's own
        independently-run slskd instance Seeker was merely pointed at.
        Confirmed live: docker compose stamps every container it
        creates with a "com.docker.compose.project.config_files" label
        naming the exact compose file used -- the only live-verified
        signal for this, not assumed. Any failure to determine this
        (Docker not running, container missing, label absent)
        conservatively returns False -- the write path in
        add_location_to_share must never touch infrastructure this app
        doesn't provably own.
        """
        try:
            result = subprocess.run(
                [
                    "docker", "inspect", self._container_name,
                    "--format",
                    '{{index .Config.Labels '
                    '"com.docker.compose.project.config_files"}}',
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
        optional/configurable here).
        """
        container = self._check_preconditions(location, confirm)
        plan = self.preview_add_location(location)
        compose_backup, slskd_yml_backup = self._back_up_both(
            container.slskd_yml_path
        )
        originals = self._edit_both_files(plan, container.slskd_yml_path)

        try:
            self._recreate(container)
        except SlskdBringUpError:
            self._roll_back(originals, container.slskd_yml_path)
            raise

        self._record_bring_up(container.share_host_path, container.data_dir)
        became_ready = self._wait_until_share_ready()
        status_after = self.get_status()

        return SharingApplyResult(
            location=location,
            compose_backup_path=compose_backup,
            slskd_yml_backup_path=slskd_yml_backup,
            directories_before=container.status_before.directories,
            files_before=container.status_before.files,
            directories_after=status_after.directories,
            files_after=status_after.files,
            became_ready=became_ready,
        )

    def _check_preconditions(
            self,
            location: LibraryLocation,
            confirm: bool,
    ) -> _RecreateContext:
        """Every refusal add_location_to_share can make, all before any
        file is touched."""
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

        config = self._get_config()
        _require_saved_credentials(config)

        status_before = self.get_status()

        for state in self.get_reconciliation(status_before):
            if state.location.id == location.id and state.shared:
                raise ShareAlreadyExistsError(
                    f"'{location.name}' is already shared."
                )

        data_dir, share_host_path = self._live_data_dir_and_share()
        slskd_yml_path = Path(data_dir) / "slskd.yml"

        if not slskd_yml_path.exists():
            raise RuntimeError(f"{slskd_yml_path} does not exist.")

        return _RecreateContext(
            config=config,
            status_before=status_before,
            data_dir=data_dir,
            share_host_path=share_host_path,
            slskd_yml_path=slskd_yml_path,
        )

    def _live_data_dir_and_share(self) -> tuple[str, str]:
        mounts = _get_live_container_mounts(self._container_name)
        data_dir = mounts.get("/app")

        if data_dir is None:
            raise RuntimeError(
                "Could not determine the running slskd container's data "
                "directory -- is it running?"
            )

        # The template requires SLSKD_SHARE_PATH, and the recreate passes
        # the live value back unchanged, so a container without this
        # mount cannot be recreated at all.
        share_host_path = mounts.get(f"{SHARE_MOUNT_ROOT}/music")

        if share_host_path is None:
            raise RuntimeError(
                f"The running slskd container has no {SHARE_MOUNT_ROOT}/"
                "music share, so Seeker can't recreate it without "
                "changing what's shared. Re-run SoulSeek setup in "
                "Settings first."
            )

        return data_dir, share_host_path

    def _back_up_both(self, slskd_yml_path: Path) -> tuple[Path, Path]:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        compose_backup = self._compose_path.with_name(
            f"{self._compose_path.name}.bak-{timestamp}"
        )
        slskd_yml_backup = slskd_yml_path.with_name(
            f"{slskd_yml_path.name}.bak-{timestamp}"
        )

        shutil.copy2(self._compose_path, compose_backup)
        shutil.copy2(slskd_yml_path, slskd_yml_backup)
        _prune_backups(self._compose_path)
        _prune_backups(slskd_yml_path)

        return compose_backup, slskd_yml_backup

    def _edit_both_files(
            self,
            plan: SharingPlan,
            slskd_yml_path: Path,
    ) -> _OriginalTexts:
        """Write the new volume line and share directory; return both
        files' previous text for _roll_back."""
        # Both new contents are computed before either file is written,
        # so a parse failure leaves both untouched and a retry can't add
        # the same volume line twice (HISTORY §74).
        originals = _OriginalTexts(
            compose=self._compose_path.read_text(),
            slskd_yml=slskd_yml_path.read_text(),
        )
        updated_compose_text = _insert_compose_volume_line(
            originals.compose, plan.compose_volume_line
        )
        updated_slskd_yml_text = _insert_slskd_share_directory(
            originals.slskd_yml, plan.slskd_share_directory_line
        )

        # Each write is atomic, so a failure leaves that file whole.
        write_text_atomic(self._compose_path, updated_compose_text)

        try:
            write_text_atomic(slskd_yml_path, updated_slskd_yml_text)
        except Exception:
            write_text_atomic(self._compose_path, originals.compose)
            raise

        return originals

    def _recreate(self, container: _RecreateContext) -> None:
        # Reuses the live share path, not docker-compose.yml's own
        # fallback text, so a recreate never changes what is shared; the
        # new location's line carries its host path literally. The same
        # bring_up_slskd the wizard and Settings use knows every variable
        # the Compose file substitutes (HISTORY §84).
        config = container.config
        bring_up_slskd(
            compose_file=str(self._compose_path),
            soulseek_username=config.slskd_username or "",
            soulseek_password=config.slskd_password or "",
            api_key=config.slskd_api_key or "",
            slskd_data_dir=container.data_dir,
            # Saved by whichever bring-up (wizard or Settings) first
            # shared a location, which this recreate requires. Read,
            # never generated: this service holds only a read-only
            # get_config callable.
            web_username=config.slskd_web_username or "",
            web_password=config.slskd_web_password or "",
            library_location_path=container.share_host_path,
        )

    def _roll_back(
            self,
            originals: _OriginalTexts,
            slskd_yml_path: Path,
    ) -> None:
        # Restoring both keeps the pair consistent: a retry must not find
        # a volume line with no matching share, or add the same line
        # twice.
        write_text_atomic(self._compose_path, originals.compose)
        write_text_atomic(slskd_yml_path, originals.slskd_yml)

    def _wait_until_share_ready(self) -> bool:
        deadline = time.monotonic() + SHARE_READY_TIMEOUT_SECONDS

        while time.monotonic() < deadline:
            try:
                status = self.get_status()
            except httpx.HTTPError:
                time.sleep(SHARE_READY_POLL_INTERVAL_SECONDS)
                continue

            if status.ready and not status.scanning and not status.scan_pending:
                return True

            time.sleep(SHARE_READY_POLL_INTERVAL_SECONDS)

        return False


def _require_saved_credentials(config: SeekerConfig) -> None:
    # The Compose file substitutes a missing variable as an empty
    # string, not as unset, so a recreate without all of these would
    # de-authenticate Seeker's own API access or log the container out
    # of SoulSeek (HISTORY §84). Refusing is strictly safer.
    missing = [
        field_name for field_name, value in (
            ("SoulSeek network username", config.slskd_username),
            ("SoulSeek network password", config.slskd_password),
            ("slskd API key", config.slskd_api_key),
        )
        if not value
    ]

    if missing:
        raise SlskdCredentialsMissingError(
            "Can't safely recreate the slskd container -- Seeker "
            "doesn't have a saved " + " and ".join(missing) + ". "
            "Re-run SoulSeek setup in Settings first, so a recreate "
            "doesn't blank a real credential."
        )


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


def _prune_backups(path: Path) -> None:
    # The timestamp format sorts chronologically by name.
    backups = sorted(path.parent.glob(f"{path.name}.bak-*"))

    for backup in backups[:-BACKUPS_KEPT]:
        backup.unlink(missing_ok=True)


# Both edits below are line-level text surgery, not a YAML round-trip:
# each file has a known, machine-written shape (Seeker's own Compose
# template, and the slskd.yml slskd generates), the project carries no
# YAML dependency, and a shape these helpers don't recognise is refused
# rather than guessed at.

def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


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

    # After the last "- ..." entry; comments and blank lines inside the
    # list don't end it.
    insert_at = volumes_index + 1

    for index in range(volumes_index + 1, len(lines)):
        if _is_blank_or_comment(lines[index]):
            continue

        if lines[index].strip().startswith("- "):
            insert_at = index + 1
            continue

        break

    lines.insert(insert_at, new_line)

    return "\n".join(lines) + "\n"


# The active top-level key, not slskd's commented-out reference copy
# ("# shares:") near the top of the file it generates.
_ACTIVE_SHARES_KEY = re.compile(r"^shares:\s*(#.*)?$")
_DIRECTORIES_KEY = re.compile(r"^directories:\s*(#.*)?$")


def _insert_slskd_share_directory(slskd_yml_text: str, new_line: str) -> str:
    lines = slskd_yml_text.splitlines()
    entry = new_line.strip()
    shares_index = next(
        (
            index for index, line in enumerate(lines)
            if _ACTIVE_SHARES_KEY.match(line)
        ),
        None,
    )

    if shares_index is None:
        if any(line.startswith("shares:") for line in lines):
            raise _unsupported_slskd_yml("an inline 'shares:' value")

        # No active block is the normal state of a freshly generated
        # slskd.yml: slskd ships the whole section commented out.
        text = slskd_yml_text if slskd_yml_text.endswith("\n") else (
            slskd_yml_text + "\n"
        )
        return f"{text}shares:\n  directories:\n{new_line}\n"

    block_end = next(
        (
            index for index in range(shares_index + 1, len(lines))
            if not _is_blank_or_comment(lines[index])
            and _indent_of(lines[index]) == 0
        ),
        len(lines),
    )
    directories_index, child_indent = _find_directories_key(
        lines, shares_index, block_end,
    )

    if directories_index is None:
        lines[shares_index + 1:shares_index + 1] = [
            " " * child_indent + "directories:",
            " " * (child_indent + 2) + entry,
        ]
        return "\n".join(lines) + "\n"

    insert_at, entry_indent = _directories_insert_point(
        lines, directories_index, block_end,
    )
    lines.insert(insert_at, " " * entry_indent + entry)

    return "\n".join(lines) + "\n"


def _find_directories_key(
        lines: list[str], shares_index: int, block_end: int,
) -> tuple[int | None, int]:
    """The index of the `directories:` key directly under `shares:`
    (None when there is none), and the indentation of that block's
    children."""
    children = [
        index for index in range(shares_index + 1, block_end)
        if not _is_blank_or_comment(lines[index])
    ]
    child_indent = _indent_of(lines[children[0]]) if children else 2

    for index in children:
        if _indent_of(lines[index]) != child_indent:
            continue  # inside another child (e.g. under filters:)

        stripped = lines[index].strip()

        if _DIRECTORIES_KEY.match(stripped):
            return index, child_indent

        if stripped.startswith("directories:"):
            raise _unsupported_slskd_yml("an inline 'directories:' value")

    return None, child_indent


def _directories_insert_point(
        lines: list[str], directories_index: int, block_end: int,
) -> tuple[int, int]:
    """Where a new entry goes in the `directories:` list, and at which
    indentation: after the list's last entry, at that entry's own
    indentation (YAML also allows a list level with its key, "  - x"
    under "  directories:"). Deeper lines continue the entry above
    them."""
    directories_indent = _indent_of(lines[directories_index])
    entry_indent: int | None = None
    insert_at = directories_index + 1

    for index in range(directories_index + 1, block_end):
        line = lines[index]

        if _is_blank_or_comment(line):
            continue

        indent = _indent_of(line)

        if (
                line.strip().startswith("- ")
                and indent >= directories_indent
                and entry_indent in (None, indent)
        ):
            entry_indent = indent
            insert_at = index + 1
            continue

        if entry_indent is not None and indent > entry_indent:
            insert_at = index + 1
            continue

        break

    if entry_indent is None:
        entry_indent = directories_indent + 2

    return insert_at, entry_indent


def _unsupported_slskd_yml(shape: str) -> RuntimeError:
    return RuntimeError(
        f"slskd.yml has {shape}, which Seeker can't edit safely. Add the "
        "share to slskd.yml by hand, using the preview as a guide."
    )
