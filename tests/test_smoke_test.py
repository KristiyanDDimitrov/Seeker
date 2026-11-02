"""`seeker-ui --smoke-test`, run in-process over the source tree.

The frozen app runs the same code; here the checks resolve against
`packaging/` and `src/`, what a source checkout ships.
"""

import json
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import qWarning

from seeker import cpu_architecture
from seeker.audio.analysis import AudioAnalysis
from seeker.ui import icons, smoke_test, theme

SRC_SEEKER = Path(smoke_test.__file__).resolve().parents[1]
CHECKS = ["imports", "theme", "fonts", "icons", "compose_template", "analysis"]


@pytest.fixture
def run(qapp, capsys):
    """Runs the smoke test; returns its exit code, its printed report
    and its stderr. Puts back the session's own theme afterwards: the
    check applies light, then dark, to the one QApplication."""

    def run_check(report_path=None):
        request = smoke_test.SmokeTestRequest(report_path=report_path)
        code = smoke_test.run_smoke_test(request)
        out, err = capsys.readouterr()
        return code, json.loads(out), err

    yield run_check
    theme.apply_theme(qapp)


def _source_modules() -> set[str]:
    names = set()
    for file in SRC_SEEKER.rglob("*.py"):
        parts = file.relative_to(SRC_SEEKER.parent).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        names.add(".".join(parts))
    return names


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], None),
        (["-psn_0_12345"], None),
        (["--smoke-test"], smoke_test.SmokeTestRequest(report_path=None)),
        (
            ["--smoke-test", "out/report.json"],
            smoke_test.SmokeTestRequest(report_path=Path("out/report.json")),
        ),
        (
            ["--smoke-test=report.json"],
            smoke_test.SmokeTestRequest(report_path=Path("report.json")),
        ),
        (
            ["--smoke-test", "-platform", "offscreen"],
            smoke_test.SmokeTestRequest(report_path=None),
        ),
    ],
)
def test_parse_request_reads_the_flag_and_its_report_path(argv, expected):
    assert smoke_test.parse_request(argv) == expected


def test_smoke_test_passes_unfrozen_and_writes_its_report(run, tmp_path):
    report_path = tmp_path / "report.json"

    code, printed, err = run(report_path)

    assert (code, err) == (0, "")
    assert json.loads(report_path.read_text()) == printed
    assert printed["passed"] is True
    assert printed["failed"] == []
    assert [check["name"] for check in printed["checks"]] == CHECKS
    assert all(check["passed"] for check in printed["checks"])
    assert printed["frozen"] is False
    assert printed["architecture"] == cpu_architecture.describe_architecture()


def test_the_import_check_imports_every_module_in_the_source_tree(run):
    _code, printed, _err = run()

    # Every module under the package, the generated build identity
    # included when an interrupted build left it behind; `seeker`
    # itself is imported to be walked.
    assert printed["modules_imported"] == len(_source_modules() - {"seeker"})
    assert set(sys.modules) >= _source_modules()


def test_a_walk_that_finds_no_modules_fails_the_import_check(
        run, monkeypatch,
):
    """Inside a frozen archive `pkgutil` may see nothing; an empty walk
    must fail rather than pass with nothing imported."""
    monkeypatch.setattr(
        smoke_test.pkgutil, "walk_packages", lambda *args, **kwargs: iter(()),
    )

    code, printed, err = run()

    assert code == 1
    assert printed["failed"] == ["imports"]
    assert err == "Smoke test failed: imports\n"


def test_a_module_that_cannot_be_imported_fails_the_import_check(
        run, monkeypatch,
):
    real_import = smoke_test.importlib.import_module

    def import_module(name):
        if name == "seeker.audio.analysis":
            raise ImportError("No module named 'numba'")
        return real_import(name)

    monkeypatch.setattr(smoke_test.importlib, "import_module", import_module)

    code, printed, _err = run()

    assert code == 1
    (imports,) = (c for c in printed["checks"] if c["name"] == "imports")
    assert "seeker.audio.analysis: ImportError: No module named 'numba'" in (
        imports["detail"]
    )


def test_a_qt_warning_while_theming_fails_the_theme_check(run, monkeypatch):
    real_apply = theme.apply_theme

    def apply_theme(app, mode="system"):
        palette = real_apply(app, mode)
        qWarning("Could not parse application stylesheet")
        return palette

    monkeypatch.setattr(smoke_test.theme, "apply_theme", apply_theme)

    code, printed, _err = run()

    assert code == 1
    assert printed["failed"] == ["theme"]
    (checked,) = (c for c in printed["checks"] if c["name"] == "theme")
    assert "Could not parse application stylesheet" in checked["detail"]


def test_a_bundle_without_its_resources_fails_their_checks(
        run, monkeypatch, tmp_path,
):
    """A frozen build missing its `datas`: resources resolve under an
    empty `_MEIPASS`. The theme still applies (the display face is
    already registered in this process), so only the resource checks
    fail."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(icons, "LUCIDE_DIR", tmp_path / "icons" / "lucide")

    code, printed, err = run()

    assert code == 1
    assert printed["failed"] == ["fonts", "icons", "compose_template"]
    assert err == "Smoke test failed: fonts, icons, compose_template\n"
    (checked,) = (c for c in printed["checks"] if c["name"] == "icons")
    assert "seeker_menubar_Template.png" in checked["detail"]


def test_the_analysis_check_finds_the_click_tracks_tempo_twice(run):
    _code, printed, _err = run()

    analysis = printed["analysis"]
    assert analysis["expected_bpm"] == pytest.approx(123.05, abs=0.01)
    for bpm in (analysis["cold_bpm"], analysis["warm_bpm"]):
        assert abs(bpm - analysis["expected_bpm"]) <= 2
    assert analysis["cold_seconds"] > 0
    assert analysis["warm_seconds"] > 0


def test_a_wrong_tempo_fails_the_analysis_check(run, monkeypatch):
    monkeypatch.setattr(
        smoke_test, "analyze_audio",
        lambda path: AudioAnalysis(bpm=61.5, camelot_key=None, key_confidence=0),
    )

    code, printed, err = run()

    assert code == 1
    assert printed["failed"] == ["analysis"]
    assert err == "Smoke test failed: analysis\n"
    (checked,) = (c for c in printed["checks"] if c["name"] == "analysis")
    assert "61.5" in checked["detail"]


def test_an_analysis_that_raises_fails_the_check_and_still_reports(
        run, monkeypatch,
):
    def analyze_audio(path):
        raise OSError("numba could not write its cache")

    monkeypatch.setattr(smoke_test, "analyze_audio", analyze_audio)

    code, printed, _err = run()

    assert code == 1
    assert printed["failed"] == ["analysis"]
    assert printed["analysis"] is None
    (checked,) = (c for c in printed["checks"] if c["name"] == "analysis")
    assert checked["detail"] == "OSError: numba could not write its cache"


@pytest.mark.parametrize("available", [True, False])
def test_chromaprint_is_reported_and_never_fails_the_test(
        run, monkeypatch, available,
):
    """Chromaprint is optional (duplicate detection only), so the report
    says whether it loads and the exit code ignores it."""
    monkeypatch.setattr(smoke_test.fingerprint, "is_available", lambda: available)

    code, printed, _err = run()

    assert code == 0
    assert printed["chromaprint_available"] is available
