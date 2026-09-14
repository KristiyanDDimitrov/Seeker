# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `873eb4f`, pushed. Tree clean (aside from an untracked
  `Claude outputs/` directory that predates this session — not part of
  the repo, left alone).
- **Local pytest (offscreen Qt, this machine, Darwin 25.6.0): first
  full-suite run `1188 passed, 29 skipped`** (the fullscreen-close pair
  didn't fire); **a second immediate run reproduced exactly the
  documented pair, `1186 passed, 2 failed, 29 skipped`**
  (`test_reopening_after_a_fullscreen_close_restores_prior_geometry`,
  `test_fullscreen_close_policy_check_ignores_a_stale_request`) — same
  order-dependent flake CLAUDE.md's Open issues already tracks, not a
  regression from this session's diff.
- **`mypy --strict src/`: clean, 104 files. `ruff check src tests`: 0
  findings.**
- **CI on `873eb4f` (this session's push): run `34859570733`,
  `failure`.** ruff clean (confirmed from the run log). The failure is
  the OTHER already-tracked CI-only flake pair
  (`test_history_refresh_button_refetches`,
  `test_review_tab_replace_button_calls_apply_upgrade_decision_with_
  delete_flag`) — the same pair that failed on S7's and S8's own CI
  runs (`34840265764`, `34857398720`), not new, not this session's
  diff (this session never touched `history_page.py`, `review_page.py`,
  or `workers.py`).

## Where we are in the plan

Round 9. Full plan: `docs/BRIEF-2026-09-09-round9.md`. Session map:
`docs/round9/SESSION-PLAN.md` — **read that, not the full ~40 KB
brief.**

- **Done: S1-S9.**
- **Next: S10** — Library page, the context header + inline picker
  (§7.2), built on S9's seam. Split point named in the session map:
  after the header lands; the picker can stand alone.

## S9 report — §7.1, lift the selection into a shared seam

**Pure refactor, no visible change — verified: `git diff --stat` below
touches only `ui/` plumbing, no page's rendered output.**

- New `src/seeker/ui/playlist_selection.py`: `PlaylistSelection`, a
  `QObject` with a `changed` signal, owned by `MainWindow` (`self.
  playlist_selection`, constructed next to `busy_actions`) and exposed
  to every page as `PageContext.playlist_selection`. Holds `playlist`
  and `track_ids`, each settable via `set_playlist()`/`set_track_ids()`
  (no-op, no signal, if the new value equals the old).
- `DashboardPage.selected_playlist` is now a property proxying to
  `self._context.playlist_selection.playlist` (getter) and `.
  set_playlist()` (setter, kept so existing external/test assignment —
  `window._dashboard_page.selected_playlist = ...` — still works
  unchanged). `_on_playlist_selected` writes into the shared object
  directly. A new `track_table.itemSelectionChanged` connection
  (`_on_track_selection_changed`) pushes `_selected_track_ids()` into
  `playlist_selection.set_track_ids()` on every selection change —
  this is the one genuinely new piece of wiring (previously nothing
  observed track-table selection changes at all; track ids were only
  ever pulled on demand at click time). Invisible to the user: nothing
  renders from it yet.
- `LibraryHost`/`TaggingPanelHost` lost their
  `get_selected_playlist`/`get_selected_track_ids` callable fields
  entirely — `TaggingPanel` (the only real consumer, 5 call sites) now
  reads `self._context.playlist_selection.playlist`/`.track_ids`
  directly, since it already holds a `PageContext`. Both Host
  dataclasses keep `refresh_track_table` unchanged — that's an action,
  not selection state, and stayed out of this row's scope per the
  brief.
- `main_window.py`'s `LibraryHost(...)` construction no longer reaches
  `self._dashboard_page.selected_playlist`/`._selected_track_ids` (a
  private-method reach) at all for those two fields — just
  `refresh_track_table=self._dashboard_page._poll_selected_playlist`,
  same private-method reach as before, unchanged (out of scope, see
  above).
- One test needed updating for the property becoming settable-only-
  via-setter rather than a plain attribute:
  `test_backend_poll_refreshes_selected_playlist_track_table`
  (`tests/test_ui_smoke.py`) assigns `window._dashboard_page.
  selected_playlist = Playlist(...)` directly — this now routes through
  the setter transparently, no test edit needed once the setter was
  added (see above); flagged here only because it's exactly the kind of
  silent test dependency a "pure refactor" row can trip over.

## Read discipline — unchanged, still why sessions blow their budget

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief section your row doesn't point at.

## Waiting on Kris

See `docs/round9/SESSION-PLAN.md`'s own "Waiting on Kris" section —
unchanged by this session. Still carried, unaddressed: click through
the Review page's splitter (S8) on a real display; no automated test
covers its persist/restore round-trip either.

## Open questions

- **§7.2 (S10) needs a product-skills design pass for the header/picker
  copy and layout** — the brief gives requirements, not the visual
  design; session map says to reach for `product-skills`.
- **S9 added one new live signal connection**
  (`track_table.itemSelectionChanged` -> `PlaylistSelection.
  set_track_ids`) that didn't exist before — invisible today since
  nothing renders from `track_ids` yet, but S10 is the first page that
  will, so this is the connection to check first if per-track selection
  ever reads stale in Library.
- Item 125 (the §2.3 quit hang), the two S4 flakes (fullscreen-close
  pair), and the CI-only flake pair (history-refresh/replace-button)
  are all unchanged — this session's own local and CI runs reproduced
  them again, nothing newly fired. Tracked in CLAUDE.md's Open issues;
  not re-litigated here.
- `docs/HISTORY.md` is now ~890 KB — still never read whole. No
  HISTORY entry written yet for §3.2 (S7), §6 (S8), or §7.1 (this
  session) — worth a combined two-tier docs pass if a future session
  has budget (Working agreement #1).

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round9/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
5. If you pushed: record the CI run id and result here too.
