"""One uv everywhere: CI's setup-uv `version:`, `required-version` in
`pyproject.toml`, and the `uv_build` range must agree.

CI once installed the latest uv (0.13.x) while the developer's Mac had
0.12.x, and the `uv_build<0.13.0` range excluded CI's version.
"""

import re
import tomllib
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def _required_uv() -> str:
    required = PYPROJECT["tool"]["uv"]["required-version"]
    assert required.startswith("==")
    return required.removeprefix("==")


def test_every_setup_uv_step_pins_the_required_version():
    assert {path.name for path in WORKFLOWS} >= {"ci.yml", "build.yml"}
    for path in WORKFLOWS:
        steps = re.findall(
            r"uses: astral-sh/setup-uv@.*\n(?:\s+with:\n(?:\s+\S.*\n)+)?",
            path.read_text(encoding="utf-8"),
        )

        assert steps, path.name
        for step in steps:
            assert f'version: "{_required_uv()}"' in step, (path.name, step)


def test_uv_build_range_contains_the_required_version():
    (requirement,) = PYPROJECT["build-system"]["requires"]
    specifier = requirement.removeprefix("uv_build")

    assert Version(_required_uv()) in SpecifierSet(specifier)
