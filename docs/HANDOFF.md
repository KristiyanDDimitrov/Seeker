# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S38 close-out (HISTORY §192). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2 failed, 2011 passed, 1 skipped`.
  Failing: `tests/test_theme.py::test_a_cell_widget_paints_the_rows_own_background`
  `[dark]` and `[light]`, the same as S37 (see §4).
  `mypy --strict src/` clean, 138 files; `ruff check src tests tools` 0.
- **CI:** `329ebe8`'s run `37759819002` green: `1985 passed, 29
  skipped`, coverage 94.53 % (floor 92 %).

## 2. Where we are

S1–S38 ticked. **Next: S39, release engineering** (BRIEF §39). Its
§39.3 waits on Kris's bundle identifier (§8).

## 3. Session report (S38)

Evidence in HISTORY §192.
- `8b1761b` (§38.1): CLAUDE.md's 108-line layout → a link to
  `docs/architecture.md#module-map` plus a seven-line summary.
- `f60adc3` (§38.2): open issues checked against all 187 CI runs;
  the focus-search and close-event flakes closed; a Search flake and
  the Cocoa theme failure added; two Testing facts.
- `01350db` (§38.3): the roadmap forward-looking only.
- `71d6449` (§38.4): the round's rules (no history in `src/`, test
  first, real-data safety, the portable Compose template).
- `300368e` (§38.5): 53 KB → 29,794 bytes; the UI rules moved word for
  word to `src/seeker/ui/CLAUDE.md`; `wheel-exclude` for it.

## 4. Key context

- **CLAUDE.md is two files now.** The root (29.8 KB) and
  `src/seeker/ui/CLAUDE.md` (12 KB: workers, window lifecycle,
  rendering, theme, tables). Claude Code documents loading a
  subdirectory's CLAUDE.md when a session reads files there;
  UNVERIFIED in this repo, so the root says to read it before any UI
  change. A new UI fact goes there; its link text must read
  `HISTORY §N` on one line (the `src/` history grep).
- **Two functions are above radon C** (`uvx radon cc -n D -s
  src/seeker`): `dashboard_page._decide_next_step` (D, 21) and
  `sharing_service._insert_slskd_share_directory` (D, 26). The round's
  exit criterion forbids them and no row owns them: fold into S39 if
  it finishes early, or give them a row.
- **For S39: `uv build --wheel` packages whatever is in
  `src/seeker/`,** including a gitignored `_build_info_generated.py`
  left by a local DMG build. A release built from a clean checkout is
  unaffected; S38 added `wheel-exclude = ["**/CLAUDE.md"]`.
- **A new CI flake, not fixed:**
  `test_search_download_best_passes_the_already_fetched_results`
  (`37599402903`, a Dependabot PR): it waits on the fake's call list,
  then asserts a label the finish handler writes, which is §128's race
  shape. Test-first fix: delay the fake, see it fail, wait on the label.
- **The Cocoa-only theme failure:** both cases fail in the full
  suite; run alone, only `[light]` fails. First check, still
  untried: rerun with only the built-in display.
- **Three 09-29/30 CI failures were stragglers**, not their named
  tests: `RuntimeError: … already deleted` from an earlier test's
  worker. None in the 99 runs since `245adcb`. Now a Testing fact.
- Carried: `set -o pipefail` before `pytest … | tail && git commit`;
  never touch slskd or real data; the full suite takes ~4.5 min, so
  run it in the background.

## 5. Decisions made

- **The UI rules moved to a nested CLAUDE.md, not condensed
  further.** The brief asks for under 30 KB without dropping a
  standing fact. Rule-plus-link rewriting reached 37 KB. Cutting
  more would have meant dropping facts, so the UI-only ones moved
  word for word to the directory they govern.
- **The quit seam and the thread pool stay in the root:** item 125,
  an open issue, rests on them.
- **The CI check covered all 187 runs, not just the last 50** (only
  two days' worth). Closing a flake needs its last occurrence.
- **Neither new flake was fixed here.** Each is a test-first change
  of its own, outside a docs row.

## 6. Blockers

None.

## 7. Files in progress

None: S38 is committed whole.

## 8. Waiting on Kris

**Approval gates:** the S39 bundle identifier
(`io.github.kristiyanddimitrov.seeker`; `seeker.spec` still says
`com.seeker.app`), the S42 publishing commands, X1 and X2 (optional).

**A cheap veto:** the brows over "ee" in the wordmark (`9ff777b`).

**Live checks (S41 checklist):** unchanged from S37: view
`docs/architecture.md` on github.com and confirm the Mermaid state
diagram renders; everything else as carried in
`git show 1b415a4:docs/HANDOFF.md` §8. The real DB still has the
three nested locations (re-read 2026-10-08).

## 9. Open questions

- Should the two radon-D functions get their own row before S41?
- Unchanged from S36: see `git show 1b415a4:docs/HANDOFF.md` §9 (the
  Downloads first-poll header, Settings' Reachable lamp, Duplicates'
  Quality at 960, and the carried items).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".
