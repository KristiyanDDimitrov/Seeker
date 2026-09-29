# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** `e339f0d` (S5 part 1 close-out) plus this handoff commit,
  pushed. Tree clean apart from the untracked `Claude outputs/`.
- **Local pytest** (offscreen Qt, 2026-09-29):
  `1277 passed, 1 skipped, 6 warnings in 86.12s` (X9 Pro mounted;
  S4's 1268 plus 9 new).
- **`mypy --strict src/`:** clean, 106 files. **`ruff check src
  tests`:** 0 findings.
- **CI on `e339f0d`:** run `36582422863`, `success` (`1249 passed, 29 skipped`: 1277 + 1 locally = 1278 = 1249 + 29).
- **CI on `6bcb180` (S4's handoff commit): run `36580274797`,
  `failure`**: `1 failed, 1239 passed, 29 skipped`. The failure was
  `test_close_event_falls_back_to_real_close_when_no_tray`, caused by
  the carried late-worker defect (`status_label.setText` on a deleted
  `QLabel`/`QListWidget` from `_handle_task_finished`). S4's handoff
  only recorded the green run on `c98b77f`.

## 2. Where we are

Phases A and B up to S4 done. **S5 part 1 done; S5 is not ticked**
(it is marked ◐ in the plan). The row overran its ~130 K budget and
stopped at its split point. **Next: finish S5 (part 2)**, then S6.

## 3. Session report (S5 part 1)

All evidence (red output, the pinned digest, the `compose config`
acceptance output) is in HISTORY §140.
- `764c4d0` §5.1–§5.2: structural template test; required
  `SLSKD_DATA_DIR`/`SLSKD_SHARE_PATH`, no `Test` mount,
  `slskd/slskd:0.26.0`, `unless-stopped`; `bring_up_slskd`'s share path
  required; Sharing refuses with no live `/shared/music`; README manual
  command.
- `738685a` §5.5 fix: Settings keeps the live share
  (`SharingService.current_share_path`), and asks when there is no
  container.
- `e339f0d` close-out: §140, plan marked ◐, credentials caution lifted.

## 4. Key context

- **Your HISTORY entry is §141** (or extend §140 with a "part 2"
  section, which reads better): `docs/history/121-150.md` plus its
  README line.
- **S5 part 2 is three items:**
  1. §5.5 consolidation. The wizard (`ui/wizard.py` `_on_bring_up_
     clicked`, about line 559) and Settings (`_recreate_with_
     credentials`) duplicate: generate a key, mkdir the data dir,
     `ensure_slskd_web_credentials`, `bring_up_slskd`, check the
     return code. They move into one `Application` method. **Persist
     timing differs:** the wizard persists only after its health poll
     reports HEALTHY (`_persist_soulseek_config`); Settings persists
     immediately. Keep both behaviours explicit (for example, a
     `persist` flag). Sharing reuses the persisted key and credentials
     and the live `/app` dir, and never generates or persists, so it can
     share only the lower "bring up and check the return code" core.
     Record that divergence. `SLSKD_LOCAL_BASE_URL` lives in
     `ui/wizard.py`; move it to the service layer if `Application`
     needs it.
  2. §5.3 per-user Compose copy in dev.
  3. §5.4 Sharing robustness (restore both files, atomic writes, keep
     5 backups, other `shares:` shapes).
- **§5.3 data-directory trace, answered from the code:** the wizard
  and Settings **already** pass `SLSKD_DATA_DIR = slskd_data_dir()` =
  `~/Library/Application Support/Seeker/slskd-data`, which does not
  exist on Kris's machine. Sharing passes the live container's `/app`
  mount. So the repo's `./slskd-data` (728 MB `downloads/`, slskd's
  own `data/` and a `slskd.yml` sharing `/shared/music` **and
  `/shared/Test`**) is used only by a manual repo-root `docker compose
  up`. Kris's `config.json` has `slskd_download_dir =
  ./slskd-data/downloads` (CWD-relative), and the next wizard or
  Settings bring-up overwrites that with the per-user path. §5.3
  should make the data dir follow the live `/app` mount when a
  container exists, and tell Kris to move `./slskd-data` himself if
  he wants its state kept. Never move it for him (§0.7).
- **Kris has no slskd container right now** (`docker ps -a` is empty;
  image `slskd/slskd:latest` = `0.26.0` by digest). The "not
  self-managed until recreated" note in BRIEF §5.3 applies only once
  one exists. The `Test` share must be re-added through Sharing if
  still wanted.
- **Project name:** Compose names the project after the Compose file's
  directory: `seeker` from the repo, `slskd-data` from the per-user
  copy. The service has a fixed `container_name: slskd`, so a
  container created under one project conflicts on `up` under the
  other. §5.3 should add a top-level `name: seeker` to the template
  (and a structural assertion).
- **Test hazard:** any test that reaches Settings' credential update
  without faking `seeker.sharing_service._get_live_container_mounts`
  hits real `docker inspect`. With no container, a real modal
  `QInputDialog` then blocks pytest. Use `_fake_live_mounts` in
  `tests/test_settings_window.py`.
- **Carried:** three `LibraryLocationNotFoundError` classes (S13);
  `_repoint_or_clear_match` drops `confirmed_at` (S8). Never touch
  slskd or real data (BRIEF §0.7).

## 5. Decisions made

- **Both bind-mount sources are required, with no default,** not only
  the share path. A relative `./slskd-data` default inside the
  per-user copy would resolve next to that copy, which is a silent
  trap. The README's manual command passes both.
- **The consolidation was deferred** to part 2 on budget. It is a
  refactor, and it is safer to land it as its own commit against the
  now-fixed behaviour.
- **Skill divergence:** `env-secrets-manager` and `adversarial-reviewer`
  were not loaded (budget). Part 2 should run `adversarial-reviewer`
  before S5's final close-out.

## 6. Blockers

None.

## 7. Files in progress

None; part 2 starts clean (the three items in Key context).

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).

**Interim cautions:** none left. "Update SoulSeek credentials" is safe
again: it keeps the live share, and asks when slskd isn't running.

**Kris's own decision:** keep or discard the repo's `./slskd-data`
(its slskd state, 728 MB of downloads, and the `Test` share). The next
Seeker bring-up uses the per-user data dir.

**Live checks:** S41's checklist (the fresh-account wizard tests the
template).

## 9. Open questions

- CLAUDE.md items 63, 70 and 125 remain open. Which row owns the
  late-worker defect (S11 or S18)? It has failed CI twice
  (`36570098069`, `36580274797`).

---

**Read discipline (still why sessions blow their budget):** never read
a whole `docs/history/*.md` file, `main_window.py` or
`test_ui_smoke.py`; `grep -n`, then read a range. Report only pytest's
summary line plus named failures. Read only BRIEF §0 plus your row's §.

**Ending a session:** follow `SESSION-PLAN.md` → "Session protocol" →
"Ending" (HISTORY entry, commit, three numbers, tick, rewrite this file,
push, record CI).
