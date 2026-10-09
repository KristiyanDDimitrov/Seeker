"""`tools/audit_dependencies.py`: CI's dependency audit. pip-audit
itself is never run here (it needs the network); the ignore list's
rules and the commands built from it are."""
import importlib.util
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType

import pytest

_TOOL = Path(__file__).resolve().parent.parent / "tools" / "audit_dependencies.py"


@pytest.fixture(scope="module")
def audit() -> ModuleType:
    spec = importlib.util.spec_from_file_location("audit_dependencies", _TOOL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_dependencies"] = module
    spec.loader.exec_module(module)
    return module


_ONE_ENTRY = """
[[ignore]]
id = "PYSEC-2026-1"
reason = "Unreachable: nothing imports the module."
expires = 2026-11-01
"""


def test_the_committed_ignore_list_parses_and_has_not_expired(audit):
    # A malformed or stale edit fails the build here, not in CI's audit
    # job alone, which a local run never reaches.
    ignored = audit.load_ignored(audit.IGNORE_FILE.read_text(encoding="utf-8"))

    assert audit.expired(ignored, datetime.now(UTC).date()) == []


def test_an_entry_carries_its_id_reason_and_expiry(audit):
    assert audit.load_ignored(_ONE_ENTRY) == [
        audit.Ignored(
            id="PYSEC-2026-1",
            reason="Unreachable: nothing imports the module.",
            expires=date(2026, 11, 1),
        ),
    ]


@pytest.mark.parametrize(
    "entry",
    [
        'id = "X"\nreason = "r"',
        'id = "X"\nexpires = 2026-11-01',
        'reason = "r"\nexpires = 2026-11-01',
        'id = "X"\nreason = "r"\nexpires = "2026-11-01"',
        'id = "X"\nreason = ""\nexpires = 2026-11-01',
    ],
    ids=["no-expiry", "no-reason", "no-id", "string-date", "empty-reason"],
)
def test_an_entry_without_an_id_reason_and_real_date_is_refused(audit, entry):
    with pytest.raises(ValueError, match="ignore"):
        audit.load_ignored(f"[[ignore]]\n{entry}\n")


@pytest.mark.parametrize(
    "text",
    ['[ignore]\nid = "X"\n', 'ignore = ["X"]\n', 'ignore = "X"\n'],
    ids=["one-table", "list-of-strings", "string"],
)
def test_an_ignore_list_of_the_wrong_shape_is_refused(audit, text):
    with pytest.raises(ValueError, match=r"\[\[ignore\]\]"):
        audit.load_ignored(text)


def test_an_entry_stops_applying_on_its_expiry_date(audit):
    ignored = audit.load_ignored(_ONE_ENTRY)

    assert audit.expired(ignored, date(2026, 10, 31)) == []
    assert audit.expired(ignored, date(2026, 11, 1)) == ignored


def test_each_live_entry_becomes_an_ignore_flag(audit, tmp_path):
    requirements = tmp_path / "requirements.txt"

    command = audit.pip_audit_command(requirements, audit.load_ignored(_ONE_ENTRY))

    assert command[-4:] == [
        "--ignore-vuln", "PYSEC-2026-1", "--requirement", str(requirements),
    ]
    assert "--strict" in command
    assert "--require-hashes" in command


class _Runner:
    """Records each command and answers with a fixed return code."""

    def __init__(self, returncode: int) -> None:
        self.commands: list[list[str]] = []
        self._returncode = returncode

    def __call__(self, command, *, check):
        self.commands.append(command)
        return subprocess.CompletedProcess(command, self._returncode)


def test_an_expired_entry_fails_before_anything_runs(audit, tmp_path, capsys):
    ignore_file = tmp_path / "audit_ignore.toml"
    ignore_file.write_text(_ONE_ENTRY, encoding="utf-8")
    runner = _Runner(0)

    result = audit.main(
        ignore_file=ignore_file, today=date(2026, 12, 1), run=runner,
    )

    assert result == 1
    assert runner.commands == []
    assert "PYSEC-2026-1" in capsys.readouterr().err


@pytest.mark.parametrize("returncode", [0, 1])
def test_the_audit_exports_the_lock_then_returns_pip_audits_result(
        audit, tmp_path, returncode):
    ignore_file = tmp_path / "audit_ignore.toml"
    ignore_file.write_text(_ONE_ENTRY, encoding="utf-8")
    runner = _Runner(returncode)

    result = audit.main(
        ignore_file=ignore_file, today=date(2026, 10, 9), run=runner,
    )

    assert result == returncode
    export, pip_audit = runner.commands
    assert export[:2] == ["uv", "export"]
    assert {"--locked", "--all-groups", "--no-emit-project"} <= set(export)
    assert pip_audit[:3] == ["uv", "tool", "run"]
    assert pip_audit[3] == audit.PIP_AUDIT
