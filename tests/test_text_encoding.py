"""Every text file src/ reads or writes is UTF-8, never the locale's
encoding, which on Windows is its ANSI code page (cp1252 on a Western
install, UNVERIFIED on hardware). Each case runs a read or write in a
fresh interpreter started with `-X warn_default_encoding`, which raises
an `EncodingWarning` wherever text is opened without an encoding (PEP
597), and fails on one raised from a module under src/seeker.
`tests/test_encoding_sweep.py` reads every site in source; this runs
the ones src/ has, the way the app does."""
import codecs
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "seeker"

# Runs a case (argv[2]) against a folder of its own (argv[1]) and
# prints where each EncodingWarning was raised. Python warns only under
# `-X warn_default_encoding`, a flag it reads as it starts, hence the
# fresh interpreter.
_HARNESS = """\
import json, sys, warnings
from pathlib import Path
tmp = Path(sys.argv[1])
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always", EncodingWarning)
    exec(sys.argv[2])
print(json.dumps([
    [warning.filename, warning.lineno] for warning in caught
    if issubclass(warning.category, EncodingWarning)
]))
"""


def _locale_text_opened(code: str, folder: Path, under: Path = SRC) -> list[str]:
    """Where in the modules under `under` `code` opened text in the
    locale's encoding, as `path:line`."""
    result = subprocess.run(  # noqa: S603 — this interpreter, a fixed harness
        [
            sys.executable, "-X", "warn_default_encoding",
            "-c", _HARNESS, str(folder), code,
        ],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    found = []
    for filename, lineno in json.loads(result.stdout):
        path = Path(filename).resolve()
        if path.is_relative_to(under.resolve()):
            found.append(f"{path.relative_to(under.resolve()).as_posix()}:{lineno}")
    return found


# Each text file src/ reads or writes, by what does it.
_SITES = {
    "an-atomic-write": (
        "from seeker.files.atomic import write_text_atomic\n"
        "write_text_atomic(tmp / 'slskd.yml', 'shares: {}\\n')\n"
    ),
    "a-locked-write": (
        "from seeker.files.atomic import write_text_locked\n"
        "write_text_locked(tmp / 'config.json', '{}')\n"
    ),
    "the-config": (
        "from seeker.config_store import load_config\n"
        "(tmp / 'config.json').write_bytes(b'{}')\n"
        "load_config(tmp / 'config.json')\n"
    ),
    "the-spotify-token": (
        "from seeker.spotify.token_store import TokenStore\n"
        "(tmp / 'token.json').write_bytes(b'{}')\n"
        "TokenStore(tmp / 'token.json').load()\n"
    ),
    "the-album-art-cache": (
        "from seeker.album_art_cache import AlbumArtCache\n"
        "AlbumArtCache(tmp).put('https://i.scdn.co/a', b'art', 'image/jpeg')\n"
        "AlbumArtCache(tmp).get('https://i.scdn.co/a')\n"
    ),
    "sharings-compose-and-slskd-yml": (
        "from seeker.soulseek.sharing_service import SharingPlan, SharingService\n"
        "compose = tmp / 'docker-compose.yml'\n"
        "compose.write_bytes(\n"
        "    b'services:\\n  slskd:\\n    volumes:\\n'\n"
        "    b'      - \"./slskd-data:/app\"\\n'\n"
        ")\n"
        "slskd_yml = tmp / 'slskd.yml'\n"
        "slskd_yml.write_bytes(b'shares:\\n  directories:\\n    - /shared/a\\n')\n"
        "plan = SharingPlan(\n"
        "    location=None, container_path='/shared/b',\n"
        "    compose_volume_line='      - \"/b:/shared/b:ro\"',\n"
        "    slskd_share_directory_line='    - /shared/b',\n"
        ")\n"
        "SharingService(None, None, None, compose_path=compose)"
        "._edit_both_files(plan, slskd_yml)\n"
    ),
}


@pytest.mark.parametrize("code", _SITES.values(), ids=list(_SITES))
def test_src_reads_and_writes_text_as_utf8(tmp_path, code):
    assert _locale_text_opened(code, tmp_path) == []


def test_the_harness_reports_text_opened_in_the_locales_encoding(tmp_path):
    """A control, so the cases above can fail: a module that reads
    text with no encoding is reported at that read, and one that names
    its encoding is not."""
    modules = tmp_path / "modules"
    modules.mkdir()
    (modules / "reader.py").write_text(
        "def read(path):\n"
        "    return path.read_text()\n"
        "def read_utf8(path):\n"
        "    return path.read_text(encoding='utf-8')\n",
        encoding="utf-8",
    )

    found = _locale_text_opened(
        f"sys.path.insert(0, {str(modules)!r})\n"
        "import reader\n"
        "(tmp / 'a.txt').write_bytes(b'a')\n"
        "reader.read(tmp / 'a.txt')\n"
        "reader.read_utf8(tmp / 'a.txt')\n",
        tmp_path,
        under=modules,
    )

    assert found == ["reader.py:2"]


# A name neither ISO 8859-1 nor cp1252 can encode, built from code
# points so that no source, command line or locale stands between it
# and the bytes.
_NAME = "Caf" + chr(0xE9) + " " + chr(0x6771) + chr(0x4EAC)

# Under the locale `_utf8_under_another_locale` sets, writes `_NAME`
# the way Seeker writes every text file (the Compose file, slskd.yml,
# the settings, the token), reads it from config.json, and adds a share
# whose path holds it to a Compose file whose path holds it already.
# Prints the encoding text opened with none would take, then the name
# the settings read.
_WRITE_AND_READ_BACK = """\
import locale, sys
from pathlib import Path
from seeker.config_store import load_config
from seeker.files.atomic import write_text_atomic
from seeker.soulseek.sharing_service import SharingPlan, SharingService
tmp = Path(sys.argv[1])
name = "Caf" + chr(0xE9) + " " + chr(0x6771) + chr(0x4EAC)
print(locale.getpreferredencoding(False))
write_text_atomic(tmp / "written.txt", name + "\\n")
config = tmp / "config.json"
config.write_bytes(('{"slskd_username": "%s"}' % name).encode("utf-8"))
print(ascii(load_config(config).slskd_username))
compose = tmp / "docker-compose.yml"
compose.write_bytes((
    "services:\\n  slskd:\\n    volumes:\\n"
    '      - "/%s/a:/shared/a:ro"\\n' % name
).encode("utf-8"))
slskd_yml = tmp / "slskd.yml"
slskd_yml.write_bytes(b"shares:\\n  directories:\\n    - /shared/a\\n")
plan = SharingPlan(
    location=None, container_path="/shared/b",
    compose_volume_line='      - "/%s/b:/shared/b:ro"' % name,
    slskd_share_directory_line="    - /shared/b",
)
SharingService(None, None, None, compose_path=compose)._edit_both_files(
    plan, slskd_yml,
)
"""


def test_text_files_are_utf8_whatever_the_locale(tmp_path):
    """Naming an encoding is not enough: the one named must be UTF-8.
    The child runs under ISO 8859-1 (`LC_ALL`, on macOS), or under
    Windows' ANSI code page, which `LC_ALL` does not change; in either,
    `_NAME` cannot be written in the locale's encoding, and UTF-8 read
    as it comes back garbled."""
    result = subprocess.run(  # noqa: S603 — this interpreter, a fixed script
        [sys.executable, "-c", _WRITE_AND_READ_BACK, str(tmp_path)],
        env={**os.environ, "LC_ALL": "en_US.ISO8859-1"},
        capture_output=True, text=True, timeout=60, check=False,
    )

    assert result.returncode == 0, result.stderr
    locale_encoding, settings_name = result.stdout.splitlines()
    # The control: text opened with no encoding would not be UTF-8 here.
    assert codecs.lookup(locale_encoding).name != "utf-8"
    assert settings_name == ascii(_NAME)
    assert (tmp_path / "written.txt").read_bytes() == f"{_NAME}\n".encode()
    assert (tmp_path / "docker-compose.yml").read_bytes() == (
        "services:\n  slskd:\n    volumes:\n"
        f'      - "/{_NAME}/a:/shared/a:ro"\n'
        f'      - "/{_NAME}/b:/shared/b:ro"\n'
    ).encode()
