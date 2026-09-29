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
Append it to the end of the last file, `121-150.md`: a
`<a name="N"></a>` line directly above `### N — <title>`, numbering
continuing from the last entry. Then add its line to that file's list
below, in the same format. When the next number passes the last
file's range, open the next range file (`151-180.md`, …) and add a
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
| [`121-150.md`](121-150.md) | §121 onward: rounds 9–11. **New entries go here.** |

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
