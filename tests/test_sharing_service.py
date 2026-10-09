import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from seeker.cli import handle_sharing_status
from seeker.config_store import SeekerConfig
from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.models.library_location import LibraryLocation
from seeker.soulseek.client import SlskdUnauthorizedError, SoulseekClient
from seeker.soulseek.sharing_service import (
    ShareAlreadyExistsError,
    SharingService,
    SharingWriteNotAllowedError,
    SlskdCredentialsMissingError,
    _insert_compose_volume_line,
    _insert_slskd_share_directory,
)

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
        LibraryLocationRepository(),
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

    reconciliation = service.get_reconciliation(service.get_status())
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

    reconciliation = service.get_reconciliation(service.get_status())

    assert all(not state.shared for state in reconciliation)


def test_sharing_status_fetches_application_state_once(
        tmp_path, monkeypatch, capsys,
):
    # `seeker sharing status` reads the status and the per-location
    # reconciliation, as a Sharing page refresh does; both come from
    # one GET of slskd's application state.
    service = make_service(tmp_path)
    seed_location(service, "Music", "/Volumes/Drive/Music")
    requested_urls: list[str] = []

    def fake_get(url, headers=None, timeout=None, params=None):
        requested_urls.append(url)

        if url.endswith("/api/v0/application"):
            return FakeResponse({"shares": {"ready": True}})

        return FakeResponse({"local": []})

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()),
    )
    application = SimpleNamespace(
        soulseek_configured=True, sharing_service=service,
    )

    handle_sharing_status(application, argparse.Namespace())

    assert "Music: not shared" in capsys.readouterr().out
    assert [
        url for url in requested_urls if url.endswith("/api/v0/application")
    ] == ["http://slskd.test/api/v0/application"]


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


def test_add_location_to_share_refuses_without_a_live_music_share(
        tmp_path, monkeypatch,
):
    # The template requires SLSKD_SHARE_PATH. A container with no
    # /shared/music mount gives no value to pass, so the recreate must
    # stop before any file is touched rather than fail halfway.
    compose_path = tmp_path / "docker-compose.yml"
    original_compose_text = (
        "services:\n"
        "  slskd:\n"
        "    volumes:\n"
        '      - "${SLSKD_DATA_DIR:?set by Seeker}:/app"\n'
        "    restart: unless-stopped\n"
    )
    compose_path.write_text(original_compose_text)

    data_dir = tmp_path / "slskd-data"
    data_dir.mkdir()
    slskd_yml_path = data_dir / "slskd.yml"
    original_slskd_yml_text = "shares:\n  directories:\n    - /shared/x\n"
    slskd_yml_path.write_text(original_slskd_yml_text)

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
                {"Destination": "/app", "Source": str(data_dir)},
            ]))

        raise AssertionError(f"unexpected command {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="/shared/music"):
        service.add_location_to_share(location, confirm=True)

    assert compose_path.read_text() == original_compose_text
    assert slskd_yml_path.read_text() == original_slskd_yml_text
    assert list(tmp_path.glob("*.bak-*")) == []
    assert list(data_dir.glob("*.bak-*")) == []


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


def _fail_temp_file_writes(monkeypatch, is_target):
    """Make write_text_atomic's temp file for a path matching
    `is_target` fail after its content is written, before the rename
    (a full disk or a crash surfacing at fsync)."""
    real_open = os.open
    real_fsync = os.fsync
    target_fds: set[int] = set()

    def recording_open(file, flags, *args, **kwargs):
        fd = real_open(file, flags, *args, **kwargs)
        if is_target(Path(file)):
            target_fds.add(fd)
        else:
            target_fds.discard(fd)
        return fd

    def failing_fsync(fd):
        if fd in target_fds:
            raise OSError("disk full (simulated)")
        real_fsync(fd)

    monkeypatch.setattr(os, "open", recording_open)
    monkeypatch.setattr(os, "fsync", failing_fsync)


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

    # The write lands in a temp sibling first (write_text_atomic).
    _fail_temp_file_writes(
        monkeypatch,
        lambda path: (
            path.parent == slskd_yml_path.parent and path.suffix == ".tmp"
        ),
    )

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


# --- Robustness: both files restored, atomic writes, pruned backups ------

_ROBUSTNESS_COMPOSE = (
    "services:\n"
    "  slskd:\n"
    "    volumes:\n"
    '      - "${SLSKD_DATA_DIR:?set by Seeker}:/app"\n'
    '      - "${SLSKD_SHARE_PATH:?set by Seeker}:/shared/music:ro"\n'
    "    restart: unless-stopped\n"
)
_ROBUSTNESS_SLSKD_YML = "shares:\n  directories:\n    - /shared/music\n"


def _ready_share_scenario(tmp_path, monkeypatch, compose_up_returncode=0):
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(_ROBUSTNESS_COMPOSE)
    data_dir = tmp_path / "slskd-data"
    data_dir.mkdir()
    slskd_yml_path = data_dir / "slskd.yml"
    slskd_yml_path.write_text(_ROBUSTNESS_SLSKD_YML)

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
    fake_run = _fake_run_for_add_location(compose_path, data_dir)

    def run(cmd, **kwargs):
        if cmd[:2] == ["docker", "compose"] and compose_up_returncode:
            result = FakeCompletedProcess(returncode=compose_up_returncode)
            result.stderr = "boom"
            return result
        return fake_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    return service, location, compose_path, slskd_yml_path


def test_add_location_to_share_restores_both_files_when_recreate_fails(
        tmp_path, monkeypatch,
):
    service, location, compose_path, slskd_yml_path = _ready_share_scenario(
        tmp_path, monkeypatch, compose_up_returncode=1,
    )

    with pytest.raises(RuntimeError, match="boom"):
        service.add_location_to_share(location, confirm=True)

    assert compose_path.read_text() == _ROBUSTNESS_COMPOSE
    assert slskd_yml_path.read_text() == _ROBUSTNESS_SLSKD_YML


def test_add_location_to_share_never_leaves_a_half_written_file(
        tmp_path, monkeypatch,
):
    # A write that dies part-way (disk full, a crash) must leave the
    # original file, not a truncated one slskd then fails to parse.
    service, location, compose_path, slskd_yml_path = _ready_share_scenario(
        tmp_path, monkeypatch,
    )
    _fail_temp_file_writes(
        monkeypatch,
        lambda path: (
            path.name.startswith("slskd.yml") and ".bak-" not in path.name
        ),
    )

    with pytest.raises(OSError, match="disk full"):
        service.add_location_to_share(location, confirm=True)

    assert slskd_yml_path.read_text() == _ROBUSTNESS_SLSKD_YML
    assert compose_path.read_text() == _ROBUSTNESS_COMPOSE
    assert sorted(
        path.name for path in slskd_yml_path.parent.iterdir()
        if ".bak-" not in path.name
    ) == ["slskd.yml"]


def test_add_location_to_share_keeps_only_the_newest_five_backups(
        tmp_path, monkeypatch,
):
    service, location, compose_path, slskd_yml_path = _ready_share_scenario(
        tmp_path, monkeypatch,
    )

    for day in range(1, 7):
        stamp = f"202601{day:02d}T000000Z"
        for path in (compose_path, slskd_yml_path):
            path.with_name(f"{path.name}.bak-{stamp}").write_text("old")

    result = service.add_location_to_share(location, confirm=True)

    for path, newest in (
            (compose_path, result.compose_backup_path),
            (slskd_yml_path, result.slskd_yml_backup_path),
    ):
        backups = sorted(path.parent.glob(f"{path.name}.bak-*"))
        assert len(backups) == 5
        assert newest in backups
        assert path.with_name(f"{path.name}.bak-20260106T000000Z") in backups
        assert not path.with_name(
            f"{path.name}.bak-20260102T000000Z"
        ).exists()


def test_insert_compose_volume_line_skips_comments_inside_the_list():
    text = (
        "services:\n"
        "  slskd:\n"
        "    volumes:\n"
        "      # slskd's own state\n"
        '      - "${SLSKD_DATA_DIR:?x}:/app"\n'
        "\n"
        "      # the music share\n"
        '      - "${SLSKD_SHARE_PATH:?x}:/shared/music:ro"\n'
        "    restart: unless-stopped\n"
    )

    updated = _insert_compose_volume_line(text, '      - "/x:/shared/y:ro"')
    lines = updated.splitlines()

    assert lines[7] == '      - "${SLSKD_SHARE_PATH:?x}:/shared/music:ro"'
    assert lines[8] == '      - "/x:/shared/y:ro"'
    assert lines[9] == "    restart: unless-stopped"


def test_insert_slskd_share_directory_finds_directories_after_filters():
    # A `shares:` block that starts with another key must gain the new
    # directory in its own list, never a second top-level `shares:`.
    text = (
        "shares:\n"
        "  filters:\n"
        "    - \\.ini$\n"
        "  directories:\n"
        "    - /shared/music\n"
        "web:\n"
        "  port: 5030\n"
    )

    updated = _insert_slskd_share_directory(text, "    - /shared/new")

    assert updated.count("shares:") == 1
    assert updated.splitlines() == [
        "shares:",
        "  filters:",
        "    - \\.ini$",
        "  directories:",
        "    - /shared/music",
        "    - /shared/new",
        "web:",
        "  port: 5030",
    ]


def test_insert_slskd_share_directory_adds_directories_to_a_block_without_one():
    text = "shares:\n  filters:\n    - \\.ini$\nweb:\n  port: 5030\n"

    updated = _insert_slskd_share_directory(text, "    - /shared/new")

    assert updated.count("shares:") == 1
    assert updated.splitlines() == [
        "shares:",
        "  directories:",
        "    - /shared/new",
        "  filters:",
        "    - \\.ini$",
        "web:",
        "  port: 5030",
    ]


def test_insert_slskd_share_directory_matches_the_lists_own_indentation():
    # YAML allows a list at its key's own indentation; a new entry
    # indented differently would break the file.
    text = "shares:\n  directories:\n  - /shared/music\n  # end\n"

    updated = _insert_slskd_share_directory(text, "    - /shared/new")

    assert updated.splitlines()[:4] == [
        "shares:",
        "  directories:",
        "  - /shared/music",
        "  - /shared/new",
    ]


@pytest.mark.parametrize("text", [
    "shares: {}\n",
    "shares:\n  directories: [/shared/music]\n",
])
def test_insert_slskd_share_directory_refuses_a_shape_it_cannot_edit(text):
    with pytest.raises(RuntimeError, match=r"slskd\.yml"):
        _insert_slskd_share_directory(text, "    - /shared/new")


def test_insert_slskd_share_directory_ignores_a_nested_directories_key():
    text = (
        "shares:\n"
        "  filters:\n"
        "    directories:\n"
        "      - not-the-share-list\n"
        "  directories:\n"
        "    - /shared/music\n"
    )

    updated = _insert_slskd_share_directory(text, "    - /shared/new")

    assert updated.splitlines()[-2:] == [
        "    - /shared/music",
        "    - /shared/new",
    ]


def test_insert_slskd_share_directory_fills_an_empty_directories_list():
    text = "shares:\n  directories:\n  filters:\n    - \\.ini$\n"

    updated = _insert_slskd_share_directory(text, "    - /shared/new")

    assert updated.splitlines() == [
        "shares:",
        "  directories:",
        "    - /shared/new",
        "  filters:",
        "    - \\.ini$",
    ]


def test_insert_slskd_share_directory_goes_after_an_entrys_continuation():
    # A line deeper than the entries continues the entry above it
    # (a folded scalar here), so the new entry goes after it.
    text = (
        "shares:\n"
        "  directories:\n"
        "    - >-\n"
        "      /shared/music\n"
        "  filters:\n"
        "    - \\.ini$\n"
    )

    updated = _insert_slskd_share_directory(text, "    - /shared/new")

    assert updated.splitlines()[:5] == [
        "shares:",
        "  directories:",
        "    - >-",
        "      /shared/music",
        "    - /shared/new",
    ]
