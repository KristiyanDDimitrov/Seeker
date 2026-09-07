"""Real build identity — git SHA, `git describe --dirty`, and the UTC
build timestamp.

Roadmap item 81 (0.1) — the real root cause behind a testing-logistics
dead end from a prior round: two builds made hours apart, from the
identical source tree, were indistinguishable from INSIDE the running
app (`pyproject.toml` is pinned at a static version string, and that
was the only thing shown anywhere). "Is this account running the
build I think it is?" needed to become a two-second visual check.

Roadmap item 81's post-implementation review (R1) — the first version
of this module WAS the file `packaging/build_dmg.py` overwrote directly.
Since it was tracked, that overwrite permanently dirtied the working
tree on every real build, and a careless `git add` would commit a real
SHA over the "dev" fallback — silently making every future dev run lie
about its own identity. Fixed by splitting the write target out: the
generated values now live in `_build_info_generated.py`, which is
gitignored and never tracked. This file is never modified by a build at
all — it just tries to import the generated module and falls back to
"dev" when it doesn't exist (an ordinary `uv run` checkout, or a fresh
clone that has never been built).
"""

__all__ = ["BUILT_AT", "GIT_DESCRIBE", "GIT_SHA"]

try:
    # Roadmap item RR1.3 — no blanket `# type: ignore` here: the
    # pyproject.toml `[[tool.mypy.overrides]]` for this exact module
    # name (`ignore_missing_imports = true`) is what makes this clean
    # under --strict whether or not the generated module actually
    # exists on disk, instead of being clean in only one of those two
    # states.
    from seeker._build_info_generated import BUILT_AT, GIT_DESCRIBE, GIT_SHA
except ImportError:
    GIT_SHA = "dev"
    GIT_DESCRIBE = "dev"
    BUILT_AT = "dev"
