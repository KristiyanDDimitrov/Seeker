import json
import subprocess
from datetime import datetime, timezone

import httpx
import pytest

from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.models.library_location import LibraryLocation
from seeker.sharing_service import (
    ShareAlreadyExistsError,
    SharingService,
    SharingWriteNotAllowedError,
    _insert_compose_volume_line,
    _insert_slskd_share_directory,
)
from seeker.soulseek.client import SoulseekClient


class FakeResponse:
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeCompletedProcess:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def make_service(tmp_path, compose_path=None, soulseek_client=None):
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    client = soulseek_client or SoulseekClient("http://slskd.test", "key")

    return SharingService(
        client,
        database,
        LibraryLocationRepository(database),
        compose_path=compose_path or (tmp_path / "docker-compose.yml"),
    )


def seed_location(service: SharingService, name: str, path: str) -> LibraryLocation:
    location = LibraryLocation(
        name=name, path=path, added_at=datetime.now(timezone.utc).isoformat(),
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
    location = seed_location(service, "Music", "/Volumes/Drive/Music")
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
