# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S8 close-out (HISTORY §200). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `6 failed, 2080 passed, 1 skipped` (+17
  tests). Failing: the six pre-existing
  `test_theme.py::test_selected_text_reads_on_a_selection_that_stands_off_the_field`
  cases. S8's earlier full run failed the old pair instead (below).
  `mypy --strict src/` clean, 138 files; `ruff check src tests tools` 0.
- **CI:** `385ac92`'s run `37929658913` green: `check` `2058 passed,
  29 skipped`, coverage 94.55 % (floor 92 %); `audit`, no known
  vulnerabilities.

## 2. Where we are

**Round 12 S8 is done.** Every AUDIT finding S8 owned is fixed
(S-05, S-06, S-07, S-12) or accepted in writing (S-03 a+b, S-09,
S-10, S-11), in AUDIT.md and in CLAUDE.md → "Accepted risks".
**Next: S9**, code health: the two radon-D functions
(`dashboard_page._decide_next_step`, `sharing_service.
_insert_slskd_share_directory`) and the flip-flopping theme failures.

## 3. Session report (S8)

- `e3c0154` S-05: `create_callback_server(expected_state, …)`; a
  wrong-state `/callback` gets a 400 and the wait goes on; `_authorize`
  checks state before `error`.
- `17b67c0` S-07: `files/atomic.py::make_private_dir()` (0700) for
  the data, log and album-art cache dirs. `ccb02d2`: a refused
  `chmod` is logged, not raised (review fix).
- `7123da0` S-12: the RichLabel-escaping sweep; every sweep scans
  `main_ui.py`. The red was shown by planting, since the change is
  test-only.
- `a4baed4` S-06: `files/naming.py::clean_peer_filename()` at
  placement. `24f13da` splits the stem and extension first (review
  fix: `.mp3` became `_mp3`). `63b2c75`: naming.py's APFS comment.
- The close-out: AUDIT statuses, CLAUDE.md "Accepted risks", the
  advisories tracked in `docs/packaging.md`, HISTORY §200, the plan
  tick and this file.

## 4. Key context

- **Observed: APFS limits a name to 255 characters, not bytes** (it
  took a 504-byte name of "é"). ext4's 255 bytes is the binding limit.
- **The local failure set flips between full runs.** S8's first run
  failed the old two (`test_a_cell_widget_paints_the_rows_own_background`
  `[dark|light]`) and passed S7's six selection cases. The last run
  failed the six. S8 touched no theme code, so this is not S8's doing. S9 owns it. The lead is still
  UNVERIFIED: the window's active state (QPalette Active vs Inactive).
- **Left as notes by the review:** the callback handler has no socket
  timeout, so a silent local connection blocks the wait past its
  deadline and past Cancel (pre-existing). `_is_fixed_text` trusts
  any UPPER_CASE attribute.
- **Carried:** Sharing's 20 s per-row rebuild (S15); `uv build
  --wheel` picks up a gitignored `_build_info_generated.py` (S16).
  Set `set -o pipefail` before `pytest … | tail && git commit`. Never
  touch slskd or real data.

## 5. Decisions made

- **Kris, 2026-10-09** (unchanged): S-06 sanitize; S-03 accept +
  track, no extension check; S-09 accept for all hosts.
- The S-07 helper also covers the album-art cache dir: the same
  exposure and one line, beyond the finding's letter.
- **Skills:** `tdd` was loaded. Its "confirm seams with the user" step
  was taken as met by AUDIT's "Test first" lines, which Kris
  approved. That is a divergence, recorded here. `adversarial-reviewer`
  ran and found two warnings, both fixed. `env-secrets-manager` was
  not needed.

## 6. Blockers

None for S9.

## 7. Files in progress

None: S8 is committed whole.

## 8. Waiting on Kris

- **S-04:** the GPL wording for the DMG (S16).
- **Visible from S8:** a downloaded file whose peer name has `:`, `?`
  or `|` now lands with `-` in their place, and one named with a
  leading dot lands with `_`.
- **Still open from S1–S7:** the live checks of §193–§196, the S5
  wording veto, the wordmark's brows (`9ff777b`), BRIEF §17, and
  `git show 1b415a4:docs/HANDOFF.md` §8. The real DB still has the
  three nested locations.

## 9. Open questions

- Does slskd 0.26.0 share anything by default on a fresh container?
  (AUDIT §8, UNVERIFIED; it needs a throwaway container.)
- Does Dependabot's `docker-compose` ecosystem bump a `tag@digest`
  line as a pair? The first PR will show.
- Should the callback handler get a socket timeout (the review's
  pre-existing note)? It is small, but no row owns it.
- Unchanged from S36: `git show 1b415a4:docs/HANDOFF.md` §9.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".
