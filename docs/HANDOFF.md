# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** this session's tick/handoff commit, on top of `9f08957` —
  "S13: comment triage — ui/pages/duplicates_page.py" (S13's ten other
  per-file commits land before it).
- **Working tree:** clean. `origin/main`: not re-checked this session —
  ask before pushing regardless.
- **pytest:** 1149 passed, 1 skipped after every individual per-file
  commit this session. The final whole-suite run hit
  `test_fullscreen_close_policy_check_ignores_a_stale_request` failing
  once (1148 passed, 1 failed, 1 skipped) — re-ran that one test alone
  immediately after and it passed. Not one of CLAUDE.md's previously
  named three round-8 flakes — added as a fourth entry there this
  session (comment-only session, so not a regression from this
  session's own work).
- **mypy --strict src/: clean, 99 files. ruff check src tests: 0
  findings.**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map: `docs/round8/
SESSION-PLAN.md` — **read that, not the full 115 KB brief.**

- **Done:** Phase 0-6 (through S11.7), **S12** (Phase 7 pass 1: six
  small files), and now **S13** (Phase 7 pass 2: `soulseek/
  download_service.py` plus all ten `ui/pages/*` modules —
  `context.py`, `history_page.py`, `static_pages.py`, `search_page.py`,
  `sharing_page.py`, `downloads_page.py`, `tagging_panel.py`,
  `dashboard_page.py`, `review_page.py`, `duplicates_page.py`).
- **Next: S14** (CLAUDE.md 8b + README — §11.2.4, §11.2.5, §11.3). Read
  §11 of the main brief fresh — the deferred-from-S1 pieces are the new
  conventions (depend on Phases 4-7, now all landed) and the
  regenerated layout tree (depends on Phase 6's `ui/pages/*`, now
  real).

## S13 report (§10.1.7)

One commit per file, eleven total. `download_service.py`: 516 -> 414
`#` lines. The ten page modules together: roughly 950 -> 780 `#`/
docstring lines (exact per-file numbers are in each commit's own
message — not re-tallied here since the real finding is qualitative,
below).

**The real finding: round 8's own Phase 6 (`MainWindow` decomposition,
S5-S11.7 — the biggest arc in the round) had never been written up in
`docs/HISTORY.md` at all.** Every page module's docstring carried its
own extraction story inline (`PageContext`'s field-by-field growth,
`TaggingPanelHost`/`DashboardHost`/`ReviewHost`'s own discovery,
Duplicates needing no second seam, S11's two Qt gotchas) with nowhere
else for that provenance to live. Per §10.1.6 ("anything you MOVE must
land in HISTORY first"), wrote it up as new **HISTORY §119** before
compressing any of those docstrings — one section, built incrementally
as each page's comments were triaged, rather than speculatively
up front.

**A second wrong citation found, same class as S12's two**: `sharing_
page.py` cited "roadmap item 62 (Phase 7)" throughout — item 62 has no
standalone HISTORY section at all; the real investigation lives under
**§56 Phase 7** (Sharing & Uploads). Fixed everywhere it appeared, same
treatment as S12's `matching.py`/`docker_setup.py` fixes. The
"R2.x"/"R3.x"/"R5"/"R7.x" style short-codes used throughout the page
files (Review/Duplicates checkbox-survives-poll-rebuild, bulk
replace/resolve, tray background operation) all resolved cleanly to
real sections (§86, §88, §90) — no further wrong citations found
there, but every one was checked against the source text before
citing it, not assumed correct from the label alone.

**Examples, from actual work:** KEEP verbatim — `download_service.py`'s
`FAILED_STATE_MARKERS` comment (Soulseek's `[Flags]` enum, comma-joined
string, no provenance attached, still 100% load-bearing). KEEP-
COMPRESSED — `_supersede_stale_duplicates`'s docstring (a real,
non-obvious return-value contract) kept in full, its "Confirmed live
2026-08-28" narrative trimmed to the fact plus a §63/§66-style link.
MOVE — the entire Phase 6 extraction story, now §119 (see above). DELETE
— `download_service.py`'s `get_review_candidates` comment referencing
its own now-irrelevant "originally deferred to a future UI" framing.

## Read discipline — this is why sessions were costing 300-700 K tokens

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't re-read a file you just edited. Don't read a brief for a
phase you aren't doing.

## Waiting on Kris — real-world actions Code cannot do

- [ ] Click the Dock icon after a normal close and after a fullscreen
      close; confirm the window returns. Reopen via Spotlight too.
- [ ] From a second device, confirm `http://<mac-lan-ip>:5030` no
      longer answers.
- [ ] Push the unpushed commits to `origin/main` (or say go ahead) —
      check `git log origin/main..HEAD` fresh, not re-verified now.

## Open questions

- **Is the GitHub repo private?** `github.com/KristiyanDDimitrov/
  Seeker/actions` 404s anonymously — if so, `update_check.py`'s 404-
  means-"no releases" assumption only holds once the repo is public.
- **`open -a Seeker` focus artifact** (§14, observed once, unconfirmed).
  S9's skip-count mismatch (29 vs. everyone else's 1) — same status.
- **Four round-8 flakes now in CLAUDE.md's Open Issues** (the fourth,
  `test_fullscreen_close_policy_check_ignores_a_stale_request`, added
  this session) — diagnose any recurrence directly, never
  `pytest-rerunfailures`.
- **S14 should spot-check citations too, same discipline as S12/S13**:
  two wrong "item N"/"CLAUDE.md item N" citations in S12, one wrong
  "roadmap item 62" (should be §56 Phase 7) throughout `sharing_page.py`
  in S13 — a real, recurring class of error in this codebase's own
  comments, not a one-off. Don't assume a citation is correct because
  it looks plausible.
- **`docs/HISTORY.md` is now ~14,100 lines** — still never read whole,
  per the standing rule; §119 (Phase 6 decomposition) is the newest
  section, at the very end of the file.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
