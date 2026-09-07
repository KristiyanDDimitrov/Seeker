import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from seeker.config_store import SeekerConfig
from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.models.library_location import LibraryLocation
from seeker.sharing_service import (
    ShareAlreadyExistsError,
    SharingService,
    SharingWriteNotAllowedError,
    SlskdCredentialsMissingError,
    SlskdUnauthorizedError,
    _insert_compose_volume_line,
    _insert_slskd_share_directory,
)
from seeker.soulseek.client import SoulseekClient

# A fully-populated config -- the real shape a completed wizard/Settings
# run leaves in the store. Used as make_service's default so every
# pre-existing test below (which predates roadmap item R6's credential
# check) keeps exercising exactly what it did before, and only the new
# R6-specific tests need to pass a deliberately incomplete config.
CONFIGURED = SeekerConfig(
    slskd_username="dj", slskd_password="hunter2", slskd_api_key="realkey",
)


class FakeResponse:
    def __init__(self, data, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://slskd.test/api/v0/x")
            raise httpx.HTTPStatusError(
                f"{self.status_code} error",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )


class FakeCompletedProcess:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def make_service(
        tmp_path, compose_path=None, soulseek_client=None, config=CONFIGURED,
):
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    client = soulseek_client or SoulseekClient("http://slskd.test", "key")

    return SharingService(
        client,
        database,
        LibraryLocationRepository(database),
        compose_path=compose_path or (tmp_path / "docker-compose.yml"),
        get_config=lambda: config,
    )


def seed_location(
        service: SharingService,
        name: str,
        path: str,
) -> LibraryLocation:
    location = LibraryLocation(
        name=name, path=path, added_at=datetime.now(UTC).isoformat(),
    )

    with service.database.transaction() as connection:
        service.library_locations.add(location, connection)
        saved = service.library_locations.get_by_name(name, connection)

    assert saved is not None
    return saved


def test_get_status_parses_real_confirmed_shapes(tmp_path, monkeypatch):
    service = make_service(tmp_path)

    def fake_get(url, headers=None, timeout=None, params=None):
        if url.endswith("/api/v0/application"):
            return FakeResponse({
                "shares": {
                    "ready": True,
                    "scanning": False,
                    "scanPending": False,
                    "faulted": False,
                    "cancelled": False,
                    "scanProgress": 100,
                    "hosts": 1,
                    "directories": 3,
                    "files": 42,
                }
            })

        if url.endswith("/api/v0/shares"):
            return FakeResponse({
                "local": [
                    {
                        "id": "abc",
                        "alias": "music",
                        "isExcluded": False,
                        "localPath": "/shared/music",
                        "raw": "/shared/music",
                        "remotePath": "@@music",
                        "directories": 3,
                        "files": 42,
                    }
                ]
            })

        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(httpx, "get", fake_get)

    status = service.get_status()

    assert status.ready is True
    assert status.directories == 3
    assert status.files == 42
    assert len(status.shares) == 1
    assert status.shares[0].local_path == "/shared/music"
    assert status.shares[0].alias == "music"


def test_get_status_raises_readable_error_on_401(tmp_path, monkeypatch):
    # Roadmap item R6.4 -- a real 401 (e.g. the container recreated
    # without Seeker's API key) must surface as an actionable message,
    # not raw httpx.HTTPStatusError text in a UI panel.
    service = make_service(tmp_path)

    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: FakeResponse({}, status_code=401),
    )

    with pytest.raises(SlskdUnauthorizedError, match="Re-run SoulSeek setup"):
        service.get_status()


def test_get_uploads_raises_readable_error_on_401(tmp_path, monkeypatch):
    service = make_service(tmp_path)

    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: FakeResponse([], status_code=401),
    )

    with pytest.raises(SlskdUnauthorizedError):
        service.get_uploads()


def test_get_uploads_returns_empty_for_real_empty_array(tmp_path, monkeypatch):
    service = make_service(tmp_path)

    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: FakeResponse([]),
    )

    assert service.get_uploads() == []


def test_get_uploads_parses_defensively(tmp_path, monkeypatch):
    service = make_service(tmp_path)

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: FakeResponse([
            {
                "username": "peer1",
                "filename": "song.flac",
                "state": "InProgress",
                "bytesTransferred": 100,
                "size": 200,
            },
            {"unexpected": "shape"},
        ]),
    )

    uploads = service.get_uploads()

    assert len(uploads) == 2
    assert uploads[0].username == "peer1"
    assert uploads[0].bytes_transferred == 100
    assert uploads[1].username is None
    assert uploads[1].state is None


def test_get_reconciliation_matches_location_to_share_via_live_mounts(
        tmp_path, monkeypatch,
):
    service = make_service(tmp_path)
    seed_location(service, "Music", "/Volumes/Drive/Music")
    seed_location(service, "Other", "/Volumes/Drive/Other")

    def fake_get(url, headers=None, timeout=None, params=None):
        if url.endswith("/api/v0/application"):
            return FakeResponse({"shares": {"directories": 1, "files": 1}})

        return FakeResponse({
            "local": [
                {
                    "id": "1",
                    "alias": "music",
                    "isExcluded": False,
                    "localPath": "/shared/music",
                    "directories": 1,
                    "files": 1,
                }
            ]
        })

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: FakeCompletedProcess(
            stdout=json.dumps([
                {"Destination": "/shared/music", "Source": "/Volumes/Drive/Music"},
                {"Destination": "/app", "Source": str(tmp_path / "slskd-data")},
            ])
        ),
    )

    reconciliation = service.get_reconciliation()
    by_name = {state.location.name: state for state in reconciliation}

    assert by_name["Music"].shared is True
    assert by_name["Music"].share is not None
    assert by_name["Music"].share.local_path == "/shared/music"
    assert by_name["Other"].shared is False
    assert by_name["Other"].share is None


def test_get_reconciliation_all_unshared_when_docker_unreachable(
        tmp_path, monkeypatch,
):
    service = make_service(tmp_path)
    seed_location(service, "Music", "/Volumes/Drive/Music")

    monkeypatch.setattr(
        httpx, "get",
        lambda url, **k: FakeResponse(
            {"shares": {}} if url.endswith("/application") else {"local": []}
        ),
    )
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()),
    )

    reconciliation = service.get_reconciliation()

    assert all(not state.shared for state in reconciliation)


def test_is_self_managed_true_when_label_matches_compose_path(
        tmp_path, monkeypatch,
):
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text("services:\n  slskd:\n")
    service = make_service(tmp_path, compose_path=compose_path)

    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: FakeCompletedProcess(stdout=str(compose_path) + "\n"),
    )

    assert service.is_self_managed() is True


def test_is_self_managed_false_when_label_differs(tmp_path, monkeypatch):
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text("services:\n  slskd:\n")
    service = make_service(tmp_path, compose_path=compose_path)

    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: FakeCompletedProcess(
            stdout="/some/other/user-managed/docker-compose.yml\n"
        ),
    )

    assert service.is_self_managed() is False


def test_is_self_managed_false_when_docker_unreachable(tmp_path, monkeypatch):
    service = make_service(tmp_path)

    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()),
    )

    assert service.is_self_managed() is False


def test_preview_add_location_derives_alias_and_readonly_mount(tmp_path):
    service = make_service(tmp_path)
    location = seed_location(service, "My Drive", "/Volumes/My Drive/Music")

    plan = service.preview_add_location(location)

    assert plan.container_path == "/shared/My Drive"
    assert plan.compose_volume_line.endswith(':ro"')
    assert "/Volumes/My Drive/Music" in plan.compose_volume_line
    assert plan.slskd_share_directory_line.strip() == "- /shared/My Drive"


def test_add_location_to_share_requires_confirm(tmp_path):
    service = make_service(tmp_path)
    location = seed_location(service, "Music", "/Volumes/Drive/Music")

    with pytest.raises(ValueError):
        service.add_location_to_share(location, confirm=False)


def test_add_location_to_share_refuses_when_not_self_managed(
        tmp_path, monkeypatch,
):
    service = make_service(tmp_path)
    location = seed_location(service, "Music", "/Volumes/Drive/Music")

    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()),
    )

    with pytest.raises(SharingWriteNotAllowedError):
        service.add_location_to_share(location, confirm=True)


def test_add_location_to_share_refuses_when_already_shared(
        tmp_path, monkeypatch,
):
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text("services:\n  slskd:\n")
    service = make_service(tmp_path, compose_path=compose_path)
    location = seed_location(service, "Music", "/Volumes/Drive/Music")

    def fake_get(url, headers=None, timeout=None, params=None):
        if url.endswith("/application"):
            return FakeResponse({"shares": {}})

        return FakeResponse({
            "local": [{
                "id": "1", "alias": "music", "isExcluded": False,
                "localPath": "/shared/music", "directories": 1, "files": 1,
            }]
        })

    monkeypatch.setattr(httpx, "get", fake_get)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "inspect"] and "Labels" in cmd[-1]:
            return FakeCompletedProcess(stdout=str(compose_path) + "\n")

        return FakeCompletedProcess(stdout=json.dumps([
            {"Destination": "/shared/music", "Source": "/Volumes/Drive/Music"},
        ]))

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ShareAlreadyExistsError):
        service.add_location_to_share(location, confirm=True)


@pytest.mark.parametrize(
    "config",
    [
        SeekerConfig(slskd_username=None, slskd_password="p", slskd_api_key="k"),
        SeekerConfig(slskd_username="u", slskd_password=None, slskd_api_key="k"),
        SeekerConfig(slskd_username="u", slskd_password="p", slskd_api_key=None),
        SeekerConfig(),
    ],
)
def test_add_location_to_share_refuses_with_missing_credentials(
        tmp_path, monkeypatch, config,
):
    # Roadmap item R6.3 -- a recreate must never run with a blank
    # credential; refusing outright is safer than letting docker
    # compose substitute an empty string. Checked BEFORE any real
    # docker/httpx call, so no subprocess/httpx patching is needed here
    # to prove it -- an unpatched real call would fail loudly on its
    # own if this check didn't short-circuit first.
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text("services:\n  slskd:\n")
    service = make_service(tmp_path, compose_path=compose_path, config=config)
    location = seed_location(service, "Music", "/Volumes/Drive/Music")

    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: FakeCompletedProcess(stdout=str(compose_path) + "\n"),
    )

    with pytest.raises(SlskdCredentialsMissingError):
        service.add_location_to_share(location, confirm=True)


def test_add_location_to_share_recreates_via_bring_up_slskd_with_real_credentials(
        tmp_path, monkeypatch,
):
    # Roadmap item R6.2 -- one env contract, not two: add_location_to_share
    # must route through the SAME bring_up_slskd the wizard/Settings use,
    # passing the real persisted credentials, not a bespoke `docker
    # compose up` that only ever knew about two of the five real
    # variables.
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(
        "services:\n"
        "  slskd:\n"
        "    volumes:\n"
        '      - "./slskd-data:/app"\n'
        '      - "/Volumes/Drive/Music:/shared/music:ro"\n'
        "    restart: always\n"
    )

    data_dir = tmp_path / "slskd-data"
    data_dir.mkdir()
    slskd_yml_path = data_dir / "slskd.yml"
    slskd_yml_path.write_text("shares:\n  directories:\n    - /shared/music\n")

    service = make_service(tmp_path, compose_path=compose_path)
    location = seed_location(service, "New Drive", "/Volumes/New/Drive")

    def fake_get(url, headers=None, timeout=None, params=None):
        if url.endswith("/application"):
            return FakeResponse({
                "shares": {
                    "ready": True, "scanning": False, "scanPending": False,
                    "faulted": False, "directories": 2, "files": 10,
                }
            })
        return FakeResponse({"local": []})

    monkeypatch.setattr(httpx, "get", fake_get)

    captured_env: dict[str, str] = {}

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "inspect"] and "Labels" in cmd[-1]:
            return FakeCompletedProcess(stdout=str(compose_path) + "\n")

        if cmd[:2] == ["docker", "inspect"]:
            return FakeCompletedProcess(stdout=json.dumps([
                {"Destination": "/shared/music", "Source": "/Volumes/Drive/Music"},
                {"Destination": "/app", "Source": str(data_dir)},
            ]))

        assert cmd == [
                "docker",
                "compose",
                "-f",
                str(compose_path),
                "up",
                "-d",
        ]
        captured_env.update(kwargs["env"])
        return FakeCompletedProcess()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = service.add_location_to_share(location, confirm=True)

    assert result.became_ready is True
    assert captured_env["SLSKD_SLSK_USERNAME"] == CONFIGURED.slskd_username
    assert captured_env["SLSKD_SLSK_PASSWORD"] == CONFIGURED.slskd_password
    assert captured_env["SLSKD_API_KEY"] == CONFIGURED.slskd_api_key
    assert captured_env["SLSKD_DATA_DIR"] == str(data_dir)
    assert captured_env["SLSKD_SHARE_PATH"] == "/Volumes/Drive/Music"


def test_add_location_to_share_rolls_back_compose_when_recreate_fails(
        tmp_path, monkeypatch,
):
    # A failed `docker compose up` must not leave the compose file
    # holding a volume line for a share the container never actually
    # got -- same rollback discipline as the slskd.yml write failure
    # test below.
    compose_path = tmp_path / "docker-compose.yml"
    original_compose_text = (
        "services:\n"
        "  slskd:\n"
        "    volumes:\n"
        '      - "./slskd-data:/app"\n'
        "    restart: always\n"
    )
    compose_path.write_text(original_compose_text)

    data_dir = tmp_path / "slskd-data"
    data_dir.mkdir()
    slskd_yml_path = data_dir / "slskd.yml"
    slskd_yml_path.write_text("shares:\n  directories:\n    - /shared/music\n")

    service = make_service(tmp_path, compose_path=compose_path)
    location = seed_location(service, "New Drive", "/Volumes/New/Drive")

    def fake_get(url, headers=None, timeout=None, params=None):
        if url.endswith("/application"):
            return FakeResponse({"shares": {"directories": 1, "files": 3}})
        return FakeResponse({"local": []})

    monkeypatch.setattr(httpx, "get", fake_get)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "inspect"] and "Labels" in cmd[-1]:
            return FakeCompletedProcess(stdout=str(compose_path) + "\n")

        if cmd[:2] == ["docker", "inspect"]:
            return FakeCompletedProcess(stdout=json.dumps([
                {"Destination": "/shared/music", "Source": "/Volumes/Drive/Music"},
                {"Destination": "/app", "Source": str(data_dir)},
            ]))

        return FakeCompletedProcess(stdout="", returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    def fake_run_with_stderr(cmd, **kwargs):
        result = fake_run(cmd, **kwargs)
        result.stderr = "boom"
        return result

    monkeypatch.setattr(subprocess, "run", fake_run_with_stderr)

    with pytest.raises(RuntimeError, match="boom"):
        service.add_location_to_share(location, confirm=True)

    assert compose_path.read_text() == original_compose_text


def test_add_location_to_share_backs_up_and_writes_both_files(
        tmp_path, monkeypatch,
):
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(
        "services:\n"
        "  slskd:\n"
        "    volumes:\n"
        '      - "./slskd-data:/app"\n'
        '      - "/Volumes/Drive/Music:/shared/music:ro"\n'
        "    restart: always\n"
    )

    data_dir = tmp_path / "slskd-data"
    data_dir.mkdir()
    slskd_yml_path = data_dir / "slskd.yml"
    slskd_yml_path.write_text(
        "# shares:\n"
        "#   directories:\n"
        "#     - ~\n"
        "shares:\n"
        "  directories:\n"
        "    - /shared/music\n"
        "  filters:\n"
        "    - \\.ini$\n"
    )

    service = make_service(tmp_path, compose_path=compose_path)
    location = seed_location(service, "New Drive", "/Volumes/New/Drive")

    call_state = {"shares_calls": 0}

    def fake_get(url, headers=None, timeout=None, params=None):
        if url.endswith("/application"):
            return FakeResponse({
                "shares": {
                    "ready": True, "scanning": False, "scanPending": False,
                    "faulted": False, "directories": 2, "files": 10,
                }
            })

        call_state["shares_calls"] += 1

        return FakeResponse({
            "local": [{
                "id": "1", "alias": "music", "isExcluded": False,
                "localPath": "/shared/music", "directories": 2, "files": 10,
            }]
        })

    monkeypatch.setattr(httpx, "get", fake_get)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "inspect"] and "Labels" in cmd[-1]:
            return FakeCompletedProcess(stdout=str(compose_path) + "\n")

        if cmd[:2] == ["docker", "inspect"]:
            return FakeCompletedProcess(stdout=json.dumps([
                {"Destination": "/shared/music", "Source": "/Volumes/Drive/Music"},
                {"Destination": "/app", "Source": str(data_dir)},
            ]))

        assert cmd[:3] == ["docker", "compose", "-f"]
        return FakeCompletedProcess()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = service.add_location_to_share(location, confirm=True)

    assert result.became_ready is True
    assert result.compose_backup_path.exists()
    assert result.slskd_yml_backup_path.exists()

    updated_compose = compose_path.read_text()
    assert '/Volumes/New/Drive:/shared/New Drive:ro' in updated_compose
    assert '/Volumes/Drive/Music:/shared/music:ro' in updated_compose

    updated_slskd_yml = slskd_yml_path.read_text()
    assert "- /shared/New Drive" in updated_slskd_yml
    assert "- /shared/music" in updated_slskd_yml
    # The commented default-template block must stay untouched -- only
    # the real active section gets the new line.
    assert "#     - ~" in updated_slskd_yml


def _fake_run_for_add_location(compose_path, data_dir):
    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "inspect"] and "Labels" in cmd[-1]:
            return FakeCompletedProcess(stdout=str(compose_path) + "\n")

        if cmd[:2] == ["docker", "inspect"]:
            return FakeCompletedProcess(stdout=json.dumps([
                {"Destination": "/shared/music", "Source": "/Volumes/Drive/Music"},
                {"Destination": "/app", "Source": str(data_dir)},
            ]))

        assert cmd[:3] == ["docker", "compose", "-f"]
        return FakeCompletedProcess()

    return fake_run


def test_add_location_to_share_creates_shares_block_when_none_exists(
        tmp_path, monkeypatch,
):
    # Roadmap item 74 (P5.1) — the actual end-to-end reported bug: a
    # container whose slskd.yml has never had an active "shares:"
    # block (e.g. slskd's own real generated default) used to make
    # add_location_to_share raise outright.
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(
        "services:\n"
        "  slskd:\n"
        "    volumes:\n"
        '      - "./slskd-data:/app"\n'
        "    restart: always\n"
    )

    data_dir = tmp_path / "slskd-data"
    data_dir.mkdir()
    slskd_yml_path = data_dir / "slskd.yml"
    fixture_path = (
        Path(__file__).parent / "fixtures" / "slskd_generated_default.yml"
    )
    slskd_yml_path.write_text(fixture_path.read_text())

    service = make_service(tmp_path, compose_path=compose_path)
    location = seed_location(service, "New Drive", "/Volumes/New/Drive")

    def fake_get(url, headers=None, timeout=None, params=None):
        if url.endswith("/application"):
            return FakeResponse({
                "shares": {
                    "ready": True, "scanning": False, "scanPending": False,
                    "faulted": False, "directories": 1, "files": 3,
                }
            })
        return FakeResponse({"local": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(
        subprocess, "run", _fake_run_for_add_location(compose_path, data_dir),
    )

    result = service.add_location_to_share(location, confirm=True)

    assert result.became_ready is True

    updated_slskd_yml = slskd_yml_path.read_text()
    assert "shares:\n  directories:\n    - /shared/New Drive\n" in (
        updated_slskd_yml
    )


def test_add_location_to_share_rolls_back_compose_on_slskd_yml_write_failure(
        tmp_path, monkeypatch,
):
    # Roadmap item 74 (P5.2) — the OLD order wrote docker-compose.yml
    # first, then parsed+wrote slskd.yml; a failure in the second step
    # left the compose file already mutated, and a retry would add the
    # same volume line a SECOND time. Both new file contents are now
    # computed BEFORE either write, and the compose write is rolled
    # back from its own just-taken backup if the second write fails.
    compose_path = tmp_path / "docker-compose.yml"
    original_compose_text = (
        "services:\n"
        "  slskd:\n"
        "    volumes:\n"
        '      - "./slskd-data:/app"\n'
        "    restart: always\n"
    )
    compose_path.write_text(original_compose_text)

    data_dir = tmp_path / "slskd-data"
    data_dir.mkdir()
    slskd_yml_path = data_dir / "slskd.yml"
    slskd_yml_path.write_text(
        "shares:\n"
        "  directories:\n"
        "    - /shared/music\n"
    )

    service = make_service(tmp_path, compose_path=compose_path)
    location = seed_location(service, "New Drive", "/Volumes/New/Drive")

    def fake_get(url, headers=None, timeout=None, params=None):
        if url.endswith("/application"):
            return FakeResponse({
                "shares": {
                    "ready": True, "scanning": False, "scanPending": False,
                    "faulted": False, "directories": 1, "files": 3,
                }
            })
        return FakeResponse({"local": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(
        subprocess, "run", _fake_run_for_add_location(compose_path, data_dir),
    )

    real_write_text = Path.write_text

    def failing_write_text(self, *args, **kwargs):
        if self == slskd_yml_path:
            raise OSError("disk full (simulated)")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write_text)

    with pytest.raises(OSError):
        service.add_location_to_share(location, confirm=True)

    # The compose file must be back to its ORIGINAL content -- not left
    # holding the new volume line with nothing on the slskd.yml side to
    # match it.
    assert compose_path.read_text() == original_compose_text
    # slskd.yml was never touched at all (the failure was on write, not
    # a partial write).
    assert slskd_yml_path.read_text() == (
        "shares:\n"
        "  directories:\n"
        "    - /shared/music\n"
    )


def test_insert_compose_volume_line_appends_after_existing_entries():
    text = (
        "services:\n"
        "  slskd:\n"
        "    volumes:\n"
        '      - "./data:/app"\n'
        "    restart: always\n"
    )

    updated = _insert_compose_volume_line(text, '      - "/x:/shared/y:ro"')
    lines = updated.splitlines()

    assert lines[3] == '      - "./data:/app"'
    assert lines[4] == '      - "/x:/shared/y:ro"'
    assert lines[5] == "    restart: always"


def test_insert_slskd_share_directory_targets_active_not_commented_block():
    text = (
        "# shares:\n"
        "#   directories:\n"
        "#     - ~\n"
        "shares:\n"
        "  directories:\n"
        "    - /shared/music\n"
        "  filters:\n"
        "    - \\.ini$\n"
    )

    updated = _insert_slskd_share_directory(text, "    - /shared/new")
    lines = updated.splitlines()

    assert lines[0] == "# shares:"
    assert lines[5] == "    - /shared/music"
    assert lines[6] == "    - /shared/new"
    assert lines[7] == "  filters:"


# --- Roadmap item 74 (P5): create the block when none exists --------------

def test_insert_slskd_share_directory_creates_block_when_none_exists():
    # Roadmap item 74 (P5.1) — the actual reported bug: a slskd.yml
    # whose entire "shares:" section is still the commented-out default
    # template (no active block at all) used to be refused outright.
    text = (
        "# shares:\n"
        "#   directories:\n"
        "#     - ~\n"
        "feature:\n"
        "  swagger: true\n"
    )

    updated = _insert_slskd_share_directory(text, "    - /shared/new")

    assert updated == (
        "# shares:\n"
        "#   directories:\n"
        "#     - ~\n"
        "feature:\n"
        "  swagger: true\n"
        "shares:\n"
        "  directories:\n"
        "    - /shared/new\n"
    )


def test_insert_slskd_share_directory_creates_block_against_real_generated_default():
    # Roadmap item 74 (P5.1) — per the brief's own instruction, tested
    # against a REAL captured slskd-generated slskd.yml, not a
    # hand-written approximation. Captured live (2026-09-02) from a
    # genuinely fresh, never-hand-edited container
    # (`docker run ... slskd/slskd` against an empty data dir) —
    # confirms live that a real freshly-generated file has NO active
    # "shares:" block at all, only the commented default template (same
    # shape docker-compose.yml's own comment already described for the
    # repo's hand-edited copy).
    fixture_path = (
        Path(__file__).parent / "fixtures" / "slskd_generated_default.yml"
    )
    text = fixture_path.read_text()
    assert "shares:\n  directories:" not in text, (
        "fixture assumption violated -- expected no active block"
    )

    updated = _insert_slskd_share_directory(text, "    - /shared/new")

    # The real fixture has no trailing newline of its own -- the
    # function must add one before appending the new block, never glue
    # "shares:" onto the previous line.
    assert not text.endswith("\n")
    assert updated == (
        text + "\nshares:\n  directories:\n    - /shared/new\n"
    )
