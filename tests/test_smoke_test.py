"""`seeker-ui --smoke-test`, run in-process over the source tree.

The frozen app runs the same code; here the checks resolve against
`packaging/` and `src/`, what a source checkout ships.
"""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from seeker import cpu_architecture, main_ui
from seeker.audio.analysis import AudioAnalysis
from seeker.ui import icons, smoke_test, theme

SRC_SEEKER = Path(smoke_test.__file__).resolve().parents[1]
SPEC = SRC_SEEKER.parents[1] / "packaging" / "seeker.spec"
CHECKS = [
    "imports", "hidden_imports", "platform_plugin", "theme", "fonts",
    "icons", "compose_template", "analysis",
]


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


@pytest.mark.parametrize("argv", [[], ["-psn_0_12345"]])
def test_parse_request_without_the_flag_is_none(argv):
    assert smoke_test.parse_request(argv) is None


@pytest.mark.parametrize(
    ("argv", "report_path"),
    [
        (["--smoke-test"], None),
        (["--smoke-test", "-platform", "offscreen"], None),
        (["--smoke-test", "out/report.json"], "out/report.json"),
        (["--smoke-test=report.json"], "report.json"),
        (["--smoke-test", "/var/report.json"], "/var/report.json"),
    ],
)
def test_parse_request_resolves_the_report_path_against_the_cwd(
        argv, report_path, monkeypatch, tmp_path,
):
    """Resolved when parsed, so the report names the file it means: a
    Finder or `open --args` launch runs with the cwd at /."""
    monkeypatch.chdir(tmp_path)
    expected = None if report_path is None else tmp_path / report_path

    assert smoke_test.parse_request(argv) == smoke_test.SmokeTestRequest(
        report_path=expected,
    )


def test_parse_request_refuses_an_empty_report_path():
    with pytest.raises(smoke_test.SmokeTestUsageError, match="--smoke-test="):
        smoke_test.parse_request(["--smoke-test="])


def test_the_entry_point_names_an_unusable_flag_and_exits_2(
        monkeypatch, capsys,
):
    monkeypatch.setattr(sys, "argv", ["seeker-ui", "--smoke-test="])

    with pytest.raises(SystemExit) as exited:
        main_ui.main()

    assert exited.value.code == 2
    assert "--smoke-test=" in capsys.readouterr().err


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


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="the hidden imports are pyobjc's, installed only on macOS",
)
def test_a_hidden_import_that_cannot_be_imported_fails_its_check(
        run, monkeypatch,
):
    """`login_item.py` imports ServiceManagement only inside a function,
    so the package walk never does; a bundle without it must fail."""
    real_import = smoke_test.importlib.import_module

    def import_module(name):
        if name == "ServiceManagement":
            raise ImportError("No module named 'ServiceManagement'")
        return real_import(name)

    monkeypatch.setattr(smoke_test.importlib, "import_module", import_module)

    code, printed, _err = run()

    assert code == 1
    assert printed["failed"] == ["hidden_imports"]
    (checked,) = (c for c in printed["checks"] if c["name"] == "hidden_imports")
    assert "ServiceManagement: ImportError" in checked["detail"]


def test_the_spec_bundles_the_hidden_imports_the_check_imports():
    """One list, so the spec and the check cannot drift apart."""
    tree = ast.parse(SPEC.read_text(encoding="utf-8"), filename=str(SPEC))
    imported = {
        (node.module, alias.name)
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    (hidden,) = (
        keyword.value for node in ast.walk(tree) if isinstance(node, ast.Call)
        for keyword in node.keywords if keyword.arg == "hiddenimports"
    )

    assert ("seeker.frozen_imports", "HIDDEN_IMPORTS") in imported
    assert ast.unparse(hidden) == "list(HIDDEN_IMPORTS)"


def test_a_bundle_without_the_native_platform_plugin_fails_its_check(
        run, monkeypatch, tmp_path,
):
    """The check runs offscreen, so only the plugin's file shows that a
    person's launch would find the native one."""
    (tmp_path / "platforms").mkdir()
    (tmp_path / "platforms" / "libqoffscreen.dylib").touch()

    class LibraryInfo(smoke_test.QLibraryInfo):
        @staticmethod
        def path(which):
            assert which == smoke_test.QLibraryInfo.LibraryPath.PluginsPath
            return str(tmp_path)

    monkeypatch.setattr(smoke_test, "QLibraryInfo", LibraryInfo)

    code, printed, _err = run()

    assert code == 1
    assert printed["failed"] == ["platform_plugin"]
    (checked,) = (c for c in printed["checks"] if c["name"] == "platform_plugin")
    assert str(tmp_path / "platforms") in checked["detail"]


def test_an_unparseable_stylesheet_fails_the_theme_check(run, monkeypatch):
    """Qt parses a stylesheet only when it polishes a widget, so setting
    a broken one warns nothing by itself."""
    real_apply = theme.apply_theme

    def apply_theme(app, mode="system"):
        palette = real_apply(app, mode)
        app.setStyleSheet(app.styleSheet() + "\nQWidget { color: ")
        return palette

    monkeypatch.setattr(smoke_test.theme, "apply_theme", apply_theme)

    code, printed, _err = run()

    assert code == 1
    assert printed["failed"] == ["theme"]
    (checked,) = (c for c in printed["checks"] if c["name"] == "theme")
    assert "Could not parse application stylesheet" in checked["detail"]


def test_a_weight_found_only_outside_the_bundle_fails_the_font_check(
        run, monkeypatch, tmp_path,
):
    """The font database merges every source of a family: SemiBold
    registered from elsewhere (this session's theme here, a system
    install for a person) must not stand in for the bundle's file."""
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    medium = theme.bundled_dir("fonts") / "BarlowSemiCondensed-Medium.ttf"
    (fonts / medium.name).write_bytes(medium.read_bytes())
    real_dir = theme.bundled_dir

    def bundled_dir(name):
        return fonts if name == "fonts" else real_dir(name)

    monkeypatch.setattr(smoke_test.theme, "bundled_dir", bundled_dir)

    code, printed, _err = run()

    assert code == 1
    assert printed["failed"] == ["fonts"]
    (checked,) = (c for c in printed["checks"] if c["name"] == "fonts")
    assert "SemiBold" in checked["detail"]


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


def test_a_check_that_raises_fails_and_the_report_is_still_written(
        run, monkeypatch, tmp_path,
):
    """Frozen by a bundler that sets no `_MEIPASS`: every bundled path
    raises AttributeError. Each check that resolves one fails with it,
    and the rest still run. Undone before `run` puts the theme back,
    which resolves bundled icons too."""
    report_path = tmp_path / "report.json"
    with monkeypatch.context() as patch:
        patch.setattr(sys, "frozen", True, raising=False)
        patch.delattr(sys, "_MEIPASS", raising=False)

        code, printed, err = run(report_path)

    failed = ["theme", "fonts", "icons", "compose_template"]
    assert code == 1
    assert printed["failed"] == failed
    assert json.loads(report_path.read_text()) == printed
    for name in failed:
        (checked,) = (c for c in printed["checks"] if c["name"] == name)
        assert checked["detail"].startswith("AttributeError: ")
    assert err == f"Smoke test failed: {', '.join(failed)}\n"


def test_a_report_that_cannot_be_written_is_named_and_fails_the_run(
        run, tmp_path,
):
    """Every check passes, but the file a windowed build is read
    through is missing: the run must say so and exit 1."""
    report_path = tmp_path / "missing" / "report.json"

    code, printed, err = run(report_path)

    assert code == 1
    assert printed["passed"] is True
    assert err.startswith(f"Could not write the smoke test report {report_path}: ")
    assert "No such file or directory" in err


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


def test_the_entry_point_runs_the_check_offscreen_and_writes_nothing_else(
        tmp_path,
):
    """The real `main_ui.main()` in a fresh process: it makes its own
    offscreen QApplication, exits with the check's code and, with HOME
    in tmp_path, leaves nothing there (no log, settings or database)."""
    home = tmp_path / "home"
    home.mkdir()
    report_path = tmp_path / "report.json"
    env = {**os.environ, "HOME": str(home)}
    env.pop("QT_QPA_PLATFORM", None)

    result = subprocess.run(  # noqa: S603 — this interpreter, a fixed script
        [
            sys.executable, "-c", "from seeker.main_ui import main; main()",
            "--smoke-test", str(report_path),
        ],
        capture_output=True, text=True, env=env, cwd=tmp_path, timeout=120,
        check=False,
    )

    assert (result.returncode, result.stderr) == (0, "")
    report = json.loads(report_path.read_text())
    assert report["passed"] is True
    assert report["platform"] == "offscreen"
    assert list(home.iterdir()) == []
