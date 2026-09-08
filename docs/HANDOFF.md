# Seeker — session handoff

**This file is the entry point for every new Claude Code session on this
project. Read it first. Overwrite it last.**

Keep it under ~120 lines. It is a baton, not a log — `docs/HISTORY.md`
is the log.

---

## Current state

- **HEAD:** `4823ad1` — "docs: HISTORY §118 for round 8 S4
  (deduplication)" (S4 close-out, pending this commit's own tick/handoff
  commit on top)
- **Working tree:** clean except this rewrite + the SESSION-PLAN.md tick
- **`origin/main`:** was 5 commits ahead as of S3's handoff, not
  re-checked this session — ask before pushing regardless.
- **pytest:** 1149 passed, 1 skipped, 0 failures this run (the two
  tracked fullscreen-close flakes did not fire — see "Known flakes")
- **mypy --strict:** clean, 86 source files
- **ruff check src tests:** **0 findings — this must stay at 0**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. The full plan is
`docs/BRIEF-2026-09-08-refactor.md`; the session-by-session map is
`docs/round8/SESSION-PLAN.md`. **Read the session plan, not the full
brief** — the full brief is 115 KB and you only need your own session's
slice of it.

- **Done:** Phase 0 (baseline), Phase 1 (toolchain, ruff config, CI),
  Phase 3 (security §6.1–§6.6), Phase 3B (§14 Dock icon), S1 (CLAUDE.md
  shrunk to 25,260 chars), S2 (§7.1 — private-attribute layering), S3
  (§7.2 — logging), **S4** (§8.1, §8.2 — deduplication).
- **Next session: S5 — Phase 6 prep + dialogs + static pages** (§9.2,
  §9.3.1: dialogs, History, Help/Support). This is the start of the
  `MainWindow` decomposition — read `docs/round8/SESSION-PLAN.md`'s own
  "Phase 6 — the part that needs the most care" section before starting,
  not just your row.

## S4 — what landed (§8.1, §8.2)

Six commits, full detail in [HISTORY §118](docs/HISTORY.md#118):

- **§8.1.1** — the seven tables' `_configure_*_columns`/
  `_size_*_columns` pairs (14 methods, ~214 lines) collapsed into
  `theme.ColumnLayout` + `theme.configure_columns()`/`size_columns()`,
  one `ColumnLayout` constant per table. Zero test edits — full suite
  green proved the move behaviour-neutral before any test could mask a
  regression.
- **§8.1.3** — found and fixed a real (if minor) E2-class gap along the
  way: `settings_window.py`'s `locations_table` never got round 7's E2
  fix (its Actions column wasn't derived at construction, because its
  real render is an async callback, not synchronous like every
  MainWindow table E2 was written against). Fixed as its own behaviour
  commit, *then* folded into `ColumnLayout` as a separate pure-refactor
  commit. `downloads_table`/`history_table`/`sharing_uploads_table`
  checked and left alone with an explaining comment — genuinely no
  `ColumnLayout` shape (no Actions column, `setStretchLastSection` only).
- **§8.1.2** — strengthened the E2.4 structural test to also assert no
  non-stretch column sits at Qt's raw `defaultSectionSize()` after
  construction. Verified the strengthening actually catches something
  via two throwaway sabotages (both reverted before committing).
- **§8.2.1** — surveyed ~10 `_render_*` table-loop methods; **no
  extraction made**. They diverge in column count, per-cell formatting,
  pre-loop guards, and post-loop side effects enough that a shared
  helper would be the "bad abstraction over eleven slightly-different
  loops" the brief warned against. This is a reported measurement, not
  a skipped task — see HISTORY §118 for the specific methods compared.
- **§8.2.2** — **not attempted**, per the brief's own instruction: it
  explicitly says to do the `_hidden_to_tray` guard dedup as part of
  Phase 6's poll-fan-out restructuring, not before it.
- **§8.2.3** — `build_stylesheet`'s 467-line/one-f-string QSS blob split
  into 11 per-concern functions. Verified stricter than a pixel diff: a
  script mechanically sliced every character from the original file
  (never retyped) and confirmed byte-for-byte identical output for both
  palettes before/after. One real bug caught while writing that script
  — naive per-function f-strings each contributed their own leading
  newline, corrupting the composed output with extra blank lines; fixed
  via the `f"""\` backslash-continuation opener. See HISTORY §118 for
  the mechanism.

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request`
(`test_ui_smoke.py`) — tracked since S2, confirmed pre-existing via
`git stash -u` against a clean tree. Fired intermittently in S3 (0-2 per
run); did not fire in this session's final full-suite run. Same likely
cause as CLAUDE.md's other tracked flakes (pytest-qt teardown / Qt
deferred-deletion timing). Not diagnosed further — out of scope for S4.

## Read discipline — this is why sessions were costing 300–700 K tokens

1. **Never read `docs/HISTORY.md` in full.** `grep -n` it, read the
   range.
2. **Never read `main_window.py` or `test_ui_smoke.py` in full.**
   `grep -n` for the symbol, read a range around it.
3. **`uv run pytest -q`**, report only the summary line plus named
   failures.
4. **`git diff --stat`** by default; full `git diff` only for the one
   file under review.
5. **Do not re-read a file you just edited to confirm the edit.**
6. **Do not read a brief for a phase you are not doing.**

## Waiting on Kris — real-world actions Code cannot do

- [ ] Physically click the Dock icon (both after a normal close and
      after a fullscreen close) and confirm the window returns.
- [ ] Reopen via Spotlight.
- [ ] From a **second device on the same network**, confirm
      `http://<mac-lan-ip>:5030` no longer answers.
- [ ] Push the unpushed commits to `origin/main` (or say go ahead and a
      future session will) — count not re-verified this session, check
      `git status` / `git log origin/main..HEAD` fresh.

## Open questions

- **Is the GitHub repo private?** Anonymous requests to
  `github.com/KristiyanDDimitrov/Seeker/actions` return 404 — if so,
  `update_check.py`'s `/releases/latest` 404-means-"no releases"
  assumption only holds once the repo is public.
- **`open -a Seeker` focus artifact** (§14, observed once, unconfirmed).
- **Three round-8 flakes already in CLAUDE.md's Open Issues, plus the
  fullscreen-close pair above** — diagnose any recurrence directly,
  never `pytest-rerunfailures`.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
