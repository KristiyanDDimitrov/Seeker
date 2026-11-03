# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 2 K tokens: a baton, not
a log. The log is `docs/history/` (short tier: `docs/history/README.md`,
grep it, never read it whole). **The plan is
`docs/phase-02/round-13/SESSION-PLAN.md`**, with status in `tasks.json`
beside it. Every document: `docs/README.md`.

---

## 1. Current state

- **Released: v0.1.1** (2026-10-26, §247).
- **HEAD is the S4c handoff commit on `b3732b2`.** Untracked: Kris's PDF
  only. No worktrees. `origin` still has `r13/S7` and `r13/S7c` (merged;
  the auto-mode classifier refused the delete:
  `git push origin --delete r13/S7 r13/S7c` is Kris's).
- **The three numbers (Cocoa):** pytest `2574 passed, 1 skipped`; mypy
  `--strict src/` clean, 149 files; ruff 0.
- **CI:** the last result I have is run `41550884285` on `826608b`:
  `check` green, `check-intel` failed one test (the S4c one, now fixed).
  The run for this push is recorded in section 3, step 1.

## 2. Where we are

Round 13: waves 0 to 3 done; wave 4: S7, S7c, S8, S8b, S4b, **S4c** done
(§262 to §265). S4c: the failing wait read `workers._callbacks`, the
whole process's count, while the flow is two workers (§265). The runner's
real cause is UNVERIFIED; `check-intel` now lists its slow tests.
**S9's Code half is half done:** the Apple silicon candidate was built
from `826608b` and is still current (nothing under `src/`, `packaging/`,
`pyproject.toml` or `uv.lock` changed since). RELEASING step 3 passed
(ad-hoc signed, `spctl` rejects, 0.1.1, thin arm64, smoke test exit 0,
cold 3.49 s, warm 0.035 s). `dist/Seeker.dmg` SHA-256 `df191247696631dec…`
(full: `shasum -a 256 dist/Seeker.dmg`, verified today). **Never quote
`dist/Seeker.dmg.sha256`: it is v0.1.1's, stale.** The Help check (a GUI
launch reads Kris's real data) is Kris's.

## 3. Next steps

1. **Read the 6th Intel run** (`gh run list --commit $(git rev-parse HEAD)`,
   full SHA; record its id here). Its `--durations` list answers S4c's open
   question: tests taking over 1 s on the runner that take ms locally mean
   it stalls. If it fails again, read the failing test, not this note.
2. **Blocker:** the Intel candidate needs a local libchromaprint. The
   classifier refused me `packaging/build_chromaprint.sh` (it downloads and
   compiles a tarball). Kris runs, once (`.chromaprint/` is gitignored and
   persists): `! packaging/build_chromaprint.sh "$PWD/.chromaprint"`.
3. Then (RELEASING steps 2-3): `SEEKER_CHROMAPRINT_DIR="$PWD/.chromaprint/lib"
   .venv-x86_64/bin/python packaging/build_dmg.py`, step 3 with
   `ARCH=x86_64` (the build replaces `dist/Seeker.app`; the arm64 app
   was checked first), then both checksums with `shasum`.
4. Write `docs/phase-02/round-13/ACCEPTANCE.md`: both SHA-256s, then
   Kris's checklist (BRIEF §9, already corrected). Commit, push; Kris's
   gate; then S10 (solo, `[ASK]`).

## 4. Key context

- A fresh worker on an existing branch: `git checkout -B r13/S<n> main`.
  Workers' suites run offscreen; the lead's Cocoa check runs alone.
- Never `cmd | tail && git commit`: a pipe hides the gate's exit code.
  zsh does not word-split an unquoted `$var` (a pytest file list failed so).
- S10: un-gate the README (`From 0.2.0`, `Download (from 0.2.0)`,
  `Until 0.2.0 is published…`), resolve nothing else pending
  (`grep -rn S7-PENDING docs` is empty).

## 5. Decisions made

- Kris (2026-11-02): the Intel bundle ships libchromaprint (`f19ad82`);
  arm64 stays on Homebrew's.
- The lead, for Kris's review: libchromaprint is built from a pinned source
  (`build_chromaprint.sh`, one revert undoes it); `SEEKER_CHROMAPRINT_DIR`
  and `.chromaprint/`; the ffmpeg-free Intel runner skips 2 more tests (§262).
- The lead (S4c): the 355 short `waitUntil`s (346 at 2000 ms) were not
  audited or raised, and `--durations` was added instead (§265).

## 6. Blockers

The Intel libchromaprint build (3.2).

## 7. Files in progress

None. `dist/` and `.chromaprint/` hold gitignored build outputs.

## 8. Waiting on Kris

- Run the libchromaprint command (3.2); the Help check and the rest of
  BRIEF §9 later.
- **Decide, after a `--durations` sample or two:** give the suite's short
  worker waits one longer named bound (the 355), or not. My view: yes if
  the runner shows stalls, and not before; a green run costs nothing.
- README's licence paragraph names libchromaprint's upstream source and
  an "LGPL 2.1" label (the vendored text says "2.1", Homebrew
  "-or-later"): confirm the wording.
- Before the final Intel release: an asset-aware update check, or a
  notice in the release notes (RELEASING §7).
- FYI: six Settings tests POSTed a login to the real slskd on
  127.0.0.1:5030 until S4b (§264); fixed, effect on slskd unknown.
- #1, #5, #7, #8 are still open though their changes are on `main`.

## 9. Open questions

- Without ffmpeg a non-audio file reads `error`, with it
  `decode_unsupported` (pinned as documented, §262): which is right?
- PyInstaller's Intel-only libomp SDK warning (§262); where numba's cache
  lives; Module map lacks `ui/row_actions.py`, `soulseek/sweep.py`,
  `soulseek/leftovers.py` (older than round 13).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. **Ending:** the plan's "Session protocol".
