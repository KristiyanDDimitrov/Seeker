# Seeker history — index

The full investigation narrative behind every numbered entry: which
hypotheses were checked and ruled out, the real numbers from each
verification run, and why each fix looks the way it does. `CLAUDE.md`
keeps only the standing facts; this is where the evidence lives.

**Resolving a reference.** A source comment or doc that says
`HISTORY §N` means entry N. Find its line below and follow the link;
every entry has an `<a name="N"></a>` anchor directly above its
heading, so `file#N` lands on it. Link to an entry as
`docs/history/<file>#N` (from the repository root), never by the
heading-derived GitHub anchor, which breaks whenever a title changes.

**Adding an entry (every session, per the round brief's §0.6).**
Append it to the end of the last file, `181-210.md`: a
`<a name="N"></a>` line directly above `### N — <title>`, numbering
continuing from the last entry. Then add its line to that file's list
below, in the same format. When the next number passes the last
file's range, open the next range file (`211-240.md`, …) and add a
section for it here. Never renumber, move or rename an existing entry
or file: every `file#N` link depends on both staying put. Keep each
file under about 150 KB.

`docs/HISTORY.md` was the single file all of this lived in until round
11 S2 split it (§137); it is now a stub pointing here.

## Files

| File | Holds |
|---|---|
| [`early-fixes.md`](early-fixes.md) | The original file's header, and the four fixes that predate the numbered roadmap |
| [`001-024.md`](001-024.md) | §1–§24: the CLI pipeline, then the first UI steps |
| [`025-031.md`](025-031.md) | §25–§31: Review, tagging, Settings, packaging |
| [`032-046.md`](032-046.md) | §32–§46: stress test, duplicate detector, early bug reports |
| [`047-071.md`](047-071.md) | §47–§71: design system, the §56 phases, open items 63 and 70 |
| [`072-107.md`](072-107.md) | §72–§107: rounds 1–5 (the P, R, B and C series) |
| [`108-120.md`](108-120.md) | §109–§120: rounds 6–8 (toolchain, security, Phase 6) |
| [`121-150.md`](121-150.md) | §121–§150: rounds 9–11 |
| [`151-180.md`](151-180.md) | §151–§180: round 11 |
| [`181-210.md`](181-210.md) | §181 onward: round 11. **New entries go here.** |

No entry was ever written for §37, §57–§61, §97 or §108; those numbers
are unused, not missing files. §62 exists only as a follow-up heading
inside the §56 phases.

## Early fixes

In [`early-fixes.md`](early-fixes.md), by heading anchor:

- [CLI bypassed Application for playlist listing](early-fixes.md#cli-bypassed-application-for-playlist-listing)
- [matcher and quality fuzzy-matching logic drifted apart twice](early-fixes.md#matcher-and-quality-fuzzy-matching-logic-drifted-apart-twice)
- [Spotify field-name history: get_current_user_playlists](early-fixes.md#spotify-field-name-history-get_current_user_playlists)
- [Spotify field-name and endpoint history: get_playlist_tracks](early-fixes.md#spotify-field-name-and-endpoint-history-get_playlist_tracks)

## Entries

Addenda (a later follow-up filed under an existing number) are indented
under their entry and live in the same file, after it.

### `001-024.md`

- §1 — Confirm end-to-end `sync` works → [001-024.md#1](001-024.md#1)
- §2 — Local library scanning → [001-024.md#2](001-024.md#2)
- §3 — Matching → [001-024.md#3](001-024.md#3)
- §4 — SoulSeek search client → [001-024.md#4](001-024.md#4)
- §5 — Quality-ranking logic → [001-024.md#5](001-024.md#5)
- §6 — Phase 1 download orchestration → [001-024.md#6](001-024.md#6)
- §7 — `check` command already reports auto/needs-review/unmatched — a `review` command to… → [001-024.md#7](001-024.md#7)
- §8 — Phase 2 upgrade-tracking → [001-024.md#8](001-024.md#8)
- §9 — Metadata normalization, Phase A — multi-artist fix, done; tag-writing not yet built → [001-024.md#9](001-024.md#9)
- §10 — Metadata normalization, Phase B — writing tags → [001-024.md#10](001-024.md#10)
- §11 — Metadata normalization, Phase C — local audio analysis (BPM + estimated key) → [001-024.md#11](001-024.md#11)
- §12 — Centralized playlist-name resolution with an offer-to-refresh UX → [001-024.md#12](001-024.md#12)
- §13 — slskd shares the local library (upload side) + Phase 3: locked-file retry → [001-024.md#13](001-024.md#13)
- §14 — Phase 4: upgrade-candidate shortlisting → [001-024.md#14](001-024.md#14)
- §15 — Polish pass — dead code, mypy --strict, docstrings, error-handling audit, coverage audit… → [001-024.md#15](001-024.md#15)
- §16 — Live re-verification against the real "Test" playlist → [001-024.md#16](001-024.md#16)
- §17 — Soulseek needs-review tier → [001-024.md#17](001-024.md#17)
- §18 — Migrated the SQLite database path from CWD-relative to an OS-conventional app-data… → [001-024.md#18](001-024.md#18)
- §19 — Frontend Phase 0, Task 1 — local JSON config store for SoulSeek/slskd settings, with… → [001-024.md#19](001-024.md#19)
- §20 — Frontend Phase 0, Task 2 — real download progress tracking (bytes_transferred/total_bytes) → [001-024.md#20](001-024.md#20)
- §21 — Fix: a real, live-discovered rejection shape (peer-offline 404) escaped the… → [001-024.md#21](001-024.md#21)
- §22 — Frontend Step 3: UI scaffolding + main dashboard → [001-024.md#22](001-024.md#22)
- §23 — Frontend Step 4: onboarding wizard → [001-024.md#23](001-024.md#23)
- §24 — Frontend Step 5: download progress view → [001-024.md#24](001-024.md#24)

### `025-031.md`

- §25 — Fix: Phase 3 retry loop didn't dedupe stale duplicate rows before retrying → [025-031.md#25](025-031.md#25)
- §26 — Frontend Step 6: Review screen → [025-031.md#26](025-031.md#26)
- §27 — Frontend Step 7: Tagging panel — UI wiring complete; live verification completed for… → [025-031.md#27](025-031.md#27)
- §28 — Frontend Step 8: Settings → [025-031.md#28](025-031.md#28)
- §29 — UI polish pass → [025-031.md#29](025-031.md#29)
- §30 — Packaging task: turn `seeker-ui` into a distributable standalone app via PyInstaller → [025-031.md#30](025-031.md#30)
  - §30, §3 retry — closing the "doesn't crash" vs (same file, after §30)
- §31 — Follow-on packaging task: wrap item 30's already-verified `.app` into a real `.dmg`… → [025-031.md#31](025-031.md#31)

### `032-046.md`

- §32 — Broad end-to-end stress test: run the whole real pipeline together, overlapping and… → [032-046.md#32](032-046.md#32)
- §33 — Task: a per-download speed/ETA estimate on the Downloads tab → [032-046.md#33](032-046.md#33)
- §34 — Task: contextual help in the UI → [032-046.md#34](032-046.md#34)
- §35 — Task: support-the-creator links → [032-046.md#35](032-046.md#35)
- §36 — Packaging polish follow-on task (macOS ad-hoc signing + `.dmg` readme, Windows Inno Setup… → [032-046.md#36](032-046.md#36)
- §38 — Phase 0 spike for the duplicate/quality detector (roadmap item 5 in the original task… → [032-046.md#38](032-046.md#38)
- §39 — Phase 1 of the duplicate/quality detector (roadmap item 5, following item 38's Phase 0… → [032-046.md#39](032-046.md#39)
  - §39, addendum — the deadlock, fixed for real (same file, after §39)
  - §39, second addendum — closing two loose ends: a wrong citation, and (same file, after §39)
- §40 — Phase 2 of the duplicate/quality detector (item 39's own Phase 1 built fingerprinting… → [032-046.md#40](032-046.md#40)
  - §40, follow-up — a real match-status gap and a real performance (same file, after §40)
- §41 — Bounded verification pass, three scoped tasks: swap the real Revolut support link in for… → [032-046.md#41](032-046.md#41)
- §42 — Custom app icon, closing the "no custom `.icns`/`.ico`" gap items 30/31/36 each flagged… → [032-046.md#42](032-046.md#42)
- §43 — Real bug report, from an actual Finder double-click launch of the packaged app (not the… → [032-046.md#43](032-046.md#43)
- §44 — Real bug report, from an actual double-click launch of the packaged app: the wizard's… → [032-046.md#44](032-046.md#44)
- §45 — Real bug report: after tracks download successfully, the Dashboard keeps showing them as… → [032-046.md#45](032-046.md#45)
- §46 — Task: tagged tracks should stop asking to be tagged → [032-046.md#46](032-046.md#46)

### `047-071.md`

- §47 — Task: build a dark design system (`ui/theme.py`, color/spacing tokens, one global QSS… → [047-071.md#47](047-071.md#47)
  - §47, follow-up — the queued progress bar's real root cause (same file, after §47)
- §48 — Task: replace `MainWindow`'s `QTabWidget` shell with a sidebar → [047-071.md#48](047-071.md#48)
- §49 — Task: replace Settings' type-a-name-then-pick-a-folder library location flow with… → [047-071.md#49](047-071.md#49)
- §50 — Task: kill the "no configured destination" dead end (default destination config, a UI… → [047-071.md#50](047-071.md#50)
- §51 — Task: a Dashboard "next step" CTA plus real empty states → [047-071.md#51](047-071.md#51)
- §52 — Task: give the wizard's SoulSeek credential form real, distinguishing copy for a… → [047-071.md#52](047-071.md#52)
- §53 — Task 9's own brief scoped one piece as explicit recon, separate from the aggregate-ETA… → [047-071.md#53](047-071.md#53)
- §54 — Task: build a History page (Dashboard's own sidebar neighbor) showing recently downloaded… → [047-071.md#54](047-071.md#54)
- §55 — Task: a GitHub-releases-based "Check for updates" action (Help menu), then — once that… → [047-071.md#55](047-071.md#55)
- §56 — Phase 0 recon (five real investigations against the live, non-empty DB and library) plus… → [047-071.md#56](047-071.md#56)
  - §56, Phase 2 — local needs-review matches get a real review flow (same file, after §56)
  - §56, Phase 3 — Settings becomes an in-window page (same file, after §56)
  - §56, Phase 4 — tagging: cover art, honest reporting, caching (same file, after §56)
  - §56, Phase 5 — download UX and the duplicate-download bug (same file, after §56)
  - §56, Phase 6 — Duplicates tab (same file, after §56)
  - §56, Phase 7 — Sharing & Uploads (same file, after §56)
- §62, follow-up — real live verification of `add_location_to_share` → [047-071.md#62](047-071.md#62)
- §63 — Open investigation, genuinely unresolved — found live during Phase 7's attended… → [047-071.md#63](047-071.md#63)
- §64 — Straightforward — built as scoped, no investigation narrative beyond what's in… → [047-071.md#64](047-071.md#64)
- §65 — Phase 0 recon (read-only, reported and approved before any code was written) → [047-071.md#65](047-071.md#65)
- §66 — 0.2 confirmed by code (not live, since it's a pure logic question): a… → [047-071.md#66](047-071.md#66)
- §67 — Phase 6.5's real-file verification, run only after explicit user confirmation of the… → [047-071.md#67](047-071.md#67)
- §68 — 0.5's "Actions-column index-drift" hypothesis was REFUTED, not fixed — the third time… → [047-071.md#68](047-071.md#68)
- §69 — 0.6's initial real numbers, and a discrepancy worth recording honestly → [047-071.md#69](047-071.md#69)
- §70 — Open, real, unresolved investigation — found live while closing out items 68-69… → [047-071.md#70](047-071.md#70)
- §71 — New work block: `docs/rounds/round-01/BRIEF.md`, six real user-reported bugs (P1-P6)… → [047-071.md#71](047-071.md#71)

### `072-107.md`

- §72 — P1 → [072-107.md#72](072-107.md#72)
- §73 — P4 → [072-107.md#73](072-107.md#73)
- §74 — P5 → [072-107.md#74](072-107.md#74)
- §75 — P6 → [072-107.md#75](072-107.md#75)
- §76 — P2 → [072-107.md#76](072-107.md#76)
- §77 — P7 (5th report) → [072-107.md#77](072-107.md#77)
- §78 — P8 + P9 → [072-107.md#78](072-107.md#78)
- §79 — P12 + P11 → [072-107.md#79](072-107.md#79)
- §80 — P10 → [072-107.md#80](072-107.md#80)
- §81 — 0.1 + 0.2 + 0.3 → [072-107.md#81](072-107.md#81)
- §82 — P13: manual track search and download → [072-107.md#82](072-107.md#82)
- §83 — R1: post-implementation review of item 81 found a real build permanently dirtying the tree → [072-107.md#83](072-107.md#83)
- §84 — R6: Sharing's 401 Unauthorized → [072-107.md#84](072-107.md#84)
- §85 — R1: AIFF files invisible to the whole app → [072-107.md#85](072-107.md#85)
- §86 — R2: poll rebuild destroyed checkbox/radio state → [072-107.md#86](072-107.md#86)
- §87 — R5: global table chrome → [072-107.md#87](072-107.md#87)
- §88 — R3: bulk actions → [072-107.md#88](072-107.md#88)
- §89 — R4: cover art in Finder → [072-107.md#89](072-107.md#89)
- §90 — R7: run in the background from the macOS menu bar → [072-107.md#90](072-107.md#90)
- §91 — RR1-RR3: post-round review of round 3's own test-suite reporting → [072-107.md#91](072-107.md#91)
- §92 — B8: Spotify 401 unrecoverable without a restart → [072-107.md#92](072-107.md#92)
- §93 — B3: rename/tagging reporting fix, plus a real crash and a real data-loss path found… → [072-107.md#93](072-107.md#93)
- §94 — B5: only download real DJ formats → [072-107.md#94](072-107.md#94)
- §95 — B1: Enter submits on wizard/Settings forms → [072-107.md#95](072-107.md#95)
- §96 — B4: the "Queued" progress bar sat at the top of its cell → [072-107.md#96](072-107.md#96)
- §98 — B10: window title showed a commit SHA → [072-107.md#98](072-107.md#98)
- §99 — B9: the macOS menu bar icon, and "Check now"'s real name → [072-107.md#99](072-107.md#99)
- §100 — B7: removed the cover.jpg sidecar feature (reverses R4.2) → [072-107.md#100](072-107.md#100)
- §101 — B11: two observations confirmed against the real production DB → [072-107.md#101](072-107.md#101)
- §102 — Post-round review: B2.2/B4.3/B6.5's pixel verification was asserted, not recorded → [072-107.md#102](072-107.md#102)
- §103 — C1: header column dividers, a real bisect instead of a third guess → [072-107.md#103](072-107.md#103)
- §104 — C2: "Action" reads as ".ction" on an empty table → [072-107.md#104](072-107.md#104)
- §105 — C3: the Dashboard progress bar is a second site, B4 never touched → [072-107.md#105](072-107.md#105)
- §106 — C4: wordmark, brows over the real "ee" → [072-107.md#106](072-107.md#106)
- §107 — C5: light and dark themes, with system-follow → [072-107.md#107](072-107.md#107)

### `108-120.md`

- §109 — D2: the theme toggle changed the icon but not the palette → [108-120.md#109](108-120.md#109)
- §110 — D3: the C2.3 header-label floor fought Stretch columns — fix applied, bug not reproduced… → [108-120.md#110](108-120.md#110)
- §111 — D1: wordmark clipped at the bottom, only the left brow visible → [108-120.md#111](108-120.md#111)
- §112 — D5 (round 6): a menu bar left-click both opened the context menu and the window on macOS → [108-120.md#112](108-120.md#112)
- §113 — D4: closing a fullscreen window left a black macOS Space behind → [108-120.md#113](108-120.md#113)
- §114 — Round 7 (E1-E4): fullscreen close reversed again, empty-table columns, a stylesheet… → [108-120.md#114](108-120.md#114)
- §115 — Round 8 Phase 1: toolchain (ruff config, pytest config, CI) → [108-120.md#115](108-120.md#115)
- §116 — Round 8 Phase 3 + 3B: security hardening and the macOS Dock icon → [108-120.md#116](108-120.md#116)
- §117 — Round 8 S1.1/S1.3: CI billing block, fresh-install web login confirmed live → [108-120.md#117](108-120.md#117)
- §118 — Round 8 S4: deduplication (§8.1, §8.2) → [108-120.md#118](108-120.md#118)
- §119 — Round 8 Phase 6 (S5-S11.7): `MainWindow` decomposed into `ui/pages/*` → [108-120.md#119](108-120.md#119)
- §120 — Round 8 §12.9: the five UI feedback channels, named and audited → [108-120.md#120](108-120.md#120)

### `121-150.md`

- §121 — Round 9 §1.4: a real capture of test_history_refresh_ → [121-150.md#121](121-150.md#121)
- §122 — Round 9 §5.1-§5.3: table sorting was silently broken on every widget-only column → [121-150.md#122](121-150.md#122)
- §123 — Round 9 §2.1: live-verified what happens to a transfer when Seeker quits mid-download → [121-150.md#123](121-150.md#123)
- §124 — Round 9 §2.2: the quit-while-downloading confirmation, and the real single seam behind it → [121-150.md#124](121-150.md#124)
- §125 — Round 9 §2.3: the "not responding" quit hang — unreproduced live, mechanism confirmed… → [121-150.md#125](121-150.md#125)
- §126 — Round 10 S1 (§1.1–§1.4): Review's Confirm button — three defects behind one report → [121-150.md#126](121-150.md#126)
- §127 — Round 10 S2 blocked, S3 (§3.1–§3.2): the stress test's stale → [121-150.md#127](121-150.md#127)
- §128 — Round 10 S4 (§4.1–§4.3): the review/history CI flakes were one → [121-150.md#128](121-150.md#128)
- §129 — Round 10 S5 (§5): reopen after a fullscreen/zoomed close fills → [121-150.md#129](121-150.md#129)
- §130 — Round 10 S6 (§6): the fullscreen-close test pair, caller found → [121-150.md#130](121-150.md#130)
- §131 — Round 9 S7 (§3.2): start Seeker at login via `SMAppService` → [121-150.md#131](121-150.md#131)
- §132 — Round 9 S8 (§6): Review page resizable, persisted splitter → [121-150.md#132](121-150.md#132)
- §133 — Round 9 S9 (§7.1): the shared `PlaylistSelection` seam → [121-150.md#133](121-150.md#133)
- §134 — Round 9 S10 (§7.2): Library context header, inline picker, and a re-entrant segfault → [121-150.md#134](121-150.md#134)
- §135 — Round 10 S7 (§7): round 9's HISTORY debt paid → [121-150.md#135](121-150.md#135)
- §136 — Round 11 S1 (§1): round documents archived, docs index, round 10's S2 closed → [121-150.md#136](121-150.md#136)
- §137 — Round 11 S2 (§2): HISTORY.md split into docs/history/, anchors that work → [121-150.md#137](121-150.md#137)
- §138 — Round 11 S3 (§3): downloads never overwrite and never guess → [121-150.md#138](121-150.md#138)
- §139 — Round 11 S4 (§4): library integrity — limbo matches and location removal → [121-150.md#139](121-150.md#139)
- §140 — Round 11 S5 (§5.1–§5.5): portable Compose template; Settings never changes what is shared; one bring-up; per-user Compose copy; robust Sharing edits → [121-150.md#140](121-150.md#140)
- §141 — Round 11 S6 (§6.1–§6.4): Spotify sync survives duplicate tracks and local files; changed playlists refresh their tracks → [121-150.md#141](121-150.md#141)
- §142 — Round 11 S7 part 1 (§7.1–§7.4, §7.7): delete past SQLite's variable limit; scan and match outside the write lock; resolved location paths → [121-150.md#142](121-150.md#142)
- §143 — Round 11 S7 part 2 (§7.5–§7.6): never create dot-led names; the destination subfolder shown is the one used → [121-150.md#143](121-150.md#143)
- §144 — Round 11 S8 part 1 (§8.1–§8.2): a rejection sticks; a manual search leaves no orphan track → [121-150.md#144](121-150.md#144)
- §145 — Round 11 S8 part 2 (§8.3): failures stay visible, with a reason, until cleared → [121-150.md#145](121-150.md#145)
- §146 — Round 11 S9 part 1 (§9.1–§9.4, §9.6, §9.8): credential writes, token lock, encoded slskd paths, outbound URLs, typed config, tolerant 429 → [121-150.md#146](121-150.md#146)
- §147 — Round 11 S9 part 2 (§9.5): an honest OAuth callback page; a cancellable Spotify wait → [121-150.md#147](121-150.md#147)
- §148 — Round 11 S9 part 3 (§9.7): peer strings render as text; the S9-wide adversarial review → [121-150.md#148](121-150.md#148)
- §149 — Round 11 S10 (§10): CI and supply chain → [121-150.md#149](121-150.md#149)
- §150 — Round 11 S11 (§11): readable errors, uncaught-exception logging, Dashboard outcomes → [121-150.md#150](121-150.md#150)

### `151-180.md`

- §151 — Round 11 S12 part 1 (§12.1, §12.2, §12.4): the poll says slskd is down; a Start slskd that never guesses → [151-180.md#151](151-180.md#151)
- §152 — Round 11 S12 part 2 (§12.3, §12.5): the outage on screen; first-session download notifications → [151-180.md#152](151-180.md#152)
- §153 — Round 11 S13 (§13.1, §13.2): one exception hierarchy; typed download states → [151-180.md#153](151-180.md#153)
- §154 — Round 11 S14 part 1 (§14.1, downloads): typed download and poll results; a failed playlist track carries its reason → [151-180.md#154](151-180.md#154)
- §155 — Round 11 S14 part 2 (§14.1 rest, §14.2, §14.3): typed library, tag and fingerprint results; `_tag_one_track` as named steps → [151-180.md#155](151-180.md#155)
- §156 — Round 11 S15 (§15.1–§15.4): CLI structure — one handler per subcommand; --help never opens the database; no print or input in a service → [151-180.md#156](151-180.md#156)
- §157 — Round 11 S16 part 1 (§16.1, §16.2): repositories without a Database; dead code out of `src/` → [151-180.md#157](151-180.md#157)
- §158 — Round 11 S16 part 2 (§16.3–§16.6): no legacy migrations; Sharing through the client; one GET per status; a freed chromaprint context → [151-180.md#158](151-180.md#158)
- §159 — Round 11 S17 part 1 (§17.1, §17.2): placement and review leave `download_service.py` → [151-180.md#159](151-180.md#159)
- §160 — Round 11 S17 part 2 (§17.3, the line ceiling): named retry steps; polling moves to `soulseek/poller.py` → [151-180.md#160](151-180.md#160)
- §161 — Round 11 S18 (§18.1–§18.6): `tests/fakes.py`, `tests/repro/`, the smoke file split by concern, a layering test, no warnings, vacuous asserts → [151-180.md#161](151-180.md#161)
- §162 — Round 11 S19 (§19.1–§19.3): Dashboard flows move to `DashboardPage`; the shell calls only public page methods; `SLF001` enforced → [151-180.md#162](151-180.md#162)
- §163 — Round 11 S20 (§20.1–§20.3): the window lifecycle leaves `MainWindow` (`WindowLifecycleController`); the theme toggle to `ui/widgets.py`; `__init__` as named steps → [151-180.md#163](151-180.md#163)
- §164 — Round 11 S21 (§21): package regrouping — `audio/`, `files/`, slskd's Docker and sharing code into `soulseek/` → [151-180.md#164](151-180.md#164)
- §165 — Round 11 S22 part 1 (§22.1–§22.2): default `local_files` reads leave fingerprints out; the Dashboard poll reads one playlist's rows (28 ms → 0.24 ms) → [151-180.md#165](151-180.md#165)
- §166 — Round 11 S22 part 2 (§22.3–§22.6): four indexes; the history poll reads only tagged files (42 → 1.8 ms); lazy `scipy.stats` (CLI import 360 → 75 ms); a 64-entry art-cache LRU; the Dashboard skips unchanged re-renders (131 → 0.2 ms at 500 tracks) → [151-180.md#166](151-180.md#166)
- §167 — Round 11 S23 (§23): test gaps (tags, CLI, entry points, splitter, upload ETA); FLAC keys also in `INITIALKEY`; a tag save that outgrows the padding goes through a copy; CI floor 92 % → [151-180.md#167](151-180.md#167)
- §168 — Round 11 S24 part 1 (§24, services half): comment hygiene in the service layer; history references outside `ui/` 250 → 72 (split point; part 2 is models, database, audio, files, CLI, config files) → [151-180.md#168](151-180.md#168)
- §169 — Round 11 S24 part 2 (§24, the rest): comment hygiene in models, database, audio, files, CLI, entry points and config files; history references outside `ui/` 72 → 0; no history in `--help` → [151-180.md#169](151-180.md#169)
- §170 — Round 11 S25 (§25): comment hygiene in `ui/`; history references in `src/` that are not `HISTORY §N` pointers 499 → 0; no history in the Scan tooltip → [151-180.md#170](151-180.md#170)
- §171 — Round 11 S26 part 1 (§26.1–§26.2): refuse a library location inside or around another (by resolved path and on-disk identity); detect the nested pairs already registered (Settings warning, `seeker library check`); what the real DB's merge must carry → [151-180.md#171](151-180.md#171)
- §172 — Round 11 S26 part 2 (§26.3–§26.4): merge a nested library location into the one kept (matches, rejections, analysis, cleanups, destinations; same physical file only); Settings Fix… and `seeker library merge`; rehearsed on a DB copy, 43 matches kept, 0 lost → [151-180.md#172](151-180.md#172)
- §173 — Round 11 S27 part 1 (§27.0–§27.1): `tools/screenshots.py` (every screen and wizard step, both themes, two sizes, public widgets only); only real surfaces paint `BG_APP`, so cell widgets, checkboxes and radios show the row or card beneath → [151-180.md#173](151-180.md#173)
- §174 — Round 11 S27 part 2 (§27.2–§27.3): a theme-aware SVG combo chevron bundled through `_MEIPASS`; buttons take their size hint (`theme.action_row()`, scrolling Settings tabs) with a sweep over every harness screen → [151-180.md#174](151-180.md#174)
- §175 — Round 11 S27 part 3 (§27.4–§27.5): a visible focus ring that means keyboard focus (`_SeekerStyle`: clicks never focus a button); every per-row and icon button named; focus starts on the playlist list and never falls into a hidden page; 1 px splitter lines in a 7 px grab band; `TwoToneProgressBar` → [151-180.md#175](151-180.md#175)
- §176 — Round 11 S28 part 1 (§28.1–§28.2): `ColumnLayout` column policy (`fit_widths`: the primary column keeps its content width, widest secondary columns give way first, refit on resize; left-aligned headers; Duplicates' Format and Bitrate merge into Quality); one-line cells that elide with the full text on hover, paths in the middle; playlist lists elide instead of scrolling sideways → [151-180.md#176](151-180.md#176)
- §177 — Round 11 S28 part 2 (§28.3–§28.4): `EmptyState` in a table's viewport on Search, Sharing, History, Review and Downloads (replacing a span-row fake); copy in the user's words (Scan library / Match tracks, plain retry statuses, Get cover art from Spotify); Downloads' Role column → an Upgrade `BADGE_ROLE` pill; a painted close control; local build time → [151-180.md#177](151-180.md#177)
- §178 — Round 11 S29 part 1 (§29.1): Review candidates show their file name with quality and peer as `SECONDARY_ROLE` text (a palette-blended colour, ≥5.9:1), local matches show the file's tags, section titles count their rows; the tall-row bug is a render before first show, fixed by §176 and now regression-tested → [151-180.md#178](151-180.md#178)
- §179 — Round 11 S29 part 2 (§29.2–§29.3): Settings tabs by job (General, Library, Connections, Matching); thresholds as 0–100 spin boxes, needs-review below auto, a warning below 80; a saved threshold of 0 no longer reads as unset (`resolve_thresholds`); the Back button removed (sidebar only); Library's options and actions grouped by job, scrolling; "Tag selected" names the Dashboard's selection → [151-180.md#179](151-180.md#179)
- §180 — Round 11 S30 (§30.1–§30.2): "Booth" and "Harmonic" rendered over the real widgets by a scratch monkeypatch module; `docs/design/visual-direction.md` (tokens, contrast, Lucide, recommendation Booth without BPM/key); equal-contrast wheel hues; 3 of 6,921 real files carry a key; a decoration icon is invisible to the column fit; stopped at §30.3; Kris picked Booth violet (A′), no BPM/key, 2026-10-07 → [151-180.md#180](151-180.md#180)

### `181-210.md`

- §181 — Round 11 S31 (§31.1–§31.4): Booth violet tokens with AA floors on every accent and status pair; `theme.active_palette()` replaces the module-token bridge; Barlow Semi Condensed bundled (titles 26 px SemiBold, section headers 16 px Medium); status lamps (`ui/status_lamp.py`); a checkbox tick; the cell-widget pixel test is order-dependent on Cocoa → [181-210.md#181](181-210.md#181)
- §182 — Round 11 S32: the shell — Lucide nav icons (vendored unchanged, recoloured at draw time by `ui/icons.py`'s `TokenIconEngine`); the brows wordmark revived as an overlay on the plain label (`ui/wordmark.py`); the page header as one unit with a 90-character subtitle; a cue lamp on the activity strip (`StatusLamp`); notices with a lit left edge → [181-210.md#182](181-210.md#182)
- §183 — Round 11 S33: the onboarding wizard — a centred 560 px column with page titles; a step indicator of status lamps (`ui/step_indicator.py`); numbered Spotify registration steps; Docker and SoulSeek status chips (`StatusChip`); one primary action per step; SoulSeek outcomes on an `InlineNotice`; a failed bring-up no longer leaves the busy bar running → [181-210.md#183](181-210.md#183)
- §184 — Round 11 S34 part 1: the Dashboard — status lamps in the track table (review states no longer links); a segmented amber meter (`theme.style_meter`) on the Dashboard and the activity strip; playlist rows with counts (`DashboardService.get_playlist_summaries`, `MISSING_STATES`); three `ElidedTextDelegate` width fixes (icon, right margin, fractional advance); the strip's busy bar animates again after progress → [181-210.md#184](181-210.md#184)
- §185 — Round 11 S34 part 2: Library — `local_files.has_art` (read at scan, set when art is embedded; NULL until read, backfilled by the next scan); `TrackStatus.has_art`; a tag-state track list that writes and shows the shared track selection; the action groups as titled cards in a wrapping 280 px column → [181-210.md#185](181-210.md#185)
- §186 — Round 11 S35a: Search (one query row, file name first, a Locked pill, Quality sorted by the ranking's key), Downloads (status lamps, reasons as secondary text, the amber meter only for a transfer, `set_busy_meter`), History (playlist as secondary text), Duplicates (Keep first, Similarity spanned, `BAND_ROLE` group bands); outcomes and errors moved off four pages' status labels onto notices; `TwoToneProgressBar` removed → [181-210.md#186](181-210.md#186)
- §187 — Round 11 S35b part 1: Review (section titles in the panel lettering, a subtitle covering all three sections), Sharing (counts and tables first; "How sharing works" behind a remembered `Disclosure`, `ui/disclosure.py`; share and upload states as lamps; errors on the notice) → [181-210.md#187](181-210.md#187)
- §188 — Round 11 S35b part 2: Help and Support — section titles in the panel lettering, an 80-character `theme.reading_column` (a per-label cap clips wrapped text), Help's paths and build in one card, Support's duplicate framing removed; `QPalette.Link`/`LinkVisited` set to `ACCENT` (test first) → [181-210.md#188](181-210.md#188)
- §189 — Round 11 S35b part 3: Settings — every `QGroupBox` a `theme.section_card` (moved from `tagging_panel`), a reading column on General/Connections/Matching, SoulSeek split from its credentials form, the floating About button removed; outcomes moved off the status labels onto `library_notice`/`connections_notice` (test first; Test connection's errors showed nowhere) → [181-210.md#189](181-210.md#189)
- §190 — Round 11 S36: README images and final visual QA — 76 screens read; a secondary text with no room for three letters takes no width (test first: Downloads' lone "…"); sentence case and "…" in the last UI strings; `--readme` renders the wizard's first step → [181-210.md#190](181-210.md#190)
- §191 — Round 11 S37: README and developer docs — 755 lines to 178 with a live CI badge; `docs/architecture.md` (the one canonical module map, regenerated; the download state machine from `schema.py`; the threading model), `docs/cli.md` (checked against the parser: three missing options, two false statements), `docs/packaging.md` (Windows/Linux still labelled unverified); the index links every document → [181-210.md#191](181-210.md#191)
- §192 — Round 11 S38: CLAUDE.md refresh — the layout a link to `docs/architecture.md`; open issues checked against all 187 CI runs (focus-search and close-event flakes closed; a Search flake and the Cocoa theme failure added); the round's rules added; 62 KB → 29.8 KB, the UI rules moved word for word to `src/seeker/ui/CLAUDE.md`; two radon-D functions found → [181-210.md#192](181-210.md#192)
- §193 — Round 12 S1: the round-12 docs committed; one selection pair, `TEXT` on a new `SELECTION` (the field rule had no `selection-color`: dark mode's selected text was near-black, light mode's white; test first); `CUE`, the lamp and meter amber at 3:1, split from text-grade `WARNING` (light `#9E5C00` → `#AD7400`); before/after images → [181-210.md#193](181-210.md#193)
- §194 — Round 12 S2: "Follow system" clears the scheme override before resolving (Cocoa reports the last explicit choice until `Unknown`; test first with a stubbed `_CocoaStyleHints`); spin-box arrows in QSS with the combo chevron per palette (Fusion's were a 2×1 px speck on Cocoa; test first); match thresholds in `QLocale.c()`, as every score prints → [181-210.md#194](181-210.md#194)
- §195 — Round 12 S3: Review rebuilds a table only when its rows change (the 2 s tick deleted the button under the pointer and its tooltip; test first: the same `QPushButton` after an equal poll); a shown tooltip dies with its widget but survives its item being replaced (observed on Cocoa), so Downloads is unaffected; Sharing's 20 s per-row button left for S15 → [181-210.md#195](181-210.md#195)
- §196 — Round 12 S4: status columns sort closest to done first through a named rank beside the states (`track_status.PROGRESS_RANK`, `download_request.PROGRESS_RANK`; test first for each); the sweep found three more (Sharing's State and Shared, Library's Tags); the Dashboard's in-place progress path needs no key update → [181-210.md#196](181-210.md#196)
- §197 — Round 12 S5: the contact email is `kristiyanddimitrov@proton.me` (About and Support; test first); Support leads with "Support the artists", the brief's draft verbatim above Donate, list items spaced to the page's rhythm (test first: the section is first, its body Seeker's own markup); the subtitle kept; before/after images → [181-210.md#197](181-210.md#197)
- §198 — Round 12 S6: the security re-audit, read-only → `docs/rounds/round-12/AUDIT.md` (S-01–S-15): no critical or high; medium are urllib3 (S7), no CI dependency audit, peer files reaching native decoders (accept + track, [ASK]) and the DMG's missing GPL/LGPL texts (S16, [ASK]); low includes the OAuth `error`-before-`state` order and unsanitized peer basenames → [181-210.md#198](181-210.md#198)
- §199 — Round 12 S7: urllib3 2.8.0 (S-01); `tools/audit_dependencies.py`, pip-audit over every locked group in a CI `audit` job (push, PR, weekly), an ignore list whose entries expire, the native libraries recorded in `docs/packaging.md` (S-02); the slskd image pinned by digest (S-08); checkout keeps no token (S-13); the local failure set flipped to six selection-colour cases, pre-existing at `e85e951` → [181-210.md#199](181-210.md#199)
- §200 — Round 12 S8: the OAuth callback ignores a request without this attempt's state (S-05); Seeker's data, log and cache dirs 0700, a refused `chmod` logged (S-07); a RichLabel-escaping sweep and `main_ui.py` swept (S-12); a peer's basename cleaned at placement, stem and extension apart (S-06); APFS limits names by characters, not bytes (observed); S-03(a)+(b), S-09, S-10, S-11 accepted in writing → [181-210.md#200](181-210.md#200)
- §201 — Round 12 S9: `_decide_next_step` D 21 → A 5 and `_insert_slskd_share_directory` D 26 → C 11 (two characterization tests first; `radon cc -n D` reports nothing); Search's download-best race reproduced with a held fake and guarded; the theme flip-flop was window activation on Cocoa (active: a focused table tints its current item; inactive: `hasFocus` never comes), both tests fixed; the external display ruled out → [181-210.md#201](181-210.md#201)
