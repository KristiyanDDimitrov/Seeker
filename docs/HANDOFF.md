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
- **HEAD:** wave 1's last close-out (S1c, §251) on `main`, pushed.
  Untracked: Kris's two PDFs only.
- **The three numbers (Cocoa, X9 Pro mounted):** pytest
  `2440 passed, 1 skipped`; mypy `--strict src/` clean, 147 files;
  ruff 0.
- **CI:** run `41466003716` on `50a6833` failed on one flaky setup
  error (§252: a test ended before its worker's handler; fixed in the
  next commit). The audit job was green. The run on the fix: see
  `gh run list --commit <full SHA>`, the run named `CI` (the others
  are Dependabot's).

## 2. Where we are

Round 13, **wave 1 done**: S0, S1b, S1, S1d, S1c all ☑ (§246 to §251).
All eight Dependabot PRs are settled. **Next: "Read docs/HANDOFF.md and
continue wave 2"**: workers **S2** and **S5** in parallel, then S2b, S3
and S5b as their dependencies land (SESSION-PLAN → Execution → Waves).

## 3. Session report (wave 1's second lead, 2026-11-02)

- Base 50 K; peak ~135 K, work ~85 K (`tokens.py measure --last 1`).
- Integrated S1 (§250) and the #13-fix worker's branch; landed #1, #12,
  #13; pinned uv 0.13.6; S1c close-out (§251). Two `suite-runner`
  checks, one CI run (`41457871688`, green on the actions bump).
- `/context` at wave start: not asked this session.

## 4. Key context for the next session

- **Push `main` before spawning a worker**: worktrees branch from
  `origin/main` (§249). Each leaves a `worktree-agent-<id>` branch;
  `git worktree unlock` (a locked one) then `remove --force`, then
  `git branch -D` it and `r13/S<n>`.
- **A worker can't spawn or load skills**, gets the core `CLAUDE.md` at
  start, a topic file on a Read in its folder; baseline ~14 K. Workers
  share the lead's scratchpad: give each a row subfolder.
- **uv is pinned to 0.13.6** in three places, kept in step by
  `tests/test_uv_pin.py` (§251). S2 rewrites `uv.lock`: a `uv`-version
  mismatch now errors ("Update uv by running `uv self update`").
- **slskd is 0.26.2** in the template. A bare `SLSKD_API_KEY` reads
  `/api/v0/logs/live` (observed, §251); the source suggested a 403.
  Verify a runtime claim, not only the source.
- **zsh: never name a loop variable `path`** (it is tied to `PATH`).
- **mypy 2.4 has no mypyc macOS x86_64 wheel** (§248). Intel's blocker
  is wheels (PF-01): numba 0.62.1 / llvmlite 0.45.1 last with Intel
  wheels; numba 0.62.1 needs numpy < 2.4.
- S5's smoke report can call `cpu_architecture.describe_architecture()`
  (Qt-free; imports `update_check`, so httpx). S9's checklist: Help →
  "Architecture:" under "Build:".
- HISTORY continues at §253.

## 5. Decisions made

- **Kris (2026-11-02, wave 1):** #5, #7, #8, #9 landed (S1b). #1, #12
  approved and landed; #13 landed as the image bump alone (Kris chose
  option (a), `role=Administrator;` in the template; the disposable
  container showed it unnecessary and, with an empty key, breaking, so
  it was not made: tell him). #6 closed for one pinned uv.
- Earlier decisions (Intel first as v0.2.0, no signing, waves with
  workers, rows ≤ 65 K): the plan and `git show d507065:docs/HANDOFF.md`
  field 5.

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

- Close PR #6 (done by the lead if it has not been: `gh pr close 6`).
  #1, #12, #13 close themselves once Dependabot sees `main` current.
- `/context` at the next lead's start.
- Later, unchanged: S9 the Intel image in the test account (BRIEF §9);
  S10 each outward step; after S10 the website's Intel download.
  R14/R15 and phase 01's carried items: `git show d507065:docs/HANDOFF.md`
  field 8.

## 9. Open questions

- `docs/cli.md:30` and `help_text.py` could mention Premium (S1d left
  them; outside §1d).
- Five README images change byte-wise on `--readme` with no UI change
  (cause UNVERIFIED, §249).
- slskd 0.26.2's disk logger is on by default: does `LeftoverService`
  ignore `logs/`? UNVERIFIED (§251).
- Phase 01's carried questions: `git show 2b7e8d9:docs/HANDOFF.md`
  field 9.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. **Ending:** the plan's "Session protocol".
