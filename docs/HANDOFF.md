# Seeker — session handoff

**This file is the entry point for every new Claude Code session on this
project. Read it first. Overwrite it last.**

Keep it under ~120 lines. It is a baton, not a log — `docs/HISTORY.md`
is the log.

---

## Current state

- **HEAD:** `24507fd` — "7.2.4: log three previously-silent library-
  loading/cache exception swallows" (S3 close-out)
- **Working tree:** clean
- **`origin/main`:** **5 commits ahead, not pushed** (dd3931e/92a6cad/
  bb7d2fd/253f347 from S2, plus this session's 2b0c84c/24507fd). Ask
  before pushing.
- **pytest:** 1148 passed, 1 skipped, 1 flaky (see "Known flakes" below
  — not a regression, reproduces on an untouched tree)
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
  shrunk to 25,260 chars), S2 (§7.1 — private-attribute layering),
  **S3** (§7.2 — logging, all five items 7.2.1–7.2.5).
- **Next session: S4 — Deduplication (§8.1, §8.2)**. See
  `docs/round8/SESSION-PLAN.md`.

## S3 — what landed (§7.2)

The brief's own count (70 service-layer prints) was close but stale —
actual count was 68 in the service layer plus 4 more in `ui/` (main_
window.py, workers.py), all now converted; two commits:

- **2b0c84c** (7.2.1–7.2.3 + part of 7.2.4) — module-level
  `logger = logging.getLogger(__name__)` in every affected module.
  Handlers live in exactly two places: `main.py` attaches a
  `StreamHandler(stdout)` with a bare `"%(message)s"` formatter (the
  CLI's print() replacement — identical visible text, confirmed by a
  real run); `main_ui.py` attaches a `RotatingFileHandler` under
  `platformdirs.user_log_dir("Seeker")` (confirmed by a real run
  producing a real log file with correctly formatted lines). Both sit
  on the shared `"seeker"` logger tree, so one `logger.*()` call
  reaches whichever handler is actually configured — no per-site
  dual-path special-casing needed. New `Application.resolve_log_dir()`
  / `DataLocations.log_dir`, surfaced in the Help page's data-locations
  list plus a new "Open Log Folder" button next to "Open Data Folder".
  Every print() converted, level chosen per message (progress -> INFO,
  recoverable issues -> WARNING, real failures -> ERROR, per-file batch
  chatter -> DEBUG). `download_service.py` keeps exactly two prints —
  both genuinely CLI-only interactive paths (`SEEKER_DEBUG_POLL`-gated
  `_debug_poll`, `_confirm_upgrade`'s `input()` confirmation), neither
  reachable from the GUI, so neither is a layering violation. Tests
  that asserted on captured stdout (`capsys`) now use `caplog`. Also
  fixed a silent double-failure found while converting
  `metadata_service.py`'s rename rollback: if the disk rename-back
  itself failed after an already-failed DB update, the result still
  unconditionally reported "renamed back" — now logged at ERROR with
  `exc_info`.
- **24507fd** (rest of 7.2.4) — an AST sweep for bare `except: pass`
  found four sites; three were genuinely silent with no logging and now
  get `logger.debug(..., exc_info=True)`: `album_art_cache.py`'s disk-
  cache write failure, `docker_setup.py`'s slskd-log health-check read,
  `audio_fingerprint.py`'s three-stage libchromaprint search loop. The
  fourth (`ui/workers.py`'s Qt-teardown-race emit) already had a real
  justifying comment and stays silent — a note was added explaining why
  it's deliberately not logged. Three more `contextlib.suppress` sites
  (`atomic_file.py` chmod-on-Windows, `main_window.py` folder-preview
  stat, `duplicate_service.py` size_bytes fallback) were reviewed and
  left alone — each already has a real comment justifying the silence.

**7.2.5 report:** remaining `print()` count outside `cli.py`: **2**,
both documented CLI-only exceptions (see above) — target was "zero
outside justified CLI voice," met. `cli.py` keeps its 84 prints
unchanged (that's its own legitimate output channel).

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request`
(`test_ui_smoke.py`) — found in S2, confirmed pre-existing via
`git stash -u` against a clean tree. This session saw the same pair
fire intermittently (never more than one per run). Same likely cause as
CLAUDE.md's other tracked flakes (pytest-qt teardown / Qt deferred-
deletion timing). Not diagnosed further — out of scope for S3.

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
- [ ] Push the 5 unpushed commits to `origin/main` (or say go ahead and
      a future session will).

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
