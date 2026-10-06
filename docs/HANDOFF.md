# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S28 part-1 close-out commit, after `17226bd`
  (§28.2). Tree clean apart from the untracked `Claude outputs/`.
- **Local** (at `17226bd`): pytest `1761 passed, 29 skipped`;
  `mypy --strict src/` clean, 132 files; `ruff check src tests tools`
  0.
- **CI:** see the close-out commit's run (recorded in the final
  message of the session that pushed it; `gh run list -L 1`).

## 2. Where we are

S1–S27 ticked; S28 part 1 (§28.1–§28.2) done, stopped at the row's
split point on budget. **Next: S28 part 2** (BRIEF §28.3 empty states,
§28.4 copy pass), then tick S28.

## 3. Session report (S28 part 1)

Evidence in HISTORY §176.
- `2efcf6a` §28.1: `ColumnLayout` policy (`theme.fit_widths`, viewport
  refit filter, left headers); Downloads/History/uploads on
  `ColumnLayout`; Duplicates' Format+Bitrate → Quality. Sweep on HEAD:
  Dashboard Track 40 px + sideways scroll, Search Filename 94, etc.
- `17226bd` §28.2: `ui/elided_text.py` (one-line cells, tooltip only
  when elided, `ColumnLayout.paths` elide in the middle);
  `elide_list_items` on the three playlist lists. HEAD: list item
  486 px in a 235 px viewport.

## 4. Key context

- **Harness for every UI row:** `uv run python tools/screenshots.py
  --page review --theme light` (seconds). Tests walk it through the
  `screenshots` fixture (`test_table_columns.py`, `test_button_sizing.py`).
- **For §28.3:** Sharing's uploads table fakes an empty state with a
  4-column `setSpan` row (`help_text.NO_UPLOADS_LABEL`, plus a
  `clearSpans()` guard against HISTORY §73). The shared component
  should replace it, not sit beside it. The Dashboard already has
  `track_empty_label`, worth reading as the existing pattern. History's
  "No downloaded or tagged tracks yet." sits on its `status_label`,
  which the feedback-channel rule says is ephemeral.
- **For §28.4:** dropping Downloads' Role column means editing
  `_DOWNLOADS_COLUMNS` (`fit_content=(1, 2, 3, 4)`) and the column
  indices in `_render_active_downloads`. The Track column should carry
  the "Upgrade" badge. The notice's "X" has `accessibleName("Dismiss")`,
  so keep a name on any replacement (the keyboard-access sweep fails
  otherwise). Search's "Download this one" is the widest per-row
  button; Sharing's header "Container Path" is jargon.
- **Testing a tooltip:** send a `QHelpEvent(ToolTip)` to the viewport
  and read `QToolTip.text()`. `plain_tooltip` wraps the text in `<p>`,
  so assert containment (`test_elided_text.py`'s `_tooltip_at`).
- **Duplicates at 960 is over-full** (every fit column at its header
  floor, "MP3, …"). The fix is a stacked group Actions cell, but a
  two-row span is ~76 px against ~92 px needed. That's for S35a.
- **For S31:** a palette change must update the chevron SVGs; white on
  dark's ACCENT is 4.35:1 (palette test floor 4.3).
- Carried: `MainWindow` does not apply the theme, `main_ui.py` does;
  radon not in the env; never touch slskd or real data; zsh does not
  word-split `$var`; reproduce CI-only UI failures with
  `QT_QPA_PLATFORM=offscreen` first; a shared fake missing a method
  stalls the suite (§171).

## 5. Decisions made

- **Cells elide, never wrap.** It's consistent across themes, where
  Review's Track had wrapped in one theme and elided in the other, and
  it keeps rows dense. The full text is one hover away.
- **Paths elide in the middle**, so the filename ending stays visible.
- **A stretch column reserves up to 40 % for its content**, so a long
  secondary column (a failure reason) never starves Track.
- **Duplicates: Format + Bitrate → one Quality column**, in Review's
  vocabulary, instead of dropping the Group or Location column.
- **Dialogs' path lists keep their sideways scrollbar:** a delete
  confirmation should show the whole path.
- **Standing rule promoted to CLAUDE.md:** every table declares a
  `ColumnLayout`; cells are one line (Qt section).

## 6. Blockers

None.

## 7. Files in progress

None committed half-done. §28.3–§28.4 not started.

## 8. Waiting on Kris

**Approval gates:** S30 visual direction; S39 bundle identifier;
S42 publishing commands; X1 and X2 (optional).

**Live checks (S41 checklist):** the nested-location Fix… with the X9
Pro mounted (keep `Music`, compare §172's counts); the stress test;
the packaged app's combo chevron; keyboard focus and VoiceOver on a
real Mac; hover tooltips on elided cells (new); the carried list in
`git show 5db1162:docs/HANDOFF.md`.

## 9. Open questions

- Carried unchanged: the Spotify wait not cancelled on close; the
  late-worker button defect (§148); Settings and Duplicates results on
  status labels (S28 part 2/S29); four CLI items (§156); the unrecorded
  transfer id and leftover `.tmp` files (X1); why a shared fake's
  missing method stalls the suite (§171, UNVERIFIED); a location whose
  stored path differs in case from disk maps no files in a merge;
  should item views get a themed focus indicator (§175).
- New: the Dashboard's Status links ("Needs review (…") are cell-widget
  labels, so they clip rather than elide with a tooltip. Fold them into
  §28.4 or S34?

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".
