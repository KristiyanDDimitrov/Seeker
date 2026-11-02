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
- **HEAD:** S1d's close-out on `main`, pushed. Untracked: Kris's two
  PDFs and `docs/phase-02/round-13/wave1-reports.md` (below).
- **The three numbers (`9716c18`, Cocoa, X9 Pro mounted):** pytest
  `2419 passed, 1 skipped`; mypy `--strict src/` clean, 146 files; ruff 0.
- **CI:** run `41441377682` green on `5da3150` (S1d's close-out): check and audit.

## 2. Where we are

Round 13, **wave 1, part done.** S1b ☑ (§248), S1d ☑ (§249). The first
lead stopped at 149 K (the soft ceiling) with two finished worker
branches not integrated. **Next: "Read docs/HANDOFF.md and continue
wave 1"**: a fresh lead integrates S1, settles S1c, then writes wave
2's handoff.

## 3. Session report (wave 1's first lead, 2026-11-02)

- B after S0: **50 K** (`tokens.py`, this session). Peak 149 K.
- Eight `upstream-reader`s in parallel, one per Dependabot PR; Kris
  answered once. #5, #7, #8, #9 landed as **local commits at the PRs'
  exact locked versions** (Kris's choice; a bare `--upgrade-package`
  picks newer ones).
- Three `row-worker`s (S1, S1d, #13's fix) and four `suite-runner`
  checks ran; none misbehaved. CI `41441377682` green on
  `5da3150`.
- `/context` at wave start: asked; not captured in this session.

## 4. Key context for the next session

- **`wave1-reports.md`** holds S1's and #13-fix's reports (status,
  branch, evidence, HISTORY draft, index line, standing facts).
  Integrate each per the plan's lead protocol step 3, then delete it.
  - **S1:** `r13/S1` @ `9afe80f`, worktree `agent-a5bb0af5f528e31b9`;
    2435 passed offscreen; 147 mypy files (new `cpu_architecture.py`).
  - **#13's fix:** `r13/S1c-slskd-logs` @ `89c5109`, worktree
    `agent-a2e4fbc5f462bd131`: the health check reads
    `/api/v0/logs/live`, falling back to `/logs` on a 404. Safe on 0.26.0.
- **Worktrees branch from `origin/main`, not local `main`** (§249):
  push before spawning, or the worker starts behind. Each leaves a
  `worktree-agent-<id>` branch to delete with the worktree. S1d's
  worktree (`agent-ab47103b78673e690`) was locked by its agent's
  process and is not removed yet: `git worktree remove` it, then
  delete `r13/S1d` and `worktree-agent-ab47103b78673e690`.
- **A worker can't spawn or load skills**, gets the core `CLAUDE.md`
  at start, a topic file on a Read in its folder; its transcript is
  `~/.claude/projects/…/<lead session>/subagents/agent-<id>.jsonl`;
  baseline ~14 K (S1, measured). Workers share the lead's scratchpad:
  give each a row subfolder.
- **uv mismatch:** CI installs the latest uv (0.13.6, unpinned);
  this Mac has 0.12.5; `uv_build<0.13.0` excludes CI's. Kris chose
  one pinned uv (S1c): close #6; pin `version:` in setup-uv,
  `required-version` and the `uv_build` range together; Kris runs
  `uv self update` (give him the exact command). Before S2's lock.
- **mypy 2.4 has no mypyc macOS x86_64 wheel** (§248): slower on Intel.
- Intel's blocker is wheels (PF-01): numba 0.62.1 / llvmlite 0.45.1
  last with Intel wheels; numba 0.62.1 needs numpy < 2.4.
- HISTORY continues at §250.

## 5. Decisions made

- **Kris (2026-11-02, wave 1):** #5, #7, #8, #9 approved and landed.
  **#1 and #12 not approved** (read: both safe; #1 needs a rebase):
  ask again. #6: close, in favour of one pinned uv. #13: fix first,
  then the bump.
- Earlier decisions (Intel first as v0.2.0, no signing, waves with
  workers, S1b/S1c [ASK] per merge, rows ≤ 65 K): the plan and
  `git show d507065:docs/HANDOFF.md` field 5.

## 6. Blockers

- **#13 needs Kris:** slskd's source makes a bare `SLSKD_API_KEY`
  ReadOnly, and 0.26.2's `/logs/live` is AdministratorOnly, so new
  installs would get 403 and still lose bad-credential and kick
  detection. Options in `wave1-reports.md`: (a) the template's
  `SLSKD_API_KEY=role=Administrator;${SLSKD_API_KEY}` (verify on a
  disposable container, never Kris's), (b) accept, (c) another source,
  (d) close #13.

## 7. Files in progress

`wave1-reports.md` (untracked); branches `r13/S1`,
`r13/S1c-slskd-logs` and their worktrees.

## 8. Waiting on Kris

- #1 and #12 approval; #13's option; `uv self update` when S1c pins uv.
- `/context` at the next lead's start.
- Later, unchanged: S9 the Intel image in the test account (BRIEF
  §9); S10 each outward step; after S10 the website's Intel download.
  R14/R15 and phase 01's carried items: `git show
  d507065:docs/HANDOFF.md` field 8.

## 9. Open questions

- `docs/cli.md:30` and `help_text.py` could mention Premium (S1d
  left them; outside §1d).
- Five README images change byte-wise on `--readme` with no UI change
  (cause UNVERIFIED, §249).
- 0.26.2 slskd's disk logger is on by default: does `LeftoverService`
  ignore `logs/`? UNVERIFIED.
- Phase 01's carried questions: `git show 2b7e8d9:docs/HANDOFF.md`
  field 9.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. **Ending:** the plan's "Session protocol".
