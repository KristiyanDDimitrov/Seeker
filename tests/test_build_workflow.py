"""`build.yml` builds both apps on their own hardware, smoke-tests the
frozen result and never publishes.

PyYAML is not a dependency, so the workflow is read as text, one step
per `      - ` entry under `steps:` (it has one job, `build`).
"""

import importlib.util
import re
from pathlib import Path

from seeker import cpu_architecture

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
BUILD = (WORKFLOWS / "build.yml").read_text()
CI = (WORKFLOWS / "ci.yml").read_text()


def _packaging_module(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "packaging" / f"{name}.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUNDLE_CHECK = _packaging_module("bundle_check")
BUNDLE_INFO = _packaging_module("bundle_info")


def _steps() -> list[str]:
    """The steps without their comment lines, which sit above the step
    they describe and would otherwise land in the one before."""
    body = BUILD.split("\n    steps:\n", 1)[1]
    body = re.sub(r"^ *#.*\n", "", body, flags=re.MULTILINE)
    return re.split(r"^      - ", body, flags=re.MULTILINE)[1:]


def _step(fragment: str) -> str:
    (step,) = [step for step in _steps() if fragment in step]
    return step


def _index(fragment: str) -> int:
    return _steps().index(_step(fragment))


def _header() -> str:
    """Everything before the job's steps: triggers, matrix, timeouts."""
    return BUILD.split("\n    steps:\n", 1)[0]


def test_it_runs_on_dispatch_tags_and_changes_to_the_build_inputs():
    header = _header()

    assert "  workflow_dispatch:\n" in header
    assert re.search(r"^    tags: \[\"v\*\"\]$", header, re.MULTILINE)
    paths = re.search(
        r"^    paths:\n((?:      (?:- |#).*\n)+)", header, re.MULTILINE,
    )
    assert paths
    listed = re.findall(r"^      - (\S+)", paths.group(1), re.MULTILINE)
    assert {"pyproject.toml", "uv.lock", "packaging/**"} <= set(listed)
    # The workflow's own file is a trigger: a workflow_dispatch run
    # needs the file on the default branch, a push does not.
    assert ".github/workflows/build.yml" in listed


def test_a_tag_filter_alone_would_skip_branch_pushes():
    # "If you define only tags ... the workflow won't run for events
    # affecting the undefined Git ref" (GitHub's workflow syntax).
    assert re.search(r"^    branches: \[\"\*\*\"\]$", _header(), re.MULTILINE)


def test_it_never_publishes():
    assert "permissions:\n  contents: read\n" in BUILD
    assert "write" not in BUILD
    assert not re.search(r"gh release|action-gh-release|gh-release", BUILD)
    assert "secrets." not in BUILD


def test_matrix_builds_each_architecture_on_its_own_pinned_runner():
    header = _header()

    assert "runner: macos-26" in header
    assert "runner: macos-15-intel" in header
    assert "-latest" not in header
    assert "runs-on: ${{ matrix.runner }}" in header
    assert "fail-fast: false" in header


def test_image_names_come_from_the_build_not_the_workflow():
    header = _header()
    for architecture in ("arm64", "x86_64"):
        image = BUNDLE_CHECK.dmg_name(architecture)
        assert re.search(
            rf"architecture: {architecture}\n\s+runner: \S+\n"
            rf"\s+image: {re.escape(image)}\n",
            header,
        ), (architecture, image)


def test_the_job_and_its_long_steps_have_timeouts():
    assert re.search(r"^    timeout-minutes: \d+$", _header(), re.MULTILINE)
    for fragment in ("build_chromaprint.sh", "build_dmg.py", "--smoke-test"):
        assert re.search(r"timeout-minutes: \d+", _step(fragment)), fragment


def test_every_action_is_pinned_to_a_commit_with_a_version_comment():
    uses = re.findall(r"uses: (\S+) *(#.*)?$", BUILD, flags=re.MULTILINE)

    assert uses
    for action, comment in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", action), action
        assert re.fullmatch(r"# v\d+\.\d+\.\d+", comment), action


def test_checkout_and_setup_uv_are_the_pins_ci_uses():
    for action in ("actions/checkout", "astral-sh/setup-uv"):
        pattern = rf"uses: {action}@[0-9a-f]{{40}} # v[\d.]+"
        ours = set(re.findall(pattern, BUILD))

        assert len(ours) == 1, action
        assert ours == set(re.findall(pattern, CI)), action


def test_the_build_runs_from_the_synced_environment_and_names_no_arch_prefix():
    runs = re.findall(r"run: (.*)", BUILD)

    assert "uv sync --locked" in runs
    assert ".venv/bin/python packaging/build_dmg.py" in runs
    assert not re.search(r"\barch -", BUILD)


def test_the_smoke_test_runs_the_built_app_with_an_absolute_report_path():
    smoke = _step("--smoke-test")

    assert 'dist/Seeker.app/Contents/MacOS/Seeker --smoke-test "$REPORT"' in smoke
    assert re.search(r"REPORT: \$\{\{ github\.workspace \}\}/dist/", smoke)
    assert _index("build_dmg.py") < _index("--smoke-test")


def test_the_image_is_checked_by_its_architecture_name():
    step = _step('test -f "dist/$IMAGE"')

    assert "IMAGE: ${{ matrix.image }}" in step
    assert _index("build_dmg.py") < _index('test -f "dist/$IMAGE"')


def test_the_report_must_show_a_frozen_native_app_that_found_chromaprint():
    step = _step("jq -e")

    for field in (".passed", ".frozen", ".chromaprint_available"):
        assert field in step
    assert ".architecture == $expected" in step
    assert "EXPECTED: ${{ matrix.expected_architecture }}" in step
    entries = _header().split("\n          - architecture: ")[1:]
    expected = {
        entry.split("\n")[0]: re.search(
            r"expected_architecture: (.*)", entry,
        ).group(1)
        for entry in entries
    }
    # Native names, never the Rosetta sentence an emulated run reports.
    assert expected == {
        "arm64": cpu_architecture.APPLE_SILICON,
        "x86_64": cpu_architecture.INTEL,
    }
    assert _index("--smoke-test") < _index("jq -e")


def test_the_intel_app_gets_a_libchromaprint_before_it_is_built():
    step = _step("libchromaprint (bundled")

    assert "if: matrix.architecture == 'x86_64'" in step
    assert "run: packaging/build_chromaprint.sh" in step
    assert "brew" not in step
    assert _index("libchromaprint (bundled") < _index("build_dmg.py")


def test_the_smoke_test_cannot_pass_on_the_build_machines_libchromaprint():
    # fingerprint.py searches /usr/local/lib after the bundle's own
    # folder; without this the Intel report would pass on the copy the
    # build installed, whether or not the bundled one loads.
    step = _step("Remove the build machine's libchromaprint")

    assert "if: matrix.architecture == 'x86_64'" in step
    assert "rm -f /usr/local/lib/libchromaprint*" in step
    assert _index("build_dmg.py") < _index("Remove the build machine's")
    assert _index("Remove the build machine's") < _index("--smoke-test")


def test_apple_silicon_relies_on_the_users_homebrew_copy():
    step = _step("libchromaprint for the smoke test")

    assert "if: matrix.architecture == 'arm64'" in step
    assert "brew install chromaprint" in step


def test_artifacts_are_short_lived_and_include_a_failed_runs_report():
    step = _step("actions/upload-artifact")

    assert "retention-days: 7" in step
    assert "if: ${{ !cancelled() }}" in step
    assert "dist/${{ matrix.image }}" in step
    assert "dist/smoke-report-${{ matrix.architecture }}.json" in step


def test_checkout_keeps_the_history_so_the_build_is_named_from_its_tag():
    step = _step("actions/checkout")

    assert "fetch-depth: 0" in step
    assert "persist-credentials: false" in step
