"""One key for comparing two host paths as folders.

A path Seeker stored (a library location) and one another program
reports (a bind mount's `Source` from `docker inspect`) can spell one
Windows folder differently: `C:/Users/...` against `c:\\users\\...`.
Every comparison of such paths goes through `path_key`.
"""

import sys
from pathlib import PureWindowsPath


def path_key(path: str) -> str:
    """`path` as a key that every spelling of one folder shares.

    On Windows: one '\\' between parts, none trailing (a drive's root
    keeps its own, `c:\\`), lower-cased as pathlib's own Windows
    equality does (`PureWindowsPath("C:/A") == PureWindowsPath("c:\\a")`).
    `str.casefold()` would also join "ß" with "ss", two names Windows
    keeps apart (UNVERIFIED on a volume). Elsewhere: `path` itself,
    compared exactly, as macOS paths always were.
    """
    if sys.platform == "win32":
        return str(PureWindowsPath(path)).lower()

    return path
