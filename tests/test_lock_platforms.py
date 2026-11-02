"""Every package `uv.lock` installs on a platform Seeker ships for has a
wheel that installs there.

`required-environments` in `pyproject.toml` makes `uv lock` fail only
for a package with no sdist. numba, llvmlite and numpy ship sdists, so
without the Intel constraints the lock moves Intel Macs to a numba
with no macOS x86_64 wheel and still passes. For them this test is the
only guard (HISTORY §253).

The walk follows the lock's own graph from the project, evaluating
each edge's marker for one platform at a time, and takes a forked
package's entry by its `resolution-markers`.
"""

import copy
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from packaging.markers import Marker
from packaging.tags import Tag, compatible_tags, cpython_tags, mac_platforms
from packaging.utils import parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
LOCK = tomllib.loads((ROOT / "uv.lock").read_text())
PYTHON = tuple(
    int(part) for part in (ROOT / ".python-version").read_text().strip().split(".")
)
CPYTHON = f"cp{PYTHON[0]}{PYTHON[1]}"
# The question is whether an architecture has a wheel at all, so any
# macOS release up to this one counts. Which release a wheel needs is
# the bundle's `minos`, checked after the build.
NEWEST_MACOS = (26, 0)

Package = dict[str, Any]


@dataclass(frozen=True)
class Platform:
    name: str
    markers: Mapping[str, str]
    platform_tags: tuple[str, ...]

    def supports(self, wheel_url: str) -> bool:
        filename = wheel_url.rsplit("/", 1)[-1]
        return not parse_wheel_filename(filename)[3].isdisjoint(
            self._supported_tags(),
        )

    def _supported_tags(self) -> frozenset[Tag]:
        # cpython_tags: cp313-cp313, cp313-abi3, then cp312-abi3 and
        # older; compatible_tags: py3-none-<platform> and py3-none-any.
        return frozenset(
            [
                *cpython_tags(
                    PYTHON, abis=[CPYTHON], platforms=self.platform_tags,
                ),
                *compatible_tags(
                    PYTHON, interpreter=CPYTHON,
                    platforms=self.platform_tags,
                ),
            ],
        )


def _markers(sys_platform: str, machine: str) -> dict[str, str]:
    python = ".".join(map(str, PYTHON))
    darwin = sys_platform == "darwin"
    return {
        "implementation_name": "cpython",
        "implementation_version": f"{python}.0",
        "os_name": "posix" if darwin else "nt",
        "platform_machine": machine,
        "platform_python_implementation": "CPython",
        "platform_release": "",
        "platform_system": "Darwin" if darwin else "Windows",
        "platform_version": "",
        "python_full_version": f"{python}.0",
        "python_version": python,
        "sys_platform": sys_platform,
        "extra": "",
    }


PLATFORMS = (
    Platform(
        "darwin/arm64",
        _markers("darwin", "arm64"),
        tuple(mac_platforms(NEWEST_MACOS, "arm64")),
    ),
    Platform(
        "darwin/x86_64",
        _markers("darwin", "x86_64"),
        tuple(mac_platforms(NEWEST_MACOS, "x86_64")),
    ),
    Platform("win32/AMD64", _markers("win32", "AMD64"), ("win_amd64",)),
)
INTEL = PLATFORMS[1]


def _applies(marker: str | None, platform: Platform) -> bool:
    return marker is None or Marker(marker).evaluate(dict(platform.markers))


def _entry(
        lock: Mapping[str, Any], edge: Mapping[str, Any], platform: Platform,
) -> Package:
    candidates = [
        package for package in lock["package"]
        if package["name"] == edge["name"]
        and edge.get("version", package["version"]) == package["version"]
        and any(
            _applies(marker, platform)
            for marker in package.get("resolution-markers", [None])
        )
    ]
    assert len(candidates) == 1, (edge, platform.name, candidates)
    return candidates[0]


def installed(
        lock: Mapping[str, Any], platform: Platform,
) -> Iterator[Package]:
    """Yield each registry package the lock installs on `platform`,
    every dependency group included, the project itself excluded."""
    (project,) = [
        package for package in lock["package"]
        if "editable" in package["source"]
    ]
    edges = [
        *project.get("dependencies", []),
        *(
            edge
            for group in project.get("dev-dependencies", {}).values()
            for edge in group
        ),
    ]
    seen: set[tuple[str, str, str]] = set()
    while edges:
        edge = edges.pop()
        if not _applies(edge.get("marker"), platform):
            continue
        package = _entry(lock, edge, platform)
        name, version = package["name"], package["version"]
        if (name, version, "") not in seen:
            seen.add((name, version, ""))
            edges.extend(package.get("dependencies", []))
            yield package
        for extra in edge.get("extra", []):
            if (name, version, extra) not in seen:
                seen.add((name, version, extra))
                edges.extend(package["optional-dependencies"][extra])


def wheel_gaps(lock: Mapping[str, Any]) -> list[str]:
    gaps = []
    for platform in PLATFORMS:
        for package in installed(lock, platform):
            label = f"{package['name']} {package['version']}"
            wheels = package.get("wheels", [])
            if not wheels:
                gaps.append(
                    f"{label} ships no wheel: it builds from source on "
                    f"{platform.name}",
                )
            elif not any(platform.supports(w["url"]) for w in wheels):
                gaps.append(
                    f"{label} has no {CPYTHON}, abi3 or pure-Python wheel "
                    f"for {platform.name}",
                )
    return gaps


def _names(lock: Mapping[str, Any], platform: Platform) -> set[str]:
    return {package["name"] for package in installed(lock, platform)}


def test_every_installed_package_has_a_wheel_for_each_platform():
    assert wheel_gaps(LOCK) == []


def test_the_platforms_are_the_locks_required_environments():
    required = [Marker(marker) for marker in LOCK["required-markers"]]

    for platform in PLATFORMS:
        matches = [m for m in required if m.evaluate(dict(platform.markers))]
        assert len(matches) == 1, platform.name
    assert len(required) == len(PLATFORMS)


def test_each_platform_falls_in_one_resolution_fork():
    for platform in PLATFORMS:
        forks = [
            marker for marker in LOCK["resolution-markers"]
            if _applies(marker, platform)
        ]
        assert len(forks) == 1, platform.name


def test_the_walk_reaches_every_locked_package():
    # A walk that reached nothing would find no gaps. Every registry
    # package is installed on at least one shipped platform today; a
    # Linux-only dependency would land here first.
    reached = {
        (package["name"], package["version"])
        for platform in PLATFORMS
        for package in installed(LOCK, platform)
    }
    locked = {
        (package["name"], package["version"])
        for package in LOCK["package"]
        if "registry" in package["source"]
    }

    assert reached == locked


def test_platform_markers_decide_what_each_platform_installs():
    darwin = _names(LOCK, PLATFORMS[0])
    windows = _names(LOCK, PLATFORMS[2])

    assert "pyobjc-framework-cocoa" in darwin
    assert "pyobjc-framework-cocoa" not in windows
    assert {"numba", "numpy", "llvmlite"} <= darwin & windows


def test_intel_takes_the_forked_entries():
    intel = {
        package["name"]: package["version"]
        for package in installed(LOCK, INTEL)
    }
    native = {
        package["name"]: package["version"]
        for package in installed(LOCK, PLATFORMS[0])
    }

    for name in ("numba", "llvmlite", "numpy"):
        assert intel[name] != native[name], name


def _intel_numba(lock: Mapping[str, Any]) -> Package:
    (numba,) = [
        package for package in installed(lock, INTEL)
        if package["name"] == "numba"
    ]
    return numba


def test_deleting_the_intel_numba_wheel_fails_naming_package_and_platform():
    lock = copy.deepcopy(LOCK)
    numba = _intel_numba(lock)
    numba["wheels"] = [
        wheel for wheel in numba["wheels"] if "x86_64" not in wheel["url"]
    ]

    assert wheel_gaps(lock) == [
        f"numba {numba['version']} ships no wheel: it builds from source "
        "on darwin/x86_64",
    ]


def test_the_native_numba_wheels_on_intel_fail_naming_package_and_platform():
    # What an unconstrained lock gives Intel: the current numba, whose
    # wheels cover every shipped platform but macOS x86_64.
    lock = copy.deepcopy(LOCK)
    numba = _intel_numba(lock)
    (native,) = [
        package for package in installed(lock, PLATFORMS[0])
        if package["name"] == "numba"
    ]
    numba["wheels"] = native["wheels"]

    assert wheel_gaps(lock) == [
        f"numba {numba['version']} has no {CPYTHON}, abi3 or pure-Python "
        "wheel for darwin/x86_64",
    ]


def _lock(*dependencies: Package) -> dict[str, Any]:
    """A lock whose project depends on each package directly, through
    the package's `edge` fields; `"edge": None` only locks it."""
    edges = [
        {"name": package["name"], **edge}
        for package in dependencies
        if (edge := package.pop("edge", {})) is not None
    ]
    project = {
        "name": "seeker", "version": "1", "source": {"editable": "."},
        "dependencies": edges,
    }
    for package in dependencies:
        package.setdefault("version", "1")
        package.setdefault("source", {"registry": "https://pypi.org/simple"})
    return {"package": [project, *dependencies]}


def _wheels(*filenames: str) -> list[dict[str, str]]:
    return [{"url": f"https://files.example/{name}"} for name in filenames]


ALL_THREE = (
    "macosx_11_0_arm64.whl", "macosx_10_15_x86_64.whl", "win_amd64.whl",
)


@pytest.mark.parametrize(
    "wheels",
    [
        pytest.param(["pure-1-py3-none-any.whl"], id="pure-python"),
        pytest.param(
            [f"lib-1-cp39-abi3-{platform}" for platform in ALL_THREE],
            id="abi3",
        ),
        pytest.param(
            ["lib-1-cp313-cp313-macosx_10_13_universal2.whl",
             "lib-1-cp313-cp313-win_amd64.whl"],
            id="universal2",
        ),
    ],
)
def test_a_wheel_for_every_platform_passes(wheels: list[str]):
    lock = _lock({"name": "lib", "wheels": _wheels(*wheels)})

    assert wheel_gaps(lock) == []


@pytest.mark.parametrize(
    ("abi", "why"),
    [("cp313t", "free-threaded"), ("cp314", "a newer Python")],
)
def test_a_wheel_for_another_interpreter_fails(abi: str, why: str):
    lock = _lock({
        "name": "lib",
        "wheels": _wheels(*(f"lib-1-{abi}-{abi}-{p}" for p in ALL_THREE)),
    })

    assert len(wheel_gaps(lock)) == len(PLATFORMS), why


def test_a_package_with_no_wheel_fails_on_every_platform():
    lock = _lock({"name": "lib", "sdist": {"url": "lib-1.tar.gz"}})

    assert wheel_gaps(lock) == [
        f"lib 1 ships no wheel: it builds from source on {platform.name}"
        for platform in PLATFORMS
    ]


def test_a_package_whose_marker_excludes_a_platform_is_not_checked_there():
    lock = _lock({
        "name": "mac-only",
        "edge": {"marker": "sys_platform == 'darwin'"},
        "wheels": _wheels("mac_only-1-cp313-cp313-macosx_10_13_universal2.whl"),
    })

    assert wheel_gaps(lock) == []


def test_an_extra_brings_in_its_optional_dependencies():
    lock = _lock(
        {
            "name": "host",
            "edge": {"extra": ["fast"]},
            "wheels": _wheels("host-1-py3-none-any.whl"),
            "optional-dependencies": {"fast": [{"name": "native"}]},
        },
        {
            "name": "native",
            "edge": None,
            "wheels": _wheels("native-1-cp313-cp313-win_amd64.whl"),
        },
    )

    assert wheel_gaps(lock) == [
        f"native 1 has no {CPYTHON}, abi3 or pure-Python wheel for {name}"
        for name in ("darwin/arm64", "darwin/x86_64")
    ]
