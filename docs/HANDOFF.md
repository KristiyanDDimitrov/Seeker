# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S36 close-out (HISTORY §190). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2013 passed, 1 skipped`, no failures.
  `mypy --strict src/` clean, 138 files; `ruff check src tests tools` 0.
- **CI:** `4e6ee27`'s run `37742497790` green.

## 2. Where we are

S1–S36 ticked. Phase K (the visual refresh) is closed. **Next: S37,
README and developer docs** (BRIEF §37). S36 already regenerated
the README's images and added Library and the wizard to its table.
S37 owns the rest of the README.

## 3. Session report (S36)

Evidence in HISTORY §190.
- `12f315d`: a secondary text that cannot show three letters before
  its "…" takes no width (test first: `assert 37 == 0` on `HEAD`).
  Downloads' Unavailable row at 960 showed a lone "…".
- `cb48b02`: copy. "Choose folder…", "Container path", and "…" in
  seven UI strings that still used "...".
- `c2bc630`: `--readme` renders the wizard's first step
  (`README_WIZARD`). Six README images regenerated, and the README's
  table now shows Library and the wizard.

## 4. Key context

- **The sweep's method:** `uv run python tools/screenshots.py` (~1
  min, 76 images in `tools/.screens/`). Reading every image costs
  ~1.5 K tokens. All dark images plus the light 1280s covered the
  row; light at 960 only repeated what dark showed.
- **`_secondary_share` now has a floor:** less room than three
  characters plus "…" means 0. A test that sets a column narrower
  than its secondary text's width under the default share now sees 0
  (one test was adjusted for exactly this; HISTORY §190).
- **macOS menu items and dialog titles stay in title case**
  ("Focus Search", "Remove Location", "Quit Anyway"). Everything
  else in Seeker's own UI is sentence case with a real "…".
- Carried: offscreen spin boxes read "90,0" (the machine's locale);
  a lamp bakes the palette in at render (a slow-poll table needs a
  repaint hook in `on_theme_changed`); `set -o pipefail` before
  `pytest … | tail && git commit`; never touch slskd or real data;
  the full suite takes ~4.5 min, so run it in the background.

## 5. Decisions made

- **Three small nits were fixed in the row. Larger ones are listed
  for a row of their own (§9), not done here**, per BRIEF §36.
- **A secondary text that cannot show a word is not drawn.** The
  hover still carries it, so nothing is lost; a lone "…" told the
  reader nothing.

## 6. Blockers

None.

## 7. Files in progress

None: S36 is committed whole.

## 8. Waiting on Kris

**Approval gates:** the S39 bundle identifier
(`io.github.kristiyanddimitrov.seeker`), the S42 publishing commands,
X1 and X2 (optional).

**A cheap veto:** the brows over "ee" in the wordmark (`9ff777b`).
The README images now show it to everyone.

**Live checks (S41 checklist):** unchanged from S35b. Settings on a
real display in both themes; Support's links; a real upload on
Sharing; S35a's and S34's look on a real display; and everything
carried in `git show cd3ba1a:docs/HANDOFF.md` §8 (fresh-account
wizard with Docker, nested-location Fix… under Settings → Library →
Fix…, the stress test, `qsvg`, Barlow and nav icons in the packaged
app, keyboard focus and VoiceOver).

## 9. Open questions

**Candidate rows from S36's sweep** (HISTORY §190 has the detail):
- On the first poll, the Downloads header says "Waiting for transfers
  to start · 0 transferring" while a row shows 66 % and
  "Calculating…". The aggregate needs two samples. Also, the harness's
  demo requests have no `id`, so the header never counts them.
- Settings → Library's Reachable column is a bare Yes/No. It should
  be a lamp (`PLAY`; `STANDBY` for an unmounted drive), which needs a
  theme-repaint hook like Sharing's `refresh_lamps`.
- Duplicates at 960 elides Quality to "MP3, …".

**Carried:**
- Refresh playlists drops the Dashboard's selection (`clear()` fires
  `currentItemChanged(None)`). This needs a test-first fix of its own.
- Settings' locations table leaves empty space under a few rows.
- History says "MP3 320kbps" where Search says "MP3, 320 kbps"
  (Review too: the stored `quality_descriptor`). A Duplicates group's
  first row is taller. The Dashboard's table does not show a Library
  selection. `poll_selected_playlist` renders a pre-switch result for
  one tick.
- `git show cd3ba1a:docs/HANDOFF.md` §9 and
  `git show 8eee663:docs/HANDOFF.md` §9 (the wizard's empty progress
  row).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".
