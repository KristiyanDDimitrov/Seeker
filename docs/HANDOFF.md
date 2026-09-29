# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** `a8e7c0d` (round 11 S3 close-out) plus this handoff commit,
  pushed. Tree clean apart from the untracked `Claude outputs/` (left
  as is: Kris's answer to §1.6).
- **Local pytest** (offscreen Qt, 2026-09-29):
  `1245 passed, 1 skipped, 6 warnings in 113.01s` (X9 Pro mounted;
  S2's 1232 plus 13 new).
- **`mypy --strict src/`:** clean, 105 files. **`ruff check src
  tests`:** 0 findings.
- **CI on `a8e7c0d`:** run `36572807959`, `success` (`1217 passed, 29 skipped`).
- **CI on S2's handoff commit `c0bcfe6`:** run `36570098069`,
  **`failure`** (`1203 passed, 29 skipped, 1 error`). S2's handoff never
  recorded it. See §4.

## 2. Where we are

Phase A done (S1, S2); Phase B started: **S3 done. Next row: S4**
(library integrity: limbo matches and location removal, BRIEF §4).
Then S5.

## 3. Session report (S3)

All evidence is in HISTORY §138 (red output, probe re-runs, numbers).
- `33a0c03` §3.3 refactor: `resolve_collision` lifted into
  `seeker/file_placement.py`, unchanged.
- `d2b7452` §3.2: `_locate_completed_file`, which checks the remote
  parent folder first, then the whole tree, by exact size, and never
  guesses. Five existing tests had seeded sizes that did not match
  their fixtures, now fixed.
- `f746d3f` §3.3: settled downloads go through `resolve_collision`.
- `c0713b9` §3.4 refactor: `_settle_target` / `_place_without_overwrite`.
- `18fb626` §3.4: same-path upgrade = atomic swap; otherwise row then
  file, behind a `same_file` guard.
- `a8e7c0d` close-out: §138, row ticked, the Replace caution lifted,
  §1.6 answer recorded, CLAUDE.md standing fact plus layout line.

## 4. Key context

- **Your HISTORY entry is §139: append it to `docs/history/121-150.md`**
  with `<a name="139"></a>` directly above `### 139 — …`, then its line
  at the end of `docs/history/README.md`.
- **The round-10 CI `SETUP ERROR` recurred** (run `36570098069`, a
  docs-only commit, so not caused by code). At setup of
  `tests/pages/test_library_page.py::test_picking_a_playlist_in_library_updates_shared_selection_and_dashboard`,
  a *previous* test's Dashboard worker finished late:
  `workers.py:460 _handle_task_finished` → `dashboard_page.py:720
  _render_track_statuses` → `track_table.setRowCount(0)` on a deleted
  `QTableWidget`, then the error path's `status_label.setText` on a
  deleted `QLabel`. `_handle_task_finished` has no guard for widgets
  deleted while a worker is in flight. This is a real test-isolation
  (and possibly shutdown) defect. S18 (test infrastructure) or S11
  (errors) should own it; S38 decides the Open-issues entry.
- **`tests/test_download_placement.py`** holds a `make_scenario()`
  helper: location `Lib`, playlist `p1` → (`Lib`, `"P"`), track `t1`,
  empty slskd dir. It is a cheap base for S4's limbo/removal tests.
- **`download_requests.size` now gates location.** A test that seeds a
  request over a fixture file must make `size` equal the file's bytes
  (or `None`), or the file is correctly refused.
- **`local_files.clear_content_derived_fields()`** exists: use it
  whenever a row's file content changes under the same path.
- **slskd naming is confirmed in its source** (`FileService.MoveFile`,
  slskd `7beef07`): `<stem>_<UtcNow.Ticks><suffix>` on a clash. Current
  slskd `master` makes the download subdirectory configurable, so never
  rely on the remote parent folder alone.
- **Pytest's skip count depends on the X9 Pro being mounted** (1 skip
  mounted, 29 unmounted). Compare totals.
- **Still true from the audit:** A-03 (Compose template, release
  blocker) and A-54 (privacy) are S5's. A stale
  `_build_info_generated.py` makes dev runs claim build `d38d80f` until
  S39. Never start, stop or recreate Kris's slskd container, and never
  write real data (BRIEF §0.7).

## 5. Decisions made

- **A new test file rather than growing `test_download_service.py`**
  (3,890 lines): the five invariants read as one unit, and S18 is
  splitting test files anyway.
- **"Logged once" is per request id per process** (an in-memory set on
  `DownloadService`); later polls log at DEBUG. Persisting it would
  need a schema change for no user-visible gain.
- **A size mismatch is refused, not tolerated.** If a peer's real file
  differs from its advertised size, the download stays `downloading`
  with one WARNING. §X1 is where such leftovers surface.
- **The same-path swap clears BPM, key, fingerprint and `tagged_at`**:
  `upsert()` preserves them by design, and they described the old audio.
- **Skill divergence:** `focused-fix` and `tdd` were not loaded. The
  brief specified the invariants and the tests, and red-then-green was
  followed by hand (red output in §138).

## 6. Blockers

None for S4.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).
§1.6 is answered (leave `Claude outputs/`).

**Interim caution until its fix lands:** no Settings → **Update
SoulSeek credentials** until S5. (The Review Replace + Delete old
caution is lifted: fixed in S3.)

**Live checks:** consolidated into S41's checklist (details in
`SESSION-PLAN.md` → "Waiting on Kris").

## 9. Open questions

- CLAUDE.md open items 63 (retry storm), 70 (stress hang; S22 has a
  lead: the 2-second poll deserialises 32.6 MB of fingerprints) and 125
  (quit hang) remain open.
- The late-worker `SETUP ERROR` above: which row fixes it (S11 or S18),
  and whether production can hit the same path on window close.

---

**Read discipline (still why sessions blow their budget):** never read
a whole `docs/history/*.md` file, `main_window.py` or
`test_ui_smoke.py`; `grep -n`, then read a range. Report only pytest's
summary line plus named failures. Read only BRIEF §0 plus your row's §.

**Ending a session:** follow `SESSION-PLAN.md` → "Session protocol" →
"Ending" (HISTORY entry, commit, three numbers, tick, rewrite this file,
push, record CI).
