"""The Intel CI job exists, is blocking, and cannot hide a library bug;
`check` type-checks the Windows branches too.

PyYAML is not a dependency, so the workflow is read as text, one job
per top-level key under `jobs:`.
"""

import re
from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
).read_text()


def _job(name: str) -> str:
    jobs = WORKFLOW.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  (\w[\w-]*):\n", jobs, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))[name]


def _uses(job: str) -> list[str]:
    return re.findall(r"uses: (\S+@[0-9a-f]{40}) # v", job)


def test_check_intel_runs_on_the_intel_image_with_a_timeout():
    job = _job("check-intel")

    assert "runs-on: macos-15-intel" in job
    assert re.search(r"timeout-minutes: \d+", job)


def test_check_intel_requires_chromaprint_and_builds_it_from_source():
    """Homebrew builds no bottles for Intel Macs any more, so
    `brew install chromaprint` would compile ffmpeg and ten more
    formulae; the build script installs the one library the tests need.
    """
    job = _job("check-intel")

    assert 'SEEKER_REQUIRE_CHROMAPRINT: "1"' in job
    assert "run: packaging/build_chromaprint.sh" in job
    assert "brew install" not in job


def test_check_intel_runs_the_suite_without_the_coverage_gate():
    runs = re.findall(r"- run: (.*)", _job("check-intel"))
    pytest_runs = [r for r in runs if r.startswith("uv run pytest -q")]

    assert len(pytest_runs) == 1
    assert not [r for r in runs if re.search(r"--cov|ruff|mypy", r)]


def test_check_intel_lists_its_slowest_tests():
    # The runner has failed two different tests on a short wait (§264,
    # §265) and nothing else records whether it stalls.
    runs = re.findall(r"- run: (.*)", _job("check-intel"))

    assert "uv run pytest -q --durations=25 --durations-min=1.0" in runs


def test_check_intel_pins_the_same_actions_as_check():
    assert _uses(_job("check-intel")) == _uses(_job("check"))
    assert len(_uses(_job("check-intel"))) == 2


def test_check_requires_chromaprint_too():
    assert 'SEEKER_REQUIRE_CHROMAPRINT: "1"' in _job("check")


def test_check_type_checks_the_win32_branches_too():
    """mypy evaluates `sys.platform` statically: a run on macOS never
    checks the body of an `if sys.platform == "win32":`, so only a run
    told the platform does.
    """
    runs = re.findall(r"- run: (.*)", _job("check"))

    assert "uv run mypy --strict src/" in runs
    assert "uv run mypy --strict --platform win32 src/" in runs


def test_check_intel_is_skipped_on_the_weekly_schedule_only():
    assert "if: github.event_name != 'schedule'" in _job("check-intel")
