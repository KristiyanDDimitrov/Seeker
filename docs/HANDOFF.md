# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `186442c` — "S11.7: repoint Tray tests at the page widget,
  drop delegating properties" (S11.7's two-commit mechanism landed;
  this session's tick/handoff commit goes on top)
- **Working tree:** clean except this rewrite. `origin/main`: not
  re-checked this session — ask before pushing regardless.
- **pytest:** a clean run is 1149 passed, 1 skipped — identical to
  S10–S11.6's own numbers, confirmed with two consecutive clean runs
  after S11.7's second commit. The tracked fullscreen-close flake pair
  fired 3 times across this session's earlier runs (once each on
  `test_application_active_is_a_near_no_op_when_already_visible` — see
  "Real gap" below, a genuine bug caught by the suite, NOT this flake
  pair — and twice on the two tracked tests), always green in
  isolation — see "Known flakes" below.
- **mypy --strict src/:** clean, 99 files. **ruff check src tests: 0
  findings — this must stay at 0.**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map: `docs/round8/
SESSION-PLAN.md` — **read that, not the full 115 KB brief.**

- **Done:** Phase 0–4, S1–S10, S11, S11.1–S11.6 (test-split, dialogs
  through Duplicates), **S11.7** (Tray, mirrors S11's own tray
  extraction). **Phase 6 (`MainWindow` decomposition + its test-split,
  §9.1–§9.3) is now fully complete** — zero `@property` delegating
  stubs remain on `MainWindow` (confirmed: `grep -c "^    @property"
  src/seeker/ui/main_window.py` → 0).
- **Next: S12** (Comment triage, pass 1 — §10.1, small files:
  `audio_formats`, `docker_setup`, `matching`, `config_store`,
  `quality`, `audio_analysis`). This starts Phase 7, a genuinely new
  phase — read §10 of the main brief fresh, the §9 Phase-6 summary in
  SESSION-PLAN.md no longer applies.

## S11.7 — what landed (§9.3.4 test-split: Tray)

Two commits (`d03666e`, `186442c`). 16 tests moved verbatim into
`tests/pages/test_tray.py`. Eight tests stayed cross-cutting in
test_ui_smoke.py — closeEvent/hide-to-tray-verification tests
(round 7's E1) that trigger a `TrayController` action along the way
(`_on_tray_open_seeker`, `_on_tray_icon_activated`,
`_on_tray_check_now`, `_on_tray_quit` from fullscreen,
`_on_application_state_changed`) but assert on MainWindow's own
`_hidden_to_tray`/`isVisible`/`_pre_fullscreen_geometry`/
`_app_state_connected`/poll-timer state, not on anything
`TrayController` owns — repointed to `window._tray.<attr>` in place.

`_on_application_state_changed` and `cleanup_before_quit` are **not**
temporary delegating stubs and were never deleted — the former is the
real QObject-bound slot `applicationStateChanged` is connected to (a
plain `TrayController` method can't hold that connection safely, per
`tray.py`'s own module docstring — Gotcha #1 from the S11-split note),
the latter owns real window-side teardown beyond hiding the tray icon.

One real internal (non-test) caller needed repointing —
`MainWindow.__init__`'s own gate on whether to connect
`applicationStateChanged` read `self._tray_icon` directly; now
`self._tray._tray_icon`.

**Real gap, worse than S11.6's own reported one:** grepping for
`window._on_tray_open_seeker(` (a call) missed
`test_application_active_is_a_near_no_op_when_already_visible`, which
referenced the identifier as a **string** —
`monkeypatch.setattr(window, "_on_tray_open_seeker", ...)`. Commit 1
(pure move) passed clean; commit 2's delegating-property deletion broke
it with a real `AttributeError`, caught by the full-suite run, not by
grep. **Grepping for `\b<name>\b` (not just `<name>(`) still isn't
enough if the identifier can appear as a bare monkeypatch string** —
grep for the plain identifier AND its quoted forms
(`"<name>"`/`'<name>'`) both, next time this pattern comes up anywhere
else in the codebase.

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` — tracked
since S2, always green in isolation. Fired twice across this session's
several full runs (consistent with S11.2–S11.6's already-elevated
reports). Someone should instrument this rather than re-reporting it.

## Read discipline — this is why sessions were costing 300–700 K tokens

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
- **Three round-8 flakes in CLAUDE.md's Open Issues, plus the
  fullscreen-close pair above (firing noticeably more often across
  S11.2–S11.7)** — diagnose any recurrence directly, never
  `pytest-rerunfailures`.
- **S12's own comment-triage pass (§10.1) now includes `ui/pages/*`
  and `ui/tray.py`/`ui/dialogs.py` for the first time** — these files
  didn't exist as separate modules before Phase 6; the brief's own
  file list for §10.1 predates the split and may need light
  reinterpretation (touch the pages named in S12/S13's own rows, not
  the pre-split `main_window.py` locations the brief still names).

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
