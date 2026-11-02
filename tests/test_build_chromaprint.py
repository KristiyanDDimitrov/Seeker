"""packaging/build_chromaprint.sh: the Intel app's libchromaprint, built
from a pinned source because Homebrew builds no new Intel bottles.

The build itself needs a compiler and the network and runs in CI
(build.yml); these tests read the script and run its functions, the
install step with cmake and sudo stubbed.
"""

import importlib.util
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging" / "build_chromaprint.sh"

# `otool -L` of Homebrew's arm64 libchromaprint 1.6.1 (2026-11-03): the
# library links the system's Accelerate, libc++ and libSystem alone.
_VERSIONS = "(compatibility version 1.0.0, current version 1.0.0)"
SYSTEM_ONLY = "\n".join(
    [
        "/opt/homebrew/lib/libchromaprint.1.dylib:",
        f"\t/opt/homebrew/opt/chromaprint/lib/libchromaprint.1.dylib {_VERSIONS}",
        f"\t/usr/lib/libSystem.B.dylib {_VERSIONS}",
        "\t/System/Library/Frameworks/Accelerate.framework/Versions/A/"
        f"Accelerate {_VERSIONS}",
        f"\t/usr/lib/libc++.1.dylib {_VERSIONS}",
        "",
    ],
)


def _bundle_info():
    spec = importlib.util.spec_from_file_location(
        "bundle_info", ROOT / "packaging" / "bundle_info.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _guard(otool_output: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — bash and the repository's script
        ["/bin/bash", "-c", f'source "{SCRIPT}"; only_system_dependencies'],
        input=otool_output, capture_output=True, text=True, check=False,
    )


def _install(tmp_path: Path, prefix: Path) -> list[str]:
    """Runs install_library with cmake and sudo stubbed on PATH and
    returns the commands the stubs saw, one line each. The sudo stub
    runs what it is given, as sudo would."""
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    log = tmp_path / "calls.log"
    (stubs / "cmake").write_text(
        f'#!/bin/bash\necho "cmake $*" >> "{log}"\n',
    )
    (stubs / "sudo").write_text(
        f'#!/bin/bash\necho "sudo $*" >> "{log}"\nexec "$@"\n',
    )
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    subprocess.run(  # noqa: S603 — bash and the repository's script
        [
            "/bin/bash", "-c",
            f'source "{SCRIPT}"; install_library /the/build "{prefix}"',
        ],
        env={"PATH": f"{stubs}:/usr/bin:/bin"},
        capture_output=True, text=True, check=True,
    )
    return log.read_text().splitlines()


# The sudo decision asks the file system, and root can write anywhere:
# these tests would pass on a bug, so only they are skipped, and only
# for root. The tests that expect no sudo run for every user.
needs_non_root = pytest.mark.skipif(
    os.geteuid() == 0, reason="root can write a read-only directory",
)


def test_the_script_is_valid_shell_and_executable():
    subprocess.run(  # noqa: S603 — bash, a fixed argument and the script
        ["/bin/bash", "-n", str(SCRIPT)], check=True,
    )
    assert SCRIPT.stat().st_mode & 0o111


def test_the_source_is_checked_against_a_pinned_hash_before_it_is_unpacked():
    text = SCRIPT.read_text()

    assert re.search(r"^SHA256=[0-9a-f]{64}$", text, re.MULTILINE)
    assert re.search(r"^VERSION=\d+\.\d+\.\d+$", text, re.MULTILINE)
    assert "shasum -a 256 -c" in text
    assert text.index("shasum -a 256 -c") < text.index("tar -xzf")


def test_it_builds_for_intel_at_the_bundles_floor_without_ffmpeg():
    text = SCRIPT.read_text()
    floor = _bundle_info().MINIMUM_SYSTEM_VERSION

    assert f"DEPLOYMENT_TARGET={floor}\n" in text
    assert "-DCMAKE_OSX_ARCHITECTURES=x86_64" in text
    assert '-DCMAKE_OSX_DEPLOYMENT_TARGET="$DEPLOYMENT_TARGET"' in text
    assert "-DFFT_LIB=vdsp" in text
    for option in ("BUILD_TOOLS", "BUILD_TESTS"):
        assert f"-D{option}=OFF" in text
    assert not re.search(r"^\s*(sudo )?brew ", text, re.MULTILINE)


def test_it_installs_where_the_spec_stages_the_library_from():
    info = _bundle_info()
    text = SCRIPT.read_text()

    assert f"prefix=${{1:-{info.INTEL_HOMEBREW_LIB.parent}}}" in text
    assert f'"$prefix/lib/{info.CHROMAPRINT_LIBRARY}"' in text


def test_a_library_that_links_only_macos_passes():
    result = _guard(SYSTEM_ONLY)

    assert result.returncode == 0, result.stderr


def test_a_homebrew_dependency_fails_and_is_named():
    homebrew = SYSTEM_ONLY + (
        "\t/usr/local/opt/ffmpeg/lib/libswresample.6.dylib "
        "(compatibility version 6.0.0, current version 6.1.100)\n"
    )

    result = _guard(homebrew)

    assert result.returncode == 1
    assert "/usr/local/opt/ffmpeg/lib/libswresample.6.dylib" in result.stderr


def test_an_rpath_dependency_fails_too():
    rpath = SYSTEM_ONLY + "\t@rpath/libavcodec.62.dylib (compatibility)\n"

    assert _guard(rpath).returncode == 1


def test_the_librarys_own_install_name_is_not_a_dependency():
    # The second line of `otool -L` is the library's own name, which is
    # /usr/local/... or @rpath/... depending on the build.
    own_name = SYSTEM_ONLY.replace(
        "/opt/homebrew/opt/chromaprint/lib/libchromaprint.1.dylib",
        "@rpath/libchromaprint.1.dylib",
    )

    assert _guard(own_name).returncode == 0


def test_a_prefix_the_user_can_write_installs_without_sudo(tmp_path):
    prefix = tmp_path / "prefix"
    (prefix / "lib").mkdir(parents=True)

    assert _install(tmp_path, prefix) == ["cmake --install /the/build"]


@needs_non_root
def test_a_prefix_the_user_cannot_write_installs_through_sudo(tmp_path):
    # /usr/local/lib on a Mac whose Homebrew belongs to another user.
    prefix = tmp_path / "prefix"
    lib = prefix / "lib"
    lib.mkdir(parents=True)
    lib.chmod(0o555)
    try:
        calls = _install(tmp_path, prefix)
    finally:
        lib.chmod(0o755)

    assert calls == [
        "sudo cmake --install /the/build",
        "cmake --install /the/build",
    ]


def test_a_prefix_that_does_not_exist_yet_installs_without_sudo(tmp_path):
    # A local Intel build into the repository: neither the prefix nor
    # its lib/ exists, and cmake would create both.
    prefix = tmp_path / "repo" / ".chromaprint"

    calls = _install(tmp_path, prefix)

    assert calls == ["cmake --install /the/build"]
    assert (prefix / "lib").is_dir()


@needs_non_root
def test_a_prefix_that_cannot_be_created_installs_through_sudo(tmp_path):
    # /usr/local/lib on a Mac with no Intel Homebrew: /usr/local is
    # root's and has no lib/ yet.
    parent = tmp_path / "root-owned"
    parent.mkdir()
    parent.chmod(0o555)
    try:
        calls = _install(tmp_path, parent / "local")
    finally:
        parent.chmod(0o755)

    assert calls == [
        "sudo cmake --install /the/build",
        "cmake --install /the/build",
    ]


def test_the_usage_names_the_variable_that_points_the_spec_at_the_prefix():
    info = _bundle_info()
    text = SCRIPT.read_text()

    assert f"{info.CHROMAPRINT_DIR_VARIABLE}=" in text


def test_a_prefix_in_the_repository_leaves_the_tree_clean():
    # RELEASING.md wants `git status` empty, and build/ is not an
    # option: PyInstaller's --clean empties it before the spec runs.
    prefix = ".chromaprint"

    command = [
        "git", "check-ignore", "-q", f"{prefix}/lib/libchromaprint.1.dylib",
    ]
    ignored = subprocess.run(  # noqa: S603 — fixed arguments
        command, cwd=ROOT, check=False,
    )

    assert ignored.returncode == 0
    assert prefix in SCRIPT.read_text()  # the usage names the same folder
