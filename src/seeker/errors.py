"""The root of every error Seeker raises for a person to read.

A `SeekerError`'s message is a sentence written for the user; the CLI
prints it and the UI shows it (both through `error_text.describe_error`).
Errors that more than one service raises live here; an error only one
module raises stays beside that module and subclasses `SeekerError`.
"""


class SeekerError(RuntimeError):
    pass


class PlaylistNotFoundError(SeekerError):
    pass


class LibraryLocationNotFoundError(SeekerError):
    pass
