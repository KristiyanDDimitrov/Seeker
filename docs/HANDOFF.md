# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `661e272`, pushed. Tree clean (aside from an untracked
  `Claude outputs/` directory that predates this session — not part of
  the repo, left alone).
- **Local pytest (offscreen Qt, this machine):** `2 failed, 1144
  passed, 29 skipped in 88.94s` — both failures are the known
  fullscreen-close flakes CLAUDE.md's Open issues already tracks,
  unrelated to this session's changes.
- **Real CI (`gh run view 34407483639`, the push of this session's four
  commits): ruff/mypy clean, pytest `1 failed, 1145 passed, 29 skipped,
  152.66s`.** Down from the prior run's `5 failed` — §1.2's fix is
  confirmed live: all three `test_callback_server.py` ConnectTimeouts
  are gone. The one remaining failure is
  `test_view_menu_focus_search_navigates_and_focuses_the_search_field`
  (§1.3's known flake, already tracked in CLAUDE.md — S2's job, not
  this session's).
- **`mypy --strict src/`: clean, 102 files. `ruff check src tests`: 0
  findings** (both local and on CI).

## Where we are in the plan

Round 9. Full plan: `docs/BRIEF-2026-09-09-round9.md`. Session map:
`docs/round9/SESSION-PLAN.md` — **read that, not the full ~40 KB
brief.**

- **Done: S1** (§1.1 workflow hygiene, §1.2 the callback-server
  bind/serve split + production auth-flow fix), four commits:
  `8b698ae` (docs), `bc1471a` (§1.1), `231b512` (§1.2 1/2, the
  library-level split), `661e272` (§1.2 2/2, the auth_manager fix).
- **Next: S2** — §1.3 (the focus-search flake), §1.4 (the history-
  refresh flake, time-boxed), §1.5a (the always-skipped-test answer).

## S1 report

**§1.1.** Bumped `actions/checkout@v4` → `@v5` and
`astral-sh/setup-uv@v5` → `@v7` (**not** `@v6` as the brief originally
scoped — verified via each action's own `action.yml` history that
`setup-uv@v6` is still `node20`; `v7.0.0` is the first release that
switches to `node24`, which is the actual fix for the stated
deprecation warning. This is the one real divergence from the brief's
literal text this session made, per §1.1's own "read the release notes
before bumping" instruction.). Also pinned `runs-on` from
`macos-latest` to `macos-26` (confirmed via `gh run view`'s Runner
Image section), with a comment naming the condition for reverting.

**§1.2.** Split `callback_server.py`'s `wait_for_callback()` into
`create_callback_server()` (bind+listen) and `serve_until_callback()`
(the serve loop), plus a new `_LoopbackHTTPServer` that skips
`HTTPServer.server_bind()`'s `socket.getfqdn()` reverse-DNS call
entirely. Then changed `auth_manager._authorize()` to create the
server, THEN open the browser, THEN serve — closing the real
production bug where a returning user's no-consent-screen redirect
could land before the callback socket existed. Two commits, as the
brief asked. `tests/test_callback_server.py`'s four connecting tests
now create the server on the test's own thread and use ephemeral
ports (`port=0`) instead of the fixed 18881-18885 range.
`tests/test_auth_manager.py`'s two `wait_for_callback`-patching tests
were updated to patch `create_callback_server`/`serve_until_callback`
instead; the reauthorize-flow test now also asserts the real
`create → open → serve` ordering, which is the actual regression this
fix closes and the old test shape couldn't have caught.

**Verified fixed, not just locally green:** pushed and read the real
CI run (`34407483639`) — all three target tests pass, count of
failures dropped from 5 to 1 (the one remaining is §1.3's, out of
scope for this session).

**Skills used:** `engineering-advanced-skills:focused-fix` was loaded
per the session map's table, but its 5-phase SCOPE→TRACE→DIAGNOSE
protocol is built for open-ended "make this feature work" repairs —
§1.2 arrived pre-diagnosed with an exact root cause and fix already
specified in the brief, so the heavy manifest/dependency-map phases
were skipped as not applicable; the fix itself still follows the
skill's fix-order discipline (one change at a time, test after each).
Noting the divergence per §0.3's instruction to record it.

**Also committed:** `docs/BRIEF-2026-09-09-round9.md` and
`docs/round9/SESSION-PLAN.md` were untracked at session start (created
outside git, alongside a duplicate untracked `Claude outputs/` copy) —
tracked them the same way round 8's brief/session-map were tracked,
so future sessions can grep them normally.

## Read discipline — unchanged, still why sessions blow their budget

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief section your row doesn't point at.

## Waiting on Kris

Unchanged from `docs/round9/SESSION-PLAN.md`'s own "Waiting on Kris"
section — see that file, not here, for the current list (approval
gates on §4.2b/§3.2/§1.2-fallback/§8.1-§8.5, and the real-desktop
checks Code cannot do). Nothing in S1 added a new one.

## Open questions

- **CLAUDE.md's Open issues still lists the `test_callback_server.py`
  trio as an open CI-only failure** — that entry is now stale (§1.2
  fixed it, confirmed on real CI) and should be moved to HISTORY as
  closed the next time someone is in CLAUDE.md for another reason; not
  urgent enough to justify its own session.
- **The repo-privacy open question is answered and removed** (brief
  §1, confirmed public 2026-09-09) — no longer appears anywhere in this
  file; if it resurfaces elsewhere, delete it there too.
- **`docs/HISTORY.md` is ~837 KB per the round 9 brief** — still never
  read whole, per the standing rule.
- Carried, unconfirmed: the five round-8 test flakes in CLAUDE.md's
  Open issues (two fired again this session's local runs, in the
  already-tracked fullscreen-close pattern — not new).

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round9/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
5. If you pushed: record the CI run id and result here too.
