"""The root of every error Seeker raises for a person to read.

A `SeekerError`'s message is a sentence written for the user; the CLI
prints it and the UI shows it (both through `error_text.describe_error`).
Errors that more than one service raises live here; an error only one
module raises stays beside that module and subclasses `SeekerError`.
"""
from pathlib import Path


class SeekerError(RuntimeError):
    pass


class PlaylistNotFoundError(SeekerError):
    pass


class LibraryLocationNotFoundError(SeekerError):
    pass


class TextFileNotUtf8Error(SeekerError):
    """A text file Seeker reads (its settings, or the Compose file or
    slskd.yml that Sharing edits) holds a byte that is not UTF-8, as an
    editor that saves in the system's code page can leave. Seeker reads
    nothing from it and leaves it as it is."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            f"{path} is not UTF-8 text, so Seeker has left it as it is. "
            "Save it as UTF-8 in a text editor, then try again."
        )
        self.path = path
