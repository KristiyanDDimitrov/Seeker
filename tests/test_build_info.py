import importlib
import importlib.util
import subprocess
import sys
import tomllib
import types
from pathlib import Path

import pytest

from seeker import _build_info

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILD_INFO_PATH = PROJECT_ROOT / "src" / "seeker" / "_build_info.py"


def test_tracked_build_info_fallback_is_dev():
    """Roadmap item 81 (0.1)'s post-implementation review (R1) — the
    tracked `_build_info.py` fallback must never be hand-edited to a
    real SHA. Reads the file's own source text directly (not via
    import), so this test can't be fooled by a real
    `_build_info_generated.py` sitting in a local dev venv from a prior
    build — see packaging/build_dmg.py, which writes there instead and
    never touches this tracked file.
    """
    source = BUILD_INFO_PATH.read_text()
    assert 'GIT_SHA = "dev"' in source
    assert 'GIT_DESCRIBE = "dev"' in source
    assert 'BUILT_AT = "dev"' in source


def test_build_info_generated_module_is_gitignored():
    gitignore = (PROJECT_ROOT / ".gitignore").read_text()
    assert "src/seeker/_build_info_generated.py" in gitignore


@pytest.fixture
def generated_build_info(monkeypatch):
    """A generated module importable as `seeker._build_info_generated`,
    as a packaging build leaves behind, and `_build_info` reloaded
    clean afterwards."""
    generated = types.ModuleType("seeker._build_info_generated")
    generated.GIT_SHA = "abc1234"
    generated.GIT_DESCRIBE = "v0.1.0-3-gabc1234"
    generated.BUILT_AT = "2026-10-10T11:17:43+00:00"
    monkeypatch.setitem(sys.modules, "seeker._build_info_generated", generated)
    yield generated
    monkeypatch.undo()
    importlib.reload(_build_info)


def test_source_run_ignores_a_generated_build_identity(
        generated_build_info, monkeypatch,
):
    """A build's generated module outlives the build on that machine;
    running from source must still say "dev", not that build."""
    monkeypatch.delattr(sys, "frozen", raising=False)

    importlib.reload(_build_info)

    assert _build_info.GIT_SHA == "dev"
    assert _build_info.GIT_DESCRIBE == "dev"
    assert _build_info.BUILT_AT == "dev"


def test_frozen_build_reads_its_generated_build_identity(
        generated_build_info, monkeypatch,
):
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    importlib.reload(_build_info)

    assert _build_info.GIT_SHA == "abc1234"
    assert _build_info.GIT_DESCRIBE == "v0.1.0-3-gabc1234"
    assert _build_info.BUILT_AT == "2026-10-10T11:17:43+00:00"


def _load_build_dmg():
    spec = importlib.util.spec_from_file_location(
        "build_dmg", PROJECT_ROOT / "packaging" / "build_dmg.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_dmg_removes_the_generated_module_after_a_failed_build(
        tmp_path, monkeypatch,
):
    build_dmg = _load_build_dmg()
    generated = tmp_path / "_build_info_generated.py"
    monkeypatch.setattr(build_dmg, "BUILD_INFO_PATH", generated)
    monkeypatch.setattr(build_dmg.sys, "platform", "darwin")
    monkeypatch.setattr(
        build_dmg, "_write_build_info", lambda: generated.write_text("x"),
    )

    def failing_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(build_dmg.subprocess, "run", failing_run)

    with pytest.raises(subprocess.CalledProcessError):
        build_dmg.main()

    assert not generated.exists()


def test_wheel_excludes_the_generated_module():
    """`uv build --wheel` packs whatever sits in the source tree."""
    backend = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(),
    )["tool"]["uv"]["build-backend"]
    assert "**/_build_info_generated.py" in backend["wheel-exclude"]
