"""Audits every locked dependency for known vulnerabilities.

    uv run --no-project tools/audit_dependencies.py

Exports `uv.lock` (runtime and dev groups: the dev group builds the
DMG, and PyInstaller's bootloader ships inside it) as hashed
requirements and runs a pinned pip-audit over every pin in it, each
platform's alike (see `audit_layers`). Exits non-zero on any finding,
or on a package pip-audit cannot audit.

A finding that cannot be fixed yet goes in `tools/audit_ignore.toml`
with a reason and an expiry date. An expired entry fails the audit
before pip-audit runs, so an exception is re-decided rather than
forgotten.

pip-audit reads Python package metadata only. The native libraries
inside wheels (libsndfile, Qt, OpenSSL, SQLite) are invisible to it;
`docs/packaging.md` records their versions for a human check at each
release.
"""
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IGNORE_FILE = REPO_ROOT / "tools" / "audit_ignore.toml"
# Bumped by hand: Dependabot does not see a tool run through `uv tool`.
PIP_AUDIT = "pip-audit==2.10.1"

Runner = Callable[..., subprocess.CompletedProcess[bytes]]


@dataclass(frozen=True)
class Ignored:
    """One advisory the audit tolerates until `expires`."""

    id: str
    reason: str
    expires: date


def load_ignored(text: str) -> list[Ignored]:
    """Parses the ignore list. Each `[[ignore]]` entry needs a
    non-empty `id` and `reason`, and an `expires` TOML date."""
    entries = tomllib.loads(text).get("ignore", [])
    if not (isinstance(entries, list)
            and all(isinstance(entry, dict) for entry in entries)):
        raise ValueError("Write each ignore entry as an [[ignore]] table.")
    ignored = []
    for index, entry in enumerate(entries):
        advisory = entry.get("id")
        reason = entry.get("reason")
        expires = entry.get("expires")
        if not (isinstance(advisory, str) and advisory):
            raise ValueError(f"The ignore entry at index {index} has no id.")
        if not (isinstance(reason, str) and reason.strip()):
            raise ValueError(f"The ignore entry for {advisory} has no reason.")
        # tomllib returns a bare date for `2026-11-01`; a quoted string
        # or a datetime is a typo.
        if type(expires) is not date:
            raise ValueError(
                f"The ignore entry for {advisory} needs an expires date "
                "written as YYYY-MM-DD, unquoted.",
            )
        ignored.append(Ignored(id=advisory, reason=reason, expires=expires))
    return ignored


def expired(ignored: Sequence[Ignored], today: date) -> list[Ignored]:
    """The entries that no longer apply: an entry stops on its
    `expires` date."""
    return [entry for entry in ignored if entry.expires <= today]


def export_command(requirements: Path) -> list[str]:
    return [
        "uv", "export", "--locked", "--all-groups", "--all-extras",
        "--no-emit-project", "--quiet", "--output-file", str(requirements),
    ]


def _package_name(requirement: str) -> str:
    name = re.split(r"[\s=<>!~;@\[]", requirement, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def audit_layers(exported: str) -> list[str]:
    """Splits a hashed `uv export` into requirements files that
    pip-audit audits in full.

    pip-audit skips, without a word, a requirement whose environment
    marker is false where it runs (read in its source, HISTORY §253):
    a macOS-only pin on CI's Linux runner, and on any machine one of
    the two pins of a package the lock forks by platform (numba on
    Intel Macs). So each file drops the markers and pins a package at
    most once, since pip-audit refuses a file that names one twice.
    """
    layers: list[list[str]] = []
    seen: dict[str, int] = {}
    current: list[str] | None = None
    for line in exported.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[0].isspace():
            # A hash line of the entry above.
            if current is None:
                raise ValueError(f"No requirement above the line {line!r}.")
            current.append(line)
            continue
        requirement, _, marker = line.partition(" ; ")
        if marker.endswith("\\"):
            requirement += " \\"
        name = _package_name(requirement)
        index = seen.get(name, 0)
        seen[name] = index + 1
        if index == len(layers):
            layers.append([])
        current = layers[index]
        current.append(requirement)
    return ["\n".join(layer) + "\n" for layer in layers]


def pip_audit_command(
        requirements: Path, ignored: Sequence[Ignored]) -> list[str]:
    # --disable-pip with --require-hashes audits the exported pins as
    # they are, without resolving or installing anything.
    command = [
        "uv", "tool", "run", PIP_AUDIT,
        "--strict", "--disable-pip", "--require-hashes",
    ]
    for entry in ignored:
        command += ["--ignore-vuln", entry.id]
    return [*command, "--requirement", str(requirements)]


def main(
        *, ignore_file: Path = IGNORE_FILE, today: date | None = None,
        run: Runner = subprocess.run) -> int:
    today = today or datetime.now(UTC).date()
    ignored = load_ignored(ignore_file.read_text(encoding="utf-8"))
    stale = expired(ignored, today)
    if stale:
        for entry in stale:
            print(
                f"{entry.id}: the ignore entry expired on {entry.expires}. "
                "Fix the dependency, or re-decide and move the date.",
                file=sys.stderr,
            )
        return 1
    with tempfile.TemporaryDirectory() as scratch:
        exported = Path(scratch) / "exported.txt"
        run(export_command(exported), check=True)
        layers = audit_layers(exported.read_text(encoding="utf-8"))
        if not layers:
            print("The lock's export names no package.", file=sys.stderr)
            return 1
        returncode = 0
        # Every file is audited, so one run reports every finding.
        for index, layer in enumerate(layers, start=1):
            requirements = Path(scratch) / f"requirements-{index}.txt"
            requirements.write_text(layer, encoding="utf-8")
            result = run(pip_audit_command(requirements, ignored), check=False)
            returncode = returncode or result.returncode
        return returncode


if __name__ == "__main__":
    sys.exit(main())
