"""The post-build check of a macOS bundle (packaging/bundle_check.py)."""

import importlib.util
import struct
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

BUILD_VERSION = """\
Load command 9
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform 1
    minos 14.0
      sdk 15.2
"""
VERSION_MIN = """\
Load command 8
      cmd LC_VERSION_MIN_MACOSX
  cmdsize 16
  version 10.13
      sdk 10.13
"""


def _load():
    spec = importlib.util.spec_from_file_location(
        "bundle_check", PROJECT_ROOT / "packaging" / "bundle_check.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _macho(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<I", 0xFEEDFACF) + b"\0" * 12)
    return path


def _bundle(tmp_path: Path) -> Path:
    app = tmp_path / "Seeker.app"
    _macho(app / "Contents" / "MacOS" / "Seeker")
    _macho(app / "Contents" / "Frameworks" / "libfoo.dylib")
    (app / "Contents" / "Resources").mkdir(parents=True)
    (app / "Contents" / "Resources" / "notes.txt").write_text("hello")
    (app / "Contents" / "Frameworks" / "link.dylib").symlink_to(
        "libfoo.dylib",
    )
    return app


class _Tools:
    """A canned lipo and otool, keyed by file name; records the calls."""

    def __init__(self) -> None:
        self.archs = {"Seeker": "arm64", "libfoo.dylib": "x86_64 arm64"}
        self.otool = {"Seeker": BUILD_VERSION, "libfoo.dylib": BUILD_VERSION}
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str]) -> str:
        self.calls.append(command)
        name = Path(command[-1]).name
        if command[0] == "lipo":
            return self.archs[name]
        return self.otool[name]


def test_macho_files_skips_text_and_symlinks(tmp_path):
    found = _load().macho_files(_bundle(tmp_path))

    assert sorted(path.name for path in found) == ["Seeker", "libfoo.dylib"]


def test_minimum_version_reads_both_load_command_forms():
    module = _load()

    assert module.parse_minos(BUILD_VERSION) == (14, 0)
    assert module.parse_minos(VERSION_MIN) == (10, 13)
    assert module.parse_minos("no version here") is None


def test_a_clean_bundle_has_no_problems(tmp_path):
    problems = _load().check_bundle(
        _bundle(tmp_path), "arm64", "15.0", _Tools(),
    )

    assert problems == []


def test_a_binary_without_the_target_architecture_is_reported(tmp_path):
    tools = _Tools()
    tools.archs["libfoo.dylib"] = "x86_64"

    problems = _load().check_bundle(
        _bundle(tmp_path), "arm64", "15.0", tools,
    )

    assert len(problems) == 1
    assert "libfoo.dylib" in problems[0] and "arm64" in problems[0]


def test_a_fat_main_executable_is_reported(tmp_path):
    tools = _Tools()
    tools.archs["Seeker"] = "x86_64 arm64"

    problems = _load().check_bundle(
        _bundle(tmp_path), "arm64", "15.0", tools,
    )

    assert len(problems) == 1
    assert "Seeker" in problems[0] and "thin" in problems[0]


def test_a_minos_above_the_floor_is_reported(tmp_path):
    tools = _Tools()
    tools.otool["libfoo.dylib"] = BUILD_VERSION.replace("14.0", "15.4")

    problems = _load().check_bundle(
        _bundle(tmp_path), "arm64", "15.0", tools,
    )

    assert len(problems) == 1
    assert "15.4" in problems[0] and "libfoo.dylib" in problems[0]


def test_minos_is_read_from_the_target_slice(tmp_path):
    tools = _Tools()
    tools.archs["libfoo.dylib"] = "x86_64"
    tools.archs["Seeker"] = "x86_64"

    _load().check_bundle(_bundle(tmp_path), "x86_64", "15.0", tools)

    otool_calls = [call for call in tools.calls if call[0] == "otool"]
    assert otool_calls
    assert all(call[1:3] == ["-arch", "x86_64"] for call in otool_calls)


def test_image_names_follow_the_architecture():
    module = _load()

    assert module.dmg_name("arm64") == "Seeker.dmg"
    assert module.dmg_name("x86_64") == "Seeker-Intel.dmg"


def test_a_source_version_is_not_a_deployment_target():
    output = (
        "Load command 3\n      cmd LC_SOURCE_VERSION\n  cmdsize 16\n"
        "  version 999.0\n" + BUILD_VERSION
    )

    assert _load().parse_minos(output) == (14, 0)
