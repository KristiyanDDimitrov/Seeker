"""The macOS bundle's Info.plist, as packaging/seeker.spec builds it."""

import importlib.util
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_bundle_info():
    spec = importlib.util.spec_from_file_location(
        "bundle_info", PROJECT_ROOT / "packaging" / "bundle_info.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundle_version_is_the_project_version():
    version = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(),
    )["project"]["version"]

    plist = _load_bundle_info().info_plist(PROJECT_ROOT)

    assert plist["CFBundleShortVersionString"] == version
    assert plist["CFBundleVersion"] == version


def test_bundle_copyright_is_the_license_line():
    plist = _load_bundle_info().info_plist(PROJECT_ROOT)

    assert plist["NSHumanReadableCopyright"] == (
        "Copyright (c) 2026 Kristiyan Dimitrov"
    )


def test_bundle_declares_its_category_and_minimum_system():
    plist = _load_bundle_info().info_plist(PROJECT_ROOT)

    assert plist["LSApplicationCategoryType"] == "public.app-category.music"
    assert plist["LSMinimumSystemVersion"] == "15.0"
