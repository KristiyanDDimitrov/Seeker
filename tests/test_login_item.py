import logging
import sys
import types

import pytest

from seeker import login_item
from seeker.login_item import LoginItemStatus


def _force_supported(monkeypatch, supported: bool) -> None:
    monkeypatch.setattr(login_item, "is_supported", lambda: supported)


def _install_fake_service_management(
        monkeypatch,
        *,
        status: int,
        register_ok: bool = True,
        unregister_ok: bool = True,
):
    fake_service = types.SimpleNamespace(
        status=lambda: status,
        registerAndReturnError_=(
            lambda _: (register_ok, None if register_ok else "boom")
        ),
        unregisterAndReturnError_=(
            lambda _: (unregister_ok, None if unregister_ok else "boom")
        ),
    )
    fake_module = types.SimpleNamespace(
        SMAppService=types.SimpleNamespace(
            mainAppService=lambda: fake_service,
        ),
        SMAppServiceStatusEnabled=1,
        SMAppServiceStatusRequiresApproval=2,
        SMAppServiceStatusNotFound=3,
    )
    monkeypatch.setitem(sys.modules, "ServiceManagement", fake_module)
    return fake_service


def test_is_supported_false_off_darwin(monkeypatch):
    monkeypatch.setattr(login_item.sys, "platform", "win32")
    monkeypatch.setattr(login_item.sys, "frozen", True, raising=False)

    assert login_item.is_supported() is False


def test_is_supported_false_when_not_frozen(monkeypatch):
    monkeypatch.setattr(login_item.sys, "platform", "darwin")
    monkeypatch.delattr(login_item.sys, "frozen", raising=False)

    assert login_item.is_supported() is False


def test_is_supported_true_when_darwin_and_frozen(monkeypatch):
    monkeypatch.setattr(login_item.sys, "platform", "darwin")
    monkeypatch.setattr(login_item.sys, "frozen", True, raising=False)

    assert login_item.is_supported() is True


def test_get_status_not_supported_off_macos(monkeypatch):
    _force_supported(monkeypatch, False)

    assert login_item.get_status() is LoginItemStatus.NOT_SUPPORTED


def test_set_enabled_not_supported_off_macos(monkeypatch):
    _force_supported(monkeypatch, False)

    assert login_item.set_enabled(True) is LoginItemStatus.NOT_SUPPORTED


@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        (0, LoginItemStatus.DISABLED),
        (1, LoginItemStatus.ENABLED),
        (2, LoginItemStatus.REQUIRES_APPROVAL),
        (3, LoginItemStatus.NOT_FOUND),
    ],
)
def test_get_status_maps_every_real_sm_app_service_status(
        monkeypatch, raw_status, expected,
):
    # The four raw ints are confirmed live against the real
    # ServiceManagement module on a real Darwin 25.6.0 machine (see
    # login_item.py's own module docstring) — not assumed constants.
    _force_supported(monkeypatch, True)
    _install_fake_service_management(monkeypatch, status=raw_status)

    assert login_item.get_status() is expected


def test_set_enabled_true_registers_and_returns_new_status(monkeypatch):
    _force_supported(monkeypatch, True)
    fake_service = _install_fake_service_management(monkeypatch, status=1)
    calls: list[object] = []
    fake_service.registerAndReturnError_ = (
        lambda err: (calls.append(err), (True, None))[1]
    )

    result = login_item.set_enabled(True)

    assert result is LoginItemStatus.ENABLED
    assert calls == [None]


def test_set_enabled_false_unregisters_and_returns_new_status(monkeypatch):
    _force_supported(monkeypatch, True)
    fake_service = _install_fake_service_management(monkeypatch, status=0)
    calls: list[object] = []
    fake_service.unregisterAndReturnError_ = (
        lambda err: (calls.append(err), (True, None))[1]
    )

    result = login_item.set_enabled(False)

    assert result is LoginItemStatus.DISABLED
    assert calls == [None]


def test_set_enabled_logs_error_on_register_failure(monkeypatch, caplog):
    _force_supported(monkeypatch, True)
    _install_fake_service_management(
        monkeypatch, status=0, register_ok=False,
    )

    with caplog.at_level(logging.ERROR):
        login_item.set_enabled(True)

    assert "Failed to register login item" in caplog.text


def test_set_enabled_logs_error_on_unregister_failure(monkeypatch, caplog):
    _force_supported(monkeypatch, True)
    _install_fake_service_management(
        monkeypatch, status=0, unregister_ok=False,
    )

    with caplog.at_level(logging.ERROR):
        login_item.set_enabled(False)

    assert "Failed to unregister login item" in caplog.text
