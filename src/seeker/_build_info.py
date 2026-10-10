"""Real build identity — git SHA, `git describe --dirty`, and the UTC
build timestamp.

Two builds of the same source tree are otherwise indistinguishable from
inside the running app (`pyproject.toml`'s version is static), so this
is what answers "is this account running the build I think it is?".

`packaging/build_dmg.py` writes the values to the gitignored
`_build_info_generated.py`, bundles it, and deletes it again; this
tracked file is never modified by a build. Only a frozen build imports
the generated module: from source the identity is always "dev", even
when an interrupted build left the module behind. Writing a tracked
file instead would dirty the tree on every build and risk committing a
real SHA over the fallback. See HISTORY §81, §83.
"""

import contextlib
import sys

__all__ = ["BUILT_AT", "GIT_DESCRIBE", "GIT_SHA"]

GIT_SHA = "dev"
GIT_DESCRIBE = "dev"
BUILT_AT = "dev"

if getattr(sys, "frozen", False):
    with contextlib.suppress(ImportError):
        # No blanket `# type: ignore` here: the pyproject.toml
        # `[[tool.mypy.overrides]]` for this exact module name
        # (`ignore_missing_imports = true`) is what makes this clean
        # under --strict whether or not the generated module exists.
        from seeker._build_info_generated import (
            BUILT_AT,
            GIT_DESCRIBE,
            GIT_SHA,
        )
