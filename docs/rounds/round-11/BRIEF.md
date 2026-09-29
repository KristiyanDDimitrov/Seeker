# Round 11 — the final polish round

**Author:** audit and design chat, 2026-09-29. **Executor:** Claude Code.
**Base commit:** `378646a` (round 10 S7 close-out; tree clean apart from
the untracked `Claude outputs/`). **Session map:**
`docs/rounds/round-11/SESSION-PLAN.md`. **Audit summary:**
`docs/rounds/round-11/AUDIT.md` (finding IDs `A-NN` below refer to it).

Read your row in the session map, then **only** §0 and the §sections that
row points at. Do not read this file whole. Every line number below is a
hint from `378646a`; `grep -n` the named symbol before trusting it.

Each section states what is **established** (reproduced, measured or read
in code, with the evidence) and what is still a **hypothesis** (your job
to confirm or kill before building on it).

---

## §0 — Ground rules

**§0.1 Read discipline (unchanged).** Never read `docs/HISTORY.md` (or,
after S2, a whole `docs/history/*.md` file), `src/seeker/ui/main_window.py`
or `tests/test_ui_smoke.py` whole. `grep -n` the symbol or section, read
that range. `pytest -q` output: summary line plus named failures.
`git diff --stat` by default.

**§0.2 Approval gates.** Items tagged **[ASK KRIS]** need an explicit yes
in the conversation before any work on them starts. Everything untagged
is pre-approved. Kris answered four questions on 2026-09-29: schedule the
v0.1.0 release, the automatic update check, the HISTORY split and the
nested-location guard; do a consistency pass **plus** a visual refresh;
archive round documents under `docs/rounds/`; keep the Windows and Linux
packaging, clearly labelled as unverified.

**§0.3 One commit per numbered item.** A refactor commit contains no
behaviour change; a behaviour commit contains no refactor.

**§0.4 Failing test first** for every bug fix. The test must fail on
unmodified `HEAD` for the stated reason. Paste the failure, then the same
test passing, into your report. Appendix A has each confirmed probe
verbatim, ready to turn into a test.

**§0.5 The three numbers** (`uv run pytest -q`, `uv run mypy --strict
src/`, `uv run ruff check src tests`) are quoted at every session end,
plus the CI run id and result whenever you push.

**§0.6 Every row writes its own HISTORY entry** before its close-out
commit. S1 appends to `docs/HISTORY.md` as usual (§136). From S2 on,
append to the last file under `docs/history/` and add the entry's line to
`docs/history/README.md` (§2 defines both). Entries continue the global
numbering (§137, §138, …).

**§0.7 Real-data safety (new).** No session writes to Kris's real
database, `config.json`, Spotify token, music files or slskd state.
- Read-only inspection is allowed: `sqlite3 -readonly
  "$HOME/Library/Application Support/Seeker/seeker.db" "…"`.
- Anything that migrates data (§4.3, §6.3, §8, §26) is rehearsed on a
  **copy** of the database in your scratchpad, and you paste the before
  and after counts.
- The real migration happens only when Kris next launches the app.
- Never start, stop or recreate Kris's slskd container. `docker inspect`
  and `docker compose … config` are fine; `docker compose up` is not.

**§0.8 Verification gates are hard stops.** If a step says "verify X
before proceeding", satisfy it first. Never backfill a verification after
committing past it.

**§0.9 No new history archaeology in comments.** Do not write "Roadmap
item N", "round N §x.y" or "item N" into source comments. A comment
states what is true now and why. Where an investigation genuinely
matters, point at it as `HISTORY §N`, which the index in §2 resolves.
§24 and §25 remove the existing ~1,025 such references; do not add more
in the meantime.

**§0.10 The audit's scratch work is not in the repository.** Its probes
and screenshots lived in the audit session's own scratchpad, which later
sessions cannot see. Appendix A preserves everything needed to reproduce
them.

---

# Phase A — Foundation

## §1 — Archive round documents, add a docs index (S1)

*Findings: A-45. Docs only.*

**Established.** `docs/` holds 11 dated briefs, `TASKS.md` (a round 5
working ledger that calls itself "not a permanent doc"), three
`roundN/SESSION-PLAN.md` folders, `HANDOFF.md`, `HISTORY.md` and
`screenshots/`. Mapping, read from each brief's own heading:

| Current file | Archive destination |
|---|---|
| `BRIEF-2026-09-02.md` | `rounds/round-01/BRIEF.md` |
| `BRIEF-2026-09-03.md` (starts with a stray `/clear`) | `rounds/round-02/BRIEF.md` |
| `BRIEF-2026-09-03-round3.md` | `rounds/round-03/BRIEF.md` |
| `BRIEF-2026-09-04.md` | `rounds/round-04/BRIEF.md` |
| `BRIEF-2026-09-05.md`, `TASKS.md` | `rounds/round-05/BRIEF.md`, `rounds/round-05/TASKS.md` |
| `BRIEF-2026-09-06.md` | `rounds/round-06/BRIEF.md` |
| `BRIEF-2026-09-07.md` | `rounds/round-07/BRIEF.md` |
| `BRIEF-2026-09-08-refactor.md`, `BRIEF-2026-09-09-security.md`, `round8/SESSION-PLAN.md` | `rounds/round-08/BRIEF.md`, `rounds/round-08/SECURITY-BRIEF.md`, `rounds/round-08/SESSION-PLAN.md` |
| `BRIEF-2026-09-09-round9.md`, `round9/SESSION-PLAN.md` | `rounds/round-09/BRIEF.md`, `rounds/round-09/SESSION-PLAN.md` |
| `BRIEF-2026-09-23-round10.md`, `round10/SESSION-PLAN.md` | `rounds/round-10/BRIEF.md`, `rounds/round-10/SESSION-PLAN.md` |

References to these paths: `CLAUDE.md` (3), `docs/HISTORY.md` (6),
`docs/HANDOFF.md` (3), `.github/workflows/ci.yml` (1 comment),
`tests/test_stress_e2e.py` (1), plus cross-links between the briefs.
Re-count with `grep -rn "BRIEF-2026\|round[0-9]*/SESSION-PLAN\|TASKS.md"`.

**Do.**
- **§1.1** First commit of the round: the four round-11 documents
  (`docs/rounds/round-11/{AUDIT,BRIEF,SESSION-PLAN}.md` and the rewritten
  `docs/HANDOFF.md`), exactly as written by the audit chat.
- **§1.2** `git mv` every file per the table, so history follows. Delete
  the stray `/clear` at the top of the round 2 brief. Repoint every
  reference, including the cross-links inside the moved briefs, so the
  archive stays navigable.
- **§1.3** Add `docs/README.md`: one line per document explaining what it
  is, plus reading orders for three audiences (a Claude Code session, a
  new contributor, a portfolio reviewer). Keep it under 60 lines.
- **§1.4** `CLAUDE.md`:
  - replace the "Round 8 … in progress" roadmap bullet with a pointer to
    round 11;
  - close the stale open issue about `test_callback_server.py` failing
    on CI. All five tests pass on CI run `35906721903`; record the
    closure in your HISTORY entry first, per working agreement 1.
  - Leave the full CLAUDE.md refresh to §38.
- **§1.5** Round 10's S2 row: mark it superseded in
  `rounds/round-10/SESSION-PLAN.md`. Evidence for the HISTORY entry:
  `select count(*) from soulseek_review_candidates` on the real database
  returns `0`, so the stuck candidate is gone. Every candidate recorded
  since item 26 stores `size`, so the legacy branch cannot recur. The
  other branches (peer offline, slskd unreachable) are covered by §11
  and §12.
- **§1.6 [ASK KRIS]** `Claude outputs/` holds two stray copies of round 9
  documents: delete it, gitignore it, or leave it. Default: leave it
  untouched.

**Acceptance.** No old path is referenced anywhere outside the archived
documents' historical prose (`grep` returns nothing). `docs/` top level
lists only `README.md`, `HANDOFF.md`, `HISTORY.md`, `rounds/` and
`screenshots/`.

---

## §2 — Split HISTORY.md, with anchors that work (S2)

*Finding: A-44. Kris approved this on 2026-09-29 (first proposed in
round 9 §8.2).*

**Established.**
- `docs/HISTORY.md` is 15,285 lines and about 900 KB. Its structure:
  header text; `## Known issues / backlog` (4 slugged `###` entries);
  `## Roadmap (direction, not urgent)`, which contains every numbered
  entry `### 1` … `### 135`; and S1's §136.
- 62 of the numbered headings carry a title (for example
  `### 115 — Round 8 Phase 1: toolchain …`). GitHub derives their anchor
  from the whole title (`#115--round-8-phase-1-…`), so a short link such
  as `docs/HISTORY.md#115` lands at the top of the file.
- `CLAUDE.md` holds 43 distinct numeric `HISTORY.md#N` links. **24 of
  them are dead** because they target titled headings: 77, 79, 83, 92,
  93, 103, 104, 109, 114–117, 119, 120, 122–125, 128 and 130–134.
- `src/` and `tests/` contain 239 comment references to HISTORY, mostly
  of the form `HISTORY §N`.

**Do.**
- **§2.1** Write a one-off split script in your scratchpad. Do not commit
  it; paste it into your HISTORY entry. It must:
  - split the numbered entries into files under `docs/history/`, by
    number range, keeping every file under about 150 KB. Proposed
    ranges: `001-030.md`, `031-060.md`, `061-090.md`, `091-110.md`,
    `111-136.md`; measure and adjust.
  - move the header text and the four "Known issues / backlog" entries
    to `docs/history/early-fixes.md`;
  - insert `<a name="N"></a>` on its own line directly above every
    numbered heading;
  - verify losslessly: the concatenation of the new files, with the
    inserted anchor lines removed, must be byte-identical to the
    original content.
- **§2.2** Add `docs/history/README.md`, the index. It carries:
  - one line per entry: `§N — <title or first line> → [file#N](file#N)`;
  - the four early-fix slugs;
  - one paragraph explaining the append rule for new entries (§0.6).
- **§2.3** Replace `docs/HISTORY.md` with a five-line stub pointing at
  `docs/history/README.md`, so that links in old commit messages still
  land somewhere.
- **§2.4** Repoint:
  - every `HISTORY.md#N` link in `CLAUDE.md`, `docs/HANDOFF.md`,
    `docs/README.md` and the round documents to its new `file#N`;
  - any path-style link in `src/` or `tests/`. Plain `HISTORY §N` text
    stays as it is, because the index resolves it.
- **§2.5** Link check: a scratch script extracts every
  `docs/history/*.md#N` link in the repository and asserts the target
  file contains `<a name="N">`. Paste its output.

**Acceptance.** The lossless check passes. The link check reports zero
dead anchors. S1's §136 lives in the last range file, and your own entry
becomes §137.

---

# Phase B — Data safety (critical)

## §3 — Downloads never overwrite and never guess (S3)

*Findings: A-01, A-02, A-04. Critical. Reach for `focused-fix` and `tdd`.*

**Established.**
- `DownloadService._move_completed_file` (`soulseek/download_service.py`)
  locates the finished file with
  `rglob(glob.escape(basename))` over the whole slskd download directory
  and takes `matches[0]`. It then calls
  `shutil.move(src, destination_dir / basename)` with no existence check.
- `shutil.move` onto an existing file **replaces** it. That is `os.rename`
  semantics on the same volume, and `copy2` followed by an unlink across
  volumes (the X9 Pro case). Probe A.2: a pre-existing, different
  `01 - Intro.mp3` in the library was overwritten.
- `apply_upgrade_decision(request_id, replace=True, delete_old=True)`
  moves the new file (above), then calls `delete_file(old_path)`. When
  the upgrade's basename equals the current file's name in the same
  folder, `old_path` **is** the new file. This is plausible for a
  128 kbps upgraded to a 320 kbps MP3 from another peer, and for any file
  already renamed by Seeker's own rename feature. Probe A.1 output, with
  the real service: the message reads "Replaced with …/Artist - Song.mp3,
  Deleted …/Artist - Song.mp3", no file remains on disk, and the
  `local_files` row plus its auto match survive. The Dashboard would then
  show "In library" for a track that no longer exists.
- Wrong file: with two downloads sharing a basename in different remote
  folders, `rglob` order decides which file is moved (probe A.2 returned
  the second album's file first).
- Real-world evidence from the dev `slskd-data/downloads/` (gitignored,
  728 MB): slskd writes `<remote parent folder>/<basename>`, and on a name
  clash appends `_<ticks>` before the extension. Example:
  `Under Pressure (Deluxe) - LOGIC/05 - LOGIC - Buried Alive_639239396236841232.flac`
  sits next to `05 - LOGIC - Buried Alive.flac`. There are 11 such
  suffixed duplicates in total. **Hypothesis:** this is slskd's documented
  rule. Confirm it against slskd's source or docs (search its
  repository for the download-path and collision logic) before relying
  on it.
- Every `download_requests` row stores `size`, the exact byte size of the
  requested file.
- `metadata_service._resolve_collision` already implements "never
  overwrite a different file; add ` (2)`, ` (3)`; the same inode is not a
  collision". Reuse it; never write a third variant.

**Invariants the fix must guarantee** (each one gets a test):
1. No file that existed before the operation is destroyed, except the
   current file of an upgrade confirmed with "Delete old file".
2. After a successful move, the track's match points at a `local_files`
   row whose file exists and holds the downloaded content.
3. The delete-old step never deletes the file the match now points at.
   Keep a `same_file` guard even though invariant 4 makes it unreachable.
4. A settled download never replaces an existing file. It gets the
   shared collision suffix, and the final name is logged and returned.
5. A request whose file cannot be located unambiguously is left for the
   next poll, never guessed, and the condition is logged once.

**Do.**
- **§3.1** Failing tests first:
  - probe A.1 as a test: same-name upgrade with `delete_old=True`
    (invariants 1–3);
  - probe A.2 as two tests: settled download over a different same-named
    file (invariant 4); two same-named downloads (invariant 5 / exact
    match).
- **§3.2** Exact location:
  - Add `_locate_completed_file(download_dir, request)`.
  - Look for candidates first in `download_dir / <remote parent name>`:
    the plain basename and any `<stem>_<digits><suffix>` variant. Use a
    whole-tree search only as the fallback.
  - When `request.size` is known, keep only candidates of exactly that
    size.
  - Exactly one survivor wins. Several same-size survivors: take the
    newest mtime (same size and name means the same download) and log
    it.
  - None: return `None`.
  - Size unknown and more than one candidate: refuse, per invariant 5.
  - A basename of `..` or empty is unlocatable; handle it explicitly.
- **§3.3** Never overwrite. The settled path goes through the shared
  collision helper. Lift `_resolve_collision` into one shared place;
  `filename_format.py` or a new `file_placement.py` both fit, and §17
  takes whichever you choose.
- **§3.4** Upgrade replace semantics:
  - "Replace" with "Delete old file" means the new file takes over the
    track. If the old file sits in the destination folder under the same
    name, move the new file in via a same-directory temp name and
    `os.replace` it onto the old path. That is one atomic swap: the old
    content is gone, as intended, and nothing else is deleted afterwards.
    The `local_files` row keeps its id and is refreshed by
    `index_single_file`.
  - Otherwise: move under a collision-free name, index it, re-point the
    match, then (with delete-old) remove the old file. The database row
    goes first and the file second, per the standing rule, guarded by
    `same_file`.
  - "Replace" without "Delete old file" always yields a collision-free
    name and leaves the old file untouched.
- **§3.5** Paste probe A.1 and A.2 re-run against the fix, showing all
  invariants hold.

**Out of scope.** Cleaning up leftover files in slskd's folder (§X1).

---

## §4 — Library integrity: limbo matches and location removal (S4)

*Findings: A-05, A-06. High. Reach for `focused-fix`, `tdd` and
`database-designer`.*

**Established — limbo matches.**
- `track_matches.local_file_id` is `ON DELETE SET NULL`, which leaves
  `match_method`, `score` and `confirmed_at` untouched ("limbo").
- `TrackMatcher.match_all` skips every row with `confirmed_at` set, even
  when `local_file_id IS NULL`, and still counts it as `auto`.
- `TrackRepository.get_unmatched_for_playlist` selects only
  `tm.track_id IS NULL OR tm.match_method IS NULL`, so limbo rows are
  never downloaded.
- `dashboard_service._compute_status` returns `NOT_FOUND` for them, so
  the next-step banner offers "Download N missing tracks" and the
  download requests nothing. That loop never ends.
- Probe A.3: confirm a match, rename the file in Finder, run
  `scan_and_match()`. Result: `('t1', None, 'auto', confirmed)`,
  `match_all` reports it as auto, and `get_unmatched_for_playlist`
  returns `[]`. The file at its new path is indexed but never linked.
- Real database, read-only: **2 limbo rows** now (Denzel Curry, "Ultimate
  – Remix" and "Ice Age"; both auto, unconfirmed).
- Paths that create limbo rows: `LibraryScanner` → `delete_missing` (the
  file vanished or moved); `LibraryService.remove_location` (cascade);
  any `local_files` delete that is not re-pointed first.

**Established — removing a location.**
- `playlists.download_location_id REFERENCES library_locations(id)` has
  no `ON DELETE` action, and `PRAGMA foreign_keys = ON` is set. Probe A.4:
  removing a location that any playlist downloads into raises
  `IntegrityError: FOREIGN KEY constraint failed`.
- `settings_window._on_remove_location_clicked` passes
  `status_label=self.locations_status_label` and no `on_error`. The raw
  SQLite text therefore lands on an ephemeral label, which breaks the
  five-channel rule; errors belong on `locations_notice`.
- There is no confirmation, although the removal cascades every indexed
  file of that location and orphans its matches, including
  human-confirmed ones.
- `SeekerConfig.default_download_location_id` can still point at the
  removed location. Resolution copes (it returns `None`), but a dangling
  id stays in `config.json`.
- An unknown name produces `logger.warning` and a silent return, so the
  caller cannot tell nothing happened.

**Do.**
- **§4.1** Failing tests:
  - probe A.3 as a test;
  - a limbo row appears in `get_unmatched_for_playlist`;
  - probe A.4 as a test.
- **§4.2** Prevent limbo at the source. Whenever `local_files` rows are
  deleted (`delete_by_id`, `delete_missing`, location removal), reset the
  dependent matches to a clean unmatched state (`match_method`, `score`,
  `confirmed_at` and `local_file_id` all `NULL`) in the same transaction.
  Use one repository method, called explicitly; no hidden trigger.
- **§4.3** Tolerate limbo everywhere:
  - `match_all` treats a confirmed row as sticky only when its
    `local_file_id` is still set;
  - `get_unmatched_for_playlist` counts `local_file_id IS NULL` as
    unmatched.
  - Add an idempotent repair to `connection._migrate`:
    `UPDATE track_matches SET match_method = NULL, score = NULL,
    confirmed_at = NULL WHERE local_file_id IS NULL AND match_method IS
    NOT NULL`.
  - Rehearse the repair on a **copy** of the real database and paste the
    count before (2) and after (0), per §0.7.
- **§4.4** `remove_location`, in one transaction:
  - clear the matches of its files (§4.2);
  - clear `download_location_id`/`download_subfolder` on every playlist
    that points at it;
  - delete the location.
  - `Application.remove_location` also clears the configured default
    destination when it matches, via `update_settings`.
  - Return a small summary dataclass: files forgotten, matches cleared,
    confirmed matches among them, playlists affected, whether it was the
    default.
  - An unknown name raises `LibraryLocationNotFoundError`.
- **§4.5** UI and CLI:
  - Add a read-only `preview_remove_location` that returns the same
    counts.
  - Settings shows a confirmation dialog built from it, for example:
    "Remove 'Music'? Seeker forgets 3,454 indexed files and 12 matches
    (3 you confirmed). 2 playlists download here and will need a new
    destination. Files on disk are not touched."
  - Errors go to `locations_notice` as `kind="error"`; the outcome goes
    there as `info`.
  - `seeker library remove` prints the summary.

**Acceptance.** All probes invert. The repair is rehearsed on a copy.
After this lands, Kris's next Scan re-evaluates the two Denzel Curry
tracks; that goes on the live checklist in §41.

---

## §5 — A portable Compose template (S5) — release blocker

*Findings: A-03, A-25, A-54, and the slskd-image part of A-34.*

**Established.**
- The tracked `docker-compose.yml` contains, at lines 54 and 55:
  - `"${SLSKD_SHARE_PATH:-/Volumes/X9 Pro/Music}:/shared/music:ro"`
  - `"/Volumes/X9 Pro/Music/Test:/shared/Test:ro"`
- The second line was committed in `bffb21b` ("…clean up working tree").
  It is the Sharing feature's in-place edit, swept into git.
- `packaging/seeker.spec` bundles the file. Both copies are in the
  current `dist/Seeker.app` (`Contents/Resources` and
  `Contents/Frameworks`).
- `docker_setup.compose_file_path()` copies the bundled file into every
  user's `slskd_data_dir()` on the first frozen run. In dev it returns
  the **CWD-relative tracked file**, so `SharingService.
  add_location_to_share` edits the repository itself. That is the root
  cause.
- `image: slskd/slskd` carries no tag, so it resolves to `latest`.
  `restart: always`.
- `add_location_to_share`, when `docker compose up` fails, restores only
  the Compose file; the `slskd.yml` edit remains. Both writes use a plain
  `write_text`, and `.bak-<timestamp>` files are never pruned.
- **Hypothesis:** on another user's Mac, Docker Desktop fails to create a
  bind-mount source under the root-owned `/Volumes`, and the wizard's
  SoulSeek step fails. Do **not** test this by starting containers on
  Kris's machine (§0.7). The fresh-account install in §41 is the live
  test.

**Do.**
- **§5.1** Failing test first: a structural test that parses the tracked
  template and asserts:
  - it contains no `/Volumes/` or `/Users/` literal;
  - every bind-mount source is an environment variable with no personal
    default;
  - the image carries an explicit version tag.
- **§5.2** Template:
  - remove the `Test` mount;
  - make the share path required, `${SLSKD_SHARE_PATH:?set by Seeker}`,
    because the wizard and the Sharing recreate always pass it (confirm
    both callers do);
  - pin the image to the version Kris runs now: read it with
    `docker inspect slskd --format '{{.Config.Image}}'` and the image's
    version label, both read-only;
  - use `restart: unless-stopped`, so a user who stops slskd is not
    overridden;
  - rewrite the comments in present tense (§0.9).
- **§5.3** Dev and frozen builds both use the per-user copy:
  - `compose_file_path()` always returns `slskd_data_dir() /
    "docker-compose.yml"`, seeded once from the template. The template
    comes from the source tree in dev and from `_MEIPASS` when frozen.
    The tracked file becomes a template the app never writes.
  - A manual `docker compose up` from the repository still works; update
    the README note.
  - **Kris's dev slskd data lives in the repository's own
    `./slskd-data/`** (gitignored; `slskd.yml`, `data/`, `downloads/`
    with 728 MB, `incomplete/`). The compose default
    `${SLSKD_DATA_DIR:-./slskd-data}` points there, and
    `~/Library/Application Support/Seeker/slskd-data` does not exist.
    The switch must not strand that data:
    - trace which `SLSKD_DATA_DIR` each caller of `bring_up_slskd` would
      pass after the change (the wizard, Settings, and Sharing, which
      reads the live container's `/app` mount);
    - write the answer into the handoff;
    - recreate nothing (§0.7).
  - **Record in the handoff:** Kris's running container was created from
    the repository path. It reads as "not self-managed" until it is next
    recreated through Seeker, and the `Test` share must be re-added
    through Sharing if Kris still wants it.
- **§5.4** Sharing robustness:
  - on a failed recreate, restore **both** files;
  - write both atomically (temp file, then replace);
  - keep only the newest 5 `.bak-*` files per file;
  - `_insert_slskd_share_directory` looks only for `shares:` immediately
    followed by `directories:`. For any other shape (for example a
    `shares:` block that starts with `filters:`), it **appends a second
    top-level `shares:` key**, a duplicate YAML key that slskd may reject
    or silently override. Handle that shape, or refuse with a clear
    error. Add tests for it, and for comment lines inside the Compose
    `volumes:` list. Text surgery stays acceptable only because both
    files are Seeker-generated; say so in a one-line comment.
- **§5.5 Privacy: Settings must never change what is shared** (A-54,
  high).
  - **Established.** `SettingsPage._on_update_credentials_clicked` passes
    `library_location_path = list(self._locations_by_name.values())[0]
    .path` to `bring_up_slskd`, under a comment claiming it "reuses
    whichever location is already shared". That dict comes from
    `list_locations()`, which uses `ORDER BY name`.
  - Kris's real locations, sorted: `Desktop` (`/Users/sinthesis/Desktop`),
    `Music`, `Test`, `x9-pro`. The dev `slskd.yml` shares `/shared/music`.
    So the next "Update SoulSeek credentials" would recreate slskd
    sharing **the Desktop folder** with the whole Soulseek network, and
    drop the music share.
  - The wizard is not affected: it uses the location chosen in its own
    step.
  - `SharingService` already does it right: it reads the live
    container's mounts (`_get_live_container_mounts`, `/shared/music`).
  - **Failing test first:** with locations named so that a non-shared
    one sorts first, updating credentials must pass the currently
    shared host path.
  - **Fix:** Settings' recreate takes the share path from the live
    container's current mount, exactly as Sharing does. When no
    container exists, it asks the user which location to share (a
    dialog); it never picks one silently.
  - Consolidate the three copies of the bring-up orchestration (the
    wizard, Settings, and Sharing's recreate) into one
    `Application`-level method. Each copy generates the API key,
    prepares the data directory, fetches web credentials, calls
    `bring_up_slskd`, checks the return code and persists config. §12's
    **Start slskd** action then reuses the same method.

**Acceptance.** Paste `docker compose -f docker-compose.yml config` run
with dummy `SLSKD_*` variables. It is read-only and starts nothing; it
must show only variable-driven mounts and the pinned image. The live
proof is §41's fresh-account install.

---

# Phase C — Correctness

## §6 — Spotify sync: duplicates, local files, stale tracks (S6)

*Findings: A-07, A-08, A-09.*

**Established.**
- Probe A.5: when `SpotifyClient.get_playlist_tracks` returns the same
  track id twice, `replace_playlist_tracks` fails with
  `UNIQUE constraint failed: playlist_tracks.playlist_id,
  playlist_tracks.track_id`, and that playlist can never load its
  tracks.
- A Spotify "local file" entry has `type: "track"`, `is_local: true` and
  `id: null`. It becomes `Track(id=None)`, and the insert fails with
  `NOT NULL constraint failed: playlist_tracks.track_id`. The
  transaction rolls back, so no `NULL` id persists.
- Neither case is covered in HISTORY or the tests (`grep is_local`).
- `sync_playlists()` saves each changed playlist's new `snapshot_id` and
  returns the playlists that need a track sync. **Both callers discard
  that list**: `cli.handle_sync` and `MainWindow._on_sync_clicked`.
- Tracks refresh only through the per-playlist "Load tracks" action.
  `_decide_next_step` offers that only when a playlist has **zero**
  cached tracks, and nothing compares `track_count` with the cached rows.
- Real database: 215 playlists; tracks loaded for only a handful
  (56 `playlist_tracks` rows).
- **Consequence:** once a loaded playlist changes on Spotify, the
  Dashboard reads "You're all set" while new tracks are missing, and the
  snapshot check then hides the change on every later refresh.

**Do.**
- **§6.1** Failing tests: the duplicate track, the local file, and a
  stale loaded playlist being reported as all set.
- **§6.2** The parser skips local files and entries with a `null` id. The
  sync service de-duplicates track ids, keeping first occurrences, and
  reports both counts. Return a small `TrackSyncResult` (local files
  skipped, duplicates collapsed, album-art URLs filled). The UI shows a
  notice when local files were skipped, because a DJ needs to know that
  those tracks can never be matched automatically.
- **§6.3** Stale-track detection:
  - Add a `playlists.tracks_snapshot_id` column through the existing
    `_add_column_if_missing` pattern. Initialise it to `snapshot_id` for
    playlists that already have `playlist_tracks` rows, so the upgrade
    does not flood "stale"; leave it `NULL` otherwise. Rehearse on a
    copy (§0.7).
  - `sync_playlist_tracks` sets it on success, in the same transaction.
- **§6.4** Refresh behaviour:
  - "Refresh playlists" (UI) and `seeker sync` (CLI) re-sync the tracks
    of every **already-loaded** playlist whose snapshot changed,
    reporting progress on the activity strip.
  - Never-loaded playlists stay unloaded; that respects the Spotify API
    budget the snapshot exists to protect.
  - The result notice reads, for example: "Refreshed 215 playlists.
    Updated tracks for 3 that changed on Spotify."
  - If a stale playlist remains (for example after a failed track sync),
    the next-step banner says "'X' changed on Spotify — refresh its
    tracks".

---

## §7 — Scale: big locations, short transactions, real paths (S7)

*Findings: A-10, A-23, A-24, A-57, A-59.*

**Established.**
- **Too many SQL variables.** `LocalFileRepository.delete_missing` binds
  one `?` per seen path. On SQLite 3.53.1, `SQLITE_LIMIT_VARIABLE_NUMBER`
  is 32,766. Probe A.6: 32,767 parameters raise `OperationalError: too
  many SQL variables`, so any location with more than 32,765 audio files
  can never finish a scan.
- **Scan transaction.** `LibraryScanner.scan` loads **every**
  `local_files` row of every location and filters in Python, although
  `get_all_for_location` exists. It then runs the whole `rglob` walk and
  every mutagen tag read inside **one** write transaction. After the
  first upsert, the RESERVED lock is held for the rest of the scan.
- **Match transaction.** `TrackMatcher.match_all` does the same with its
  CPU-bound fuzzy pass. It also filters candidates by duration with a
  linear scan per track.
- **Hypothesis:** other writers (the 20-second `poll_downloads`, tagging)
  wait out SQLite's 5-second default busy timeout and fail with
  "database is locked" during a large first scan. Confirm with a
  measurement (two threads against a copy) before claiming it; fix the
  transaction shape regardless.
- **Relative paths.** `LibraryService.add_location` stores
  `str(Path(path))` unresolved, despite the variable's name
  `resolved_path`. Probe A.7: `./Music` is stored as `Music`. `~/Music`
  is not expanded and fails with the misleading "drive may not be
  connected".
- **Hidden folders.** One of Kris's locations is a volume root
  (`/Volumes/X9 Pro`). Today no indexed file lives under a dot-folder,
  but a volume-root location would index `.Trashes` if trashed audio
  existed.

**Do.**
- **§7.1** Failing test: build a location with more than 32,766 rows (a
  single `executemany`) and call `delete_missing`; it fails today. Fix:
  compute removed ids in Python (the scanner already holds
  `existing_by_relative_path`) and delete in chunks through
  `executemany`.
- **§7.2** Scanner:
  - fetch with `get_all_for_location`;
  - walk and read tags **outside** any transaction;
  - write upserts in batches of about 200 in short transactions;
  - delete missing rows in one short transaction at the end;
  - skip hidden **directories** (any directory component starting with
    `.`: `.Trashes`, `.Spotlight-V100`, `.fseventsd`) and AppleDouble
    `._*` files. Do **not** skip audio files merely because their name
    starts with `.`; §7.5 stops Seeker from creating them, but a user
    may own one;
  - log unreadable-tag failures at DEBUG with `exc_info` instead of
    swallowing them silently.
- **§7.3** `match_all`: read in one short transaction, compute outside
  any transaction, and write every upsert in one short transaction.
  Duration pre-filter: sort the files by duration and `bisect` the
  ±5-second window; files without a duration stay candidates. Pin the
  unchanged results with a before/after equivalence test on a fixture.
- **§7.4** Both add-location paths use `Path(path).expanduser().
  resolve()`. The not-found message mentions a disconnected drive only
  for paths under `/Volumes`. Add tests for `./x` and `~/x`.
- **§7.5 Never create hidden names** (A-57).
  - **Established.** Probe:
    - `build_track_filename('...And You Will Know Us by the Trail of
      Dead', 'Relative Ways', 'mp3')` returns
      `'...And You Will Know Us by the Trail of Dead - Relative Ways.mp3'`;
    - `sanitize_path_component('.late night mix')` returns
      `'.late night mix'`.
  - Both start with `.`, so Seeker's rename and its per-playlist
    download folder create files and folders that Finder, and many DJ
    file browsers, hide.
  - Kris's data has no such paths today (`relative_path like '.%' or
    like '%/.%'` returns 0), so this is preventive.
  - **Fix:** both builders replace leading dots, for example with `_`,
    the choice common taggers make; pick one and document it. Test with
    the artist above and a dot-led playlist name.
- **§7.6 The destination subfolder the user sees is the one used**
  (A-59).
  - **Established.** `DestinationDialog`'s path preview renders
    `sanitize_path_component(subfolder)`, but `selected_subfolder()`
    returns the **raw** text. That raw text is what `set_destination`
    persists, and what `_move_completed_file` joins onto the location
    path, unsanitized. `seeker playlists set-destination --subfolder`
    has the same gap.
  - So `240KM/H` previews as `240KM-H` but downloads into nested
    `240KM/H` folders.
  - `../Elsewhere` previews as a harmless `..-Elsewhere`, but the real
    download lands **outside** the library location. `Path.relative_to`
    is purely lexical, so the resulting `local_files.relative_path`
    starts with `..`, and the next scan cannot see the file.
  - **Fix:** validate once at the service boundary (`set_destination`
    and resolution). Allow only a single sanitized component, or, if
    nested subfolders are wanted, a relative path whose every component
    is sanitized, with no `..` and not absolute. The dialog previews
    exactly what the service will use. Reject invalid input with a clear
    message instead of silently rewriting it. Tests for `240KM/H`,
    `../x` and `/abs`.
- **§7.7** If the X9 Pro drive is mounted, time `scan_and_match()`
  against a **copy** of the database, before and after (the files are
  only read). Paste both numbers. If the drive is not mounted, say so;
  do not skip silently.

---

## §8 — Review decisions stick; failures stay visible (S8)

*Findings: A-21, A-22, A-33. Split point: after §8.2.*

**Established.**
- **Rejections do not stick.** `LibraryService.reject_match` deletes the
  match row, and the next `scan_and_match` recreates the same
  needs-review pair. `DownloadService.reject_review_candidate` deletes
  the candidate row, and the next download run can record the same
  candidate again. Both docstrings call this "a deliberate non-feature";
  from the user's side it is a loop.
- **Orphan manual tracks.** `download_manual` saves a `manual:<uuid>`
  track **before** searching, so a search that finds nothing (or raises)
  leaves an orphan row behind. The real database has 1.
- **Invisible failures.**
  - The Downloads page drops a finished row after about 60 seconds.
  - History excludes failures, and its own copy says to "see the
    Downloads page".
  - No failure reason is stored: there is no column for it, and the
    poll discards slskd's state and exception text after classifying
    them.

**Do.**
- **§8.1** Persist rejections:
  - Add two tables:
    - `rejected_local_matches(track_id, local_file_id, rejected_at)`,
      primary key on both ids, `ON DELETE CASCADE` from both parents;
    - `rejected_soulseek_candidates(track_id, username, filename,
      rejected_at)`.
  - `match_all` excludes rejected pairs from a track's candidates and
    falls through to the next best.
  - The download pipeline filters rejected peer and file pairs before it
    chooses a needs-review or auto candidate for that track.
  - Update the Reject tooltips: "Seeker won't suggest this file for this
    track again."
- **§8.2** Create the manual track only when a request is actually made
  (or delete it on every no-request exit). Add an idempotent `_migrate`
  cleanup that deletes manual tracks with no `download_requests` and no
  `track_matches` rows. Rehearse on a copy: 1 before, 0 after.
- **§8.3** Failures stay visible:
  - Add `download_requests.failure_reason TEXT`, set whenever a row
    becomes `failed` or `unavailable`. Store a short, human-readable
    reason derived from slskd's state or exception text, such as "Peer
    rejected: file not shared" or "Timed out".
  - The Downloads page keeps `failed` and `unavailable` rows until the
    user clears them with a "Clear finished" action, backed by a
    `dismissed_at` column. Completed rows keep the 60-second window.
  - Show the reason in the status cell, with the full text in a tooltip.
  - Update History's copy so it matches.

---

# Phase D — Security and supply chain

## §9 — Application hardening (S9)

*Findings: A-14, A-15, A-16, A-55, A-60, plus config hygiene. Reach for
`env-secrets-manager`. This is a large row: if it overruns, §9.1–§9.3
are the split point, and §9.4–§9.8 can stand alone.*

**Established.**
- **Credential writes.** `atomic_file.write_text_locked` writes the temp
  file at the process umask (0644 on a default macOS account), *then*
  chmods it to 0600. For that window, the Spotify refresh token or the
  slskd credentials are readable by other local users. There is no
  `fsync`, although the docstring promises power-cut safety, and a failed
  write leaks the temp file.
- **Token refresh race.** `SpotifyAuthManager.get_valid_token` has no
  lock. The "sync" and "sync_tracks" busy keys differ, so both can run
  at once. When the token has expired, both refresh. Spotify rotates the
  refresh token, so the loser's refresh fails with an HTTP 400, and it
  falls back to `_authorize()`: a surprise browser window and a race for
  port 8888.
- **Unencoded usernames.** `SoulseekClient.get_download_status` and
  `get_download_exception` interpolate the peer's username into the URL
  path unencoded. httpx probe (Appendix A.8):
  - `what?ever` becomes path `/…/what` with query `ever/1234`;
  - `hash#tag` becomes a fragment;
  - `../../../application` is dot-normalized to `/api/application/1234`,
    an API-key-authenticated GET to a different slskd endpoint.
  Whether the Soulseek server permits these characters in usernames is
  **unverified**; percent-encoding is correct regardless.
- **Album-art URLs.** `_download_album_art` fetches the stored URL with
  no scheme or host check. All 56 stored URLs are `https://i.scdn.co/…`.
  `update_check` returns GitHub's `html_url`, which is opened
  unvalidated.
- **OAuth callback page.** It always says "Spotify authorization
  complete", even when the redirect carries `error=access_denied`.
- **Config loading.**
  - `config_store.load_config` lists every field by hand, so a new field
    forgotten there silently resets on every load. It also never
    type-checks hand-edited values.
  - `config.py` calls `load_dotenv()` at import, which walks up from the
    installed module's own directory, including a frozen bundle's
    parents.

**Do.**
- **§9.1** `write_text_locked`:
  - create the temp file with `os.open(tmp, O_WRONLY | O_CREAT | O_EXCL,
    0o600)`;
  - write, `fsync`, then `os.replace`;
  - fsync the parent directory, best effort;
  - remove the temp file on any failure.
  - Tests: patch `os.open` to capture the mode (0600 from creation), and
    check that a failure leaves no temp file.
- **§9.2** Guard the refresh with a lock and a double check: reload the
  token after acquiring the lock. Test with two threads and a fake
  refresh endpoint: exactly one refresh happens, and both threads get
  the new token.
- **§9.3** Encode path segments with `urllib.parse.quote(username,
  safe="")` (and the transfer id). Tests assert the request path for the
  three hostile names.
- **§9.4** Album art: accept only `https` URLs whose host is `i.scdn.co`
  or ends in `.scdn.co` or `.spotifycdn.com`. Anything else is skipped
  and logged, never fetched. Release URL: accept only the
  `https://github.com/KristiyanDDimitrov/Seeker/` prefix; otherwise open
  the releases page.
- **§9.5** OAuth callback and wait (A-60):
  - render an accurate page for the `error` parameter ("Authorization
    was cancelled — return to Seeker to try again");
  - add `Cache-Control: no-store`, `Content-Security-Policy: default-src
    'none'` and `Referrer-Policy: no-referrer`;
  - **make the wait cancellable.**
    - **Established.** The wizard's `_on_connect_spotify_clicked`, and
      Settings' Re-authorize, run `connect_spotify` in a worker that
      disables the button for up to `CALLBACK_TIMEOUT_SECONDS` (300 s).
    - A mistyped Client ID makes Spotify show its own `INVALID_CLIENT`
      page, which never redirects, so the user waits 5 minutes with no
      way out.
    - Worse, typing in the Client ID field re-enables Connect
      (`_update_connect_button_state`). A second click then fails to
      bind `127.0.0.1:8888`, which the first server still holds, and
      shows a raw "Address already in use".
    - **Fix:** `serve_until_callback` accepts a cancel event, checked
      between short `handle_request` timeouts, and the pending attempt
      closes its socket on cancel. While waiting, the UI shows "Waiting
      for approval in your browser…" with **Cancel** and a hint to check
      the Client ID if Spotify shows an error. Connect stays disabled
      until the attempt ends or is cancelled.
    - Tests: cancel returns promptly and frees the port; a second
      attempt after cancel binds successfully.
- **§9.6** Config:
  - make `load_config` generic over `dataclasses.fields(SeekerConfig)`;
    a value of the wrong type falls back to the field default with a
    warning;
  - add one test that sets **every** field to a non-default value and
    round-trips it.
  - Move `load_dotenv` into the CLI entry point, using
    `find_dotenv(usecwd=True)`. Verify the GUI still reads a project-root
    `.env` under `uv run seeker-ui`, and say what you found.
- **§9.7 Peer strings render as text, never as markup or terminal
  control** (A-55).
  - **Established.** `InlineNotice`'s label, every page's status labels
    and summary labels use Qt's default `AutoText`. Qt treats a string
    as rich text when something tag-like appears before its first line
    break.
  - Error messages embed peer-controlled filenames and usernames, for
    example `SoulseekDownloadError("slskd rejected the download of
    '{filename}' from '{username}'…")`. Probe: the filename
    `<a href="https://evil.example">Update Seeker</a>.mp3` makes the
    whole notice rich text, rendered as "…download of 'Update
    Seeker.mp3'…" with the link styled.
  - Tooltips (for example Review's runner-up filename) auto-detect rich
    text the same way.
  - The duplicates delete confirmation is safe **only** because its
    first line happens to be plain text; any future edit could change
    that.
  - `cli.handle_search` prints `file.username` and `file.filename`
    verbatim, so ANSI and OSC escape sequences in a peer's filename
    reach the terminal.
  - **Do:**
    - `setTextFormat(Qt.TextFormat.PlainText)` on every label that shows
      dynamic text: the notice, status labels, summary labels;
    - escape (`html.escape`) any dynamic text placed in a tooltip or a
      deliberately rich label;
    - give every `QMessageBox` built from dynamic text an explicit
      `PlainText` format;
    - add a small `printable()` helper that strips C0 and C1 control
      characters (except tab) from peer strings before the CLI prints
      them.
  - **Tests:** a notice fed that filename renders it literally; a
    tooltip escapes it; the CLI search output contains no ESC byte.
- **§9.8** `SpotifyClient._get`'s 429 branch calls `response.json()`,
  which raises on an empty body, and `int(Retry-After)`, which raises on
  the HTTP-date form the header may also use. Make both tolerant: an
  unknown reason, and an unparseable `Retry-After` treated as no header.
  One test each.

---

## §10 — CI and supply chain (S10)

*Finding: A-34. Reach for `ci-cd-pipeline-builder` and
`dependency-auditor`.*

**Established.**
- **`.github/workflows/ci.yml`:**
  - actions are pinned by tag, not commit SHA;
  - there is no `permissions:` block;
  - `uv sync --all-extras --dev` runs without `--locked`;
  - there is no uv cache, no concurrency cancel and no timeout;
  - `runs-on: macos-26` carries a comment saying "revert to macos-latest
    once that diagnosis is closed out". That round 9 diagnosis has
    effectively closed: CI has been green on 8 consecutive runs since
    round 10 S4's race fix (`ddc1f6e` through `378646a`). The earlier
    long red streak was that race, which is now fixed.
  - Coverage is computed but not enforced (no branch flag, no floor);
    the audit measured 90.3 % with branch coverage.
- **Dependencies:**
  - no dependency-update automation and no `SECURITY.md`;
  - `ui/workers.py` imports `shiboken6`, which arrives only transitively
    (deptry DEP003);
  - pip-audit is clean;
  - patch updates are available for numpy, platformdirs, rapidfuzz,
    pyinstaller, ruff and scipy-stubs.
- **Formatting:** 11 blank-line slips (ruff's preview `E30x` rules) in
  `cli.py`, `spotify/auth.py`, `ui/help_text.py` and
  `ui/pages/duplicates_page.py`.

**Do.**
- **§10.1** Workflow:
  - `permissions: contents: read`;
  - `concurrency` (group by workflow and ref, `cancel-in-progress:
    true`);
  - `timeout-minutes: 30`;
  - SHA-pinned actions with version comments;
  - `setup-uv` with `enable-cache: true`;
  - `uv sync --locked --all-extras --dev`;
  - `pytest --cov=seeker --cov-branch --cov-fail-under=89`.
  - Decide the runner pin: keep `macos-26` for reproducibility, with the
    comment rewritten to say so, or revert to `macos-latest`. Record the
    choice.
- **§10.2** Add `.github/dependabot.yml` (weekly updates for the
  `github-actions` and `uv` ecosystems) and a short `SECURITY.md`
  (report privately through GitHub security advisories; scope: this
  repository).
- **§10.3** Declare `shiboken6` explicitly in `pyproject.toml`. Run
  `uv lock --upgrade` for the patch updates; if anything beyond patch
  level moves, stop and list it. Run the full suite.
- **§10.4** ruff: add `preview = true`, `explicit-preview-rules = true`
  and `extend-select = ["E30"]`. Fix the 11 findings. Enable
  `G201`/`TRY400` and convert the four `logger.error(…, exc_info=True)`
  calls to `logger.exception`. Never narrow `--select` together with
  `--fix` (CLAUDE.md).

**Acceptance.** CI is green on the new workflow; record the run id.
`uv lock --check` is clean. Paste the dependabot configuration.

---

# Phase E — Observability and error UX

## §11 — Errors people can read; logs that catch everything (S11)

*Findings: A-17, A-18, A-56. Reach for `observability-designer`.*

**Established.**
- **Raw worker errors.** `ui/workers.py`'s `Worker.run` emits
  `str(error)`, so users read `[Errno 61] Connection refused`,
  `FOREIGN KEY constraint failed`, or an empty string. A bare
  `AssertionError()` renders as a lone "Error:"; the audit's screenshot
  of the Sharing page shows exactly that.
- **Render bugs.** `_handle_task_finished` writes `f"Error: {error}"` to
  the status label when a completion handler itself raises.
- **Uncaught exceptions.** `main_ui.py` installs no `sys.excepthook`, no
  `threading.excepthook` and no Qt message handler. An exception raised
  in a Qt slot is printed to stderr, which a Finder-launched `.app`
  discards; it never reaches `seeker.log`. Worker threads are already
  covered since round 10 §1.3.
- **App identity and lifetime.**
  - `main_ui.py` never sets the application name, version or display
    name.
  - It keeps the post-wizard window alive by monkeypatching
    `qt_app.dashboard_window` with a `type: ignore`.
- **CLI.** It catches four `PlaylistNotFoundError` variants and prints
  them; everything else (`httpx.ConnectError`, `sqlite3.Error`) escapes
  as a raw traceback.

**Do.**
- **§11.1** Add `seeker/error_text.py` with a single `describe_error(exc)
  -> str`. It is Qt-free and shared by the UI and the CLI.
  - Seeker's own errors keep their message.
  - `httpx` transport errors name the host they failed to reach, with
    the next step: slskd means "is Docker running?", Spotify means
    "check your connection", GitHub means "try later".
  - HTTP 5xx says which service returned it.
  - `sqlite3.Error` gives a short sentence plus "details are in the log
    (Help → Open Log Folder)".
  - An empty message falls back to the exception's class name plus the
    log pointer.
  - Tests cover every branch.
- **§11.2** Workers emit `describe_error(error)`. The completion-handler
  path shows "Couldn't display the result — details are in the log"
  instead of `Error: …`. Update the tests that assert raw exception
  text; keep the ones asserting domain messages.
- **§11.3** Uncaught exceptions:
  - install `sys.excepthook` and `threading.excepthook`, both logging at
    CRITICAL with `exc_info`;
  - install `qInstallMessageHandler`, mapping Qt warnings to the log;
    drop only messages you can show are benign, such as the offscreen
    "propagateSizeHints", each with a comment.
  - Test: a slot that raises, driven by a real signal, appears in
    `caplog`.
- **§11.4** Set the application name, display name and version (from
  `importlib.metadata`). Replace the monkeypatched attribute with a
  typed holder.
- **§11.5** CLI: catch `SeekerError` (§13 creates the class; until it
  lands, catch the existing tuple), `httpx.TransportError` and
  `sqlite3.OperationalError`, and print `describe_error`. Other
  exceptions still traceback, because a bug report needs one.
- **§11.6 Dashboard outcomes people can read (A-56, high).** This is
  round 10's Defect A, still present on the Dashboard itself.
  - **Established.** `DashboardPage._poll_selected_playlist` runs every
    2 seconds whenever a playlist is selected and the window is visible.
    It calls `run_worker(..., status_label=self.status_label)`, which
    clears that label at the start of **every** tick.
  - `MainWindow._on_sync_clicked`, `_on_sync_tracks_clicked`,
    `_on_scan_clicked`, `_on_match_clicked` and `_start_download` all
    pass the same label and no `on_error` that shows anything. Their
    errors (a Spotify rate limit, an auth failure, "no destination",
    slskd down) are therefore visible for 2 seconds at most.
  - `_on_scan_and_match_finished` writes the scan-and-match summary to
    that label, then calls `_poll_selected_playlist()` itself. Probe
    (FakeApplication, playlist selected): the label reads `''`
    immediately after the scan finishes, so **the summary is never
    visible**.
  - **Failing tests first:** the scan summary is still readable after the
    next poll tick; a failing "Refresh playlists" leaves its error
    readable.
  - **Fix:**
    - route every Dashboard action's outcome and error to
      `dashboard_notice`, the persistent InlineNotice, as round 10 did
      for Review and as `_on_download_finished` already does for its
      success path;
    - stop passing `status_label` to the periodic poll, which has
      nothing to say there;
    - keep the status label for in-progress text only.
  - Then sweep every periodic `run_worker` call (`grep -n
    "run_worker\|run_busy_worker"`, check each timer-driven one) for
    the same pattern, and list what you checked.
  - **Cross-page feedback, the same defect class.** The Dashboard row's
    **Tag** button and its context-menu **Re-tag** are forwarded
    (`MainWindow._on_tag_track_clicked` / `_on_retag_track_clicked` →
    `self._library_page._tagging_panel…`) into `TaggingPanel`, whose
    `TaggingPanelHost` carries the **Library** page's `notice` and
    `status_label`. A tag failure started from the Dashboard ("file not
    found", "unsupported format") is therefore reported on a page the
    user is not looking at.
  - The outcome must land on the notice of the page the action was
    started from: the caller supplies the feedback target, or the
    tagging actions move into a shared controller that reports to it.
    Test: tag from a Dashboard row with a failing fake; the Dashboard
    notice shows the failure.

---

## §12 — Say when slskd is down (S12)

*Findings: A-11, A-58.*

**Established.**
- `DownloadService.poll_downloads` wraps each request in `except
  Exception`. When slskd is down, every `httpx.ConnectError` increments
  `counts["failed"]` without changing the database, and the poll returns
  normally.
- `MainWindow._trigger_backend_poll`'s `on_poll_error` shows the tray
  message "Seeker couldn't reach slskd — check that it's running", which
  can therefore essentially never fire for that case.
- `check_slskd_health` runs only in the wizard and in Settings.
- Docker Desktop not starting after a reboot is the common real case:
  downloads sit "Queued" with no explanation.

**Do.**
- **§12.1** Failing test: a fake client raising `httpx.ConnectError`,
  after which the poll reports the outage instead of counting failures.
- **§12.2** Service:
  - on a transport error, abort the poll and raise a new
    `SlskdUnreachableError(base_url)`;
  - never count unreachable as failed;
  - the **Start slskd** action calls the single `Application`-level
    bring-up method that §5.5 consolidated, with the currently shared
    path. Do not add a fourth copy of the orchestration. If §5.5 has not
    landed, stop and say so.
- **§12.3** UI, following the five-channel rule:
  - on the Dashboard, a persistent next-step notice reads "SoulSeek
    isn't reachable — downloads are paused until slskd is running",
    with a **Start slskd** action;
  - the Downloads page carries the same notice;
  - the tray notifies once per outage (edge-triggered) and again only
    after a recovery;
  - everything clears automatically on the first successful poll.
  - Tests: edge-triggering, recovery, and the action calling the
    consolidated bring-up method.
- **§12.4** CLI: `seeker downloads status` prints the same sentence and
  exits with a non-zero status.
- **§12.5 First-session download notifications** (A-58).
  - **Established by code reading.** `TrayController.seed_notification_
    cutoff` sets `_last_notified_download_at` only when history already
    holds at least one event. `check_for_download_notifications` returns
    early while that value is `None`; its own comment reads "Seeding
    hasn't completed yet (or found nothing) — skip this cycle".
  - So on a fresh install, or any launch with empty history, the value
    stays `None` for the whole session, and no "downloads finished"
    notification ever fires, not even for the first download.
  - **Failing test first:** empty history at startup, then a new
    DOWNLOADED event after the next backend poll, notifies.
  - **Fix:** when seeding finds nothing, the cutoff becomes "now" (UTC
    ISO, the same format as `occurred_at`). Keep "seeding in flight"
    distinct from "seeded, empty".

---

# Phase F — Structure (behaviour-neutral)

Every row in this phase is a pure refactor. The test suite must pass
unchanged, apart from mechanical renames. Reach for `tech-debt-tracker`
(re-run its scanner and show the targeted category counts dropping) and
for `pr-review-expert` before the close-out commit.

## §13 — One exception hierarchy; typed download states (S13)

*Findings: A-35, A-36.*

**Established.**
- **Duplicate exception classes.** Four separate
  `PlaylistNotFoundError` classes exist (`spotify/sync_service.py`,
  `soulseek/download_service.py`, `library/service.py`,
  `library/metadata_service.py`), plus two `LibraryLocationNotFoundError`
  classes (`download_service`, `duplicate_service`).
  `cli.run` imports them under four aliases.
- **Hard-coded format list.** `UnsupportedDownloadFormatError` hard-codes
  "mp3, flac, wav, aiff and m4a", which duplicates
  `audio_formats.DOWNLOADABLE_EXTENSIONS`.
- **Stringly typed states.** The download state machine appears as about
  300 string literals in `src/` and about 400 in `tests/`. Its status
  subsets are defined in three places with different meanings:
  - `download_request_repository.TERMINAL_STATUSES` =
    `{completed, failed, unavailable}`, which excludes `superseded`
    although `schema.py` calls it terminal;
  - `dashboard_service`'s `ACTIVE_DOWNLOAD_STATUSES`,
    `_AWAITING_REVIEW_STATUSES` and `_RETRYING_STATUSES`;
  - `downloads_page._DOWNLOAD_TERMINAL_STATUSES` =
    `{completed, failed, ready_for_review, unavailable}`.
  A `dashboard_service` comment also points at "download_service.py's
  TERMINAL_STATUSES", which is not where it lives.

**Do.**
- **§13.1** Add `seeker/errors.py` with `SeekerError(RuntimeError)` and
  one `PlaylistNotFoundError`, one `LibraryLocationNotFoundError`, and
  every other user-facing error moved in or subclassed. The CLI catches
  `SeekerError`. The format list is derived from
  `DOWNLOADABLE_EXTENSIONS` in a fixed display order.
- **§13.2** In `models/download_request.py`, add `DownloadStatus` and
  `DownloadRole` as `StrEnum`s, plus **named** status sets, each defined
  once with a one-line meaning:
  - which statuses stamp `completed_at` (today's exact
    `TERMINAL_STATUSES`, renamed so the name tells the truth);
  - in flight;
  - awaiting a human;
  - retrying;
  - blocks re-download;
  - shows no further progress.
  Behaviour stays identical: `StrEnum` compares equal to the stored
  strings, so no database migration is needed.
  - Replace the literals in `src/`; tests may keep plain strings.
  - `DownloadRequest.status` is typed `DownloadStatus`, and row mapping
    converts on read.
  - Rewrite the `schema.py` status comment in present tense and point it
    at the enum.

---

## §14 — Typed service results (S14)

*Finding: A-37.*

**Established.** These services return `dict[str, Any]` or
`dict[str, int]`, and `ui/help_text.py`'s formatters plus
`ui/tag_result_panel.py` index into them by string key:
- `download_playlist`, `download_manual`, `poll_downloads`;
- `LibraryService.scan_all` and `scan_and_match`, `TrackMatcher.
  match_all`;
- `MetadataService.tag_tracks`, `fix_missing_art_for_playlist`;
- `DuplicateService.compute_fingerprints`.

`select_downloads` returns a nested tuple, `tuple[SoulseekFile | None,
list[SoulseekFile], tuple[SoulseekFile, float, tuple[SoulseekFile,
float] | None] | None]`. `RenameResult` and `BulkUpgradeReplaceResult`
are already dataclasses; they are the precedent.

**Do.**
- **§14.1** Add one dataclass per result type, alongside its service or
  in `models/`, with the same fields. The CLI, UI formatters and tests
  switch to attributes. Two exceptions to strict neutrality, both listed
  in the handoff:
  - `download_playlist`'s per-track failures carry their reason
    (`describe_error`), so the UI can list them;
  - the "paused" early return uses the same type.
- **§14.2** Give `select_downloads` a `DownloadSelection(settled,
  upgrade_shortlist, needs_review)` return type.
- **§14.3** `MetadataService._tag_one_track` has complexity **E (32)**
  and mutates the shared `counts` and `details` dicts it is passed. With
  `TagResult` in place, it becomes named steps: resolve the target file,
  decide what to skip, write text tags, embed art, analyse, persist,
  classify the outcome. Each step returns a value instead of mutating
  shared state. radon must report C or better. The existing
  `test_metadata_service*.py` suites are the safety net; they must pass
  unchanged apart from reading the dataclass.

---

## §15 — CLI structure (S15)

*Finding: A-38.*

**Established.**
- **Complexity.** `cli.handle_library` has cyclomatic complexity 52:
  one 260-line `if`/`elif` over 11 subcommands. Its fallback usage
  string lists only 8 of them. `cli.run` dispatches with an
  `if`/`elif` of its own (complexity 18).
- **Duplicate variable.** `build_parser` binds `review_parser` twice.
- **Formatter placement.** `cli.py` imports `format_file_size` and
  `format_timestamp` from `seeker.ui.formatting`, so the CLI reaches
  into the Qt package for presentation-agnostic helpers.
- **CLI code in a service.** `DownloadService.review_pending_upgrades`
  and `_confirm_upgrade` call `input()` and `print()`: CLI code inside a
  service. `_debug_poll` prints when `SEEKER_DEBUG_POLL=1` is set.

**Do.**
- **§15.1** Idiomatic dispatch: `set_defaults(handler=…)` per subparser,
  `required=True` subparsers, and one small function per subcommand.
  `handle_library` disappears.
- **§15.2** Move the shared formatters to `seeker/formatting.py`, and
  have `ui/formatting.py` re-export or import them.
- **§15.3** Move the interactive upgrade review into `cli.py`; the
  service keeps only the explicit-decision methods. `_debug_poll`
  becomes `logger.debug`, and `SEEKER_DEBUG_POLL` raises that logger's
  level. Update CLAUDE.md's note about the two `print` calls.
- **§15.4** `main.main()` constructs `Application()` **before** argparse
  runs. So `seeker --help`, or a typo'd command, opens the real
  database, runs the schema initialisation and migrations, and runs the
  `.env` → config migration, just to print usage text. The audit ran
  `seeker --help` three times; the database and `config.json` mtimes
  stayed unchanged, because every step is idempotent, but help must not
  touch user data at all. Parse first; construct `Application` only
  once a real command is dispatched. Test: `--help` with a path patched
  to a read-only or missing data directory succeeds.

**Acceptance.** radon shows no CLI function above complexity C. Every
`seeker … --help` output matches before and after, apart from the fixed
usage string (paste the diff).

---

## §16 — Service-layer cleanup and dead code (S16)

*Finding: A-39.*

**Established.**
- **Unused repository parameter.** All 8 repositories take a `Database`
  and store `self.database`, which is **never read**; every method takes
  a `connection`. There are 36 construction sites in `application.py`
  and 154 in the tests. `SpotifySyncService` builds its own repositories
  instead of receiving them.
- **Dead code**, verified with a token-level reference count over `src/`
  and `tests/`:
  - `help_text.DUPLICATES_FOLDER_NOT_IN_A_LOCATION`: no references at
    all;
  - `DownloadRequestRepository.get_active_for_track`: comments only;
  - `SharingPage._current_sharing_reconciliation`: written, never read;
  - `DuplicatesPage._current_duplicates_location_name`: written, never
    read in `src/`; check its one test reference;
  - `TrayHost.get_hidden_to_tray`: wired, never called;
  - the unused parameters `FlowLayout._smart_spacing(control_type)` and
    `DuplicateService._compute_one(details)`;
  - two unnecessary `pass` statements (`sharing_service.py`);
  - one `raise X()` (RSE102);
  - `bin(i).count('1')` in place of `int.bit_count()` (FURB161).
- **Production code only tests call:** `formatting.format_speed`,
  `audio_fingerprint.hamming_similarity`,
  `TrackRepository.save_playlist_track` (20 test uses) and
  `callback_server.wait_for_callback`. Keep `theme.contrast_ratio` and
  `workers.debug_snapshot`; they are deliberate test hooks.
- **Legacy migrations.** `application.py`'s CWD-relative migrations
  (`LEGACY_DATABASE_PATH`, `LEGACY_SPOTIFY_TOKEN_PATH`) only ever applied
  to Kris's pre-release dev install, which is already migrated: the
  repository's `.seeker/` is empty. The `.env` → config migration stays,
  because the README documents `.env` for the CLI.
- **Sharing bypasses the client.** `sharing_service` builds slskd URLs
  itself and calls the client's private `client._headers()`.
  `get_reconciliation()` calls `get_status()` again, so one Sharing
  refresh makes that request twice.
- **Misplaced module content.** `soulseek/quality.py` holds local-file
  audio analysis (`LocalFileQuality`, `analyze_local_file_quality`),
  which only the duplicate finder uses.

**Do.**
- **§16.1** Drop the unused repository parameter everywhere (mechanical;
  mypy guides you), and inject `SpotifySyncService`'s repositories.
- **§16.2** Delete the dead code. For test-only helpers, move the logic
  into the tests or a test helper, and delete it from `src/`.
- **§16.3** Remove the two legacy path migrations and their tests.
- **§16.4** `SoulseekClient` gains `get_application()`, `get_shares()`
  and `get_uploads()`, keeping `_get_or_raise_unauthorized`'s 401
  semantics. `sharing_service` uses them and fetches status once per
  snapshot.
  - `SharingService.add_location_to_share` has complexity **D (23)**.
    Split it into its phases: preconditions (confirm, self-managed,
    credentials, not already shared); plan and backup; edit both files;
    recreate; wait for ready; roll back. That lands the rollback that
    §5.4 made correct as one named step. radon must report C or better.
  - `get_download_status` and `get_download_exception` send the
    identical GET. Have one call return both the state and the
    exception, and have the rejection path in `poll_downloads` reuse it
    instead of fetching twice.
- **§16.5** Move the local audio-quality analysis to
  `library/audio_quality.py`. The shared `quality_tier_for_format`
  stays where both callers can reach it.
- **§16.6** `audio_fingerprint._StreamingFingerprinter` frees its native
  context in `__del__` and never checks `chromaprint_new` for a NULL
  return; a NULL context would be passed on to every later call. Make it
  a context manager (free in `__exit__`), and raise `FingerprintError`
  on a NULL context. The rest of the binding checks out: the sample
  count matches chromaprint's API, and the returned string is copied
  before `chromaprint_dealloc`.

**Acceptance.** vulture at 60 % confidence reports nothing new beyond Qt
overrides and dataclass fields. The token reference-count script from
Appendix A.9 prints no production symbol that only tests use.

---

## §17 — Split download_service.py (S17)

*Finding: A-40. Split point: after the placement extraction.*

**Established.**
- `soulseek/download_service.py` is 1,902 lines, has 40 methods and a
  fan-out of 26, and is the only module below maintainability grade A
  (radon: B, 16.8).
- Complexity hot spots: `_retry_locked_request` D(23), `poll_downloads`
  C(18), `download_playlist` C(15).
- It holds four concerns:
  - search and request (`download_playlist`, `download_manual`,
    `search_manual`);
  - polling, retry and cascade;
  - file placement (§3's code);
  - review (SoulSeek candidates confirm/reject, upgrade review/apply).

**Do.**
- **§17.1** Extract `soulseek/placement.py`: locate, move, index and
  match, plus the collision helper if §3 put it here.
- **§17.2** Extract `soulseek/review_service.py` with a `ReviewService`
  for candidates and upgrades. `Application` exposes it, and the Review
  page and CLI call it directly.
- **§17.3** Break `_retry_locked_request` into named steps: supersede
  check, backoff check, attempt, classify, persist.
- No module in `soulseek/` stays above about 800 lines, and no function
  above complexity C.

**Acceptance.** Tests pass unchanged, apart from import paths and the
new service seam. Paste the radon output before and after.

---

## §18 — Test infrastructure (S18)

*Finding: A-42.*

**Established.**
- **Fakes in a test module.** About 600 lines of `Fake*` classes live in
  `tests/test_ui_smoke.py`. Thirteen test modules and
  `docs/screenshots/generate.py` import them from that module.
- **Fake contract.** `FakeSharingService`'s default `status=None`
  violates the real contract: `get_status` returns `ShareStatus` or
  raises.
- **Smoke file size.** `test_ui_smoke.py` is 4,786 lines and 149 tests,
  still the shell's catch-all after the page extraction.
- **Investigation scripts.** Six `tests/_*_repro.py` scripts sit beside
  the tests. Three of them (`_stress_hang`, `_stress_step3_no_locked`,
  `_stress_step4_scale`) are referenced only from HISTORY.
- **Warnings.** Two tests in `test_metadata_service.py` produce six
  librosa `UserWarning`s from audio that is too short.
- **Layering rule not enforced.** CLAUDE.md's rule that presentation
  never imports repositories currently holds, but no test enforces it.
  The private-attribute rule does have one.

**Do.**
- **§18.1** Add `tests/fakes.py`, and update every importer and the
  screenshot script. Fix the fake's default status to a real
  `ShareStatus`.
- **§18.2** Move all six repro scripts to `tests/repro/`. Update
  `test_workers_deadlock_regression.py`'s paths and the ruff
  per-file-ignore glob.
- **§18.3** Split `test_ui_smoke.py` by concern, for example
  `tests/shell/test_window_lifecycle.py`, `test_theme_toggle.py`,
  `test_menus.py` and `test_tray_integration.py`. Keep test names
  unchanged, and move whole tests only.
- **§18.4** Add a layering test, an AST sweep:
  - `ui/`, `cli.py` and the entry points never import `seeker.database`;
  - `cli.py` never imports `seeker.ui` (true once §15 moves the shared
    formatters);
  - nothing outside `ui/` and `main_ui.py` imports PySide6;
  - `models/` imports nothing from `seeker` except `models`.
- **§18.5** Remove the warnings by making the synthetic audio long
  enough, not by filtering them.
- **§18.6** Sample for vacuous tests. Round 10 found one: it asserted a
  label read `""` immediately, which passes whether or not anything
  happened (HISTORY §126). Grep for assertions made directly after an
  asynchronous trigger (a `click()`, `run_worker` or `emit`) with no
  `waitUntil` on the effect, and for `assert … == ""` or `not
  isVisible()` checks that the initial state already satisfies. Read at
  least 20 hits and fix each real one so it waits on the effect, the
  §4 pattern from round 10. List every hit checked.

---

## §19 — MainWindow I: Dashboard flows move to DashboardPage (S19)

*Finding: A-41 (first half).*

**Established.**
- `ui/main_window.py` is 2,281 lines. (CLAUDE.md still says 1,842, the
  post-Phase-6 figure.)
- The Dashboard's action flows still live on the shell, about 250 lines:
  `_on_sync_clicked`, `_on_scan_clicked`, `_on_scan_and_match_finished`,
  `_on_match_clicked`, `_on_download_clicked`, `_open_destination_dialog`,
  `_start_download`, `_on_download_finished`, `_on_sync_tracks_clicked`,
  and the three tag forwarders.
- They are the source of most of the 46 private-member accesses
  (ruff `SLF001`) from `main_window.py` into pages, for example
  `self._dashboard_page._poll_selected_playlist()` and
  `self._library_page._tagging_panel._on_tag_track_clicked(...)`.
- `DashboardHost` exists only to route those flows back.

**Do.**
- **§19.1** The flows move into `DashboardPage`, or a small
  `dashboard_actions.py` that it owns, and use `PageContext`'s
  `run_busy_worker`.
- **§19.2** Pages expose small public methods for what the shell
  legitimately needs (`refresh()`, `poll()`); the shell calls only
  those. `DashboardHost` shrinks or disappears; say which.
- **§19.3** `SLF001` over `ui/main_window.py` reaches 0. Paste
  `ruff check --select SLF001` before and after.

---

## §20 — MainWindow II: extract the window lifecycle (S20)

*Finding: A-41 (second half). High-risk code: every item here has a
bug history (HISTORY §113, §114, §124, §125, §129, §130).*

**Established.** About 500 lines of window lifecycle remain on
`MainWindow`:
- `closeEvent`, `showEvent`, `start_hidden_to_tray`, `show_restored`;
- `_restore_window_geometry` and `_persist_window_geometry`;
- the hide-to-tray confirmation (`_confirm_hidden_to_tray`,
  `_check_hidden_to_tray`, `_is_exposed_at_platform_level`);
- the fullscreen Dock policy check;
- the quit confirmation and `cleanup_before_quit`.

`_ThemeToggleButton`, a custom-painted class, lives in the same file.
`__init__` is about 290 lines, of which about 70 are code.

**Do.**
- **§20.1** Extract a `WindowLifecycleController` into
  `ui/window_lifecycle.py`, following the `TrayController` precedent: it
  owns this state and these methods, and `MainWindow` delegates the Qt
  event overrides to it. Moves only; no behaviour change.
- **§20.2** Move `_ThemeToggleButton` to `ui/widgets.py`.
- **§20.3** `MainWindow.__init__` reads as a short sequence of named
  build steps.

**Acceptance.**
- The suite passes 10 consecutive full runs.
- On CI, the fullscreen-close pair
  (`test_fullscreen_close_policy_check_ignores_a_stale_request` and its
  sibling) and
  `test_view_menu_focus_search_navigates_and_focuses_the_search_field`
  pass on the push.
- `main_window.py` is under about 1,100 lines.
- Add "run the stress test" to Kris's list in the handoff, because
  CLAUDE.md requires it after any lifecycle change.

---

## §21 — [ASK KRIS] Package regrouping (S21)

*Optional. Run only after an explicit yes. Reach for
`migration-architect`.*

**Why.**
- `src/seeker/` has 25 top-level modules beside 6 packages. A newcomer
  cannot see which modules are services, which are file utilities and
  which are audio code.
- Proposal: `seeker/audio/` (analysis, fingerprint, formats, tag I/O
  from `metadata.py`, local quality); `seeker/files/` (atomic writes,
  deletion, naming and sanitising); and slskd's Docker and sharing code
  moves into `seeker/soulseek/`. That takes the top level from 25
  modules to about 14.
- **Cost:** every import, every `monkeypatch`/`patch` target string in
  the tests, and both layout documents change.
- **Blame:** `git mv` keeps it, via `git log --follow` and `blame -C`,
  unlike the reformatting CLAUDE.md rejected.

**If approved.**
- One commit per package, with a mechanical rewrite script pasted into
  the HISTORY entry.
- Patch targets are rewritten by the same script.
- If any failure is not mechanical, stop and report it.

---

# Phase G — Performance and test gaps

## §22 — Performance (S22)

*Findings: A-19, A-20, A-31, A-32. Reach for `performance-profiler`.
Measure before and after on a **copy** of the real database (§0.7).*

**Established.**
- **Dashboard poll cost.**
  `DashboardService.get_playlist_track_status` runs every 2 seconds
  while the window is visible. It fetches **whole tables**:
  - every `local_files` row, including `fingerprint`;
  - every `track_matches` and `download_requests` row;
  - every review candidate.
  All of that renders one playlist.
- **Measured on a copy of the real database.**
  - 3,655 of 6,921 rows carry fingerprints, 32.6 MB of text in total
    (average 8.9 KB, maximum 89 KB).
  - The whole-table fetch has a median of **28.7 ms** per poll, plus
    about 33 MB of string allocation.
- **Other callers.** The same fingerprint-inclusive
  `LocalFileRepository.get_all` also backs `history_service`,
  `TrackMatcher.match_all`, `generate_match_report` and the scanner.
  Only `duplicate_service` needs fingerprints.
  - `history_service.get_recent_events` also runs on **every 20-second
    backend poll**, through `TrayController.check_for_download_
    notifications`, even while the window is hidden in the menu bar. So
    the menu-bar-resident app re-reads all 32.6 MB of fingerprints three
    times a minute, doing nothing visible. §22.1's fingerprint-free
    default fixes this caller too; measure it separately.
- **Hypothesis, open item 70.** The production-scale hang arrived right
  after fingerprinting and implicated whole-process GIL starvation. The
  2-second poll deserialising every fingerprint on a worker thread is a
  concrete lead. Record it in CLAUDE.md's item-70 entry; §41's stress
  run tests it.
- **No secondary indexes.** `EXPLAIN QUERY PLAN` confirms a full `SCAN`
  for `track_matches WHERE local_file_id = ?` (also used by the `ON
  DELETE SET NULL` action), for `download_requests WHERE track_id = ? …`,
  for `playlist_tracks … WHERE pt.track_id = ?`, and for
  `download_requests WHERE status = 'locked' ORDER BY requested_at`
  (with a temporary B-tree).
- **Import time.** `audio_analysis.py` imports `scipy.stats` at module
  level only to build an optional `uniform` prior. It costs 279 of the
  348 ms of `import seeker.cli`, and 454 of the 724 ms of the GUI import
  when cold.
- **Album-art cache.** `AlbumArtCache._memory` has no bound and lives as
  long as the app's `MetadataService` singleton.

**Do.**
- **§22.1** `LocalFileRepository`'s default column set excludes the
  fingerprint columns. Add `get_all_with_fingerprints` (and the
  per-location variant) for `duplicate_service`. The model's fingerprint
  fields stay optional.
- **§22.2** Add a playlist-scoped repository query for the Dashboard: a
  join from `playlist_tracks` through `tracks`, `track_matches`,
  `local_files` (light columns), and the requests and candidates for
  those track ids only. `_compute_status` stays unchanged.
- **§22.3** Add these indexes to `SCHEMA`, idempotent:
  - `track_matches(local_file_id)`
  - `download_requests(track_id)`
  - `download_requests(status, requested_at)`
  - `playlist_tracks(track_id)`
  Paste `EXPLAIN QUERY PLAN` before and after.
- **§22.4** Import `scipy.stats` lazily, inside the branch that builds
  the prior, with a `# noqa: PLC0415` stating the measured cost. Paste
  `python -X importtime` before and after.
- **§22.5** Bound the in-memory art cache with a small LRU (about 64
  entries); the disk cache keeps persistence.
- **§22.6** The Dashboard re-renders on every 2-second tick.
  - **Established:** `_render_track_statuses` → `_apply_track_filter_
    and_render` rebuilds **every** row on every tick. It creates new
    `QTableWidgetItem`s, a new cell widget in the Progress column (a
    blank `QWidget()` for every row that is not downloading) and a new
    actions widget, and destroys the old ones on the main thread.
  - Selection survives: the audit's probe re-rendered twice with
    identical data and kept `['t1','t2','t3']`. So this is cost, not a
    bug.
  - **Do:** skip the rebuild when the statuses have not changed (compare
    a cheap signature of track id, state and progress). Where only
    progress changed, update values in place. Drop the blank
    placeholder widgets.
  - Measure main-thread render time for a 500-track playlist, before
    and after, with the §27.0 harness data.

**Acceptance.** Poll median and allocations before and after, the
`EXPLAIN QUERY PLAN` output, and the import time, all pasted. No
behaviour change; the tests pass.

---

## §23 — Test gaps (S23)

*Finding: A-13. Reach for `tdd`.*

**Established.** Branch coverage 90.3 %. Weakest modules:

| Module | Coverage | Gap |
|---|---|---|
| `metadata.py` | 58 % | Every FLAC and MP4 branch missed: `write_text_tags`, `embed_album_art`, `read_embedded_art`, `write_analysis_tags` |
| `cli.py` | 70 % | |
| `ui/upload_eta.py` | 55 % | |
| `main.py`, `main_ui.py` | 0 % | |
| `library/metadata_service.py` | 83 % | |
| `application.py` | 85.5 % | |

From round 10's S7 handoff: no test covers the Review splitter's
persist and restore round trip.

**Do.**
- **§23.1** `metadata.py`: write real files in the tests. `soundfile` can
  write FLAC. For M4A, commit a tiny silent fixture (a few KB, made once
  with `ffmpeg`, recorded in the HISTORY entry). Cover text tags, art
  embed and read-back, analysis tags, and `save_tags`, per format.
- **§23.2** CLI: one test per subcommand's happy path and main error path
  (§15 makes these easy).
- **§23.3** Entry points:
  - `_configure_logging` writes to a temp log directory;
  - the §11 hooks are installed;
  - `main()` smoke tests run with `Application` and `QApplication`
    patched.
- **§23.4** Review splitter round trip, including `cleanup_before_quit`.
- **§23.5** Raise the CI floor to the new measured value minus one.
- **§23.6** Two unverified tag-writing questions come out of the audit's
  read of `metadata.py`. Settle both with evidence before changing
  anything:
  - **FLAC key field.** Analysis writes the key as the Vorbis comment
    `KEY`. Many DJ tools (Traktor, Mixed In Key, and possibly Rekordbox
    and Serato) read `INITIALKEY`. Check each tool's documentation. If
    `INITIALKEY` is the common field, write both, so analysed keys
    appear in the DJ's software.
  - **In-place saves.** `save_tags` saves in place. The first cover-art
    embed usually outgrows a file's metadata padding, and mutagen then
    rewrites the file around the audio. **Hypothesis:** a crash or power
    loss mid-save can leave a corrupt audio file. Measure what mutagen
    does, per format. If it rewrites in place, save resizing writes to a
    same-directory temp copy and `os.replace` it. Where that is not
    possible, explain why.

---

# Phase H — Hygiene

## §24 — Comment and config hygiene: core (S24)

*Finding: A-43. Reach for `tech-debt-tracker`.*

**Established.** About 1,025 references of the form `round N`, `§N`,
`Roadmap item N` or `item N` exist in `src/` comments. The config files
carry the same archaeology: `pyproject.toml`, `docker-compose.yml` (now
the template), `ci.yml` and `packaging/*`. CLAUDE.md already sets the
rule: "A comment earns its place by telling the next person something
the code cannot". Round 8's triage applied it only in part.

**The rule for this pass.**
- **Keep** the present-tense why, and invariants and gotchas that are
  still true.
- **Delete** narratives of what happened: dates, "confirmed live
  2026-08-27", "a real bug this closes", round and item numbers. Where a
  standing fact came out of an investigation, end the comment with
  `See HISTORY §N.` once.
- Docstrings follow the same rule.
- Never change code in this row.

**Do.** Cover everything outside `ui/`, plus the config and packaging
files. Measure with the counting script from Appendix A.10 before and
after. Target: no `Roadmap item`, `round N` or bare `§` left outside
`HISTORY §N` pointers.

## §25 — Comment hygiene: ui/ (S25)

The same rule and measurement for `src/seeker/ui/` (about 600 of the
references: `main_window` 112, `theme` 41, `dashboard_page` 40,
`review_page` 39, `duplicates_page` 38, `settings_window` 27, `tray` 24,
`downloads_page` 21, `help_text` 20, …).

---

# Phase I — Nested library locations (approved)

## §26 — Guard nested locations; guided cleanup (S26)

*Finding: A-46. Kris approved this on 2026-09-29 (first proposed in
round 9 §8.3). Reach for `database-designer` and `migration-architect`.
The real cleanup needs Kris at the keyboard.*

**Established.** The real database, read-only, holds four locations:

| Location | Path | Rows |
|---|---|---|
| `x9-pro` | `/Volumes/X9 Pro` (a **volume root**) | 3,458 |
| `Music` | `/Volumes/X9 Pro/Music` | 3,454 |
| `Test` | `/Volumes/X9 Pro/Music/Test` | 9 |
| `Desktop` | `/Users/sinthesis/Desktop` | 0 |

Every file under `Music` is indexed twice: 6,921 rows for about 3,460
real files. `add_location` and `add_location_from_path` check only exact
path-string uniqueness. `file_deletion.same_file` already detects one
physical file indexed under two rows.

**Do.**
- **§26.1** Guard: both add paths compare **resolved** paths and refuse
  a location inside, or containing, an existing one. The error names
  the conflict and suggests the fix.
- **§26.2** Detection: `LibraryService.find_nested_locations()`.
  Settings shows a warning row with a **Fix…** action; the CLI adds
  `seeker library check`.
- **§26.3** Merge: `merge_nested_location(redundant_id, keep_id)`
  re-points every match, duplicate-cleanup record and playlist
  destination from the redundant location's rows to the equivalent rows
  of the kept location (same physical file by relative-path mapping,
  confirmed by `same_file`), then removes the redundant location through
  §4's safe removal. Behind the Fix… action, show a confirmation dialog
  with counts.
- **§26.4** Rehearse on a copy (§0.7): keep `Music`, merge `x9-pro` and
  `Test` into it. Paste the counts: rows before and after, matches
  re-pointed, and **zero** matches lost. Then hand the real click to
  Kris, and add it to §41's checklist.

---

# Phase J — UI consistency (objective defects)

Reach for `frontend-design` (the "quality floor" and writing guidance)
in all three rows. Every UI row, here and in Phase K, pastes before and
after screenshots made with the harness that §27.0 builds. The audit
rendered every page with `FakeApplication` demo data at 1280×820 and
960×640, in both themes.

## §27 — Theme defects with one root cause; focus and accessibility (S27)

*Findings: A-29, A-47.*

**Established.**
- **Background banding.** `theme._base_qss` sets
  `QWidget { background-color: BG_APP }`, which every nested `QWidget`
  matches, `QCheckBox` and `QRadioButton` included.
  `#cellWidgetContainer { background: transparent }` covers only the
  `cell_widget` container. Visible results:
  - two-tone table rows, with the Progress and Actions cells on
    `BG_APP` while the rest of the row is `BG_SURFACE` (very visible in
    the light theme);
  - dark boxes behind the "Keep all" and "Confirm delete" labels in
    Duplicates;
  - a band behind every radio and checkbox row in Settings.
- **No combo arrows.** `QComboBox::drop-down { border: none; }` with no
  `::down-arrow` image leaves combos arrowless (Duplicates' location
  picker, History's "Show"), so they read as text fields.
- **Button sizing.** Buttons stretch full width in Settings, the wizard
  and Duplicates, but are compact elsewhere.
- **Invisible focus.** No `:focus` style exists for buttons, so
  keyboard focus is invisible outside text inputs.
- **Accessible names.** Zero `setAccessibleName` calls. The
  custom-painted, icon-only theme toggle is unnamed, and per-row
  "Confirm" and "Reject" buttons carry no row context.
- **Heavy splitters.** Review's splitter handles are 6 px full-width
  `BORDER_STRONG` bars.
- **Low contrast.** Progress text in the light theme is dark on violet.

**Do.**
- **§27.0** Build the screenshot harness first. `docs/screenshots/
  generate.py` imports fakes from a test module (fixed in §18), calls
  private page methods, and gives its demo review candidate
  `score=0.91` on a 0–100 scale. Replace it with `tools/screenshots.py`:
  - one fixed demo dataset, covering every track status, active and
    failed downloads, review items and history;
  - every page, both themes, at 1280×820 and 960×640, written to a
    gitignored `tools/.screens/`;
  - a `--readme` mode that writes the committed README images to
    `docs/screenshots/`.
  Document the command in `docs/README.md`. The audit's version of this
  harness rendered 48 images in a single offscreen run.
- **§27.1** Scope the page background to real surfaces (the main window,
  dialogs, and page roots), and make generic `QWidget`, `QCheckBox` and
  `QRadioButton` transparent. Pixel-sample tests follow the §103
  pattern: a cell-widget pixel equals the row's pixel, in both themes.
- **§27.2** Draw the combo arrow with a small theme-aware SVG chevron,
  bundled through the `_MEIPASS` pattern.
- **§27.3** Button sizing rule: buttons take their size hint and never
  stretch, unless a layout explicitly asks for a full-width primary.
  Fix the offenders.
- **§27.4** Add a visible focus ring for buttons, checkboxes, radios and
  tabs. Add accessible names to icon-only controls, and row-contextual
  names ("Confirm Nova Reyes – Voltage Drop") to per-row buttons.
- **§27.5** Slim the splitter handles to a 1 px line with a wider grab
  area. Fix the progress text contrast; §31 later re-verifies it
  against the new palette.

## §28 — Tables, empty states, copy (S28)

*Findings: A-48, A-49.*

**Established.**
- **Column allocation.**
  - Downloads: Progress takes about 620 px while Track, Playlist, Role
    and Status wrap to three lines.
  - History: Detail stretches while Track truncates.
  - Headers are centred over left-aligned content.
- **Clipped playlist names.** The Dashboard's playlist list clips long
  names behind a horizontal scrollbar instead of eliding them.
- **Missing empty states:** Search results, both Sharing tables, an
  empty History, and the empty Review sections.
- **Dismiss control.** The next-step notice dismisses with a boxed
  letter "X".
- **Jargon.**
  - Downloads shows "Role: Settled/Upgrade", "Retrying
    (locked/queued)" and "Unavailable (gave up retrying)".
  - Library says "Fill missing art URLs".
  - The wizard says "…same as the CLI".
  - The Dashboard offers both "Rescan and match library" and "Re-match
    library".
  - The Search subtitle is awkward.
  - Help says "has this playlist's tracks been loaded".
  - Help shows the build time as raw ISO with microseconds; §39 fixes
    the stale value.
- `ui/help_text.py` holds the copy.

**Do.**
- **§28.1** Column policy in `theme.ColumnLayout`: the primary text
  column (Track or Filename) stretches; the others size to content with
  floors; headers align with their content. Apply it to every table.
- **§28.2** Elide long names with a tooltip; no horizontal scrollbar on
  the playlist list.
- **§28.3** Empty states: one shared component (an icon, one sentence,
  and an optional action) on every table listed above. Follow
  frontend-design's rule: "an empty screen is an invitation to act".
- **§28.4** Copy pass over `help_text.py` and inline strings: plain
  verbs, sentence case, user vocabulary. Drop the Role column in favour
  of an "Upgrade" badge. Replace the "X" with a proper close control.
  Format the build time. Keep the button labels and result notices
  consistent ("Refresh playlists" reports "Refreshed…").

## §29 — Review and Settings information architecture (S29)

*Findings: A-12, A-30.*

**Established.**
- **Review, SoulSeek table.** The candidate cell renders only
  `f"{quality_descriptor} — {username}"`. The winner's filename appears
  nowhere, not even in a tooltip; the runner-up does get one.
- **Review, local-match table.** It shows the path, location and score,
  but not the `tag_artist`/`tag_title` that `NeedsReviewMatch` carries
  for exactly this judgement.
- **Row height.** At 1280×820 the first Review table's rows stretch to
  about 95 px, while the other tables are normal.
- **Section titles** show no counts.
- **Settings tabs:** Library Locations, Playlist Destinations,
  Connection, Thresholds. **Appearance, Menu Bar Notifications and
  Startup all live under Thresholds.** The thresholds are full-width
  `QLineEdit`s with no range or ordering validation.
- **Library page.** The two checkboxes (options) share one wrapping row
  with five action buttons, and about 70 % of the page is empty.
  "Tag selected" acts on the Dashboard's selection, which is not visible
  from Library.

**Do.**
- **§29.1** Review:
  - SoulSeek candidates show the file's basename as the primary text,
    with quality and peer as secondary text, and the full remote path in
    a tooltip;
  - local matches show "Tags: artist – title";
  - fix the row height;
  - show counts in the section titles.
- **§29.2** Settings tabs become **General** (Appearance, Startup,
  Notifications), **Library** (locations plus destinations),
  **Connections** (Spotify, SoulSeek) and **Matching** (thresholds, as
  `QDoubleSpinBox` 0–100 with needs-review strictly below auto,
  enforced). `select_tab` callers and the wizard shortcuts keep working;
  add a test that every `SETTINGS_TAB_*` still resolves.
  - `_on_save_thresholds_clicked` checks only that the values are numbers
    and correctly ordered. Auto 10 with needs-review 5 is accepted, and
    it auto-matches almost anything; "Tag playlist" would then write
    Spotify metadata onto wrong files, the harm the thresholds exist to
    prevent. Bound both values to 0–100, and show an inline warning
    (don't forbid) when auto drops below the shipped default's
    neighbourhood, for example below 80, naming the consequence.
  - Settings is reachable from the sidebar **and** has its own
    "← Back" button: two navigation models on one page. Keep one.
    The recommendation is the sidebar only, with the Back button
    removed, unless a test shows the Back button carries state the
    sidebar does not (for example, returning to a specific page). Say
    which you chose and why.
- **§29.3** Library:
  - options sit in their own group;
  - actions are grouped by job (Tags, Cover art, File names), each with
    one sentence of explanation;
  - "Tag selected" names what is selected ("Tag 3 selected on
    Dashboard"), or is disabled with a tooltip when nothing is.
  The full visual treatment comes in §34.

---

# Phase K — Visual refresh (approved)

Reach for `frontend-design` in every row: ground the design in the
subject, spend boldness in one place, and critique screenshots.

## §30 — [ASK KRIS] Visual direction (S30)

*Finding: A-51. This row produces a decision document and screenshots,
and no merged product code.*

**Brief.**
- **Subject:** a DJ's library tool; a DJ's own playlists, library, and
  the SoulSeek network.
- **Audience:** DJs who prepare sets on a Mac, often in the dark.
- **Primary job:** see what a set is missing, and get it into the
  library correctly tagged.
- The current theme is the generic "near-black with one violet accent"
  pattern the skill warns about, and `theme.py`'s own docstring calls
  the light palette "UNTUNED — a real designer's pass … hasn't happened
  yet".

**Do.**
- **§30.1** Render **two** grounded directions on the real app: palette
  variants behind a scratch environment variable, screenshots of the
  Dashboard, Review, the wizard and Settings in both themes. Start from
  these and refine; do not copy them blindly:
  - **"Booth":** neutral graphite rather than purple-tinted surfaces.
    CDJ hardware language: amber for "cue" (in progress), green for
    "play" (in library), LED-style status dots instead of text-only
    status, and segmented, meter-style progress bars. Condensed panel
    lettering for page titles, for example an OFL face such as Barlow
    Semi Condensed.
  - **"Harmonic":** Seeker already computes Camelot keys and BPM
    (`local_files.camelot_key`, `bpm`). Make the Camelot wheel's
    12-hue key colours the one bold element: key chips in the track
    table, and a small wheel mark in the wordmark. Everything else stays
    quiet and neutral, with one cool accent.
- **§30.2** Write `docs/design/visual-direction.md`:
  - tokens for each direction: 4–6 named colours per theme, the type
    roles and scale, spacing, radius;
  - WCAG contrast numbers, computed with `theme.contrast_ratio`;
  - the icon set proposal: one open-source set with a licence that
    allows bundling, for example Lucide (ISC) or Phosphor (MIT);
  - the screenshots;
  - your recommendation.
  Show BPM and key on the Dashboard only if Kris wants them; that is
  part of the decision.
- **§30.3 STOP.** Kris picks a direction, a mix, or neither. §31–§36
  start only after that answer, and the answer is recorded in the
  document.

## §31 — Refresh foundation: tokens, type, palette accessor (S31)

**Established.**
- `Palette` (a frozen dataclass) is the source of truth.
- A back-compat bridge, `_set_module_tokens`, reassigns module-level
  names (`theme.ACCENT`, …) on every theme switch, for "~60 existing
  call sites". Only **2** production reads remain
  (`_ThemeToggleButton.paintEvent`'s `TEXT_MUTED`, in `ui/widgets.py`
  after §20.2, and
  `dashboard_page`'s `QColor(theme.ACCENT)`), plus 34 in the tests.
- There are no inline stylesheets and no hex colours outside
  `theme.py`.

**Do.**
- **§31.1** Implement the approved tokens in `DARK` and `LIGHT`. Keep the
  contrast tests, extend them to the new status colours, and keep them
  green.
- **§31.2** Replace the bridge with `theme.active_palette()`. Migrate the
  2 production reads and the 34 test reads, and delete
  `_set_module_tokens` and its docstring.
- **§31.3** If a typeface was approved: bundle it (OFL, with its licence
  file), register it with `QFontDatabase.addApplicationFont` through the
  `_MEIPASS` pattern, and add it to `seeker.spec`'s datas. Set the type
  scale as tokens.
- **§31.4** Add the status colour system as tokens, used by §32–§35.

## §32 — Refresh: the shell (S32)

Sidebar navigation icons (the approved set, theme-aware SVGs through the
`_MEIPASS` pattern), the wordmark and logo treatment, the page header
(title and subtitle), the activity strip and the notices. Every
`_NAV_PAGES` entry gets an icon, and the Help, Support and Settings
entries get icons of their own. Take screenshots in both themes.

## §33 — Refresh: onboarding wizard (S33)

*The first impression.*

**Established.**
- Content sits about 9 px from the window edge.
- There is no branding, welcome or step indicator.
- Every button is full width.
- Two-thirds of the window is empty.
- The Spotify step explains app registration in one sentence.
- "Docker is running." is plain text.
- The SoulSeek step's copy mentions the CLI.

**Do.** Redesign it as:
- a centred column of at most about 560 px;
- a step indicator (3 required-then-optional steps, since this content
  really is a sequence);
- numbered sub-steps for registering the Spotify app;
- status chips for the Docker and slskd states;
- one primary action per step.
Keep every existing wizard test's behaviour, and update the widget
lookups.

## §34 — Refresh: Dashboard and Library (S34)

- **Dashboard.** The approved status system replaces the link-styled and
  plain status text. Playlist rows show counts, such as "30 · 7
  missing". There is a clear primary action, and BPM and key appear if
  Kris approved them in §30.
- **Library.** Show the selected playlist's tracks with their tag state
  (tagged, untagged, missing art), so "Tag selected" has something to
  select on this page. The action groups from §29.3 are styled as the
  approved components.

## §35 — Refresh: remaining pages (S35a, S35b)

- **S35a:** Search (a compact form row, results with the filename first,
  empty state), Downloads (§28's columns, status system, failures from
  §8), History, and Duplicates (visual group separation).
- **S35b:**
  - Review (§29's information, restyled);
  - Sharing: counts and tables first; the five-paragraph "Why this page
    exists" collapses behind a "How sharing works" disclosure,
    remembered per viewer;
  - Help and Support;
  - Settings (§29's tabs, restyled).

## §36 — README images and final visual QA (S36)

**Established.** The committed README images date from 2026-09-09,
before round 9's Library header and before round 10, and the visual
refresh changes every page again.

**Do.**
- Run `tools/screenshots.py --readme` (from §27.0) and commit the new
  images: the Dashboard in both themes, Review, Duplicates, Library, and
  the wizard's first step.
- Sweep every page in both themes at both sizes for leftovers: clipping,
  misalignment, unstyled widgets, copy that the earlier rows missed.
  Fix small nits in this row. List larger ones as new rows in the
  handoff; do not widen this row.

---

# Phase L — Docs

## §37 — README and developer docs (S37)

*Finding: A-50. Reach for `codebase-onboarding`.*

**Established.**
- The README is 741 lines: "Building a standalone app" 227, "Project
  layout" 125 (duplicated in CLAUDE.md), "What it does" 104.
- Its badges are static and stale ("tests-1,150" against 1,204).

**Do.**
- **§37.1** A README under about 200 lines:
  - what Seeker is and who it is for, in plain words;
  - one hero screenshot;
  - features;
  - install: download the DMG from Releases (after §42), or run from
    source;
  - quick start;
  - an architecture summary with a small diagram;
  - quality: a live CI badge replaces the static test and lint badges;
  - links onward.
- **§37.2** Move the depth into `docs/`:
  - `docs/architecture.md`: the layering, a module map (the **one**
    canonical layout; CLAUDE.md links to it), the download state
    machine, the data flow, and the threading model (workers and the
    dispatcher);
  - `docs/cli.md`: the command reference;
  - `docs/packaging.md`: building and signing. The Windows and Linux
    sections keep their "written, never verified on real hardware"
    labels, per Kris's decision.
- **§37.3** `docs/README.md` links all of these.

## §38 — CLAUDE.md refresh (S38)

*Finding: A-45.*

**Do.**
- **Current layout:** link `docs/architecture.md` instead of keeping a
  second copy. Keep a 10-line map at most.
- **Open issues:** verify each one against the last 50 CI runs (`gh run
  list --limit 50 --json conclusion,headSha`) and against this round's
  fixes; close what is closed (moving the detail to HISTORY first,
  working agreement 1). Record the item-70 lead from §22.
- **Roadmap:** only what is still forward-looking.
- **Conventions:** add every new rule this round introduced (§0.7
  real-data safety, the error text layer, `DownloadStatus`, the
  compose-template rule, the comment rule), each with its HISTORY link.
- **Length:** CLAUDE.md is about 39 KB today. Target under 30 KB,
  without dropping any standing fact.

---

# Phase M — Release (approved)

## §39 — Release engineering (S39)

*Findings: A-26, A-27, A-28. Reach for `changelog-generator` and
`runbook-generator`.*

**Established.**
- **Stale build identity.** `src/seeker/_build_info_generated.py`
  (gitignored), left over from the last `packaging/build_dmg.py` run,
  makes every later run from source report that build (the Help page
  shows `d38d80f` at HEAD `378646a`). The module's own docstring
  promises the opposite.
- **Info.plist** (`packaging/seeker.spec`):
  - `CFBundleShortVersionString` and `CFBundleVersion` hard-code
    `"0.1.0"`, a second copy of `pyproject.toml`'s version;
  - `bundle_identifier="com.seeker.app"`;
  - `NSHumanReadableCopyright` is empty (LICENSE: "Copyright (c) 2026
    Kristiyan Dimitrov");
  - there is no `LSApplicationCategoryType` and no
    `LSMinimumSystemVersion`.
- **Gatekeeper.** `packaging/Read Me First.txt` and the README tell users
  to right-click → Open. **Hypothesis:** macOS 15 and later removed that
  override, and users must choose System Settings → Privacy & Security →
  Open Anyway. The host runs macOS 26, and §41 verifies this on a
  quarantined download.
- **Version metadata.** `seeker-0.1.0.dist-info` **is** bundled, so the
  frozen update check can read its version, and `Version("v0.1.0")`
  parses.

**Do.**
- **§39.1** `_build_info` imports the generated module only when
  `sys.frozen` is set; `build_dmg.py` deletes the generated file in a
  `finally` after bundling. Format the build time for people.
- **§39.2** The spec reads the version from `pyproject.toml`. Fill in
  the copyright, `public.app-category.music`, and a minimum system
  version (use the lowest macOS the bundled PySide6 supports; check it).
- **§39.3 [ASK KRIS]** The bundle identifier. Recommend
  `io.github.kristiyanddimitrov.seeker`. It must change before the first
  release: the login item, notification permission and Launch Services
  all key on it, and Kris's own login-item registration must be redone
  once.
- **§39.4** Rewrite the Gatekeeper instructions for current macOS, with
  both paths (Open Anyway, and removing the quarantine attribute for
  advanced users), marked "verified on macOS 26 in §41".
- **§39.5** Add `CHANGELOG.md` in Keep a Changelog format, with v0.1.0
  summarising the product (not the rounds), and `RELEASING.md`:
  - build;
  - verify: `codesign -dvvv`, `spctl -a -vv` expected to reject an
    unnotarized build, and a checksum;
  - tag;
  - `gh release create` with the DMG and its SHA-256;
  - verify "Check for updates…";
  - rollback (delete the release, keep the tag or retag).

## §40 — Automatic update check (S40)

*Approved by Kris on 2026-09-29, in the shape round 9 §4.2b proposed:
opt-in, at most once every 24 hours, at startup only, off the UI
thread, silent on failure, with a Settings toggle that defaults to off.*

**Established.** `update_check.check_for_update()` never raises and
already returns `UP_TO_DATE`, `UPDATE_AVAILABLE`, `UNAVAILABLE` or
`NO_RELEASES_PUBLISHED`. Today it runs only from Help → Check for
updates….

**Do.**
- Add `SeekerConfig.auto_update_check: bool = False` and
  `last_update_check_at: str | None`, with the all-fields round-trip
  test from §9.6.
- A startup hook runs the check off the UI thread when enabled and more
  than 24 hours have passed.
- Every non-`UPDATE_AVAILABLE` outcome stays silent (logged at INFO).
  An available update produces one tray notification plus a Help menu
  badge.
- The toggle lives in Settings → General (§29).
- Tests cover every status.

## §41 — Release-candidate acceptance (S41) — Kris and Code

**Code prepares.**
- A release-candidate build from the tip, with its checksum.
- A single checklist in the handoff.
- Every automatable check scripted: System Events for the fullscreen
  and geometry paths (round 10 §5 recipes, `grep -n "AXFullScreen"` in
  the history), and a `docker compose config` of the per-user copy.

**Kris runs, in a fresh macOS user account:**
1. Download and open the DMG. Walk the Gatekeeper flow and confirm
   which instructions are true on macOS 26.
2. The wizard end to end: Spotify, the library, and SoulSeek with Docker
   (the live test of §5's portable template).
3. Sync, scan, a real download, tag, rename.

**Kris runs, on Kris's own account:**
- the §26 nested-location Fix… (the real click);
- the §4 limbo tracks re-matching after a scan;
- `SEEKER_RUN_STRESS_TEST=1 uv run pytest tests/test_stress_e2e.py`
  (the item-70 lead from §22, and the lifecycle change from §20);
- the three fullscreen and geometry paths (round 10 §5);
- start at login on the packaged app (round 9 §3.2);
- `http://<mac-lan-ip>:5030` must not answer from a second device;
- the Review splitter and Library header on a real display, both
  themes.

Any failure becomes a fix row before §42. Do not ship around it.

## §42 — Publish v0.1.0, close the round (S42)

**Do.**
- Follow `RELEASING.md`, in this order:
  1. `git tag v0.1.0` on the release commit;
  2. build from exactly that commit, with a clean tree;
  3. checksum the DMG;
  4. push the tag;
  5. `gh release create` with the DMG, its SHA-256 and the notes.
  Steps 4 and 5 are outward-facing: show Kris the exact commands and the
  release notes, and run them only after an explicit yes.
- Verify "Check for updates…" against the real release (`UP_TO_DATE`).
- Point the README install section at the release.
- Close the round: the final HISTORY entry, the CLAUDE.md roadmap, and
  a handoff stating that the round is complete and naming any
  [ASK KRIS] items never answered.

---

# Optional rows (unscheduled) — [ASK KRIS]

## §X1 — Clean up leftover slskd downloads

*Finding: A-52.* The dev slskd download folder holds 728 MB in 24 files
that Seeker never moved: superseded attempts, failures, and 11 `_<ticks>`
duplicates. Nothing ever removes them. Proposal:
- a Downloads-page action, "Clean up leftover files…";
- it lists files in slskd's download and incomplete folders that no
  pending or ready-for-review request references;
- sizes are shown, with explicit confirmation;
- it deletes nothing that an active transfer uses.

## §X2 — Retry and cancel on the Downloads page

*Finding: A-53.*
- **Retry** on `failed` and `unavailable` rows re-requests the same
  candidate, or runs a fresh search if Kris prefers.
- **Cancel** on `queued` rows calls slskd's transfer-cancel endpoint;
  verify it against the live slskd, read-only first.

---

# Appendix A — Probe scripts

All probes run against throwaway databases and files. Replace `$SP`
with your scratchpad directory. Each block ran on `378646a` and printed
the output shown.

**A.1 — Same-name upgrade with "Delete old file" loses the track (§3).**

```python
# Setup: library P/Artist - Song.mp3 ("OLD"), slskd Music/Artist - Song.mp3 ("NEW"),
# track t1 auto-matched to the old file, request role=upgrade status=ready_for_review.
svc = DownloadService(db, None, pl, tr, loc, dr, tm, lf, rc, str(B/"slskd"))
msg = svc.apply_upgrade_decision(req.id, replace=True, delete_old=True)
# printed:
#   Replaced with …/lib/P/Artist - Song.mp3
#   Deleted …/lib/P/Artist - Song.mp3
#   file on disk exists: False
#   local_files rows: [(1, 'P/Artist - Song.mp3')]
#   track_matches: [('t1', 1, 'auto')]
```

The full setup: create the repositories on `Database(B/"p.db")`, add
location `Lib` at `B/"lib"`, save playlist `p1` with destination
`(Lib, "P")`, save track `t1`, then
`replace_playlist_tracks("p1", ["t1"])`. Index the old file with
`index_single_file(loc, "P/Artist - Song.mp3", lf, c)` and upsert its
auto match. Add the `DownloadRequest(track_id="t1", username="peer",
filename="@@peer\\Music\\Artist - Song.mp3", format="mp3",
role="upgrade", status="ready_for_review", size=17, …)`.

**A.2 — Overwrite and wrong-file pick (§3).**

```python
(base/"lib/01 - Intro.mp3").write_text("USER'S EXISTING FILE (different song)")
(base/"slskd/AlbumA/01 - Intro.mp3").write_text("download for track A")
(base/"slskd/AlbumB/01 - Intro.mp3").write_text("download for track B")
matches = list((base/"slskd").rglob(glob.escape("01 - Intro.mp3")))
# ['slskd/AlbumB/01 - Intro.mp3', 'slskd/AlbumA/01 - Intro.mp3']
shutil.move(str(matches[0]), str(base/"lib/01 - Intro.mp3"))
# library file now contains: download for track B
```

**A.3 — Confirmed match left in limbo (§4).**

```python
svc.add_location("Lib", str(B/"lib")); svc.scan_all()
tm.upsert(TrackMatch("t1", fid, "needs_review", 75.0, "x"), c); svc.confirm_match("t1")
f.rename(B/"lib/A/Moved in Finder.mp3")
svc.scan_and_match()
# {'added': 1, 'removed': 1, 'auto': 1, 'needs_review': 0, 'unmatched': 0, ...}
# track_matches: [('t1', None, 'auto', 1)]
# get_unmatched_for_playlist: []
```

**A.4 — Removing a destination location crashes (§4).**

```python
locs.add(LibraryLocation(name="Lib", path=..., added_at="x"), c)
pls.save(Playlist(id="p1", name="P", track_count=0, snapshot_id=None), c)
pls.set_destination("p1", loc.id, None, c)
locs.delete(loc.id, c)   # IntegrityError: FOREIGN KEY constraint failed
```

**A.5 — Spotify duplicates and local files (§6).**

```python
def item(tid, name, is_local=False):
    return {"item": {"type": "track", "id": tid, "name": name, "is_local": is_local,
            "artists": [{"name": "A"}], "album": {"name": "Al", "images": []},
            "duration_ms": 1000}}
class StubClient(SpotifyClient):
    def __init__(self, entries): super().__init__("tok"); self.entries = entries
    def _get_all_pages(self, url, params=None): return self.entries
# [item("t1","x"), item("t1","x")] → IntegrityError UNIQUE constraint failed:
#     playlist_tracks.playlist_id, playlist_tracks.track_id
# [item("t2","y"), item(None,"my_local.mp3", True)] → IntegrityError NOT NULL
#     constraint failed: playlist_tracks.track_id
```

**A.6 — SQLite host-parameter limit (§7).**

```python
c = sqlite3.connect(":memory:")   # sqlite 3.53.1
c.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)   # 32766
c.execute(f"delete from t where a not in ({','.join('?'*32767)})", [...])
# OperationalError: too many SQL variables
```

**A.7 — Relative and `~` paths (§7).** `svc.add_location("Music",
"./Music")` stores `'Music'`. `svc.add_location("Home", "~")` raises
`LibraryUnavailableError: Library path ~ does not exist … drive … may
not be connected`.

**A.8 — Unencoded usernames (§9).**

```python
httpx.URL(f"http://localhost:5030/api/v0/transfers/downloads/{user}/1234")
# 'what?ever'            → path '/api/v0/transfers/downloads/what'  query b'ever/1234'
# 'hash#tag'             → path '/api/v0/transfers/downloads/hash'  fragment 'tag/1234'
# '../../../application' → path '/api/application/1234'
```

**A.9 — Production symbols never referenced in `src/` (§16).**
Tokenize every `src/**/*.py` file and count `NAME` tokens, plus
identifier-shaped short strings, for `getattr` and Qt string lookups.
For each `def`, `class` and upper-case module constant, report the ones
whose `src` count is 1 (only the definition), together with their count
in `tests/`. On `378646a` it printed: `hamming_similarity` (tests 4),
`get_active_for_track` (0), `save_playlist_track` (20),
`wait_for_callback` (2), `format_speed` (4),
`DUPLICATES_FOLDER_NOT_IN_A_LOCATION` (0), `contrast_ratio` (13),
`debug_snapshot` (1).

**A.10 — Comment-archaeology count (§24, §25).**

```bash
grep -rnoE "(round [0-9]+|Round [0-9]+|§[0-9]+(\.[0-9]+)*|Roadmap item [0-9A-Z.]+|item [0-9]+)" src/ | wc -l
# 1025 on 378646a; report per file with: grep -rlE … | xargs -I{} sh -c 'echo "$(grep -cE … {}) {}"' | sort -rn
```

# Appendix B — Real-data snapshot (read-only, 2026-09-29)

- **Real paths:**
  - database: `~/Library/Application Support/Seeker/seeker.db` (38 MB,
    `journal_mode=delete`);
  - config: `config.json` (0600); token: `spotify_token.json` (0600);
  - log: `~/Library/Logs/Seeker/seeker.log` (442 B, last written Sep 10).
- **Counts:**
  - 215 playlists, 57 tracks (1 manual, orphaned), 56 `playlist_tracks`;
  - 4 locations, 6,921 `local_files` (3,655 fingerprinted, 32.6 MB of
    fingerprint text);
  - 52 `track_matches` (2 in limbo), 0 SoulSeek review candidates;
  - `download_requests`: completed/settled 8, failed/settled 5,
    superseded/upgrade 4, unavailable/settled 1, unavailable/upgrade 3.
- **Album-art URL host:** `i.scdn.co` (56 of 56).
- **Dev slskd folder** (`<repo>/slskd-data/downloads`, gitignored):
  728 MB in 24 files, 11 of them `_<ticks>` duplicates.
