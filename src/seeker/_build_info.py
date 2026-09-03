"""Real build identity — git SHA, `git describe --dirty`, and the UTC
build timestamp.

Roadmap item 81 (0.1) — the real root cause behind a testing-logistics
dead end from a prior round: two builds made hours apart, from the
identical source tree, were indistinguishable from INSIDE the running
app (`pyproject.toml` is pinned at a static version string, and that
was the only thing shown anywhere). "Is this account running the
build I think it is?" needed to become a two-second visual check.

`packaging/build_dmg.py` OVERWRITES this file with the real values
just before invoking PyInstaller, so a packaged build always bundles
its own real identity — never committed with real content (see
.gitignore). This checked-in version is the dev-run fallback:
`uv run seeker`/`seeker-ui` reads it unmodified, so a dev run is
honestly labeled "dev" rather than showing a stale git SHA from
whenever this file last happened to get regenerated locally.
"""

GIT_SHA = "dev"
GIT_DESCRIBE = "dev"
BUILT_AT = "dev"
