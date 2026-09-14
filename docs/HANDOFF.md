# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `1707ab7`, pushed. Tree clean (aside from an untracked
  `Claude outputs/` directory that predates this session — not part of
  the repo, left alone).
- **Local pytest (offscreen Qt, this machine, Darwin 25.6.0): `1186
  passed, 2 failed, 29 skipped`** — the 2 failures are the already-
  documented S4 flake pair (`test_reopening_after_a_fullscreen_close_
  restores_prior_geometry`, `test_fullscreen_close_policy_check_
  ignores_a_stale_request`), confirmed pre-existing this session via
  `git stash -u` (fails identically on unmodified HEAD). Re-running
  full-suite locally without those two selected: 1186 passed.
- **`mypy --strict src/`: clean, 103 files. `ruff check src tests`: 0
  findings.**
- **CI on `1707ab7` (this session's push): run `34840265764`, `2
  failed`.** ruff/mypy both clean; `src/seeker/login_item.py` shows
  100% coverage. The 2 failures are the OTHER already-tracked flake
  pair (`test_history_refresh_button_refetches`,
  `test_review_tab_replace_button_calls_apply_upgrade_decision_with_
  delete_flag`) — not new, not this session's diff (neither test
  touches login_item.py/config_store.py/application.py/main_ui.py/
  main_window.py/settings_window.py's new code paths).

## Where we are in the plan

Round 9. Full plan: `docs/BRIEF-2026-09-09-round9.md`. Session map:
`docs/round9/SESSION-PLAN.md` — **read that, not the full ~40 KB
brief.**

- **Done: S1-S7.**
- **Next: S8** — Review page resizable panes (§6). Split point: after
  the splitter works, before persistence.

## S7 report — §3.2, start Seeker at login

**Approval gate cleared this session** — Kris chose `SMAppService`
over the `LaunchAgent` plist alternative (asked live via
AskUserQuestion at session start, per the session plan's own gate).
Removed from `docs/round9/SESSION-PLAN.md`'s "Waiting on Kris".

**What landed:**
- `src/seeker/login_item.py` — new module wrapping
  `SMAppService.mainAppService()`. `is_supported()` gates on
  `sys.platform == "darwin"` AND `sys.frozen` (a `uv run` dev process
  has no bundle identifier to register against). `get_status()`
  always reads the REAL live ServiceManagement status, never a
  mirrored `config.json` boolean — confirmed live on this real Darwin
  25.6.0 machine (unbundled `uv run python`): `status()` returns `3`
  (`NotFound`) without raising, and `registerAndReturnError_`/
  `unregisterAndReturnError_` are real bound methods — the four raw
  status ints (0-3) are confirmed against the real module, not
  assumed. What real register()/unregister() does against a genuine
  `.app` bundle is UNVERIFIED here (is_supported() never lets a dev
  run reach those calls) — needs a real packaged-build check.
- `pyobjc-framework-ServiceManagement>=10.0; sys_platform == 'darwin'`
  added to `pyproject.toml`; mypy override added (no py.typed marker,
  same gap as `AppKit`).
- `packaging/seeker.spec`'s `hiddenimports` gains
  `"ServiceManagement"` — same "PyInstaller can't see a deferred
  import" reason the existing `AppKit`/`Foundation`/`objc` entries are
  there for. **Untested by any automated check** (nothing in this
  repo tests the spec file) — first real packaged build should
  confirm the login item actually registers.
- `config_store.py` gains `start_hidden_at_login: bool = False` — the
  "start hidden in the menu bar" companion option. This field is
  standalone, not a mirror of the login-item's own on/off state.
- `Application.login_item_supported`/`login_item_status()`/
  `set_login_item_enabled()` — thin passthroughs to `login_item.py`.
- `MainWindow.start_hidden_to_tray()` — skips `show()` entirely
  (never shows-then-hides, which would flash a frame) when a tray
  icon exists; returns `False` when there's no tray to hide behind, in
  which case `main_ui.main()` shows the window normally. Wired at the
  same seam `main_ui.main()`'s existing `window.show()` call already
  was.
- Settings' new "Startup" group (`_build_thresholds_tab`, after
  Notifications) — two checkboxes ("Start Seeker at login", "Start
  hidden in the menu bar") plus a status label for the
  `REQUIRES_APPROVAL`/unsupported states. `refresh_login_item_state()`
  re-reads the real status on every real Settings page show
  (`MainWindow._on_page_changed`, same lazy-refresh-on-show pattern
  Duplicates/Sharing/History already use) — a login item revoked via
  System Settings shows as off here too, no restart needed. Enabling
  login-at-startup defaults "start hidden" on every time (not just
  once); disabling login leaves "start hidden" untouched, since
  `main_ui.main()` applies it on every launch regardless of how the
  process started (there's no reliable in-process signal to
  distinguish a login-triggered launch from a Finder double-click —
  same always-on-when-enabled behavior other login-item apps use).

**New tests:** `tests/test_login_item.py` (mocks `sys.modules
["ServiceManagement"]` directly to exercise `get_status`/`set_enabled`
against every real status value without needing a real bundle),
plus additions to `test_config_store.py`, `test_application.py`,
`test_settings_window.py`, `test_ui_smoke.py` (including
`FakeApplication` gaining `login_item_supported`/`login_item_status`/
`set_login_item_enabled`, defaulted to the same "unsupported" state a
real dev-run `Application` reports, so no pre-existing test needed to
change).

## Read discipline — unchanged, still why sessions blow their budget

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief section your row doesn't point at.

## Waiting on Kris

See `docs/round9/SESSION-PLAN.md`'s own "Waiting on Kris" section.
This session adds one real-desktop check there: **confirm on a real
packaged `.app` build that "Start Seeker at login" actually registers**
(System Settings > General > Login Items) and that "start hidden"
skips the window on the next real login-triggered launch — nothing in
this session verified real register()/unregister() behavior, only the
gating logic around it.

## Open questions

- **§3.1's real applied-pixel behavior is still unverified by any
  automated test**, and **§3.2's real register()/unregister() behavior
  against a packaged `.app` is unverified by anything but reading the
  real API shape** — both need the same real-Mac session. Worth
  combining into one real-hardware pass rather than two.
- **Item 125 (the §2.3 quit hang), the two S4 flakes, the fullscreen-
  close pair, and the other tracked CI-only flakes are all unchanged**
  — this session's own CI run reproduced the S4 pair again (see above),
  nothing newly fired. Tracked in CLAUDE.md's Open issues; not
  re-litigated here.
- `docs/HISTORY.md` is now ~890 KB — still never read whole. No
  HISTORY entry written yet for §3.2 — worth adding given the real
  live SMAppService investigation above, if a future session has
  budget for the two-tier docs pass (Working agreement #1).

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round9/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
5. If you pushed: record the CI run id and result here too.
