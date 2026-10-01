# Round 11 — session plan

**Purpose (unchanged): keep each Claude Code session inside a
predictable token budget.** This file is the index. The task text is in
`docs/rounds/round-11/BRIEF.md` and the ranked findings are in
`AUDIT.md`; nothing here repeats them.

**Budget: 150 K ceiling, ~120 K target.** Rounds 9 and 10 held this on
every row they ran by keeping one cohesive change per row. Three rules
apply:

1. **A row is one cohesive change.** Approving several items is approval
   to *do* them, not to do them in one session.
2. **Stop at your row's boundary even with budget left.**
3. **If a row overruns, stop at its named split point**, commit, and say
   exactly where you stopped (the handoff's "Files in progress" field).

This is the final polish round, and it is long by design: Kris asked for
completeness over economy. The order front-loads what protects the
user's files. The round can pause after any row without leaving the
codebase worse than it found it.

---

## Session map

`§` points into `BRIEF.md`. **[ASK]** rows start only after Kris's
explicit yes.

| # | Session | Executes | Est. | Split point if overrunning |
|---|---|---|---|---|
| **Phase A — Foundation** | | | | |
| ☑ S1 | Archive round docs, docs index, commit the round-11 docs, close round 10's S2 | §1 | ~70 K | After §1.2 (moves and links); the index can follow |
| ☑ S2 | Split HISTORY.md with anchors that work | §2 | ~110 K | After §2.1's lossless split is verified |
| **Phase B — Data safety (critical)** | | | | |
| ☑ S3 | Downloads never overwrite, never guess | §3 | ~130 K | After §3.3; the upgrade semantics (§3.4) can stand alone |
| ☑ S4 | Library integrity: limbo matches and location removal | §4 | ~130 K | After §4.3; removal (§4.4–§4.5) can stand alone |
| ☑ S5 | A portable Compose template (release blocker); Settings never changes what is shared (privacy) | §5 | ~130 K | After §5.2 and §5.5 (the blocker and the privacy fix); §5.3–§5.4 can stand alone |
| **Phase C — Correctness** | | | | |
| ☑ S6 | Spotify sync: duplicates, local files, stale tracks | §6 | ~120 K | After §6.2; staleness (§6.3–§6.4) can stand alone |
| ☑ S7 | Scale: big locations, short transactions, real and visible paths (HISTORY §142, §143) | §7 | ~140 K | After §7.1 and §7.4–§7.6 (limits and paths); §7.2, §7.3 and §7.7 (transaction shape and timing) can stand alone |
| ☑ S8 | Review decisions stick; failures stay visible | §8 | ~130 K | After §8.2 |
| **Phase D — Security** | | | | |
| ☑ S9 | Application hardening, including peer-string escaping | §9 | ~130 K | After §9.3; §9.4–§9.8 can stand alone |
| ☑ S10 | CI and supply chain | §10 | ~90 K | After §10.2 |
| **Phase E — Observability** | | | | |
| ☑ S11 | Readable errors; logs that catch everything; Dashboard outcomes that stay readable | §11 | ~130 K | After §11.2; §11.6 can stand alone |
| ☑ S12 | Say when slskd is down; first-session download notifications (HISTORY §151, §152) | §12 | ~110 K | After §12.2 |
| **Phase F — Structure (behaviour-neutral)** | | | | |
| ☑ S13 | One exception hierarchy; typed download states | §13 | ~130 K | After §13.1 |
| ☑ S14 | Typed service results (HISTORY §154, §155) | §14 | ~120 K | After the download and poll results |
| ☑ S15 | CLI structure (HISTORY §156) | §15 | ~110 K | After §15.1 |
| ☑ S16 | Service-layer cleanup and dead code (HISTORY §157, §158) | §16 | ~120 K | After §16.2 |
| ☑ S17 | Split `download_service.py` | §17 | ~130 K | After §17.1 |
| ☑ S18 | Test infrastructure | §18 | ~120 K | After §18.2; the smoke-file split can stand alone |
| ☑ S19 | MainWindow I: Dashboard flows move to DashboardPage | §19 | ~130 K | After the sync, scan and match flows move |
| ☑ S20 | MainWindow II: extract the window lifecycle | §20 | ~130 K | After geometry and close move; hide-to-tray can follow |
| ☑ S21 | **[ASK]** Package regrouping | §21 | ~120 K | After the first package |
| **Phase G — Performance and tests** | | | | |
| ☑ S22 | Performance (part 1 §22.1–§22.2, HISTORY §165; part 2 §22.3–§22.6, HISTORY §166) | §22 | ~120 K | After §22.1–§22.2 (the poll) |
| ☑ S23 | Test gaps | §23 | ~120 K | After §23.1 (`metadata.py`) |
| **Phase H — Hygiene** | | | | |
| ☐ S24 | Comment and config hygiene: core | §24 | ~130 K | After the services half |
| ☐ S25 | Comment hygiene: `ui/` | §25 | ~130 K | After `main_window.py` and `theme.py` |
| **Phase I — Nested locations** | | | | |
| ☐ S26 | Guard nested locations; guided cleanup | §26 | ~120 K | After §26.2 |
| **Phase J — UI consistency** | | | | |
| ☐ S27 | Screenshot harness; theme root causes; focus and accessibility | §27 | ~120 K | After §27.1 |
| ☐ S28 | Tables, empty states, copy | §28 | ~120 K | After §28.2 |
| ☐ S29 | Review and Settings information architecture | §29 | ~120 K | After §29.1 |
| **Phase K — Visual refresh** | | | | |
| ☐ S30 | **[ASK]** Visual direction: two grounded options; Kris picks | §30 | ~110 K | Hard stop at §30.3 |
| ☐ S31 | Refresh foundation: tokens, type, palette accessor | §31 | ~110 K | After §31.2 |
| ☐ S32 | Refresh: the shell | §32 | ~100 K | After the nav icons |
| ☐ S33 | Refresh: onboarding wizard | §33 | ~110 K | None; small enough to finish |
| ☐ S34 | Refresh: Dashboard and Library | §34 | ~130 K | After the Dashboard |
| ☐ S35a | Refresh: Search, Downloads, History, Duplicates | §35 | ~120 K | Per page |
| ☐ S35b | Refresh: Review, Sharing, Help, Support, Settings | §35 | ~120 K | Per page |
| ☐ S36 | README images and final visual QA | §36 | ~80 K | None |
| **Phase L — Docs** | | | | |
| ☐ S37 | README and developer docs | §37 | ~110 K | After §37.1 |
| ☐ S38 | CLAUDE.md refresh | §38 | ~90 K | None |
| **Phase M — Release** | | | | |
| ☐ S39 | Release engineering | §39 | ~110 K | After §39.2 |
| ☐ S40 | Automatic update check | §40 | ~90 K | None |
| ☐ S41 | Release-candidate acceptance (**Kris and Code**) | §41 | ~70 K | — |
| ☐ S42 | Publish v0.1.0 (Kris approves the outward actions); close the round | §42 | ~60 K | — |
| **Optional — [ASK]** | | | | |
| ☐ X1 | Clean up leftover slskd downloads | §X1 | ~100 K | — |
| ☐ X2 | Retry and cancel on the Downloads page | §X2 | ~110 K | — |

### Why this order

- **Phase A first.** Every later row writes a HISTORY entry. Splitting
  HISTORY before anyone appends means no entry has to move twice.
- **Phase B before everything else.** Three findings can destroy a
  user's files or break the app on another Mac. Nothing else in the
  round matters more.
- **Phases C–E before the refactors.** Phase F moves code around. It
  should move *fixed* code, so each refactor row can prove itself
  against an unchanged, correct test suite.
- **S18 before S19–S20.** Both MainWindow rows rewrite tests that
  import fakes from `test_ui_smoke.py`. Moving the fakes first means
  they are edited once.
- **Phase G after Phase F.** The new queries and tests land in the
  modules' final homes.
- **Phase H after all code moves** (otherwise comments are rewritten
  twice) and **before the UI rows**, so the refresh sessions read less
  noise. They must still follow §0.9 for new comments.
- **S26 after S4 and S7.** The merge depends on safe removal and
  resolved paths.
- **Phase J before Phase K.** The refresh builds on a theme that already
  renders correctly. S30 stops for Kris's decision.
- **Phase M last, with acceptance (S41) before publishing (S42).** A
  release is outward-facing; it ships only what S41 verified on a clean
  account.

---

## Skills: resolve these at the start of every session

List your available skills and resolve the real names first. Kris asked
for the `engineering-advanced-skills` bundle; its skills are listed
under their short names.

| Rows | Reach for |
|---|---|
| S1, S2, S37, S38 | `codebase-onboarding` (a docs structure a newcomer can navigate) |
| S3, S4, S6, S7, S8 | `focused-fix` (feature-wide repair) and `tdd` (failing test first); plus `database-designer` for S4 and S7 |
| S5, S9 | `env-secrets-manager`; the engineering bundle's `adversarial-reviewer` before the close-out commit |
| S10 | `ci-cd-pipeline-builder`, `dependency-auditor` |
| S11, S12 | `observability-designer` |
| S13–S20, S24, S25 | `tech-debt-tracker` (re-run its scanner; show the targeted counts drop); `pr-review-expert` before each close-out |
| S21 | `migration-architect` |
| S22 | `performance-profiler` |
| S23 | `tdd` |
| S26 | `database-designer`, `migration-architect` |
| S27–S36 | `frontend-design` (ground the design in the subject, spend boldness in one place, keep a quality floor, critique screenshots) |
| S39–S42 | `changelog-generator`, `runbook-generator`, `ship-gate` (re-run in S41; adjudicate web-only checks as the audit did) |
| Any row, optional | `self-eval` for an honest score of the work before close-out |

If a skill contradicts the brief, follow the skill for **how** and the
brief for **what**, and record the divergence in the handoff.

---

## Session protocol

**Starting.** Read, in this order and nothing else:

1. `docs/HANDOFF.md`
2. This file, **your row only**
3. `BRIEF.md` §0, plus the § your row executes
4. `CLAUDE.md`

**Working.**
- One commit per numbered item.
- Failing test first for every fix (§0.4).
- Read files by range, never whole (§0.1).
- Real data is read-only and migrations are rehearsed on a copy (§0.7).

**Stopping.** At your row's boundary, or at its named split point.

**Ending.**
1. Append your HISTORY entry: `docs/HISTORY.md` in S1; from S2 on, the
   last file under `docs/history/`, plus its index line.
2. Commit. Quote the three numbers.
3. Tick your box here.
4. Rewrite `docs/HANDOFF.md` following the contract below.
5. Push, and record the CI run id and its result.

**S1 only:** the first commit of the round is the four documents the
audit chat wrote: `AUDIT.md`, `BRIEF.md` and this file under
`docs/rounds/round-11/`, and the rewritten `docs/HANDOFF.md`. They are
not yet committed.

### The handoff contract

The next session is a stranger. `docs/HANDOFF.md` carries these nine
fields, in this order, in under about 120 lines. The last five follow
the `tc-tracker` handoff format.

1. **Current state:** the HEAD commit, whether the tree is clean, the
   three numbers, and the CI run id and result.
2. **Where we are:** rows done, and the next row.
3. **Session report:** one line per commit, with where the before and
   after evidence is (the HISTORY entry). Do not narrate.
4. **Key context:** anything discovered that changes a later row, and
   the gotchas it took real effort to find. Write each as a statement
   with its evidence. This is the field that gets dropped and matters
   most.
5. **Decisions made:** each decision with its rationale. Promote any
   standing rule to CLAUDE.md in the same commit.
6. **Blockers:** what stops progress right now. Empty means none.
7. **Files in progress:** only when stopping at a split point, as path
   plus state (`editing`, `partially_done`, `needs_review`).
8. **Waiting on Kris:** approval gates, then live checks.
9. **Open questions.**

---

## Waiting on Kris

**Interim cautions: avoid these until their fix lands.**

- ~~**Until S3:** on Review, do not use **Replace** with **Delete old
  file** checked.~~ Lifted: fixed in S3 (A-01, HISTORY §138).
- ~~**Until S5:** do not use Settings → Connection → **Update SoulSeek
  credentials**.~~ Lifted: fixed in S5 part 1 (A-54, HISTORY §140).

**Approval gates:**

- [x] **S1 §1.6** — `Claude outputs/`: delete it, gitignore it, or leave
      it. **Answered 2026-09-29: the default, leave it.**
- [x] **S10 §10.2** — turn on the repository's private vulnerability
      reporting, so `SECURITY.md`'s advisory link works. **Done by Kris
      2026-09-30; confirmed `{"enabled":true}` via
      `gh api repos/{owner}/{repo}/private-vulnerability-reporting`.**
- [x] **S21** — package regrouping (`seeker/audio/`, `seeker/files/`,
      and slskd code into `soulseek/`): yes or no. **Answered
      2026-10-01: yes, all three. Done in S21 (HISTORY §164).**
- [ ] **S30** — the visual direction: "Booth", "Harmonic", a mix, or
      neither. Also whether the Dashboard shows BPM and key.
- [ ] **S39 §39.3** — the bundle identifier. Recommended:
      `io.github.kristiyanddimitrov.seeker`. It must change before the
      first release.
- [ ] **S42** — the exact `git tag` and `gh release create` commands and
      release notes, before they run.
- [ ] **X1, X2** — optional features: leftover-download cleanup;
      retry and cancel on Downloads.

**Real-desktop checks Code cannot do,** consolidated into S41's
checklist (carried items marked):

- [ ] Fresh macOS user account: DMG, Gatekeeper, the full wizard with
      Docker. This is the live test of S5.
- [ ] After S4: a Scan re-matches the two Denzel Curry tracks that are
      in limbo now.
- [ ] After S26: the nested-location Fix… (the real click).
- [ ] *(carried from rounds 9 and 10)* The stress test:
      `SEEKER_RUN_STRESS_TEST=1 uv run pytest tests/test_stress_e2e.py`,
      with the X9 Pro mounted and Spotify and slskd up. It now also
      tests S22's item-70 lead and S20's lifecycle move.
- [ ] *(carried from round 10 §5)* Fullscreen close → Dock reopen;
      windowed resize → close → reopen; fullscreen close → quit →
      relaunch.
- [ ] *(carried from round 9 §3.2)* "Start Seeker at login" on the
      packaged app, and "start hidden".
- [ ] *(carried)* From a second device, `http://<mac-lan-ip>:5030` must
      not answer.
- [ ] *(carried)* The Review splitter and Library header on a real
      display, both themes.

---

## Exit criteria for the round

Measured in S42's close-out. Each item is a number or a yes/no.

- Every finding in `AUDIT.md` is either fixed, with its row ticked, or
  recorded as consciously deferred with a reason.
- CI is green on the release commit. Branch coverage is at or above the
  floor S23 sets, and CI enforces the floor.
- `mypy --strict` is clean, and `ruff check`, with the added E30, G201
  and TRY400 rules, reports 0 findings.
- radon reports no function above complexity **C** in `src/`.
- `ruff check --select SLF001 src/seeker/ui/main_window.py` reports 0.
- `grep -rcE "Roadmap item|round [0-9]+|§[0-9]"` over `src/` reports 0
  outside `HISTORY §N` pointers.
- The README is under about 200 lines, and the docs index links every
  document.
- v0.1.0 is published on GitHub with its DMG and SHA-256, and "Check
  for updates…" returns up-to-date against it.
