# Round 12 — Kris's walkthrough, a security re-audit, and the release

**Author:** planning chat, 2026-10-08. **Executor:** Claude Code.
**Base commit:** `eacdfc1` (round 11 S38 handoff; tree clean apart from
the untracked `Claude outputs/`). **Session map:**
`docs/rounds/round-12/SESSION-PLAN.md`.

Round 11 ended at S38 with four release rows and two optional rows
left. Before the release, Kris used the app by hand and reported nine
items. This round fixes those, re-audits security, builds the daily
sweep Kris thought already existed, and then runs the carried release
rows. Carried rows keep their round-11 text: this brief points at
`docs/rounds/round-11/BRIEF.md` (written as "R11 §N") and does not
copy it.

Read your row in the session map, then **only** §0 and the sections
that row points at. Line numbers are hints from `eacdfc1`: `grep -n`
the named symbol before trusting one.

Each section separates what is **established** (read in code,
reproduced or measured during planning, with the evidence) from what
is a **hypothesis** (your job to confirm or rule out before building
on it).

---

## §0 — Ground rules

**R11 §0.1–§0.10 apply unchanged:** read discipline, approval gates,
one commit per numbered item, a failing test first, the three
numbers, a HISTORY entry for every row, real-data safety, hard-stop
verification gates, no history archaeology in comments, and scratch
work that stays outside the repository. Read R11 §0 once at the start
of your row: `sed -n 19,83p docs/rounds/round-11/BRIEF.md`.

Additions for this round:

**§0.11 Kris's answers (2026-10-08).** These are decisions; do not
ask again.
- **Daily sweep:** opt-in, so the Settings toggle defaults to off. At
  most once every 24 hours while Seeker runs, it searches again for
  missing tracks in loaded playlists. Paced, logged, and it sends one
  tray summary (§10).
- **Status order:** closest to done first. In library → Downloading
  → Retrying → Awaiting review → Needs review → Candidate to review →
  Not found (§4).
- **Bundle identifier:** `io.github.kristiyanddimitrov.seeker`. This
  answers R11 §39.3's gate (§16).
- **X1 and X2:** both are in (§12, §13).
- **Visual choices** (selection colour, the amber tone) are Code's to
  make. Kris said "whatever else you see fit". Show the before and
  after screenshots in the HISTORY entry.

**§0.12 HISTORY numbering continues at §193.** Append entries to
`docs/history/181-210.md`. When §210 is reached, start
`211-240.md` the way S2 of round 11 defined.

**§0.13 Every visual change gets screenshots.** Run `uv run python
tools/screenshots.py`. Read the affected screens in both themes
before the change and after it, and name them in the HISTORY entry.
Planning found that the harness writes 78 PNGs to `tools/.screens/`
in about two minutes.

---

# Phase A — Kris's walkthrough

## §1 — Theme colours: dark-mode selection, the light-mode amber (S1)

*Reach for `frontend-design`. Read `src/seeker/ui/CLAUDE.md` first.*

**Established.**
- **Selected text in dark mode turns near-black.** `build_qpalette`
  (`theme.py:936`) sets `Highlight` to `ACCENT` (`#9A7DFF`) and
  `HighlightedText` to `ON_ACCENT` (`#120E1F`). `ON_ACCENT` is
  deliberately dark ink, because it sits on a lit button. Any widget
  that takes the palette's selection instead of a QSS
  `selection-color` therefore draws near-black text on a bright
  violet: selectable `QLabel`s and probably more. Inputs are worse.
  The field rule (`theme.py:1281–1287`, covering `QLineEdit`,
  `QComboBox`, both spin boxes and `QPlainTextEdit`) sets
  `selection-background-color: ACCENT_SUBTLE` (`#262236`, nearly the
  field's own colour) but sets **no** `selection-color`. The text
  therefore falls back to `HighlightedText`, near-black on
  near-black. This is almost certainly what Kris saw. The rules at
  `:1314` and `:1329` set both and are fine.
- **The light-mode amber reads brown.** `LIGHT.WARNING` is `#9E5C00`.
  It is chosen dark enough to pass text contrast on a light surface,
  and the same token fills the cue lamps and the progress meter
  (`style_meter`, `set_busy_meter`). Planning saw it in
  `dashboard-light-1280x820.png` and `downloads-light-*.png`: the
  meter segments look brown, not amber.

**Hypothesis.** A non-text mark (a lamp or a meter segment) only needs
3:1 against its background under WCAG 1.4.11, while text needs 4.5:1.
One token is serving both thresholds, and that is why it is dark.

**Do.**
- **§1.1** Selection: decide one selection pair for each theme and
  apply it everywhere. That covers the `Highlight`/`HighlightedText`
  palette roles and every QSS `selection-*`, including the
  `selection-color` missing from the field rule. In dark mode, aim
  for light text on a mid violet, visibly distinct from the field. `test_theme.py` asserts the contrast pair, at
  4.5:1 or better. The failing test first: a selected `QLineEdit` in
  dark mode, painted, gives a `HighlightedText` contrast below 4.5:1
  against `Highlight`, or a near-black text colour.
- **§1.2** Amber: split the lamp and meter fill from the text-grade
  warning. Use a new token, `CUE` (or similar), held to at least 3:1
  against `BG_SURFACE`. Choose a warmer, more golden amber in light
  mode. `WARNING` keeps the text role. `test_theme.py` asserts both
  pairs. Check every `WARNING` use (`git grep -n "WARNING"
  src/seeker/ui`) and move each one to the token that matches its
  role.
- Screenshots for both themes go in the HISTORY entry (§0.13).

## §2 — "Follow system" applies at once; spin-box arrows in dark mode (S2)

**Established.**
- **The theme does not follow the system when it should.**
  `apply_theme` (`theme.py:988`) calls `resolve_palette(mode)` at
  line ~1013, *before* it resets the style hints with
  `setColorScheme(Qt.ColorScheme.Unknown)` at ~1025. Suppose the app
  is in Dark and the OS is Light. Choosing "Follow system" then
  resolves `"system"` by reading `styleHints().colorScheme()`, which
  still reports the override, Dark. So the palette stays dark until
  the OS scheme changes.
- **The spin-box arrows don't show in dark mode.** On Settings →
  Matching, the two `QDoubleSpinBox`es show dark buttons with no
  visible arrow in `settings-matching-dark-960x640.png`. `theme.py`
  styles `QSpinBox`/`QDoubleSpinBox` as a field (`:1281`) but has no
  `::up-arrow`, `::down-arrow`, `::up-button` or `::down-button`
  rule. `QComboBox::down-arrow` gets a palette-drawn chevron file
  (`combo_chevron_path`), and the spin box has no equivalent.

**Hypothesis.** The theme ordering above is the whole cause.
Confirm it with a test before fixing.

**Do.**
- **§2.1** The failing test first: set the theme to dark while the
  system reports light, then switch to "system". The applied palette
  must be `LIGHT`. Offscreen never emits `colorSchemeChanged`
  (CLAUDE.md, Testing), so stub the platform scheme the way
  `test_theme.py` already does. Fix it by clearing the override
  before resolving, or by reading the platform's own scheme rather
  than the overridden hint. Check the main-window re-entrancy guard
  (`main_window.py:211–220`, `_apply_theme_mode`), which is there
  for exactly this signal.
- **§2.2** Spin-box arrows: add up and down chevrons through
  `_palette_icon`, the way the combo box does: one file per palette,
  drawn in `TEXT_MUTED`, plus a hover and pressed state for the
  buttons. The failing test first: grab a spin box in dark mode and
  assert that the arrow region contains pixels contrasting with the
  button at 3:1 or better. While you are there, the field shows
  `90,0` (locale decimal comma) on a Mac set to a comma locale, but
  Review prints scores as `72.6`. Pick one, using `QLocale.c()` on
  the spin box or the system locale everywhere. Record which and why.

## §3 — Review's tooltips stay until the pointer moves (S3)

**Established.** The tooltips on Confirm, Reject, Replace and
Decline disappear after one or two seconds. `ReviewPage`'s
`poll_review_items` (`review_page.py:334`) runs on the 2-second
display timer. `_render_review_items` rebuilds all three tables on
every tick (`setRowCount` plus a new cell widget per row), even when
nothing changed. The button under the pointer is destroyed, and its
tooltip goes with it.

**Do.**
- **§3.1** The failing test first: render the same data twice. A
  row's Confirm button must be the *same* object after the second
  render. It is a new object today.
- **§3.2** Rebuild a table only when what its rows were built from
  has changed. The Dashboard already does this with `_RenderedRows`
  (ui/CLAUDE.md, "rebuilds only when what its rows were built
  from changes"). Use the same shape: a key per table, made of its
  rows' identities and the active palette. Counts, the nav badge and
  the tray counts still update on every tick.
- Audit the other 2-second pollers (Downloads and the others) for
  the same unconditional rebuild under a tooltip-bearing widget.
  Fix any you find the same way, one commit each, or list them in
  the handoff.

## §4 — Status columns sort by progress, not alphabetically (S4)

**Established.** The Dashboard's Status column is a plain
`QTableWidgetItem(_STATE_LABELS[status.state])`
(`dashboard_page.py:959`), so ascending sorts alphabetically:
Awaiting review, Candidate to review, Downloading, In library, Needs
review, Not found, Retrying. The Downloads page's Status column very
likely has the same shape (`downloads_page.py`).

**Do.**
- **§4.1** The failing test first: sort the Dashboard by Status
  ascending and assert this order (§0.11): In library → Downloading
  → Retrying → Awaiting review → Needs review → Candidate to review
  → Not found.
- **§4.2** Define the order once, beside the states
  (`models/track_status.py`, a named ranking). Put a
  `SortKeyItem` (`ui/table_sort.py`) in the Status column. Keep it
  in step with the in-place progress update path (`:1051`), which
  already mutates sort keys.
- **§4.3** Downloads: the same treatment over `DownloadStatus`.
  Closest to done first: Completed → Downloading → Queued → Retrying
  (locked, shortlisted) → Ready for review → Failed → Unavailable. If
  the right order is not obvious, mirror the Dashboard's logic and
  record the order in HISTORY. Define it as a named mapping in
  `models/download_request.py`, never as a literal at the call site
  (CLAUDE.md, download states).
- `git grep -n "Status" src/seeker/ui/pages` for any other status
  column (History, Library), and treat each one the same way.

## §5 — The Support page: contact email, and support the artists (S5)

**Established.** `help_text.ABOUT_DIALOG_AUTHOR_LINE`
(`help_text.py:1431`) holds `kristiyanddimitrov@gmail.com`. The About
dialog and the Support page both show it. `tests/pages/test_dialogs.py:129`
pins it. Nothing else in the tracked tree (outside the history)
contains the address.

**Do.**
- **§5.1** The email becomes `kristiyanddimitrov@proton.me`, in the
  string and in its test. Check `SECURITY.md`, `README.md` and
  `pyproject.toml`'s authors in the same commit.
- **§5.2** A new first section on the Support page, above Donate.
  Its point: Seeker finds music but pays the people who made it
  nothing, so support them. Use the draft below unless it renders
  badly. Kris can veto the wording in the handoff.

  > **Support the artists**
  >
  > Seeker helps you find music. It pays the people who made it
  > nothing. You can.
  >
  > - **Buy the tracks you play out**, on Bandcamp, on Beatport, or
  >   straight from the label.
  > - **Go to their shows.** A ticket goes further than a stream ever
  >   will.
  > - **Wear the merch, buy the record.**
  > - **Credit them.** Tag the artist when you post a set, and answer
  >   the "track ID?" question.
  >
  > Every set you play is built on someone's late nights in the
  > studio. Keep them in it.

  Use a `RichLabel` with escaped data, a `theme.section_card`-style
  section as the page's other sections have, and
  `theme.reading_column` (ui/CLAUDE.md). Re-order the
  `SUPPORT_TAB_SUBTITLE` if it no longer leads. Add a test that the
  section exists, comes first, and contains no unescaped markup from
  data.
- Screenshots of Support in both themes (§0.13).

---

# Phase B — Security and code health

Kris asked for the app to be "absolutely secure, ordered, clean,
professional and manageable". No codebase is absolutely secure. What
this phase can deliver is a written threat model, every finding fixed
or consciously accepted with a reason, and the checks that keep it
that way enforced in CI. Say that plainly in the HISTORY entry.

## §6 — Security re-audit (S6): read-only, produces `AUDIT.md`

*Reach for `security-review`, `engineering-skills:security-pen-testing`,
`engineering-advanced-skills:dependency-auditor` and
`engineering-skills:adversarial-reviewer`. Read-only on `src/`.*

**Established.** Round 8 had a security brief
(`docs/rounds/round-08/SECURITY-BRIEF.md`). Round 11 hardened the app
in §9 (R11 §9.1–§9.8: atomic 0600 credential writes, the token
refresh lock, quoted slskd path segments, the album-art host
allowlist, the OAuth callback and its wait, config validation,
peer strings as plain text, Spotify 429 handling). It also hardened
CI and the supply chain in §10 (SHA-pinned actions, Dependabot,
`shiboken6` declared, ruff preview rules). Planning ran
`uvx pip-audit` over `uv export --no-dev` on `eacdfc1`:

```
urllib3 2.7.0   PYSEC-2026-4177 / -4176 / -4175   fix: 2.8.0
```

`urllib3` comes in through `requests` ← `pooch` ← `librosa`. CI has
no dependency-audit step: the workflow runs ruff, mypy and pytest
only. A quick grep found no `shell=True`, `verify=False`, `pickle`,
`yaml.load` or `eval` in `src/`, and 12 `subprocess` call sites.

**Do.** Write `docs/rounds/round-12/AUDIT.md`, numbered `S-NN`, each
finding with evidence, severity, an exploit sketch (the class of
problem, never a working exploit) and a fix row. At minimum, cover:
1. **A threat model:** assets (Spotify token, the slskd API key and
   both logins, music files, the DB), trust boundaries (remote
   Soulseek peers, slskd, Spotify, GitHub releases, the local user,
   other local users, the LAN) and entry points.
2. **Every `subprocess` call:** argument lists only, no
   user-controlled executable, and a resolved path where PATH
   matters (§44's launchd PATH merge).
3. **Every network call:** TLS and timeouts, redirects followed or
   not, response size caps (a malicious peer, or slskd, returning
   huge bodies), and the update check's trust in GitHub's
   response.
4. **The filesystem:** peer-supplied filenames on every path
   (placement, rename, tag write), symlink following on delete,
   rename and move, temp files, and permissions on the DB, logs and
   config dir.
5. **Secrets:** grep logs, exceptions and `describe_error` text for
   token, key or password leakage. Read a real log (read-only) for
   any secret-shaped string.
6. **Qt rendering:** any remaining `RichLabel`/tooltip/HTML sink fed
   by data. Re-run the four `test_plain_text.py` sweeps and read
   what they skip (working agreement 5).
7. **SQL:** every f-string or `%` in an SQL string.
8. **Docker and Compose:** the per-user copy's ports, mounts and
   image pin. slskd's own advisories for the pinned version.
9. **Packaging:** what the DMG contains (no `.env`, no tests, no
   CLAUDE.md), the hardened-runtime and entitlements question for an
   ad-hoc signed app, and the bundled libraries' versions.
10. **Dependencies:** the `pip-audit` result above, plus a licence
    check of what is bundled.
11. **Defaults:** anything listening, anything sent off the machine
    without the user asking.

Rank the findings. Do not fix anything in this row. Kris reads the
audit before S7 starts (an [ASK KRIS] gate for any finding whose fix
changes behaviour that Kris uses).

## §7 — Security fixes I: dependencies and CI (S7)

**Do.**
- **§7.1** Bump `urllib3` to ≥ 2.8.0 in `uv.lock` (an override or a
  constraint if `requests` pins it). The failing check first:
  `pip-audit` reporting the three IDs.
- **§7.2** CI gains a dependency-audit job (`pip-audit` over `uv
  export --no-dev --locked`, SHA-pinned action or `uvx` with a pinned
  version). It fails on any known vulnerability and allows a
  documented ignore list with an expiry date for each entry.
- **§7.3** Any S-NN that §6 ranks critical or high and that is
  dependency-, CI- or packaging-shaped.

## §8 — Security fixes II: application findings (S8)

**Do.** The rest of `AUDIT.md`'s fix rows, in rank order, one commit
each, each starting with a failing test. A finding consciously
accepted gets its reason in `AUDIT.md` and, if it is a standing fact,
in CLAUDE.md. Split point: after the critical and high findings.

## §9 — Code health: radon D and the two undiagnosed failures (S9)

*Carried from round 11's handoff §4 and §9.*

**Established.** `uvx radon cc -n D -s src/seeker` reports
`dashboard_page._decide_next_step` (D, 21) and
`sharing_service._insert_slskd_share_directory` (D, 26). Round 11's
exit criterion forbids both, and no row owned them.

**Do.**
- **§9.1 and §9.2** Bring each function to C or better. These are
  refactor commits, so the behaviour must not change: the existing
  tests pass unmodified. Add tests first wherever the function's
  branches are not covered (`--cov-branch` on the module).
- **§9.3** `test_search_download_best_passes_the_already_fetched_results`:
  the test-first fix the round-11 handoff describes. Delay the fake,
  see the test fail, then wait on the label the finish handler
  writes.
- **§9.4** `test_a_cell_widget_paints_the_rows_own_background`
  (Cocoa only): rerun it with only the built-in display. Diagnose it
  or record what was ruled out. Never use
  `pytest-rerunfailures`.

---

# Phase C — Features

## §10 — The daily sweep (S10 service, S11 UI)

**Established (Kris assumed this existed; it does not).**
- Nothing searches again for a track that came up Not found, and
  nothing looks again at an `unavailable` row. The only background
  retry is the locked loop in `DownloadPoller` (`poller.py:286`). It
  reissues the *same* peer and file, backing off 60 s → 120 s → … →
  3,600 s, and marks the row `unavailable` after
  `LOCKED_RETRY_MAX_ATTEMPTS = 8`. That is about 3 hours in all. The
  comments call it a "daily cadence" design, but that described a
  user running `seeker downloads status` once a day, not a timer.
- `download_playlist` (`download_service.py:247`) already searches
  every unmatched track whose requests don't block a redownload.
  `failed` and `unavailable` don't block (`FAILED_OUTCOMES`,
  `models/download_request.py:37`), so a second run of
  `download_playlist` re-searches them. Rejected candidates are
  skipped (`rejected_soulseek_candidates`).

**Hypotheses to confirm before building.**
- A re-search might pick the very candidate that just went
  `unavailable`. Check `quality.py`'s ranking and the rejection
  tables. If it would, exclude a candidate that ran out its locked
  budget in the last N days.
- `download_playlist` runs sequential slskd searches. Measure one
  search's wall time on the fake and read slskd's search timeout, so
  you can size a per-sweep cap.

**Do (S10, service and CLI; no Qt).**
- **§10.1** `SeekerConfig.auto_sweep_enabled: bool = False` and
  `last_sweep_at: str | None`, with the all-fields round-trip test
  (R11 §9.6).
- **§10.2** A `SweepService` (or a method on an existing service, if
  that reads better) with `run_sweep() -> SweepResult`, a dataclass in
  `models/`. For each *loaded* playlist (`tracks_snapshot_id` set)
  that has a resolvable destination, it runs the missing-track search
  through `download_playlist`'s own path. It does not refresh from
  Spotify, which spares the API budget (CLAUDE.md). It caps the total
  searches per sweep; the rest wait for the next sweep, oldest
  first. It stops at once on `SlskdUnreachableError` and does not
  stamp `last_sweep_at`. It honours `downloads_paused`.
- **§10.3** A pure `sweep_due(now, last_sweep_at, enabled) -> bool`,
  true when enabled and 24 hours or more have passed or it has never
  run. Tested at the boundaries.
- **§10.4** `seeker downloads sweep` (respecting `docs/cli.md`), so the
  same thing can be run by hand or from cron. It prints a summary:
  searched, requested, still missing, skipped (with the reason).
- **§10.5** A HISTORY entry that records the "daily cadence" history
  and what changed.

**Do (S11, UI).**
- **§11.1** A Settings → General toggle, "Look again for missing
  tracks once a day", off by default, with a sentence on what it does
  (slskd searches only; no Spotify calls).
- **§11.2** The shell checks `sweep_due` at startup, after the first
  good backend poll, and then once an hour. When it is due, it runs
  the sweep on `MainWindow.thread_pool` through `run_worker`, shown
  in the activity strip (`busy_actions`). It never runs a second
  sweep while one is running.
- **§11.3** A sweep that requested at least one download sends one
  tray notification (under the existing "Downloads finished" toggle,
  or a new one if that reads wrong). A sweep with nothing new is
  silent and logged at INFO.
- **§11.4** Tests: the toggle round-trip, due versus not due, the
  no-overlap guard, and silence when nothing is found.

## §12 — X2: Retry and Cancel on the Downloads page (S12)

R11 §X2, approved 2026-10-08. **Retry** on `failed` and `unavailable`
rows runs a fresh search for that track (§10's path, one track). That
is better than re-asking the same peer, which is what made it fail.
**Cancel** on `queued` rows calls slskd's transfer-cancel endpoint.
Verify the endpoint against the live slskd **read-only first**
(`docker inspect`, the slskd API docs for the pinned version). A
`DELETE` on a real transfer is a write, so get Kris's yes before you
try it live. A cancelled row becomes `failed` with
`failure_reason="Cancelled by you"` (CLAUDE.md: every such transition
passes `failure_reason=`). Buttons go through `cell_widget(...,
row_label=)` (ui/CLAUDE.md).

## §12b — Fall back to the next-best file (S12b)

Added 2026-10-09, after S12. Kris asked whether automatic downloading
"tries the best quality one, and if it doesn't work, tries the next".
It does that for upgrades only. Line numbers are from `376519b`.

**Established (read in code at `376519b`).**
- `select_downloads` (`quality.py:218`) ranks with `_sort_key` (tier,
  bitrate, unlocked first, shorter queue). It returns one *settled*
  file, plus up to `MAX_UPGRADE_SHORTLIST = 3` *upgrades* ranked
  ahead of it. When the top file is unlocked and practical
  (`quality.py:243`), it returns that file alone. Every file ranked
  behind it is discarded with the search results.
- Only an upgrade cascades (`poller.py:217` → `_cascade_upgrade`,
  sequential by design, HISTORY §14). A rejected settled row becomes
  `locked`, which re-asks the same peer 8 times over ~3 hours and then
  becomes `unavailable`, or it becomes `failed`. Neither tries another
  file. `test_settled_role_rejection_does_not_trigger_upgrade_cascade`
  (`tests/test_download_service.py:2169`) pins this. Its purpose is
  to keep a settled failure from activating the *upgrade* shortlist,
  and it stays true.
- **A settled peer offline at enqueue fails the whole track.**
  `search_and_request` calls `_request_and_record` (`:475`), and the
  synchronous 404's `SoulseekDownloadError` propagates out of it.
  `download_playlist` counts a track failure and writes no row, so a
  later search is not steered away from that peer either. A
  shortlisted upgrade that gets the same 404 is handled: it becomes
  `locked` (`_activate_shortlisted_entry`).
- **A re-search skips only `unavailable` pairs and Review Rejects**
  (`_without_rejected`, `download_service.py:867`; the cooldown is
  `UNAVAILABLE_COOLDOWN`, 30 days). A `failed` pair, including
  "Cancelled by you", can be picked again by Retry or the sweep.
  `completed_at` is stamped on `failed` as well
  (`STAMPS_COMPLETED_AT`), so the same window query can cover it.
- The parts that can be reused:
  - `status='shortlisted'` and `rank` exist with no CHECK on `role`,
    so no migration is needed. `get_next_shortlisted` (repository
    `:531`) is **not** role-scoped.
  - `supersede_other_active_for_track` (`:573`) is hard-scoped to
    `role='upgrade'`.
  - Downloads already labels `shortlisted` "Queued as backup", and
    its upgrade badge keys on role.
  - The Dashboard's track state takes `IN_FLIGHT` first, then
    `RETRYING_IN_BACKGROUND`, so a settled backup reads correctly
    with no change.
- Nothing supersedes anything when a settled file completes. Today
  there is never a second settled row to supersede.

**Kris's answers (2026-10-09).** These are decisions; do not ask
again.
- **A locked settled file falls back at once**, the way an upgrade
  does. The locked row keeps its quiet retry loop. Whichever settled
  row is placed first wins, and the other active settled rows for that
  track are superseded.
- **A re-search skips a (peer, file) that went `failed` or
  `unavailable` for the track within 30 days**, cancellations
  included. One window, one rule.

**Code's calls (veto in the handoff if wanted).**
- Up to 3 backups (`MAX_SETTLED_BACKUPS`, untuned like
  `MAX_UPGRADE_SHORTLIST`): the files ranked next behind settled, by
  the same rule that chose settled (practical and unlocked first, then
  unlocked). A locked file is never a backup, since it would only lock
  again.
- A person's choice gets no backups: a confirmed needs-review
  candidate (`review_service.py:188`) or a manual download. The
  person picked that file.
- **Cancelling a settled row ends it**: its backups are superseded,
  as a cancelled upgrade's are (HISTORY §205).
- A superseded row's transfer is not cancelled in slskd; the database
  is the only thing changed, as upgrades work today. Its file becomes
  a leftover, which is one reason this row comes before S13's cleanup.

**Hypotheses to confirm before building.**
- `_activate_shortlisted_entry` marks an at-once `Succeeded` as
  `READY_FOR_REVIEW` (`poller.py:422`). That is right for an upgrade
  and wrong for a settled backup, which must reach placement. Confirm
  it, and confirm that leaving a settled backup `downloading` lets the
  next poll place it.
- While its backup runs, a `failed` settled row still offers Retry,
  which answers `ALREADY_IN_PROGRESS`. Check what the notice says on
  screen. If it reads wrong, fix the wording; don't hide the button.
- If every settled backup fails while an upgrade lands, the upgrade
  goes to Review and the track has no file. That is pre-existing, so
  confirm and record it, don't change it.

**Do (one commit each, a failing test first).**
- **§12b.1** `select_downloads` returns `settled_backups` beside
  `settled`. This is a pure function, so test it on the clean case,
  the impractical-top case and the all-locked case (no backups).
- **§12b.2** `search_and_request` records the backups as `shortlisted`
  settled rows, ranked 2–4. `get_next_shortlisted` takes a role.
  `_cascade_upgrade` becomes one cascade over a role: a settled row
  that goes `failed` or `locked` activates the next settled backup in
  the same poll, and never an upgrade (the 2169 test stays green). An
  at-once success leaves the backup in flight for placement.
- **§12b.3** A settled peer offline at enqueue is recorded `locked`
  (the same classification as a shortlisted entry), its backup is
  requested at once, and the track counts *requested*. An unrecognized
  HTTP error stays loud, as today.
- **§12b.4** A settled completion supersedes the track's other active
  *settled* rows (a role-parameterized supersede), never its upgrades.
  `cancel_download` on a settled row supersedes its backups.
- **§12b.5** `_without_rejected` skips `FAILED_OUTCOMES` pairs inside
  the window; rename the constant and the repository query to say so.
  Test inside and outside the window, and with "Cancelled by you".
- **§12b.6** Close-out:
  - CLAUDE.md's SoulSeek facts: the sweep line's "went `unavailable`"
    and a settled-fallback line.
  - `schema.py`'s `shortlisted` comment ("upgrade rank 2/3").
  - Screenshots of Downloads with a backup row, in both themes
    (§0.13).
  - HISTORY.

**Not in this row.** A remote queue that never moves has no time
limit: a settled file can wait in "Queued, Remotely" indefinitely.
That is a separate decision (how long, and whether to then fall back)
and it joins the handoff's open questions.

## §13 — X1: Clean up leftover slskd downloads (S13)

R11 §X1, approved 2026-10-08. A Downloads-page action, "Clean up
leftover files…", lists files in slskd's download and incomplete
folders that no pending or ready-for-review request references.
It shows sizes, asks for explicit confirmation, and deletes nothing
an active transfer uses. **Real-data safety:** test against a
scratch tree only. The real slskd folders are read-only to the
session; Kris runs the first real cleanup.

## §14 — Automatic update check (S14)

R11 §40 unchanged: opt-in, at most once every 24 hours, at startup
only. Reuse §11.2's due-check shape (two features on one pattern), so
make `sweep_due` a general `is_due(now, last, interval)` if both read
better that way.

---

# Phase D — Fresh-eyes QA

## §15 — QA sweep over every screen (S15)

*Reach for `frontend-design`.*

Kris found nine things by hand; a stranger would find more. Read all
78 harness screens (§0.13) in both themes, at both sizes, with an
eye for alignment, clipping, inconsistent wording, colour misuse and
states that contradict each other. Fix the small ones (one commit
each, a test where a test can hold it) and list the rest in the
handoff.

**Planning saw these on `eacdfc1`; start with them.**
- **Downloads header:** "Waiting for transfers to start · 0
  transferring" while a row shows Downloading at 66 %
  (`downloads-light-1280x820.png`). This may be the harness's
  first-poll state (round 11's carried "Downloads first-poll header"
  question). Decide which, and fix it if it is real.
- **A selected radio button in dark mode is a solid violet disc** with
  no inner dot (`settings-general-dark-1280x820.png`). The
  unselected ones are rings. Check `QRadioButton::indicator:checked`
  (`theme.py:1528`, shared with the checkbox).
- **Dashboard, light:** the Status cell's secondary text elides to
  "Candidate fo…" beside "Needs review". Either the text is worth
  showing in full or it is not worth showing.
- **Review:** the Runner-up column shows a peer name with a score
  (`demo_peer_2 (64.0)`), while Candidate shows a filename. Make
  the two columns read alike.
- The round-11 handoff's §9 carried questions: Settings' Reachable
  lamp, and Duplicates' Quality column at 960 px.

---

# Phase E — Release (carried from round 11)

## §16 — Release engineering (S16)

R11 §39 unchanged, with §39.3 answered: the bundle identifier is
`io.github.kristiyanddimitrov.seeker` (§0.11). After the change, Kris
re-enables "Start Seeker at login" once on the packaged app. Put that
on S17's checklist.

## §16c — Bring slskd back when its container is gone (S16c)

**Kris, 2026-10-10:** "I recently deleted the slskd container within
Docker and now I can't seem to bring it back up from the app." Added
as a row before S17, which needs slskd up.

**Measured at planning (read-only, nothing started):** Docker 29.8.1
is running; no `slskd` container exists.
- **"Start slskd" refuses by design.** `Application.restart_slskd()`
  reads the share folder from the *live* container
  (`sharing_service.current_share_path()`), so a deleted container
  gives `SlskdStartRefusedError` ("can't find the slskd container it
  set up"). It also needs the saved SoulSeek network login.
- **The only working path is hidden.** Settings → Connections →
  "Update SoulSeek credentials" recreates a missing container
  (retype the login, then a picker asks which location to share).
  Nothing says it is the way back, and it is UNVERIFIED end to end
  against a deleted container.
- **Kris's config can't drive a recreate:** `slskd_username` and
  `slskd_password` are `null` (an install from before Seeker saved
  them); `slskd_download_dir` is the *relative*
  `./slskd-data/downloads`.
- **The old container's data is not where a recreate would look.**
  Its `/app` was the repository's `slskd-data/` (`slskd.yml`, `data/`,
  17 entries in `downloads/`). A recreate today uses
  `slskd_data_dir()` (the app-data `slskd-data/`, which holds only
  the per-user Compose file), so slskd's state and those downloads
  would be left behind.

**The work, one commit each, a failing test first** (fake
`subprocess.run`/`detect_docker_state`; no test runs the real
`docker`):
1. **Every bring-up Seeker makes records what a recreate needs:** the
   share path and the data folder, both absolute, in `config.json`
   (through `write_text_locked`). That means `start_slskd`, and
   Sharing's recreate too. The download folder is saved absolute from
   now on. The relative one is a bug: a `.app`'s cwd is not the repo.
2. **`restart_slskd()` recreates a missing container from what was
   recorded**, still never guessing: with Docker up and no container,
   it uses the saved share, data folder and login. It refuses only
   for what is actually missing, and says which.
3. **A visible way back in the UI.** When "Start slskd" is refused
   for missing facts, the notice offers Settings → Connections, where
   a "Start slskd" form (or the existing section, renamed and made
   clear) shows the login (saved values prefilled), the folder to
   share (the saved one first) and the data folder (saved, else the
   default, with "Choose…" so Kris can point it at the old one). The
   wording says what happens to slskd's state.

**Code's calls:** the form's exact shape; whether a found data folder
(one with a `slskd.yml`) is offered by name. **Kris, live, at the
keyboard (never Code):** the first real bring-up, choosing the old
`slskd-data/` or a fresh one. Never start, stop or recreate the
container from a session. Screenshots per §0.13.

## §17 — Release-candidate acceptance (S17) — Kris and Code

R11 §41 unchanged, plus these checks from this round:
- the theme switch to Follow system, from both Light and Dark, while
  the OS shows the other scheme (§2);
- a Review tooltip held for 10 s or more (§3);
- the daily sweep enabled, with `last_sweep_at` edited back by more
  than 24 h in a **scratch copy** of `config.json`, then a launch
  pointed at it, if the app supports that; otherwise Kris enables it
  on the real config and waits a day;
- Retry, Cancel and Clean up on the real slskd (§12, §13), with Kris
  at the keyboard;
- "Start Seeker at login" turned on again once on the packaged app:
  the bundle identifier changed in S16, so the old registration is
  for `com.seeker.app` (§16);
- the carried live checks in R11's session plan → "Waiting on Kris".

Any failure becomes a fix row before S18.

## Acceptance failures, 2026-10-12 (S17a–S17f)

**Kris, 2026-10-12, from a manual run on the test macOS account**
(the build in `dist/`, rebuilt 2026-10-12 12:10; its SHA-256 no
longer matches the candidate's `dist/Seeker.dmg.sha256`). Six
failures, each a fix row before S18 (§17: "never shipped around").
Planning read code and Kris's own database read-only. **The test
account's database and log are not readable from Kris's account**
(`/Users/test/Library/…`: permission denied), so anything that needs
them waits on Kris (SESSION-PLAN → "Waiting on Kris").

HISTORY numbering continues at §223 in `docs/history/211-240.md`.

## §17a — The Dashboard's next step waits for the scan (S17a)

**Kris:** "upon pressing 'Scan Library', the text then changes to
showing 'X files missing', but then after the actual scan is done, it
updated to the real number. … wait until scanning is done to show how
many tracks are missing."

**Established (read in code).**
- The next step for a playlist is `_playlist_step`
  (`ui/pages/dashboard_page.py:247`). It offers "Scan library" while
  `has_scanned_library` is false, and otherwise counts `MISSING_STATES`
  and shows "N tracks missing from '…'".
- `LibraryService.has_scanned_library()` (`library/service.py:271`) is
  true once **any** `local_files` row exists.
- The scanner commits in batches of `UPSERT_BATCH_SIZE = 200`
  (`library/scanner.py:25`). The first batch makes
  `has_scanned_library` true seconds into the scan.
- `scan_and_match()` matches only after the whole scan
  (`library/service.py:622`). Until then no track is matched, so the
  2 s `poll_next_step` counts **every** track as missing. That is
  Kris's "X", the playlist's total.

**Do, one commit each, a failing test first.**
1. While a scan or a match runs (`busy_actions.is_running("scan")`
   or `"match"`), the next step shows no count. Say what is happening
   ("Scanning your library…", no action), or keep the step from before
   the click; Code's call. The fact belongs in `_NextStepFacts`, so
   `_decide_next_step` stays pure. The test: a fake scan that blocks
   after the first batch, a poll tick, and no "missing" text.
2. Audit the other places that count during a scan: the playlist
   list's "N · M missing" (`_playlist_counts`) and the track table's
   statuses. Fix what flashes the same way (one commit), or list it in
   the handoff with the reason it stays.

**Not in scope:** `has_scanned_library`'s proxy (its docstring
accepts it). Screenshots per §0.13 if the step's wording changes.

## §17b — Find duplicates: the "freeze" at 3589 of 3611 (S17b)

**Kris:** "I did a full fingerprinting that got 3611 fingerprints,
when running Find Duplicates … once it got to 3589 of 3611, it
froze. Quit the app, did it again — same thing."

**Established, by arithmetic over the code: 3589 is the last
progress the throttle lets through, not where the work stops.**
- `Worker._report_progress` (`ui/workers.py:177`) emits only every
  `PROGRESS_EMIT_EVERY_N = 25`th call, or after
  `PROGRESS_EMIT_MIN_INTERVAL_S = 0.25` s. Its counter spans every
  stage of the task.
- `_cluster_duplicate_groups` (`library/duplicate_service.py:893`)
  reports "Decoding fingerprints" 3611 times, then
  `_cluster_by_similarity` reports "Comparing" k of 3611 (when every
  file has a duration). The k-th comparison is call 3611 + k. The last
  multiple of 25 in range is 7200, so **k = 3589**. The remaining 22
  comparisons finish well inside 0.25 s, and nothing is emitted for
  them. The same point every run follows from that arithmetic.
- **After "Comparing" comes a stage with no progress at all:** for
  every file in every cluster, `analyze_local_file_quality`
  (`audio/quality.py:39`) reads the **whole audio file twice**
  (`_measure_clipping_ratio` as int16, `_measure_integrated_loudness`
  as float64) and runs pyloudnorm. On large lossless files on an
  external drive, that is seconds per file.

**Hypothesis (confirm or rule out first).** The run is not frozen. It
is in that silent quality stage, and its length scales with how many
files sit in duplicate groups. Kris quitting during it is a likely
cause of a §17c beach ball. Confirm by timing the stage at scale (a
synthetic run, or Kris's own library read-only with the X9 Pro
mounted; analysis only reads files). Also confirm that the UI thread
stays responsive while it runs. If the UI itself hangs, this is a
different bug: stop and record it.

**Do, one commit each, a failing test first.**
1. **A stage's last report is never dropped:** the throttle always
   emits `current == total`. The test is the 3611/25 arithmetic above,
   with a fake clock.
2. **The quality stage reports progress** ("Measuring quality i of
   m"). m is the number of files in clusters.
3. **The quality stage costs what it must:** decode each file once
   for both measures, and keep it off the path if the measures can be
   deferred (Code's call; measure before and after, and quote both).
4. If (3) can't make it short, the run stops on request (Cancel, and
   §17c's quit) between files. That is a `threading.Event`, like the
   sweep's `stop`.

**Split point:** after (2). The user then sees the run is alive.

## §17c — Quit never hangs on a running task (S17c)

**Kris:** "When quitting the app, more than once, rather than
successfully closing the app, I got the beach ball and it froze. …
at least 3 times."

**Established.** This is open item 125 (CLAUDE.md → Open issues):
`MainWindow.thread_pool`'s destructor waits for every in-flight
runnable (HISTORY §125, measured in isolation), so a quit lasts as
long as the slowest running task. `cleanup_before_quit` logs the
pool's active thread count at quit (`seeker.ui.window_lifecycle`).
Kris's own log shows `active=0` on every quit since 2026-10-01, so
the hangs happened on the test account, whose log Code cannot read.
The sweep already stops on quit; nothing else long-running does
(fingerprinting, Find duplicates, scan, match, tagging).

**Hypothesis.** Each hang was a quit while a long worker ran (§17b's
silent stage is the prime suspect for at least one of them). Item
125's next step was to quit during a scan, a fingerprint or a search.

**Evidence first (Waiting on Kris):** the test account's
`~/Library/Logs/Seeker/seeker.log*` copied to `/Users/Shared/`. Look
at the `cleanup_before_quit: starting, thread_pool active=N` lines
and what ran before each hang. Then reproduce one in a test: a
runnable that blocks, a real quit, and a measured exit.

**Do, one commit each, a failing test first.**
1. **One stop signal for long work:** the long services take a stop
   event (the sweep's shape) and check it between items. The shell
   sets it on the quit seam, before `aboutToQuit`. Work done so far
   is kept: a fingerprint stored is stored.
2. **The quit waits a bounded time**, then exits. Bounded means
   `waitForDone(ms)`. Whether to exit hard after the bound needs a
   measured reason; never `os._exit` before the database's last
   transaction closes. If a quit cancels visible work, the quit
   confirmation says so.
3. Update CLAUDE.md's item 125 and the thread pool fact with what was
   measured.

**Decision for Kris (default unless vetoed): quitting stops a running
scan, fingerprint run or duplicate search at once. What finished
stays.**

**Split point:** after (1) for the duplicate search and fingerprints.

## §17d — Fullscreen and back: tables refit without per-row work (S17d)

**Kris:** "when going fullscreen in the app, it is extremely buggy.
Not only slower, but also not as 'fluid' — you see tables resizing
and going one over another … Going back from fullscreen to windowed
mode leads to the same behaviour. This is new."

**Established (read in code).** Every table's viewport has a
`_ColumnFitter` (`ui/theme.py:836`). On every resize event that
changes the viewport's width, it calls `_fit_content_columns`
(`theme.py:793`), which reads **each row** in Python-level work:
- `header_label_floor` and `label_floor` for each fit-content column.
  `label_floor` (`ui/elided_text.py:416`) calls the Python delegate's
  `sizeHint` once per row.
- `sizeHintForColumn` for each fit-content column, and again for
  each stretch column. Each calls the Python `ElidedTextDelegate.
  sizeHint`, which since `e7d8c66` (round 12 S15 §15.7, 2026-10-10)
  also measures secondary text.
- a scan of every row for a cell widget.

A macOS fullscreen transition animates the window through many
sizes. Each step re-measures every visible table's rows. None of
that work depends on the width: only `fit_widths`' budget does.

**Hypothesis.** The per-row re-measuring is the regression. Its
round-12 growth (`e7e9d07` `label_floor`, 2026-10-09; `e7d8c66`) is
"new since the last build". Confirm by **measuring before fixing**: a
resize storm (say 30 widths from 1280 to 2560) over the Dashboard,
Library and Duplicates with production-scale fakes (~3,600 rows),
timed at `HEAD` and at round 12's base `eacdfc1`. "Tables going one
over another" may be a second symptom (a stale layout during the
animation). Check it separately in screenshots or a recording.

**Do, one commit each, a failing test first** (the test counts
`sizeHint` calls per resize: 0 rows' worth after this fix).
1. **Measure once per render, fit per resize:** `size_columns` caches
   the wants and floors with the fitter. A resize only re-runs
   `fit_widths` over the cached numbers (O(columns)).
2. If (1) is not enough, coalesce the refits into one per event-loop
   turn (`QTimer.singleShot(0)`), and measure again.
3. Quote the storm's timings before and after in the HISTORY entry.

**Kris, live, after the fix:** fullscreen and back on the packaged
app, on the Dashboard, Library and Duplicates.

## §17e — The tray menu in fullscreen (S17e)

**Kris:** "When in fullscreen mode, when clicking on the top right
tray icon, the menu disappears immediately. Don't know if it's
expected behaviour, but it's annoying. Fix if possible."

**Established.** `TrayController._on_tray_icon_activated`
(`ui/tray.py:209`) does nothing on macOS: AppKit opens the menu by
itself (HISTORY §112). The menu's actions are re-rendered by
`render_tray_menu` (`tray.py:296`). `on_application_state_changed`
(`tray.py:249`) reopens the window when the app turns active with the
window hidden. Nothing in the code is specific to fullscreen.

**Hypotheses, none confirmed:** (a) a click on the status item while
the app is in a fullscreen Space activates the app, and something
reacting to that (`applicationStateChanged`, a fullscreen Space
switch, a render) closes the menu; (b) AppKit's own behaviour for a
status item over a fullscreen Space's auto-hiding menu bar; (c)
`render_tray_menu` edits an open menu, and Cocoa rebuilds it.

**Do.**
1. Add `logger.debug` (enabled per logger, like
   `SEEKER_DEBUG_POLL`) on the menu's `aboutToShow`/`aboutToHide`,
   `applicationStateChanged`, and `render_tray_menu`'s entry. Kris
   reproduces it once in a dev run. The log shows what ran between
   show and hide.
2. Fix it if the cause is ours, with a test of that mechanism. If it
   is AppKit's, say so with the observation (Working agreement 4),
   and record it as a known limitation in the HISTORY entry and
   Help's troubleshooting.

**Code's call:** whether (1) ships or stays a dev-only switch. After
§17d, because both rows touch fullscreen.

## §17f — Review: "Confirm all" for a section (S17f)

**Kris:** "At the Reviews page, add the option for a person to
'confirm all' entries in a column. Do, of course, prompt the user to
make sure he'd like to do that just in case."

**Read as:** one "Confirm all" per Review section, in the header row
the way Upgrades' "Replace all" is (`review_page.py:203`). Review's
three sections are stacked tables (SoulSeek candidates, Upgrades,
Local matches); Upgrades already has its bulk action. Code's
interpretation; Kris may veto.

**Established.**
- **Local matches:** `LibraryService.confirm_match` (`library/
  service.py:730`) is a database write only. Review's comment says no
  double-confirm is needed for it (HISTORY §27).
- **SoulSeek candidates:** `ReviewService.confirm_review_candidate`
  (`soulseek/review_service.py:141`) calls `request_download` per
  track (network). A batch can partly fail.
- **The precedent:** "Replace all": `BulkReplaceUpgradesDialog`, then
  `apply_upgrade_decisions_batch` (`review_service.py:476`) returning
  `BulkUpgradeReplaceResult`, with failed rows offered again by the
  next poll (`review_page.py:715–755`).

**Do, one commit each, a failing test first.**
1. **Service:** one batch method per section. Each returns a result
   dataclass in `models/` (`confirmed`, `failures`; `failed` derives
   from it). It goes on past a failed item, and failures stay
   reviewable. The track ids come from what is on screen
   (Replace all's "built fresh from what's on screen", HISTORY §76,
   §88), never a re-query.
2. **UI:** a "Confirm all (N)" button per section, disabled at 0,
   with a confirmation through `plain_text.question` that names the
   count and what happens ("N downloads will start" for SoulSeek; "N
   matches will be kept" for local). The result goes to the page's
   notice through `describe_error` for failures. The button follows
   ui/CLAUDE.md's render rules: a render decides its enabled state,
   so it is never `run_worker`'s `button=`.
3. Screenshots per §0.13 (Review in both themes) and the button
   sizing and keyboard sweeps.

**Split point:** after the local matches section (no network).

## §17h–§17k — Nothing freezes the app (added 2026-10-12)

**Kris (2026-10-12, after S17c):** "Anything that can make the app
freeze needs to be fixed." S17c (HISTORY §226) made fingerprinting and
both duplicate searches stop on quit and bounded the quit's wait at
5 s; every other long task still keeps the process alive until it
ends, because `~QThreadPool` waits for it (the sample in §226). These
rows close every case S17c's session found, plus one main-thread
stall. **The pattern is §226's:** a service takes `stop:
threading.Event | None`, checks it before each item, keeps what is
done, and a page passes `self._context.quitting`; a wait becomes
`stop.wait(interval)` instead of `time.sleep(interval)`.

## §17h — A finish handler survives a deleted button (S17h)

**Established (the test account's log, `/Users/Shared/seeker.log`).**
Four `CRITICAL seeker.ui.error_hooks: Uncaught exception` with
`RuntimeError: … QPushButton already deleted` at
`ui/workers.py:_handle_task_finished`'s `button.setEnabled(True)`
(2026-10-08 18:47, 18:58, 18:59; 2026-10-12 12:22). Read in code: the
raise skips the rest of the handler, so `on_finished` never runs and
`_schedule_native_delete(worker)` is never called; `_handle_task_error`
has the same line. Every one fell during a playlist download (its
searches logging around it, the download itself still running), so a
short worker finished after a re-render deleted its button, which
`ui/CLAUDE.md`'s "`button=None` for a button a rebuild can delete"
rule forbids. The call site is not identified.

**Hypothesis.** A per-row or poll-rendered button on the Dashboard
(the page a playlist download runs from) is passed as `button=`.

**Do, one commit each, a failing test first.**
1. **The handler survives:** a `run_worker` whose button is deleted
   before it finishes still runs `on_finished` (or `on_error`) and
   frees its worker. Guard with `shiboken6.isValid(button)`; never a
   bare `except RuntimeError` around the rest.
2. **The call site:** find the `button=` that a rebuild can delete
   (an AST or harness sweep over `run_worker`/`run_busy_worker` calls,
   or reproduce over the fakes with a poll re-render mid-task), and
   move it to `button=None` with its busy state in the rendered key.
   Then check what the user saw: whether a busy action stayed
   "running" in the activity strip.

**Split point:** after (1).

## §17i — Quit stops the network waits (S17i)

**Established (read in code; times from the log or the constants).**
- `DownloadService.download_playlist` loops over every unmatched track
  with no stop (`soulseek/download_service.py:327`); each
  `search_and_request` took 16–22 s in the log, so a large playlist
  runs for hours, and a quit waits for all of it.
- `SoulseekClient.search` polls until `isComplete` or its 45 s
  timeout with `time.sleep(poll_interval)` (`soulseek/client.py:194`):
  the sweep stops only between searches, so a quit mid-search waits up
  to 45 s, past S17c's 5 s bound.
- Spotify: a rate limit sleeps up to 60 s (`spotify/client.py:198`);
  `connect_spotify` waits up to `CALLBACK_TIMEOUT_SECONDS` = 300 s for
  the browser (`spotify/callback_server.py:20`); `refresh_playlists`
  re-syncs playlist after playlist.
- Sharing's share-ready poll sleeps up to `SHARE_READY_TIMEOUT_SECONDS`
  = 120 s (`soulseek/sharing_service.py:595`).
- slskd's bring-up runs `docker compose up` with a 120 s timeout
  (`soulseek/docker_setup.py:413`) and a health poll.

**Do, one commit each, a failing test first.**
1. **The playlist download** stops between tracks; the result says it
   stopped; requests already made stay made.
2. **A search's wait** takes the stop (`stop.wait`), so the sweep and
   the playlist download end mid-search; a stopped search requests
   nothing.
3. **Spotify:** the rate-limit wait and the callback wait end on the
   stop (the callback server shuts down); the sync stops between
   playlists, each finished playlist kept.
4. **Sharing's share-ready poll** ends on the stop.
5. **The slskd bring-up:** measure it first. Never kill `docker
   compose` mid-recreate without a measured reason; if it cannot
   stop safely, the quit confirmation says a bring-up is running, and
   the HISTORY entry records why.

Tests fake the HTTP layer and `subprocess`, never a real API or the
real `docker` (CLAUDE.md → Testing).

**Split point:** after (2), the playlist download and the search wait.

## §17j — Quit stops library work; a sweep keeps it so (S17j)

**Established (read in code).** `LibraryService.scan_and_match`
(a 3,615-file first scan took 12 s in the log), `MetadataService.
tag_tracks`/`tag_playlist` (with Analyze audio, BPM/key per file),
`apply_renames`, `merge_location` and `remove_location` take no stop.

**Do, one commit each, a failing test first.**
1. **Scan, tagging, renames:** stop before the next file, never
   inside one: a tag write goes through `save_tags()` whole, a rename
   is disk then DB row whole (CLAUDE.md → Database). What is done
   stays.
2. **Merge and remove:** measure at production scale on a scratchpad
   copy of the DB first (§224's recipe); add a stop only if one takes
   longer than the 5 s bound, between its short batches.
3. **A sweep test fails the build** when a `run_worker` or
   `run_busy_worker` call in `ui/` starts a service call that takes a
   `stop` without passing `quitting`, and lists every call that takes
   none, each with its measured reason (working agreement 5).
4. **The window during the bounded wait:** with every long task
   stoppable, measure a quit mid-task again. If the wait can still
   show a frozen window, hide the window before `waitForDone`
   (whether a hide shows without an event-loop turn on Cocoa is
   UNVERIFIED: observe it).
5. Update CLAUDE.md's item 125 and the thread pool fact; close item
   125 if nothing is left.

**Split point:** after (1).

## §17k — Duplicates' resize stall (S17k)

**Established (§225, measured).** Each resize step on Duplicates takes
~67 ms at 1,800 groups: Qt repositions its 5,400 cell widgets, the
same as at the round's base. A 30-step fullscreen transition holds
the main thread about 2 s.

**Do.** Measure the storm first (§225's recipe). Replace the per-row
cell widgets with a delegate-painted control, or create them only for
visible rows, whichever measures cheaper, keeping the keyboard access
and button sweeps green. Measure after; screenshots per §0.13
(Duplicates, both themes).

**Split point:** after the measurement and one approach.

## §17l–§17o — Before the new candidate (added 2026-10-14)

**Kris (2026-10-14), on the handoff's open questions before S17g:**
look into slskd's `429`; fix Replace all and Resolve all if they need
it; move Settings' and the wizard's tasks onto the shell's pool if it
improves things and breaks nothing; add a quit confirmation to the
wizard. The test segfault (§231) was left to Code's judgement:
**skipped.** Its crash site is wherever the cyclic GC happens to run,
not `_Brows`' code: no allocation there differs from any other paint.
It showed 1 run in 25 of a three-file loop and never in a full run or
on CI, and an investigation has no bounded end. A crash in the real
app would leave a macOS crash report in
`~/Library/Logs/DiagnosticReports/`. Reopen it if it shows on CI or
in the app.

## §17l — slskd's enqueue limit answers `429` (S17l)

**Established (slskd 0.26.0's source, the tag the Compose template
pins; `TransfersController.cs`).** Both enqueue endpoints share
`DownloadRequestLimiter = new SemaphoreSlim(2, 2)` and take it with
`Wait(0)`: a third enqueue while two are in flight gets an immediate
`429`, body "Only one concurrent operation is permitted. Wait until
the previous request completes" (the text says one, the limit is
two). An enqueue holds its slot through the peer's endpoint lookup
and `EnqueueAsync`, so it can take seconds. The same controller turns
any other exception into a `500` with the exception's message: item
63's lead (a `500` on this endpoint) is a different path from this
one.

**Established (the test account's log, 2026-10-08 18:58:41).** The
`429` hit Review's Confirm (`review_service.confirm_review_candidate`
→ `request_download`), not the playlist download: a playlist download
was running at the time. The candidate was placed at 18:59:56, so a
second attempt succeeded.

**Established (code).** `request_download` treats a `429` as
unrecognized and re-raises the raw `httpx.HTTPStatusError`. Seeker
enqueues from several threads at once: the playlist download and the
sweep (`_request_and_record`), the poll (`_activate_shortlisted_entry`
and `_attempt_locked_retry`), and Review's Confirm, Confirm all and
upgrade Replace, Retry and manual search. So a `429`:
- fails a Review Confirm, which the user then sees;
- fails a track in a playlist download or a sweep after its search
  (up to 45 s) was spent, with no row recorded;
- spends one of a locked row's 8 retries (`except Exception` →
  `_advance_locked_retry`), though slskd never asked the peer.

**Hypothesis (check first).** A `429` raised from
`_activate_shortlisted_entry` (it catches only `SoulseekDownloadError`)
propagates out of `_cascade`, leaving the backup `shortlisted` beside
a failed row, and no later poll activates it. S17f's Confirm all
makes three enqueues at once likelier.

**Do, one commit each, a failing test first.**
1. **Seeker never runs two enqueues at once:** one lock in
   `SoulseekClient` around the batch POST (a module-level lock: pages
   and services build their own clients), so one process stays under
   slskd's limit of two.
2. **A `429` is "slskd is busy", never a failure:** `request_download`
   waits briefly and retries a bounded number of times (a CLI sweep
   from cron is a second process the lock cannot see). If slskd stays
   busy, raise a `SeekerError` that `describe_error` words, and that
   the locked-retry path treats like `httpx.TransportError`: no
   attempt spent. Then the hypothesis above, with a test, fixed if
   true.

**Split point:** after (1).

## §17m — Review's Replace and the bulk buttons' enabled state (S17m)

**Established (§228 → "Not done").** An upgrade's Replace passes no
`on_error`, so a failed Replace shows nothing on Review: an error the
user never sees (CLAUDE.md: errors go to an `InlineNotice`). Review's
"Replace all" and Duplicates' "Resolve all groups" pass `button=`,
but their enabled state is decided at render (`setEnabled(len(…) >
0)`), so the finish re-enables one over an empty list until the next
render. That is cosmetic: Replace all's click returns on an empty
list. Whether Resolve all's does is not checked.

**Do, one commit each, a failing test first.**
1. Replace's failure reaches Review's feedback target through
   `describe_error`.
2. The two buttons keep their render rule after a finish
   (`ui/CLAUDE.md`'s §145 rule; Duplicates' per-row variant from §228
   shows the pattern), and Resolve all's click on an empty list is
   checked.

**Split point:** none.

## §17n — Settings' tasks on the shell's pool (S17n)

**Established (§231–§233; code).** `SettingsWindow` and
`OnboardingWizard` each make their own `QThreadPool()`. A pool's
destructor waits for its running tasks, outside `cleanup_before_quit`'s
5 s bounded wait and its log. **Only Settings can move:** it opens
from `MainWindow`, while the wizard runs on a first launch before any
`MainWindow` exists (`main_ui.py`), so it keeps its own pool and §17o
covers it.

**Risk to measure, not assume.** The shell's pool has Qt's default
thread count (`idealThreadCount()`). Settings' short checks could
queue behind long tasks only if every thread were busy. Count the
long tasks that can run at once (playlist download, sweep, scan,
fingerprints, duplicates, tagging) against this Mac's
`idealThreadCount()`, and record it.

**Do, a failing test first.** Settings takes the shell's pool (and
its `quitting` event for any long task). The quit sweep
(`tests/test_quit_stop_sweep.py`) covers its calls, and a task still
running at quit is logged like any other. Settings closed mid-task
must still be safe (the worker's context object).

**Split point:** none.

## §17o — The wizard asks before quitting a bring-up (S17o)

**Established (§232).** Closing the wizard while a bring-up runs
waits for Compose (up to 120 s) with no word. `MainWindow`'s quit
confirmation already names a bring-up through
`Application.is_starting_slskd()`.

**Do, a failing test first.** Closing the wizard (and ⌘Q, through
the same `QEvent.Type.Quit` seam, CLAUDE.md) while
`is_starting_slskd()` asks first, with the same wording as the
shell's confirmation. Cancel keeps the wizard open. Confirm quits
and waits, as now. No question when nothing is starting.
Screenshots per §0.13 (the question, both themes).

**Split point:** none.

## §18 — Publish v0.1.0, close the round (S18)

R11 §42 unchanged. Kris approves the exact `git tag`/`gh release
create` commands and the release notes before they run. Closing the
round also closes round 11: the handoff says both are complete.
