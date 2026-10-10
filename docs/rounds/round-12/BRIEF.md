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

## §18 — Publish v0.1.0, close the round (S18)

R11 §42 unchanged. Kris approves the exact `git tag`/`gh release
create` commands and the release notes before they run. Closing the
round also closes round 11: the handoff says both are complete.
