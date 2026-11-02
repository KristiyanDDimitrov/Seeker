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
- **HEAD:** S5's close-out (§256) on `main`, pushed. Untracked: Kris's
  PDF only. No worktrees, no `r13/*` branches left.
- **The three numbers (Cocoa, X9 Pro mounted):** pytest
  `2496 passed, 1 skipped`; mypy `--strict src/` clean, 149 files;
  ruff 0. Native `seeker-ui --smoke-test`: exit 0.
- **x86_64 (Rosetta, offscreen):** `17 failed, 2424 passed, 9 skipped`
  at S3 (§255), one cause: arm64-only libchromaprint. The main
  checkout's `.venv-x86_64` exists (CLAUDE.md → Commands).
- **CI:** `41477482836` (S2), `41480581499` (S2b, S3) and `41485315126`
  (S5 and the handoff, `a00b88e`, 12 m 27 s) green. `ci.yml` has
  `cancel-in-progress: true`: a push before a run ends cancels it (S5's
  `41485193721` was), so watch the run on the last push.

## 2. Where we are

Round 13, **wave 2: S2, S2b, S3, S5 ☑** (§253 to §256). **Left in
wave 2: S5b** (frozen arm64 smoke test). **Next: "Read
docs/HANDOFF.md and continue wave 2, then wave 3"**: workers **S5b**,
**S3b** (re-planned ~35 K, §255) and **S6** in parallel (≤ 3), then S4
and S6b (SESSION-PLAN → Execution → Waves).

## 3. Session report (wave 2's lead, 2026-11-02)

- Base 50 K; peak ~160 K, work ~109 K (`tokens.py measure --last 1`):
  past the soft ceiling, so S5b wasn't started. Integrating five
  reports and their close-outs costs a lead ~20 K a row.
- Six workers (S2, S2b, S3, S5, two fix rounds), two `diff-reviewer`s,
  five `suite-runner` checks. S5's first worker peaked ~135 K: its
  review found 10 gaps; a fresh worker fixed 9 on the same branch.
- `/context` at wave start: not asked.

## 4. Key context for the next session

- **Push `main` before spawning**; worktree cleanup: `git worktree
  unlock`, `remove --force`, `git branch -D worktree-agent-<id>
  r13/S<n>`. To hand a branch to a fresh worker: remove its worktree,
  keep the branch, tell the worker `git checkout r13/S<n>`.
- **diff-reviewer pays off** on feature rows (S5: two checks that
  passed vacuously). Run it before every merge of new code.
- **S5b** (handoff notes in §256): build with `uv run python
  packaging/build_dmg.py`, run `dist/Seeker.app/Contents/MacOS/Seeker
  --smoke-test /abs/report.json` (absolute path). Open: review finding
  3 (frozen `walk_packages` sees only what was bundled; the fallback is
  `build_dmg.py` writing the module list into the bundle); qt.conf vs
  PluginsPath and libqoffscreen bundled, both UNVERIFIED. The spec now
  imports `seeker.frozen_imports` via `sys.path`: not yet run by a real
  build.
- **S3b**: the skip for test_duplicate_service's 17 must not hide an
  Intel lookup bug (working agreement 5); timings with cleared numba
  caches; the "Platforms" facts. **S4** needs `brew install
  chromaprint` on the Intel runner.
- Rosetta exposes no AVX (llvmlite: `westmere`): no `NUMBA_CPU_NAME`.
- `required-environments` does not guard sdist packages; the lock test
  (§254) does. A plain relock keeps versions; `-P`/`--upgrade` is
  where Intel's pins would break.
- HISTORY continues at §257.

## 5. Decisions made

- **Lead (wave 2):** S2 review findings 2–4 and S5 findings 1, 2, 4–10
  fixed before merge; S5 finding 3 deferred to S5b. S5's click track
  runs at 123.05 BPM, not BRIEF §5's 120 (librosa's lag grid, §256).
- Earlier: `git show 50a6833:docs/HANDOFF.md` field 5.

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

- **numpy's floor** (§253 Open): global `>=2.3` as the brief says, or
  `>=2.5.2` off Intel and `>=2.3` on it (same lock today; guards the
  native set against a future cap). The lead recommends the split.
- **Dependabot #14** (setup-uv 10.3.2 → 10.3.3, green): approve? It
  touches `ci.yml`, which S4 copies.
- #1, #5, #7, #8 are still open though their changes are on `main`;
  PR #6 is closed.
- `/context` at the next lead's start.
- Later, unchanged: S9's Intel image test (BRIEF §9); S10's outward
  steps; R14/R15 and phase 01's items: `git show d507065:docs/HANDOFF.md`
  field 8.

## 9. Open questions

- `docs/cli.md`/`docs/packaging.md` don't mention `--smoke-test` (S5b
  or S8). `docs/cli.md:30` and `help_text.py` could mention Premium.
- The Linux audit's pyobjc coverage is inferred from the layering, not
  printed (§253).
- Five README images change byte-wise on `--readme` (§249); slskd's
  disk logger vs `LeftoverService` (§251); phase 01's: `git show
  2b7e8d9:docs/HANDOFF.md` field 9.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. **Ending:** the plan's "Session protocol".
