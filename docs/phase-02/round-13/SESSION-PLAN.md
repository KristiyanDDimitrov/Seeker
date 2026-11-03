# Round 13 — session plan

**Purpose: keep every session inside a measured token budget.** This
file is the index. The task text lives in `BRIEF.md` (`§`), the
findings in `AUDIT.md` (`PF-NN`); nothing here repeats them. Status is
machine-tracked in `tasks.json` beside this file. Re-planned on
2026-11-02 with the session-plan method; it replaces the 2026-10-17
map (11 rows, est. 60–120 K each), keeping its order and its § numbers.

Paths: `BRIEF.md` is `docs/phase-02/round-13/BRIEF.md`, `AUDIT.md` is
`docs/phase-02/AUDIT.md`.

**Budget (peak context):** baseline B = 62 K measured (S0 aims for
~54 K) · target ~120 K · soft ceiling 150 K (finish the commit in
flight, stop at the split point) · hard ceiling 180 K (stop editing,
write the handoff). Rows are packed to ≤ 65 K of work, so that B +
work stays near the target (see Estimate notes). A `row-worker`
subagent starts lower, est. ~30 K (UNVERIFIED; wave 1 records it), so
a worker's peak is about 30 K + work.

1. **A row is one cohesive change.** Approving several items approves
   doing them, not doing them in one session.
2. **Stop at your row's boundary even with budget left.**
3. **If a row overruns, stop at its named split point**, commit, and
   record exactly where you stopped (handoff field 7). A split point
   here supersedes the brief's.

> **Execution moved (2026-11-03):** this round's open rows run in
> [`../autodev/SESSION-PLAN.md`](../autodev/SESSION-PLAN.md), an
> `autonomous-development` plan; status lives in its `tasks.json`.

## Session map

`§` points into `BRIEF.md`. **[ASK]** rows start only after Kris's
explicit yes. **Gate** rows block the next row until Kris verifies.
Est. work includes the type's risk factor; est. peak is B + work.

| # | Session | Type | Executes | Est. work | Split point if overrunning |
|---|---|---|---|---|---|
| **A — Method and groundwork** | | | | | |
| ☑ S0 | Baseline cut: a `CLAUDE.md` core plus path-scoped topic files; two plugins off in this folder (scope approved 2026-11-02) | Refactor | "S0" below | ~45 K | After the split is committed, before the pointer sweep |
| ☑ S1 | Help → Build names the architecture, and Rosetta (PF-05) | Behaviour | §1.2 | ~65 K | After the Qt-free function and its tests |
| ☑ S1b | **[ASK]** v0.1.1's record; Dependabot #5 mypy, #7 ruff, #8 platformdirs, #9 python-dotenv | Behaviour | §1b | ~60 K | After v0.1.1's record and two PRs |
| ☑ S1c | **[ASK]** Dependabot #1 checkout, #6 uv_build, #12 setup-uv, #13 slskd; the `dependabot.yml` comment | Behaviour | §1b | ~65 K | After #1 and #12 (the actions) |
| ☑ S1d | Spotify Premium in the README and the wizard | Behaviour | §1d | ~60 K | After the wizard step and its test |
| **B — Intel installs and passes the suite** | | | | | |
| ☑ S2 | The Intel pins and the forked lock; native set unchanged; audit (PF-01) | Behaviour | §2 steps 1–3 | ~60 K | After the lock commit, before the audit |
| ☑ S2b | `tests/test_lock_platforms.py` | Behaviour | §2 step 4 | ~50 K | — |
| ☑ S3 | `.venv-x86_64` under Rosetta; the whole suite on x86_64; the failure list; re-plans S3b | Investigation | §3 steps 1–3 | ~65 K | After the environment's versions are pasted |
| ☑ S3b | Rosetta triage: the chromaprint skip that cannot hide an Intel lookup bug (one cause, §255), timings, commands and platform facts | Investigation | §3 steps 4–6 | ~35 K (re-estimated by S3) | After the chromaprint skip commit, before the timings |
| ☑ S4 | CI: a blocking `macos-15-intel` job (PF-03) | Behaviour | §4 | ~45 K | After the first run is recorded; a runner-only failure becomes its own row |
| **C — Both apps build and pass a smoke test** | | | | | |
| ☑ S5 | `seeker-ui --smoke-test`, passing unfrozen (PF-06) | Feature | §5 steps 1–2 | ~80 K | After the import, theme and resource checks pass with the report written; analysis and chromaprint then move to S5b |
| ☑ S5b | The smoke test on the frozen Apple silicon app | Behaviour | §5 step 3 | ~45 K | After the first frozen report |
| ☑ S6 | `target_arch` explicit; per-architecture names; the post-build `lipo`/`minos` check (PF-02, PF-04) | Feature | §6 steps 1–2 | ~65 K | After step 1, with both bundle sizes |
| ☑ S6b | The Intel app built under Rosetta: post-build check, smoke test, timings | Behaviour | §6 steps 3–4 | ~40 K | — |
| ☑ S7 | `build.yml`: both apps built and smoke-tested in CI | Feature | §7 | ~50 K | After the first dispatched run is recorded |
| **D — Document, accept, release** | | | | | |
| ☑ S8 | Documents for two Macs (PF-04, PF-07) | Docs | §8 | ~50 K | After README and RELEASING |
| ☐ S9 | **Gate.** Release-candidate acceptance: Code's half, then Kris's checklist | Release | §9 | ~35 K | At the gate |
| ☐ S10 | **[ASK]** Publish v0.2.0; close round 13 | Release | §10 | ~45 K | At each approval |

Total ≈ 980 K of work over 18 rows. The brief's §1.1 (commit the
planning documents) ran at the re-plan.

### S0 — the baseline cut

No brief section; this is it. Kris chose the scope on 2026-11-02.

1. Kris runs `/context` once at the start; the split (system prompt,
   tools, MCP, memory files, skills) goes into the HISTORY entry.
2. `.claude/settings.local.json` (untracked) sets
   `marketing-skills@claude-code-skills` and
   `product-skills@claude-code-skills` to `false` under
   `enabledPlugins`. A marketing session in this folder turns them back
   on.
3. `CLAUDE.md` becomes a core of ≤ ~15 KB: Architecture, Layout,
   Conventions, Commands, Working agreements, and a topic index that
   names each file below ("read before touching X"). Default homes:
   Spotify/OAuth → `src/seeker/spotify/CLAUDE.md`; SoulSeek/slskd →
   `src/seeker/soulseek/CLAUDE.md`; Database →
   `src/seeker/database/CLAUDE.md`; Packaging → `packaging/CLAUDE.md`;
   Testing → `tests/CLAUDE.md`; Qt and threading →
   `src/seeker/ui/CLAUDE.md`; Accepted risks, Open issues and Roadmap →
   a document the core links (S0 picks it). **Move, never delete**
   (working agreement 1): every fact keeps its wording and its § link.
   Move by line range with a script, never by re-typing.
4. Every pointer to a moved section (`grep -rn "CLAUDE.md" src tests
   tools docs/*.md`) still resolves, and a link check finds 0 broken.
5. Path-scoped loading: read one file in `src/seeker/soulseek/` and
   record whether its `CLAUDE.md` arrives as a system reminder. Replace
   `src/seeker/ui/CLAUDE.md:4`'s UNVERIFIED with what was seen; S1
   confirms it from a fresh session.

**Done when:** the core is ≤ ~15 KB; every moved fact exists exactly
once; the link check is clean; the check is green. S1 measures the
yield.

### Why this order

- **S0 first:** every later row pays B.
- **S1** is independent and small. It lands before S5, so the smoke
  report can carry the architecture line, and before S9, whose
  checklist reads Help → Build.
- **S1b and S1c before S2:** five of the eight PRs change `uv.lock`
  and three change `ci.yml` or the build; S2 rewrites the lock, and S4
  and S7 copy the action pins.
- **S1d early:** it doesn't depend on the Intel work and reaches
  `main` early, whenever v0.2.0 ships.
- **S2 → S2b → S3:** nothing installs on Intel without the pins; the
  lock test guards them; then the suite runs.
- **S3 before S4:** Rosetta gives a fast local failure list, and the
  runner confirms it on real hardware. A failure only the runner
  shows is the most informative result this round can produce.
- **S5 before S6:** the smoke test passes on the known-good Apple
  silicon build before it judges the Intel one.
- **S7 after S6b:** it automates what S5b and S6b did by hand.
- **S8 before S9:** the acceptance run follows the README.
- **Round 14 may run beside this round** (phase README → Rounds).
  Shared: `ci.yml` (S1c, S4, S7; R14 S1, S11), `RELEASING.md` (S8),
  `packaging/` (S6), `pyproject.toml` with `uv.lock` (S1b, S1c, S2).
  Whoever lands second builds on the other's change, never over it.

### Reading lists

Every row first reads the **common list** (~5 K): `docs/HANDOFF.md` ·
its row here (`grep -n "S<n>"` this file, then that range) ·
`BRIEF.md:28-91` (§0) · `docs/phase-01/round-11/BRIEF.md:19-83`
(R11 §0). UI rows (S1, S1d, S5) add `src/seeker/ui/CLAUDE.md` (4.8 K).
After S0 a topic `CLAUDE.md` arrives by itself when a file in its
folder is read (if S0 confirms it); otherwise read it per the core's
index. Then:

- **S0** (~5 K): `CLAUDE.md` headings (`grep -n "^##"`; the text is in
  context) · `.claude/settings.local.json` · `docs/README.md` (1.4 K)
  · `src/seeker/ui/CLAUDE.md:1-10` · `docs/history/241-270.md:148-222`
  (the entry format, 1.2 K)
- **S1** (~10 K): `BRIEF.md:126-148` · `AUDIT.md:167-181` ·
  `src/seeker/_build_info.py` (0.4 K) · `src/seeker/ui/dialogs.py:40-110`
  (0.8 K) · `src/seeker/ui/pages/static_pages.py:120-150` (0.4 K) ·
  `tests/pages/test_static_pages.py:60-100` (0.5 K) ·
  `docs/architecture.md` Module map (`grep -n` the `ui/` rows, ~0.4 K) · ui `CLAUDE.md`
- **S1b** (~5 K): `BRIEF.md:150-202` (0.8 K) · `gh pr view <n> --json
  title,files,statusCheckRollup` per PR (~0.5 K each) ·
  `CHANGELOG.md:1-30` (0.3 K) · `pyproject.toml:1-56` (0.4 K) ·
  `docs/history/241-270.md:148-222` (1.2 K)
- **S1c** (~6 K): `BRIEF.md:150-202` (0.8 K) ·
  `.github/workflows/ci.yml` (0.7 K) · `.github/dependabot.yml` (0.2 K)
  · `pyproject.toml:30-38` · HISTORY §204 and §238 (`grep -n` the
  index, then each range, ~3 K) · `gh pr view` per PR
- **S1d** (~8 K): `BRIEF.md:204-232` (0.5 K) ·
  `src/seeker/ui/wizard.py:180-260` (1.0 K) · `README.md:60-97`
  (0.4 K) · `tests/test_wizard.py:80-110` (0.4 K) ·
  `tools/screenshots.py:695-715` (0.2 K) · `CHANGELOG.md:1-30` · ui
  `CLAUDE.md`
- **S2** (~6 K): `BRIEF.md:234-299` (0.9 K) · `AUDIT.md:84-116`
  (0.6 K) · `pyproject.toml:1-56` (0.4 K) ·
  `tools/audit_dependencies.py` (1.3 K) · uv's documentation on
  `constraint-dependencies` and `required-environments` (~3 K)
- **S2b** (~3 K): `BRIEF.md:263-299` (0.5 K) · `uv.lock` by `grep -n`
  only: `resolution-markers`, then numba's entries (~1.5 K) and one
  sdist-only or pure package entry
- **S3** (~1 K): `BRIEF.md:301-346` (0.6 K) · `.gitignore`
- **S3b** (~2 K + each failure): S3's HISTORY entry (its failure list)
  · `BRIEF.md:322-346` · each failing test by range
- **S4** (~1.5 K): `BRIEF.md:348-376` (0.4 K) · `AUDIT.md:140-149` ·
  `.github/workflows/ci.yml` (0.7 K)
- **S5** (~12 K): `BRIEF.md:378-422` (0.6 K) · `AUDIT.md:187-201` ·
  `src/seeker/main_ui.py` (1.6 K) · `src/seeker/audio/analysis.py:52-128`
  (0.9 K) · `packaging/seeker.spec:95-171` (0.7 K) · the theme's font,
  icon and template lookups by `grep -n` (~1 K) ·
  `docs/architecture.md` Module map (`grep -n` the `ui/` rows, ~0.4 K) · ui `CLAUDE.md`
- **S5b** (~3 K): `BRIEF.md:386-422` (0.5 K) · `packaging/build_dmg.py`
  (1.0 K) · `packaging/seeker.spec:95-171` (0.7 K) ·
  `RELEASING.md:27-76` (0.5 K)
- **S6** (~6 K): `BRIEF.md:424-469` (0.6 K) · `AUDIT.md:118-138` and
  `:151-165` (0.7 K) · `packaging/seeker.spec` (2.0 K) ·
  `packaging/build_dmg.py` (1.0 K) · `packaging/bundle_info.py:1-60`
  (0.6 K) · HISTORY §214 (the `minos` measurement, ~1 K)
- **S6b** (~2.5 K): `BRIEF.md:444-469` (0.4 K) ·
  `packaging/bundle_info.py:100-176` (~1 K) · HISTORY §215 (vendored
  licences, ~1 K)
- **S7** (~2 K): `BRIEF.md:471-492` (0.3 K) · `.github/workflows/ci.yml`
  (0.7 K) · `packaging/build_dmg.py` (1.0 K)
- **S8** (~6 K): `BRIEF.md:494-517` (0.3 K) · `AUDIT.md:151-165` and
  `:203-211` (0.6 K) · `README.md:55-100` (0.5 K) · `docs/packaging.md`
  (2.5 K) · `RELEASING.md` (1.3 K) · `CHANGELOG.md:1-30` ·
  `packaging/Read Me First.txt` (0.3 K)
- **S9** (~2 K): `BRIEF.md:519-546` (0.5 K) · `RELEASING.md:27-76`
  (0.5 K) · `docs/phase-01/round-12/ACCEPTANCE.md`'s headings (the
  format)
- **S10** (~3 K): `BRIEF.md:548-556` · `RELEASING.md` (1.3 K) · this
  file's Exit criteria · `docs/history/241-270.md:148-222` (v0.1.0's
  release entry as the model, 1.2 K)

### Skills

Load one only where it is listed: each costs its `SKILL.md` on load.
Workers load none: `row-worker` has no Skill tool, whose listing would
raise its baseline.

| Rows | Skill | Load cost |
|---|---|---|
| S1, S1d, S2b, S5, S6 | `tdd` (a failing test first) | ~1.1 K |
| S1b, S1c, S2 | `engineering-advanced-skills:dependency-auditor` | ~1.3 K |
| S3b, only for an x86_64-only failure | `engineering-advanced-skills:focused-fix` | ~3.9 K |
| S4, S7 | `engineering-advanced-skills:ci-cd-pipeline-builder` | ~0.9 K |
| S9, S10 | `engineering-advanced-skills:ship-gate` | ~1.9 K |
| Any, only with budget left | `engineering-skills:adversarial-reviewer` before close-out | ~3.4 K |

If a skill contradicts the brief, follow the skill for **how** and
the brief for **what**, and record the divergence in the handoff.

## Execution: a lead and parallel workers

Kris wants less context rot and more speed; token limits don't matter
to him (2026-11-02). So most rows run as subagents, each in a fresh
context and its own git worktree, several at once, under one lead
session per wave.

**Executors.**

- **Solo:** a top-level session runs the row itself: S0 (which also
  confirms that the agents in `.claude/agents/` load) and S10.
- **Lead:** the top-level session Kris talks to, one per wave. It does
  no row's core work except S1b and S1c (one `upstream-reader` per
  Dependabot PR, in parallel; Kris approves each merge; a PR that
  needs a code change gets a worker) and S9's Code half. It spawns
  workers, relays every question and approval to Kris, and integrates
  finished rows.
- **Worker:** a `row-worker` subagent, spawned in the background with
  `isolation: "worktree"`: one row in its own context, on branch
  `r13/S<n>`.

**Waves.** A lead starts each row of its wave once the row's
`depends_on` rows are integrated, at most 3 workers at once (suites,
numba's JIT and PyInstaller compete for the CPU).

| Wave | Executor | Rows |
|---|---|---|
| 0 | solo | S0 |
| 1 | lead | S1b, S1c (the lead); workers S1, S1d |
| 2 | lead | workers S2 and S5, then S2b, S3, S5b |
| 3 | lead | workers S3b and S6, then S4 and S6b |
| 4 | lead | workers S7 and S8, then S9's Code half (the lead), then Kris's gate |
| 5 | solo | S10 |

Critical path: S0, S1b, S1c, S2, S3, S3b, S4, S7, S9, S10 (10 of 18
rows). A lead nearing ~120 K starts no worker, integrates what has
finished and writes the handoff; a fresh lead continues the wave. S4
and S7 need CI: the worker writes and validates the workflow and stops
with "needs CI"; the lead pushes the branch or dispatches the run and
resumes the worker with the result through `SendMessage`. After
integrating S3, the lead creates the main checkout's `.venv-x86_64`
with S3's recorded commands (its check needs it from S3b on). Kris
may ask for a wave as a Workflow script ("use a workflow"); not the
default.

**Workers** follow `.claude/agents/row-worker.md`: `uv sync --locked`
in the worktree, offscreen suites, the Working rules; no push, GitHub
change, docker or shared file; a stop at the boundary, the split
point, a question for Kris or ~120 K; then one fixed-format report
with a HISTORY draft.

**The lead's protocol.**

1. **Start:** `docs/HANDOFF.md`, this section, `tasks.json`; the check
   on `main` via `suite-runner`.
2. **Spawn:** `Agent(subagent_type="row-worker", isolation="worktree",
   description="Round 13 S<n>", prompt="Execute row S<n> of
   docs/phase-02/round-13/SESSION-PLAN.md. main is at <sha>.")`, plus
   any answer from Kris the row needs. `SendMessage` is a deferred
   tool: load it with ToolSearch before resuming a worker.
3. **Integrate** finished rows one at a time: `diff-reviewer` on the
   branch (optional); rebase it onto `main` in its worktree
   (`git -C <worktree> rebase main`), then `git merge --ff-only
   r13/S<n>`, resolving CHANGELOG conflicts; the check on `main`,
   native Cocoa (the three numbers), via `suite-runner`; the worker's
   HISTORY draft under the next free number, with its index line; its
   standing facts into `CLAUDE.md` or the topic file; its `tasks.json`
   row (`actual_peak_k` from its USAGE line) and box; commit "S<n>
   close-out (HISTORY §N)"; push; CI in the background (Working,
   below); `git worktree remove` and delete the branch.
4. **End of wave, or at ~120 K:** overwrite `docs/HANDOFF.md` with the
   rows done, in flight and next.

**Helper agents** in `.claude/agents/`; any top-level session may use
them, workers can't:

| Agent | Use | Model |
|---|---|---|
| `suite-runner` | A suite (native, offscreen or `.venv-x86_64`) or the check: summary, duration, each failure's cause | sonnet |
| `ci-watcher` | A run's conclusion and job times; on failure the last 40 log lines and a diagnosis | haiku |
| `upstream-reader` | One upgrade's notes, changelog and diff: ≤ 250 words and a verdict | inherit |
| `diff-reviewer` | An adversarial review of a branch's diff: ≤ 10 ranked findings | inherit |
| `row-worker` | One row in a worktree (above) | inherit |

**Parallel safety.** One writer: only the lead writes
`docs/HANDOFF.md`, `tasks.json`, `docs/history/*`, this file's boxes
and `main`'s history, and only it pushes. HISTORY numbers follow
integration order. Workers' suites run offscreen, so the lead's Cocoa
check runs alone. Each worktree has its own environments; none uses
the main checkout's. At most 3 workers at once.

**UNVERIFIED until wave 1 records them** (in its HISTORY entries and
the handoff): custom agents load at session start; subagents receive
`CLAUDE.md` or not; a subagent can't spawn subagents;
`isolation: "worktree"`'s branch naming, location and cleanup; a
worker's baseline, and where subagent transcripts are stored
(`tokens.py measure` reads only top-level ones). **Fallback:** if a
worker misbehaves, its row runs as a solo session, as before.

## Session protocol

Solo sessions and leads follow this protocol, workers follow
`.claude/agents/row-worker.md`, and a lead runs the Ending steps for
each row it integrates (step 4, the handoff, at the wave's end or at
~120 K).

**Starting.** Read, in this order and nothing else:

1. `docs/HANDOFF.md`
2. This file: **your row, its reading list and this protocol only**
3. The § sections your row points at, plus each `PF-NN` they name
4. The files on your reading list, by the ranges given

Then run the check, summary lines only: `uv run pytest -q 2>&1 |
tail -3` · `uv run mypy --strict src/ | tail -1` · `uv run ruff check
src tests tools | tail -1`. A failure you inherited is your first job;
say so in the handoff. **Wave 1's lead only:** first run `python3
~/.claude/skills/session-plan/scripts/tokens.py measure --last 1` and
record the new B (S0's yield) in `tasks.json` and the handoff.

**Working.** One commit per change; a fix or behaviour change starts
with a test that fails on unmodified `HEAD` for the stated reason.
Read by range, never a large file whole; search with `grep -n`. Check
your context at each commit (`/context`). Real data is read-only;
under Rosetta, BRIEF §0.5. **Delegate what would flood the context:**
a full suite to `suite-runner`; broad searches to Explore; upstream
research to `upstream-reader`, one per dependency, in parallel; a
review to `diff-reviewer`. CI: the run id from `gh run list --commit
<full SHA>`, then `gh run watch <id> --exit-status > <file> 2>&1` in
the background, so its output never reaches the context; a failure
goes to `ci-watcher`.

**Stopping.** At your row's boundary, its split point, or the soft
ceiling, whichever comes first.

**Ending.**

1. Append the history entry: the full tier in
   `docs/history/241-270.md` under `<a name="N"></a>` and
   `### N — <title> (round 13 S<n>)`, from §246; its one line (≤ 160
   characters) in `docs/history/README.md`.
2. Promote any new standing rule to `CLAUDE.md` (after S0, to its
   topic file), linked to the entry.
3. In `tasks.json`: set your row's `status`, `commits` and `history`,
   and `actual_peak_k` from
   `python3 ~/.claude/skills/session-plan/scripts/tokens.py measure --last 1`
   (a worker's row: its report's USAGE line). Tick your box above.
4. Overwrite `docs/HANDOFF.md` (nine fields, ≤ ~2 K tokens).
5. Commit, and quote the check's numbers (native; from S3b on, also
   the x86_64 suite's summary line for a row that changed code or
   dependencies). Push, and record the CI run id and result.

## Waiting on Kris

**Approval gates:**

- [x] **S0:** scope chosen on 2026-11-02 (the `CLAUDE.md` split and
      the two plugins off).
- [ ] **S1b, S1c:** each merge, from the row's one-line verdicts.
- [ ] **S10:** the exact `git tag`, `git push` and `gh release
      create` commands and the release notes, shown before they run.

**Live checks:**

- [ ] **S0:** `/context` at the start of the session.
- [ ] **Each wave:** Kris starts the lead session; workers' questions
      reach him through it.
- [ ] **S9:** the Intel image in the test account on the M4 Pro
      (BRIEF §9's list). No slskd bring-up there.
- [ ] **S9, if an Intel Mac turns up:** the same list, plus a slskd
      bring-up with a test Soulseek account.
- [ ] **After S10:** the website's Download button points at
      `releases/latest/download/Seeker.dmg` (read 2026-10-30), which
      stays the Apple silicon image. Add an Intel download, and
      update its "Latest" line, which still said v0.1.0 then.
- [ ] **Optional:** if v0.2.0 is far off, S1d's Premium note could go
      out first as a 0.1.2 patch (Kris's call; not planned).

## Exit criteria

Measured in S10's close-out; each is a number or a yes/no.

- `uv sync --locked` installs on x86_64 macOS from the universal lock;
  S2 changed no native package version (its before-and-after export);
  `tests/test_lock_platforms.py` passes.
- Each of the eight Dependabot PRs is merged or closed with a reason
  (S1b, S1c), and v0.1.1 has its HISTORY entry.
- The suite passes on x86_64 under Rosetta and on `macos-15-intel`
  (CI, blocking), with any skip naming what it excludes.
- Both apps pass the post-build check and the smoke test, locally and
  in `build.yml`; the Intel runner's cold and warm analysis times are
  recorded.
- v0.2.0 is published with `Seeker.dmg`, `Seeker-Intel.dmg` and their
  `.sha256` files; both apps' update checks say up to date.
- Help → Build names the architecture, and says Rosetta when
  translated. The README and the wizard say Spotify Premium is
  required.
- CI is green on the release commit; coverage at or above the floor;
  `mypy --strict` clean; `ruff check` 0.
- B after S0 is recorded, and every row's `actual_peak_k` is filled.
- Wave 1's UNVERIFIED items are recorded.

## Estimate notes

- **B** (`tokens.py measure --last 20`, 2026-11-02): median 57 K,
  59–63 K since 2026-10-17. Most of it is Claude Code's own prompt
  and tools, which the project can't cut; S0 can cut `CLAUDE.md`
  (37 KB, ~10.6 K) to a ~15 KB core (−6 K) and two plugins' skill
  listings (−1 to −3 K, UNVERIFIED: the listing may be budget-capped
  and refill). Est. peaks assume B ≈ 54 K after S0; S1 measures it.
- **Row cap 65 K, not the skill's 85 K:** 85 K assumes B ≤ 35 K. At
  B ≈ 54 K, 65 K of work peaks near 120 K. S5 (~80 K, est. peak
  ~134 K) is the one exception, with an early split point.
- **Units:** the reading list ×1.3 · the common list (~5 K ×1.3) · the
  check ~2 K · writing at 2× the new text · each run 0.5–2 K, plus
  2–5 K per traceback · close-out 8–10 K · ~5–6 K of turn overhead.
  Then × the type's factor: Behaviour 1.2, Feature 1.4, Investigation
  2.0, Refactor, Docs and Release 1.0.
- **Calibration:** round 12's 14 sessions used a median 86 K of work
  (max 212 K), with rows that bundled several items; the skill's
  calibration point is ~120 K per cohesive row. These rows are smaller
  by design. If S0–S2 run more than 25 % over their estimates,
  re-estimate the rest with `tokens.py measure` and record the change
  here.
- **Investigation rows re-plan:** S3's close-out re-estimates S3b
  from the failure list, and adds an S3c in `tasks.json` if there are
  more than ~3 distinct causes.
- **Waiting is not tokens:** the x86_64 suite under Rosetta (S3, S3b)
  and CI runs of 30–45 minutes (S4, S7) cost wall-clock time. Poll
  them sparingly.
- **Workers and leads:** a worker's baseline should sit well below a
  top-level session's (a short tool list, no skill listing): est.
  15–25 K, UNVERIFIED; wave 1 records the real value. Row estimates
  stay; a worker's est. peak is ~30 K + work instead of ~54 K + work.
  Observed 2026-11-02: a general-purpose subagent started at 54 K,
  with `CLAUDE.md` and the skill listing in its context; row-worker's
  shorter tool list should start lower (UNVERIFIED by how much).
  A lead spends ~10–12 K per integrated row, so 4–5 rows per lead
  session; wave 1's lead also does S1b and S1c itself, so that wave
  may need two leads.
- **Speed:** 10 of 18 rows are on the critical path; with up to 3
  workers at once, wall-clock should fall by roughly 40 % (an
  estimate, not a measurement).
