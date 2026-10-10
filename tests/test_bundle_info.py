"""The macOS bundle's Info.plist, as packaging/seeker.spec builds it."""

import hashlib
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


def test_bundle_identifier_is_the_release_one():
    """The login item, notification permission and Launch Services all
    key on it, so it never changes after the first release."""
    assert _load_bundle_info().BUNDLE_IDENTIFIER == (
        "io.github.kristiyanddimitrov.seeker"
    )


def _license_datas():
    return _load_bundle_info().license_datas(PROJECT_ROOT)


def _bundled_files(datas) -> dict[str, Path]:
    """Each bundled licence file's path in the app, to its source."""
    return {
        f"{destination}/{Path(source).name}": Path(source)
        for source, destination in datas
    }


def test_every_runtime_distribution_ships_a_licence_text():
    """A dependency added without a licence text fails here, as the
    build itself would, rather than shipping without one."""
    bundle_info = _load_bundle_info()
    names = set(bundle_info.runtime_distributions())

    folders = {
        destination.split("/")[1] for _, destination in _license_datas()
    }

    assert folders == names | {"python"}


def test_the_runtime_closure_is_seekers_requirements_and_theirs():
    names = set(_load_bundle_info().runtime_distributions())

    # Direct, transitive (librosa's), and a development tool that the
    # bundle never ships.
    assert {"seeker", "mutagen", "shiboken6", "soxr"} <= names
    assert "pytest" not in names


def test_the_copyleft_components_ship_their_licence_texts():
    files = _bundled_files(_license_datas())

    assert "Version 2, June 1991" in files["licenses/mutagen/COPYING"].read_text()
    assert "Version 2.1, February 1999" in (
        files["licenses/soxr/COPYING.LGPL"].read_text()
    )
    for name in ("pyside6", "pyside6-addons", "pyside6-essentials", "shiboken6"):
        assert files[f"licenses/{name}/LGPL-3.0.txt"].is_file()
        assert files[f"licenses/{name}/GPL-3.0.txt"].is_file()
    # libgfortran, inside scipy's wheel: GPL-3.0 with the GCC exception.
    assert "GCC RUNTIME LIBRARY EXCEPTION" in (
        files["licenses/scipy/LICENSE.txt"].read_text()
    )


def test_seeker_and_python_ship_their_own_licences():
    files = _bundled_files(_license_datas())

    assert files["licenses/seeker/LICENSE"] == PROJECT_ROOT / "LICENSE"
    assert "PYTHON SOFTWARE FOUNDATION LICENSE" in (
        files["licenses/python/LICENSE.txt"].read_text()
    )


def test_vendored_licence_texts_are_the_published_ones():
    """GNU's texts as gnu.org serves them, PyObjC's as its framework
    wheels carry it: a vendored licence is never edited."""
    vendored = PROJECT_ROOT / "packaging" / "licenses"
    digests = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in vendored.iterdir()
    }

    assert digests == {
        "GPL-3.0.txt":
            "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986",
        "LGPL-3.0.txt":
            "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118",
        "PyObjC-MIT.txt":
            "0ca04b07928d4872b9d9bb22187ca0426dd8bfab08f26eada0999a71dc81aaff",
    }


def test_a_vendored_licence_is_only_for_a_wheel_without_its_own():
    """Once a wheel starts carrying its text, its vendored entry goes."""
    bundle_info = _load_bundle_info()
    distributions = bundle_info.runtime_distributions()

    for name in bundle_info.VENDORED_LICENSES:
        assert name in distributions
        assert bundle_info.own_license_files(distributions[name]) == []


def test_bundled_licence_files_never_overwrite_each_other():
    datas = _license_datas()

    assert len(_bundled_files(datas)) == len(datas)
