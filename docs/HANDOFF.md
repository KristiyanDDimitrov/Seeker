# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `5175429`, pushed. Tree clean (aside from an untracked
  `Claude outputs/` directory that predates this session — not part of
  the repo, left alone).
- **Local pytest (offscreen Qt, this machine, Darwin 25.6.0): `1191
  passed, 29 skipped`, run twice.** Both runs reproduced the same
  already-tracked order-dependent pair
  (`test_reopening_after_a_fullscreen_close_restores_prior_geometry`,
  `test_fullscreen_close_policy_check_ignores_a_stale_request`) —
  confirmed pre-existing via `git stash -u`: both pass clean on
  unmodified `HEAD` too.
- **`mypy --strict src/`: clean, 104 files. `ruff check src tests`: 0
  findings.**
- **CI on `5175429` (this session's push): run `34862342815`,
  `failure`.** ruff/mypy both clean on the run log. The failure is the
  OTHER already-tracked CI-only flake pair
  (`test_history_refresh_button_refetches`,
  `test_review_tab_replace_button_calls_apply_upgrade_decision_with_
  delete_flag`) — the same pair that failed on S7/S8/S9's own CI runs
  (`34840265764`, `34857398720`, `34859570733`) — not new, not this
  session's diff (this session never touched `history_page.py`,
  `review_page.py`, or `workers.py`).

## Where we are in the plan

**Round 10 is scheduled — start at S1.** Brief:
`docs/BRIEF-2026-09-23-round10.md`. Session map:
`docs/round10/SESSION-PLAN.md`. Round 9 (S1-S10) is complete.

- The design chat wrote the round-10 brief, session plan, and this
  section on 2026-09-23 without committing them. **S1's first commit
  is those three files.**
- Where round 10 came from: Kris's hand-testing after round 9. Review
  Confirm silently fails (with a moving cell highlight), the window
  reopens at default size after a fullscreen close, and the stress
  test fails with `'MainWindow' object has no attribute
  'playlist_list'`. Investigating those also produced concrete causes
  for both CI-only flakes and the fullscreen-close test pair. All are
  in the brief.
- **HEAD at time of writing: `d38d80f`** (not `5175429` as the Current
  state section above says; `d38d80f` is the S10 close-out on top of it).

## S10 report — §7.2, the Library context header + inline picker

- `library_page.py`: a new persistent header (`theme.make_card`) above
  the tagging controls. Populated state: `"Acting on '<name>' — N
  tracks in this playlist."` (badge="muted") plus a "Change playlist"
  toggle button. Empty state (`help_text.LIBRARY_NO_PLAYLIST_TEXT`,
  badge="warn"): the button hides and the picker — a `QListWidget`
  sourced from `sync_service.list_playlists` the same way Dashboard's
  own `playlist_list` is — is forced open instead of just naming the
  problem. Picking an item (`itemClicked`/`itemActivated`) writes
  `PlaylistSelection.set_playlist()` and collapses the picker
  explicitly (needed for the picking-the-already-selected-playlist
  no-op case, where `changed` never fires).
- **Library is now a second writer of `PlaylistSelection`, not just a
  reader** — this is the part that touched `dashboard_page.py` too.
  Before this session Dashboard never subscribed to `changed` at all
  (it only ever wrote, then rendered explicitly right after); a write
  originating from Library's picker needs Dashboard to actually listen.
  Added `_on_shared_selection_changed` (connected to `changed`) ->
  `_sync_playlist_list_highlight()` (blockSignals + `setCurrentItem`/
  `setCurrentRow(-1)`, never a bare unblocked one — avoids a redundant
  re-entrant `_on_playlist_selected` round-trip) + `_poll_
  selected_playlist()` + `_poll_next_step()`.
- **Real segfault found and fixed, not just theorized:** the
  reconciliation above, called synchronously, crashed when `changed`
  fired from *inside* `track_table`'s own `itemSelectionChanged`
  handler (`_on_track_selection_changed` writes `track_ids` there,
  round9 §7.1) — a synchronous `_poll_selected_playlist()` re-entrantly
  clearing that same table's row count, from inside its own selection-
  changed signal's emission, is a real SIGSEGV, reproduced locally via
  `tests/pages/test_library_page.py::
  test_force_retag_checkbox_passed_through_all_three_triggers`. Fixed
  by deferring the reconciliation via `QTimer.singleShot(0, ...)` —
  this codebase's own established pattern for exactly this
  (`ui/workers.py`'s deferred native delete cites the same idiom).
  Worth remembering if any *other* future write to a shared page-level
  Qt signal ever gets connected from inside a widget's own
  selection/data-changed handler.
- `theme.set_variant`'s unpolish/polish-repaint logic generalized into
  `theme.set_dynamic_property(widget, name, value)` (the header's
  warn/muted badge switch needed the identical pattern set_variant
  already had, just for a different property name) — `set_variant` is
  now a one-line wrapper over it; no call site needed to change.
- `help_text.py`: `LIBRARY_TAB_SUBTITLE` reworded (no longer claims
  Library only reads Dashboard's selection); added
  `TOOLTIP_CHANGE_LIBRARY_PLAYLIST` and `LIBRARY_NO_PLAYLIST_TEXT`.
- Tests: 4 new in `tests/pages/test_library_page.py` (empty-state
  offers the picker, populated-state names playlist+count, "Change
  playlist" reveals a picker populated from the fake sync service,
  picking updates both the shared selection and Dashboard's own
  highlight/track table) + 1 new in `tests/pages/test_dashboard_page.py`
  (`test_dashboard_reflects_a_selection_write_that_originates_
  elsewhere` — writes `window.playlist_selection.set_playlist(...)`
  directly, simulating Library's picker, and asserts Dashboard's
  `playlist_list` highlight and `dashboard_service` call follow it).
- **Divergence from the session map's skill guidance, recorded per its
  own instruction:** the session map pointed §7.2 at `product-skills`
  for "dialog copy, settings placement... the Library context header
  and empty state." Invoked `product-skills:cs-product` with the exact
  design brief; it routed to a generic product-team router (RICE/WSJF
  scoring, participant counts, OST linting, canon citations) built for
  discovery/roadmap work, not a single small UI copy/layout decision —
  clearly the wrong tool for this task's shape. Made the header/picker/
  empty-state design call directly instead, grounded in this
  codebase's own established Qt/copy conventions (existing badge
  styles, `InlineNotice` warning tone, Dashboard's own playlist-list
  pattern) rather than forcing the mismatched skill. A future session
  routing a *real* discovery/prioritization question through
  `product-skills` should expect the heavier framework — it's likely
  right for that shape of question, just not this one.

## Read discipline — unchanged, still why sessions blow their budget

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief section your row doesn't point at.

## Waiting on Kris

See `docs/round9/SESSION-PLAN.md`'s own "Waiting on Kris" section —
unchanged by this session. Still carried, unaddressed: click through
the Review page's splitter (S8) on a real display; the Library context
header/picker (this session) on a real display, both themes; no
automated screenshot exists for either.

## Open questions

- Item 125 (the §2.3 quit hang), the fullscreen-close pair (S4/S5's own
  area), and the CI-only flake pair (history-refresh/replace-button)
  are all unchanged — this session's own local and CI runs reproduced
  them again, nothing newly fired. Tracked in CLAUDE.md's Open issues;
  not re-litigated here.
- `docs/HISTORY.md` is still ~890 KB, never read whole. No HISTORY
  entry written yet for §3.2 (S7), §6 (S8), §7.1 (S9), or §7.2 (this
  session) — §8.2 (splitting HISTORY.md) is exactly the kind of thing
  this backlog is an argument for, but still needs Kris's yes first.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round9/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
5. If you pushed: record the CI run id and result here too.
