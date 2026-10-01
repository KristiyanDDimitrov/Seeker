import ast
import importlib
from pathlib import Path

from seeker.audio.formats import (
    DOWNLOADABLE_EXTENSIONS,
    downloadable_formats_text,
)
from seeker.errors import SeekerError
from seeker.soulseek.download_service import UnsupportedDownloadFormatError

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"


def _public_error_classes() -> list[tuple[str, str]]:
    found = []

    for path in sorted((SRC_ROOT / "seeker").rglob("*.py")):
        module = ".".join(path.relative_to(SRC_ROOT).with_suffix("").parts)

        for node in ast.parse(path.read_text()).body:
            # A leading underscore marks an error that never leaves its
            # module (duplicate_service's per-file fingerprint failures,
            # caught one frame up), so no person ever reads it.
            if (
                    isinstance(node, ast.ClassDef)
                    and node.name.endswith("Error")
                    and not node.name.startswith("_")
            ):
                found.append((module, node.name))

    return found


def test_every_public_error_class_is_a_seeker_error():
    classes = _public_error_classes()

    # The sweep itself must see the classes it exists to check.
    assert ("seeker.soulseek.client", "SlskdUnreachableError") in classes

    outside = [
        f"{module}.{name}"
        for module, name in classes
        if not issubclass(
            getattr(importlib.import_module(module), name), SeekerError,
        )
    ]

    assert outside == []


def test_each_shared_error_is_defined_once():
    names = [name for _module, name in _public_error_classes()]

    assert names.count("PlaylistNotFoundError") == 1
    assert names.count("LibraryLocationNotFoundError") == 1


def test_the_format_list_names_every_downloadable_extension():
    text = downloadable_formats_text()

    assert text == "mp3, flac, wav, aiff, aif and m4a"
    assert {f".{name}" for name in text.replace(" and ", ", ").split(", ")} == (
        DOWNLOADABLE_EXTENSIONS
    )


def test_the_unsupported_format_message_uses_the_shared_list():
    message = str(UnsupportedDownloadFormatError("OGG"))

    assert message == (
        "Seeker only downloads mp3, flac, wav, aiff, aif and m4a — this one "
        "is .ogg."
    )
