"""`seeker-ui --smoke-test [REPORT]`: checks that a build can run, then
exits.

Meant for a frozen build, whose `hiddenimports` and `datas` are kept
by hand in `packaging/seeker.spec`: a module, font, icon or the
Compose template missing from the bundle shows up here rather than
when a person launches the app. It touches no logging, no
`Application`, no database and no user folder, so it is safe to run
on any machine.

The report is one JSON object, printed and, when a path follows the
flag, also written there (a windowed build may have no console). The
exit code is 0 when every check passed, else 1, with the failed
checks named on stderr.
"""

import importlib
import json
import pkgutil
import platform
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from PySide6.QtCore import QMessageLogContext, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QFontDatabase, QImage
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

import seeker
from seeker import _build_info, cpu_architecture
from seeker.soulseek import docker_setup
from seeker.ui import icons, theme, tray

SMOKE_TEST_FLAG = "--smoke-test"

# The two faces packaging/fonts/ carries, at the weights the theme
# sets (theme.WEIGHT_MEDIUM, theme.WEIGHT_SEMIBOLD).
_DISPLAY_STYLES = ("Medium", "SemiBold")

_QT_WARNINGS = (
    QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg,
)


@dataclass(frozen=True)
class SmokeTestRequest:
    """`--smoke-test` was given, with the report's path if one
    followed it."""

    report_path: Path | None


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass
class SmokeReport:
    checks: list[CheckResult] = field(default_factory=list)
    modules_imported: int = 0
    platform: str = ""
    architecture: str = ""
    frozen: bool = False
    version: str = ""
    build: str = ""
    python: str = ""

    @property
    def failed(self) -> list[str]:
        return [check.name for check in self.checks if not check.passed]

    def to_json(self) -> str:
        return json.dumps(
            {"passed": not self.failed, "failed": self.failed, **asdict(self)},
            indent=2,
        )


def parse_request(argv: Sequence[str]) -> SmokeTestRequest | None:
    """The request in `argv` (the arguments after the program name),
    or None without the flag. A following argument is the report's
    path unless it starts with "-" (a Qt option such as `-platform`)."""
    for index, argument in enumerate(argv):
        if argument.startswith(f"{SMOKE_TEST_FLAG}="):
            return SmokeTestRequest(
                report_path=Path(argument.removeprefix(f"{SMOKE_TEST_FLAG}=")),
            )
        if argument == SMOKE_TEST_FLAG:
            following = argv[index + 1:index + 2]
            if following and not following[0].startswith("-"):
                return SmokeTestRequest(report_path=Path(following[0]))
            return SmokeTestRequest(report_path=None)
    return None


def run_smoke_test(request: SmokeTestRequest) -> int:
    """Runs every check, prints the report (and writes it to
    `request.report_path`), and returns the process's exit code."""
    report = SmokeReport(
        architecture=cpu_architecture.describe_architecture(),
        frozen=bool(getattr(sys, "frozen", False)),
        version=_package_version(),
        build=_build_info.GIT_DESCRIBE,
        python=platform.python_version(),
    )

    imports, report.modules_imported = _check_imports()
    report.checks.append(imports)

    app = _application()
    report.platform = app.platformName()
    report.checks.append(_check_theme(app))
    report.checks.append(_check_fonts())
    report.checks.append(_check_icons())
    report.checks.append(_check_compose_template())

    text = report.to_json()
    print(text)
    if request.report_path is not None:
        request.report_path.write_text(text + "\n", encoding="utf-8")
    if report.failed:
        print(f"Smoke test failed: {', '.join(report.failed)}", file=sys.stderr)
        return 1
    return 0


def _package_version() -> str:
    try:
        return version("seeker")
    except PackageNotFoundError:
        return "unknown"


def _application() -> QApplication:
    """The process's QApplication: a new one on the offscreen platform,
    so the check needs no display; the existing one when a caller (a
    test) already made it."""
    existing = QApplication.instance()
    if existing is None:
        return QApplication([sys.argv[0], "-platform", "offscreen"])
    assert isinstance(existing, QApplication)
    return existing


def _check_imports() -> tuple[CheckResult, int]:
    """Imports every module of the `seeker` package. The walk must find
    this module: one that sees nothing inside a frozen archive would
    otherwise pass with nothing imported."""
    problems: list[str] = []

    def on_walk_error(name: str) -> None:
        problems.append(f"{name}: {_describe(sys.exception())}")

    names = sorted(
        module.name
        for module in pkgutil.walk_packages(
            seeker.__path__, f"{seeker.__name__}.", onerror=on_walk_error,
        )
    )
    if __name__ not in names:
        problems.append(
            f"The package walk found {len(names)} modules, not including "
            f"{__name__}, so it cannot have seen the package.",
        )
    imported = 0
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as error:  # any failure to import is the finding
            problems.append(f"{name}: {_describe(error)}")
        else:
            imported += 1
    detail = "; ".join(problems) or f"Imported {imported} modules."
    return CheckResult("imports", not problems, detail), imported


def _describe(error: BaseException | None) -> str:
    return f"{type(error).__name__}: {error}"


@contextmanager
def _qt_warnings() -> Iterator[list[str]]:
    """Collects Qt's warnings while the block runs (a stylesheet Qt
    cannot parse is reported only this way), then puts back the
    previous handler."""
    warnings: list[str] = []

    def handler(
            message_type: QtMsgType, _context: QMessageLogContext, message: str,
    ) -> None:
        if message_type in _QT_WARNINGS:
            warnings.append(message)

    previous = qInstallMessageHandler(handler)
    try:
        yield warnings
    finally:
        qInstallMessageHandler(previous)


def _check_theme(app: QApplication) -> CheckResult:
    """Applies the light theme, then the dark, as Settings can."""
    problems: list[str] = []
    with _qt_warnings() as warnings:
        for mode, expected in (("light", theme.LIGHT), ("dark", theme.DARK)):
            if theme.apply_theme(app, mode) != expected:
                problems.append(f"The {mode} theme resolved another palette.")
            if not app.styleSheet():
                problems.append(f"The {mode} theme set no stylesheet.")
    problems.extend(f"Qt: {warning}" for warning in warnings)
    detail = " ".join(problems) or "Applied the light and the dark theme."
    return CheckResult("theme", not problems, detail)


def _check_fonts() -> CheckResult:
    """Every bundled font file loads as the display face, which offers
    each weight the theme uses."""
    directory = theme.bundled_dir("fonts")
    files = sorted(directory.glob("*.ttf"))
    problems = [] if files else [f"No font files in {directory}."]
    for file in files:
        font_id = QFontDatabase.addApplicationFont(str(file))
        if font_id == -1:
            problems.append(f"Qt cannot load {file}.")
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        # Loaded once more only to read its family; theme.py's own
        # registration stays.
        QFontDatabase.removeApplicationFont(font_id)
        if theme.DISPLAY_FAMILY not in families:
            problems.append(f"{file.name} is {families}, not the display face.")
    styles = QFontDatabase.styles(theme.DISPLAY_FAMILY)
    missing = [style for style in _DISPLAY_STYLES if style not in styles]
    if missing:
        problems.append(f"{theme.DISPLAY_FAMILY} lacks {', '.join(missing)}.")
    detail = " ".join(problems) or (
        f"Loaded {len(files)} font files: {theme.DISPLAY_FAMILY} "
        f"{', '.join(styles)}."
    )
    return CheckResult("fonts", not problems, detail)


def _bundled_icons() -> list[Path]:
    """Every icon file the UI asks for by name."""
    palette_icons: list[Callable[[theme.Palette], Path]] = [
        theme.combo_chevron_path, theme.spin_up_arrow_path,
        theme.spin_down_arrow_path, theme.check_tick_path,
        theme.radio_dot_path,
    ]
    return [
        *(icon(palette) for icon in palette_icons
          for palette in (theme.LIGHT, theme.DARK)),
        *(icons.LUCIDE_DIR / f"{name}.svg" for name in icons.NAV_ICONS.values()),
        tray.tray_icon_path(),
    ]


def _icon_loads(path: Path) -> bool:
    if path.suffix == ".svg":
        return QSvgRenderer(str(path)).isValid()
    return not QImage(str(path)).isNull()


def _check_icons() -> CheckResult:
    paths = _bundled_icons()
    with _qt_warnings():
        # Qt warns for each file it cannot open; the check names them.
        unreadable = [path for path in paths if not _icon_loads(path)]
    if unreadable:
        names = ", ".join(str(path) for path in unreadable)
        return CheckResult("icons", passed=False, detail=f"Cannot load {names}.")
    return CheckResult("icons", passed=True, detail=f"Loaded {len(paths)} icons.")


def _check_compose_template() -> CheckResult:
    path = docker_setup.compose_template_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return CheckResult("compose_template", passed=False, detail=str(error))
    if "services:" not in text:
        return CheckResult(
            "compose_template", passed=False,
            detail=f"{path} has no services.",
        )
    return CheckResult(
        "compose_template", passed=True, detail=f"Read {path.name}.",
    )
