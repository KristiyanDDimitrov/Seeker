# Seeker — session handoff

**This file is the entry point for every new Claude Code session on this
project. Read it first. Overwrite it last.**

Keep it under ~120 lines. It is a baton, not a log — `docs/HISTORY.md`
is the log.

---

## Current state

- **HEAD:** `2058c2d` — "9.2/9.3.1: Phase 6 prep (PageContext) +
  History/Help/Support pages" (S5 close-out, pending this commit's own
  tick/handoff commit on top)
- **Working tree:** clean except this rewrite + the SESSION-PLAN.md tick
- **`origin/main`:** was 15 commits ahead as of S4's handoff, not
  re-checked this session — ask before pushing regardless.
- **pytest:** 1147 passed, 1 skipped, 0 failures this run (the two
  tracked fullscreen-close flakes did not fire — see "Known flakes")
- **mypy --strict:** clean, 91 source files
- **ruff check src tests:** **0 findings — this must stay at 0**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map:
`docs/round8/SESSION-PLAN.md`. **Read the session plan, not the full
brief** — the brief is 115 KB, you only need your own session's slice.

- **Done:** Phase 0 (baseline), Phase 1 (toolchain, ruff config, CI),
  Phase 3 (security §6.1–§6.6), Phase 3B (§14 Dock icon), S1 (CLAUDE.md
  shrunk), S2 (§7.1), S3 (§7.2 — logging), S4 (§8.1, §8.2 —
  deduplication), **S5** (§9.2, §9.3.1 — Phase 6 prep + dialogs +
  History/Help/Support pages).
- **Next session: S6 — Search + Sharing pages** (§9.3.1). Read
  `docs/round8/SESSION-PLAN.md`'s own "Phase 6 — the part that needs the
  most care" section before starting, not just your row — and read the
  "Phase 6 mechanics, refined by S5" section below, since S5 found real
  gaps in that section as originally written.

## S5 — what landed (§9.2, §9.3.1: dialogs, History, Help/Support)

Two commits, full detail in the commit messages (`112c74a`, `2058c2d`):

- **Dialogs** (`112c74a`) — the five `QDialog` subclasses plus
  `build_support_links_row()` moved verbatim to new `ui/dialogs.py`.
  `main_window.py` re-exports the names, so test imports didn't need to
  change yet — pointing them at `seeker.ui.dialogs` directly is
  deferred to S11 (§9.3.4).
- **Phase 6 prep + first three pages** (`2058c2d`) — `ui/pages/context.py`
  (`PageContext`, the seam, plus `build_page`/`build_subtitle_label`
  relocated verbatim so every future page can reach them without a
  circular import). `ui/pages/history_page.py` (`HistoryPage`) and
  `ui/pages/static_pages.py` (`HelpPage`, `SupportPage`) — the three
  easiest pages per §9.3.1's ordering. `MainWindow` keeps temporary
  delegating properties for `HistoryPage`'s four tested attributes;
  Help/Support needed none.
- Visually verified, not just test-green: a throwaway offscreen-QPA
  script (real theme stack, `FakeApplication`) grabbed all three pages
  in both themes and matched the Phase 0.3 baselines
  (`~/seeker-baselines/2026-09-08/`) structurally — layout/chrome/
  spacing/colors identical, content differs only because it's
  synthetic. Not committed; worth a real version if this recurs S6–S10.

## Phase 6 mechanics, refined by S5 — read before S6

Two real gaps in SESSION-PLAN.md's 5-step mechanism, found on the first
pages moved:

1. **`PageContext` needed a fifth field the brief's own sketch didn't
   have: `run_busy_worker`**, bound from `MainWindow._run_busy_worker` —
   any page with a background action needs it. `notify` was left OUT
   (no real implementation to bind it to yet). See the dataclass's own
   docstring.
2. **"Zero test edits" only covers `window.<attr>`-style widget access
   — not a page's private module-level helper patched by dotted path,
   and not a MainWindow builder method called directly for a fresh
   instance.** Three tests needed real (narrow, documented) fixes this
   session: `_open_in_file_manager` and `webbrowser.open` were both
   patched via `main_window_module.<name>`, which stopped resolving
   once the real code moved modules; `window._build_help_page()` was
   called directly for a throwaway instance, which no longer exists
   (now `window._help_page`, the real registered one). **Before
   assuming a page is a clean zero-edit move**, grep the page's test
   block for `monkeypatch.setattr(main_window_module,` and
   `window._build_<page>` — Search/Sharing are the next candidates.

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` — tracked
since S2. Fired once in the full suite this session, passed 2/2 in
isolation right after. Same pytest-qt teardown / Qt deferred-deletion
cause already documented. Not diagnosed further.

## Read discipline — this is why sessions were costing 300–700 K tokens

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
in full — `grep -n` the symbol/section, read that range. `uv run
pytest -q`: report only the summary line plus named failures. `git
diff --stat` by default, full diff only for the file under review.
Don't re-read a file you just edited. Don't read a brief for a phase
you aren't doing.

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
