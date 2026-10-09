"""Structural checks on the tracked `docker-compose.yml` template.

Every Seeker install copies this file, so nothing in it may name one
person's machine: a personal bind-mount source fails (or shares the
wrong folder) on anyone else's Mac, and an image pinned by tag alone
can change under a pinned client.

The file is parsed line by line rather than with a YAML library: it is
Seeker's own template, its shape is fixed, and the project carries no
YAML dependency.
"""

import re
from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "docker-compose.yml"

# `${NAME}` or `${NAME:?message}` — a variable Seeker must pass, never
# one that falls back to a default baked into the template.
REQUIRED_VARIABLE = re.compile(r"^\$\{[A-Z][A-Z0-9_]*(:\?[^}]*)?\}$")


def _template_lines() -> list[str]:
    return TEMPLATE_PATH.read_text().splitlines()


def _uncommented(lines: list[str]) -> list[str]:
    return [line for line in lines if not line.lstrip().startswith("#")]


def _volume_entries() -> list[str]:
    lines = _uncommented(_template_lines())
    start = next(
        index for index, line in enumerate(lines)
        if line.strip() == "volumes:"
    )
    entries: list[str] = []

    for line in lines[start + 1:]:
        stripped = line.strip()

        if not stripped.startswith("- "):
            break

        entries.append(stripped[2:].strip().strip('"'))

    return entries


def _bind_source(entry: str) -> str:
    # The source ends at the first ':' outside a `${...}` expression;
    # a `${VAR:?msg}` source carries its own ':' inside the braces.
    if entry.startswith("${"):
        return entry[:entry.index("}") + 1]

    return entry.split(":", 1)[0]


def test_template_names_no_personal_path():
    for line in _uncommented(_template_lines()):
        assert "/Volumes/" not in line, line
        assert "/Users/" not in line, line


def test_every_bind_mount_source_is_a_required_variable():
    entries = _volume_entries()

    assert entries, "the template has no volumes to check"

    for entry in entries:
        source = _bind_source(entry)
        assert REQUIRED_VARIABLE.match(source), (
            f"{entry!r}: source {source!r} must be a variable with no "
            "default"
        )


def test_the_share_mount_is_read_only():
    share_entries = [
        entry for entry in _volume_entries()
        if "SLSKD_SHARE_PATH" in entry
    ]

    assert len(share_entries) == 1
    assert share_entries[0].endswith(":ro")


def test_image_carries_a_version_tag_and_its_digest():
    # A tag can be moved on Docker Hub; the digest cannot. The tag stays
    # for the reader (and Dependabot), the digest is what Docker pulls.
    image_lines = [
        line.strip() for line in _uncommented(_template_lines())
        if line.strip().startswith("image:")
    ]

    assert len(image_lines) == 1
    image = image_lines[0].removeprefix("image:").strip()
    assert re.fullmatch(
        r"slskd/slskd:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", image,
    ), image


def test_restart_policy_respects_a_user_stopping_slskd():
    restart_lines = [
        line.strip() for line in _uncommented(_template_lines())
        if line.strip().startswith("restart:")
    ]

    assert restart_lines == ["restart: unless-stopped"]


def test_project_name_is_fixed():
    # Compose otherwise names the project after the file's directory:
    # "seeker" from the repository, "slskd-data" from the per-user
    # copy. With a fixed container_name, a container created under one
    # project then conflicts on `up` under the other.
    top_level = [
        line for line in _uncommented(_template_lines())
        if line and not line[0].isspace()
    ]

    assert "name: seeker" in top_level
