# Seeker — session handoff

**This file is the entry point for every new Claude Code session on this
project. Read it first. Overwrite it last.**

Keep it under ~120 lines. It is a baton, not a log — `docs/HISTORY.md`
is the log.

---

## Current state

- **HEAD:** `bb7d2fd` — "7.1.3: enforce the no-private-Application-
  access rule with an AST sweep" (S2 close-out)
- **Working tree:** clean
- **`origin/main`:** **3 commits ahead, not pushed** (dd3931e/92a6cad/
  bb7d2fd — S2's three commits). Ask before pushing.
- **pytest:** 1146 passed, 2 failed, 1 skipped (see "New flake" below —
  reproduces identically on an untouched tree, not a regression from
  this session's work)
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
  shrunk to 25,260 chars), **S2** (§7.1 — Application's private-attribute
  layering leak, all three items 7.1.1–7.1.3).
- **Next session: S3 — Layering: logging (§7.2)**. See
  `docs/round8/SESSION-PLAN.md`.

## S2 — what landed (§7.1)

The brief's own count (twelve private-attribute reaches from `ui/` into
`Application`) was stale — the file had grown to **sixteen** by the
time this session ran. All sixteen fixed, in three commits:

- **7.1.1** (`dd3931e`) — added `Application.settings` (read-only
  property over `_config_store`) and `Application.update_settings
  (**changes)` (generic persist-and-refresh, the counterpart to the
  existing domain-specific setters like `persist_default_destination`).
  Also made `_slskd_base_url`/`_slskd_api_key`/`_slskd_download_dir`
  **public** (dropped the leading underscore) — these fold in the
  env-var fallback that `settings.slskd_base_url` alone doesn't have,
  and `ui/settings_window.py`'s connection tab genuinely needs the
  resolved value, not just the raw config-store field.
- **7.1.2** (`92a6cad`) — replaced all sixteen call sites (eleven reads
  in `settings_window.py`, five in `main_window.py`, one write in
  `settings_window.py`'s `_on_save_thresholds_clicked` that now calls
  `update_settings()` instead of assigning `_config_store` directly).
  Deleted now-unused `dataclasses.replace`/`config_store.load_config`/
  `save_config`/`resolve_config_path` imports from `settings_window.py`.
  `FakeApplication` in `test_ui_smoke.py` grew matching `settings`/
  `update_settings`/`slskd_base_url`/`slskd_api_key` members (it's
  embedded live inside `MainWindow` via `SettingsPage`, so it needs the
  same public surface the real `Application` now has).
- **7.1.3** (`bb7d2fd`) — new AST sweep test,
  `test_no_private_application_attribute_access_in_ui` in
  `test_ui_smoke.py`, same shape as round 7's `setStyleSheet` sweep:
  walks `src/seeker/ui/**/*.py` (recursive — ready for `ui/pages/*` once
  Phase 6 lands) and fails on any `self.application._*` access. Verified
  it actually catches a violation (tested against a standalone snippet,
  not by breaking and re-fixing real code).

**No behavior change** — `_config_store` itself still exists internally
on `Application`; tests that construct a **real** `Application` and poke
`application._config_store` directly (`test_settings_window.py`,
`test_application.py`'s own fallback tests) were left alone since
that's a test's own setup of a real object it owns, not a UI-layer
violation the new sweep is checking for.

## New flake found this session — not a regression, reproduces on a
## clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request`
(`test_ui_smoke.py`, both in the fullscreen-close/Dock-icon area) failed
across this session's full-suite runs. **Confirmed pre-existing**: ran
the full suite twice on a `git stash -u`'d clean tree (pre-S2) and got
the identical two failures both times, with S2's diff entirely absent.
Same general shape as the three flakes CLAUDE.md's Open Issues already
tracks (`test_close_event_falls_back_to_real_close_when_no_tray` et
al.) — likely the same underlying pytest-qt teardown/Qt-deferred-
deletion timing issue, just landing on different tests this time.
**Not diagnosed further this session** — out of scope for S2, and
CLAUDE.md's own rule says diagnose a recurrence directly rather than
reaching for `pytest-rerunfailures`. Whichever session picks up
CLAUDE.md's flake list next should add these two names to it.

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
- [ ] Push S2's three commits to `origin/main` (or say go ahead and a
      future session will).

## Open questions

- **Is the GitHub repo private?** Anonymous requests to
  `github.com/KristiyanDDimitrov/Seeker/actions` return 404 — if so,
  `update_check.py`'s `/releases/latest` 404-means-"no releases"
  assumption only holds once the repo is public.
- **`open -a Seeker` focus artifact** (§14, observed once, unconfirmed).
- **Three round-8 flakes already in CLAUDE.md's Open Issues, plus the
  two new ones found this session (above)** — diagnose any recurrence
  directly, never `pytest-rerunfailures`.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
