"""The Intel CI job exists, is blocking, and cannot hide a library bug;
`check` type-checks the Windows branches too, and a Windows job runs
the suite without failing the run until the suite passes there.

PyYAML is not a dependency, so the workflow is read as text, one job
per top-level key under `jobs:`.
"""

import re
from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
).read_text()


def _jobs() -> dict[str, str]:
    jobs = WORKFLOW.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  (\w[\w-]*):\n", jobs, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def _job(name: str) -> str:
    return _jobs()[name]


def _uses(job: str) -> list[str]:
    return re.findall(r"uses: (\S+@[0-9a-f]{40}) # v", job)


def _runs(job: str) -> list[str]:
    """Each step's `run:` command; a folded one (`run: >-`) is joined
    with spaces, as YAML folds it.
    """
    steps = re.findall(r"^( *)- run: (.*)\n((?:\1    \S.*\n)*)", job, re.MULTILINE)
    return [
        " ".join(line.strip() for line in folded.splitlines())
        if command == ">-" else command
        for _indent, command, folded in steps
    ]


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
    runs = _runs(_job("check-intel"))
    pytest_runs = [r for r in runs if r.startswith("uv run pytest -q")]

    assert len(pytest_runs) == 1
    assert not [r for r in runs if re.search(r"--cov|ruff|mypy", r)]


def test_check_intel_lists_its_slowest_tests():
    # The runner has failed two different tests on a short wait (§264,
    # §265) and nothing else records whether it stalls.
    runs = _runs(_job("check-intel"))

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
    runs = _runs(_job("check"))

    assert "uv run mypy --strict src/" in runs
    assert "uv run mypy --strict --platform win32 src/" in runs


def test_check_windows_runs_on_the_windows_image_offscreen_with_a_timeout():
    job = _job("check-windows")

    assert "runs-on: windows-2025" in job
    assert "QT_QPA_PLATFORM: offscreen" in job
    assert re.search(r"timeout-minutes: \d+", job)


def test_only_check_windows_may_fail_without_failing_the_run():
    """The suite has never passed on Windows. The change that makes it
    pass deletes the job's `continue-on-error` and this exception.
    """
    jobs = _jobs()
    windows = jobs.pop("check-windows")

    assert re.search(r"^    continue-on-error: true$", windows, re.MULTILINE)
    # Every other job, a future one too; the jobs named here only prove
    # the parse found them, so the sweep cannot pass over nothing.
    assert {"check", "check-intel", "audit"} <= jobs.keys()
    for name, job in jobs.items():
        assert "continue-on-error" not in job, name


def test_check_windows_runs_the_suite_alone():
    """ruff, both mypy runs and the coverage gate run in `check`.
    `-rfEs` lists each skip's reason beside the failures and errors,
    and a test still running after five minutes dumps every thread's
    stack, so a run the job's timeout kills still names the test that
    hung. A module that cannot import on Windows is one ERROR and the
    rest of the suite still runs; without the flag pytest stops at
    collection, and the failure list is that one line.
    """
    runs = _runs(_job("check-windows"))

    assert runs == [
        "uv sync --locked --all-extras --dev",
        "uv run pytest -q -rfEs --durations=25 --durations-min=1.0"
        " -o faulthandler_timeout=300 --continue-on-collection-errors",
    ]


def test_check_windows_pins_the_same_actions_as_check():
    assert _uses(_job("check-windows")) == _uses(_job("check"))


def test_check_windows_is_skipped_on_the_weekly_schedule_only():
    assert "if: github.event_name != 'schedule'" in _job("check-windows")


def test_check_intel_is_skipped_on_the_weekly_schedule_only():
    assert "if: github.event_name != 'schedule'" in _job("check-intel")
