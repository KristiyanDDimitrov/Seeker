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
- **HEAD:** wave 3's close-outs on `main`, pushed. Untracked: Kris's PDF
  only. No worktrees, no `r13/*` branches left.
- **The three numbers (Cocoa):** pytest `2522 passed, 1 skipped` (S6;
  S4 added 6 tests, CI: `2500 passed, 29 skipped` on both macOS jobs);
  mypy `--strict src/` clean, 149 files; ruff 0.
- **CI:** `41506032138` green on `085ff27`: `check` 9 m, `check-intel`
  19.5 m (first real Intel run, §261), `audit`. `cancel-in-progress` is
  on: watch the run on the last push. A macos-26 job once sat queued 25
  minutes and was cancelled: re-push, not a code bug.

## 2. Where we are

Round 13: **waves 0 to 3 done** (§246 to §261: S5b §257, S3b §258, S6
§259, S6b §260, S4 §261). **Next: wave 4** (SESSION-PLAN → Execution →
Waves): workers **S7** (needs CI: `build.yml`) and **S8** (docs), then
S9's Code half (the lead), then Kris's gate; wave 5 is S10 (solo).

## 3. Session report (waves 2-3's lead, 2026-11-02)

- Eight workers/fix rounds, four `diff-reviewer`s, five `suite-runner`
  checks. Reviews found real defects on S5b (vacuous test), S6 (Java
  class magic, import-time arch, minos padding). Worker peaks ~35-75 K.
- Two workers wrote the same HISTORY number (§257): the lead renumbers
  on rebase; tell parallel workers "HISTORY numbers are the lead's".

## 4. Key context for the next session

- **Push `main` before spawning**; cleanup: `git worktree remove
  --force`, `git branch -D worktree-agent-<id> r13/S<n>`. To hand a
  branch to a fresh worker: remove its worktree, keep the branch, tell
  it `git checkout r13/S<n>`. A reviewer must not check out in the main
  checkout.
- **S7**: build commands: `<venv>/bin/python packaging/build_dmg.py`,
  then `Seeker.app/Contents/MacOS/Seeker --smoke-test /abs/report.json`
  (no `arch` prefix on the Intel runner). Give the first cold analysis a
  generous timeout (37 s Rosetta). Copy `ci.yml`'s pins and
  `brew install chromaprint`.
- Image names: `Seeker.dmg` (arm64), `Seeker-Intel.dmg`; `bundle_check`
  runs in every build. Intel bundle 333 MB vs arm64 318 MB.
- `ruff check packaging` has 12 findings, outside CI's gate.

## 5. Decisions made

- S5 click track at 123.05 BPM (§256). S6's check reports a failing
  lipo/otool as a problem rather than skipping it (§259).

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

- **Intel app has no fingerprinting** (§260): the bundle holds no
  libchromaprint (the arm64 app has it). Bundle an x86_64 build of it,
  or ship Intel without? S7 and the release notes depend on it.
- **numpy's floor** (§253 Open): global `>=2.3`, or `>=2.5.2` off Intel
  and `>=2.3` on it. The lead recommends the split.
- **Dependabot #14** (setup-uv 10.3.2 -> 10.3.3, green): approve? It
  touches `ci.yml`.
- #1, #5, #7, #8 are still open though their changes are on `main`.
- `/context` at the next lead's start.
- Later: S9's Intel image test (BRIEF §9); S10's outward steps.

## 9. Open questions

- `docs/cli.md`/`docs/packaging.md` don't mention `--smoke-test` (S8).
- PyInstaller warns of sklearn's libomp SDK version and three missing
  hidden imports (harmless so far, §260). Where numba's cache lives.
- Linux audit's pyobjc coverage inferred (§253); five README images
  change byte-wise on `--readme` (§249).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. **Ending:** the plan's "Session protocol".
