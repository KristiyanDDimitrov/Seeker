# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S35a close-out (HISTORY §186). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `1987 passed, 1 skipped` (+8). `mypy --strict src/` clean,
  137 files; `ruff check src tests tools` 0.
- **CI:** `070bde8`'s run `37674156397` green.

## 2. Where we are

S1–S35a ticked. **Next: S35b** (BRIEF §35, second bullet): Review,
Sharing, Help and Support, Settings.

## 3. Session report (S35a)

Evidence in HISTORY §186.
- `7b8c10b`: Search — one query row (Return searches), file name
  first, Quality column, Locked pill; outcomes and errors on a notice.
- `fcb9956`: Downloads — status lamps, reasons/percentages as
  secondary text, the amber meter only for a transfer
  (`theme.set_busy_meter`), aligned bars.
- `0935911`: History — playlist as secondary text; refresh errors on a
  notice.
- `de1a0a5`: removes `TwoToneProgressBar` and
  `style_determinate_progress_bar` (no user left).
- `fa4c1a6`: Duplicates — outcomes and errors on a notice.
- `3574e56`: Duplicates — Keep first, Similarity spanned, `BAND_ROLE`
  group bands, Resolve all above the table; harness shows 3 groups.

## 4. Key context

- **Channel fix recipe** (used on all four pages): an `InlineNotice` at
  the top of the page's content, `FeedbackTarget(status_label,
  notice)`, `show_outcome`/`show_error` for results, and
  `on_error=self.feedback.show_error` on every worker (run_worker's
  default puts the error on the label, which the next run wipes).
  Settings (`settings_window.py` ~:577–1161) and the wizard's Spotify
  and Library steps still put results on labels: S35b.
- **An empty status label on its own line is a blank band** under the
  subtitle; put it in an existing row of controls (Downloads, History,
  Duplicates do).
- **`elided_text.BAND_ROLE`** bands a cell with AlternateBase at paint
  time; a cell under a cell widget needs an item carrying it.
- **A busy bar's still frame looks full**: next to a meter it reads as
  done. In a table, show one only for a started transfer, in amber
  (`set_busy_meter`); the activity strip keeps the accent.
- **`wrap_progress_bar` now ends in a stretch**, so fixed-width bars
  sit at the cell's left with or without a label.
- **`run_busy_worker` has no double-start guard**; a second trigger
  that bypasses the disabled button (Return in a field) must check
  `busy_actions.is_running(key)` itself.
- The harness's Duplicates screen now has three groups: S36's
  `duplicates.png` README image will change.
- Carried: `set -o pipefail` before `pytest … | tail && git commit`;
  never touch slskd or real data; zsh does not word-split `$var`;
  judge fine detail on a 2× Cocoa grab; the full suite takes ~4 min,
  so run it in the background; split a mixed `tests/fakes.py` diff
  per commit by hunk (`git apply --cached` on a filtered patch).

## 5. Decisions made

- **Search keeps visible "Artist"/"Title" captions** (buddied
  `PlainLabel`s) rather than placeholders alone: a filled field would
  otherwise lose its label.
- **Downloads' locked row reads "Retrying"**, the Dashboard's word,
  with "File locked by the peer" beside it.
- **No bar for queued or finished downloads**: the lamp says it; a bar
  added nothing but a second, misleading signal.
- **The Duplicates Group number column is gone**: bands and spans say
  where a group ends. Promoted to CLAUDE.md with `BAND_ROLE`.
- **No lamps on History**: a lamp is a current state; History is a
  record of past events.

## 6. Blockers

None.

## 7. Files in progress

None: S35a is committed whole.

## 8. Waiting on Kris

**Approval gates:** the S39 bundle identifier
(`io.github.kristiyanddimitrov.seeker`), the S42 publishing commands,
X1 and X2 (optional).

**A cheap veto:** the brows over "ee" in the wordmark (`9ff777b`).

**Live checks (S41 checklist):** the Downloads lamps, meter and busy
bar on a real display in both themes, and whether the dark Duplicates
band is visible enough on a real screen (subtle by design: #282C31 on
#1E2125); plus S34's (Library's Cover art column against real files,
the first scan's extra time on the X9 Pro, the Dashboard's lamps and
meter, the playlist counts) and everything carried in
`git show cd3ba1a:docs/HANDOFF.md` §8 (fresh-account wizard with
Docker, nested-location Fix…, the stress test, `qsvg` and Barlow and
nav icons in the packaged app, keyboard focus and VoiceOver).

## 9. Open questions

- At 960 a Downloads failure reason elides to a few characters (full
  text on hover); a Duplicates group's first row is taller than the
  rest; History's Detail says "MP3 320kbps", Search and Duplicates
  "MP3, 320 kbps".
- **Refresh playlists drops the Dashboard's selection** (pre-existing:
  `_populate_playlists`' `clear()` fires `currentItemChanged(None)`).
  Take it in S35b or as its own test-first fix.
- The Dashboard's table does not show a selection made on Library;
  Library's context sentence could shrink.
- `poll_selected_playlist` renders a pre-switch result for one tick
  (pre-existing, self-correcting).
- Carried unchanged: `git show cd3ba1a:docs/HANDOFF.md` §9 and
  `git show 8eee663:docs/HANDOFF.md` §9 (Review's column budget at 960
  for S35b, Settings' subtitle wrap, the wizard's empty progress row).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".
