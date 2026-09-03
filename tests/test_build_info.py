from pathlib import Path

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
