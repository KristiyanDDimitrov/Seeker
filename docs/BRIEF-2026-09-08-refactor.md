# Brief for Claude Code — round 8: the codebase-wide refactor,
# security, and documentation pass

You are starting cold. Everything you need is in this file or named by
path inside it. Read it end to end before touching anything.

This is **not** a defect round. Rounds 1–7 fixed reported bugs. This
round is the pass Kris asked for before the project is considered
finished: make the codebase something a stranger can read, keep it
behaviourally identical, close the real security gaps, and leave the
project's own documentation genuinely useful to whoever opens it next.

Two audiences, and both are real:

1. **Users.** Seeker has to keep working exactly as it does today. Every
   phase below is behaviour-preserving unless it explicitly says
   otherwise, and every phase closes with the full test suite.
2. **Hiring managers and engineers reading this on Kris's CV.** They
   will open `src/seeker/ui/main_window.py`, see a 6,575-line file, and
   form an opinion in about eight seconds. That opinion is currently
   wrong about the quality of what's underneath it — the service layer,
   the repository split, the threading model and the test suite are all
   genuinely good. The refactor's job is to stop the entry point from
   lying about the rest.

---

## 0. Ground truth — what I measured, and how

Every number in this brief came from running something against the real
tree, not from reading. Where I could not run something, I say so and
hand you the command instead of a conclusion.

**Repository:** `~/PycharmProjects/Seeker` (macOS, Python 3.13, `uv`).

**Baseline commit at the time of writing:** `6b0c19c` ("Add round-6
brief"), with round 7 (E1–E4) **uncommitted in the working tree**:

```
 M CLAUDE.md
 M docs/HISTORY.md
 M src/seeker/ui/main_window.py     (+623 −529 vs 6b0c19c)
 M src/seeker/ui/theme.py
 M tests/test_theme.py
 M tests/test_ui_smoke.py
?? docs/BRIEF-2026-09-07.md
```

Round 7's E2 (`_configure_*_columns` split), E3 (`#cardInner`,
`PROGRESS_BAR_HEIGHT`/`PROGRESS_BAR_RADIUS`) and E4 (`QLabel#wordmark`)
are already in the tree. E1 (fullscreen close) may or may not be
finished — I did not verify it, and it is not this round's business.

> **Precondition, non-negotiable: this round starts from a clean tree.**
> Round 7 must be committed (or stashed) and `git status --short` must be
> empty before Phase 0.1. A refactor diff mixed with an unfinished defect
> fix is unreviewable, and if something breaks you will not know which
> half did it. If the tree is dirty when you start, stop and say so.

### Size and shape, measured

| | |
|---|---|
| `src/` Python | **26,994 lines**, 85 files, 19,094 code lines |
| `tests/` Python | **30,921 lines**, 49 test modules, **1,082 test functions** |
| Largest source file | `ui/main_window.py` — **6,575 lines** |
| Largest class | `MainWindow` — **5,277 lines, 179 methods** |
| Functions over 60 lines | **76** of 780 |
| Functions over 100 lines | **25** |
| Standalone `#` comment lines in `src/` | **4,204** = **22.0%** of code lines |
| …in `ui/main_window.py` | **1,481** = **34.6%** |
| …in `soulseek/download_service.py` | **516** = **42.5%** |
| …in `docker_setup.py` | 139 = **73.2%** |
| …in `audio_formats.py` | 37 comment lines to **18** code lines |
| `CLAUDE.md` | **133,098 chars**, 2,039 lines, 113 roadmap items |
| Last recorded suite result | 1,098 passed, 1 skipped, `mypy --strict` clean |

### Ten longest functions (`file:line`, length)

```
467  build_stylesheet                   ui/theme.py:604
350  build_parser                       cli.py:94
316  _tag_one_track                     library/metadata_service.py:370
261  handle_library                     cli.py:647
216  poll_downloads                     soulseek/download_service.py:826
203  MainWindow.__init__                ui/main_window.py:1300
188  _render_duplicate_groups           ui/main_window.py:4145
188  download_playlist                  soulseek/download_service.py:282
188  _fix_one_track_art                 library/metadata_service.py:743
183  add_location_to_share              sharing_service.py:341
```

### What is already good — do not "improve" these

Say this out loud before you start deleting things, because a refactor
that damages what already works is worse than no refactor:

- **The layering rule holds.** `grep -rE "^(from|import).*(database|sqlite3|repositor)" src/seeker/ui/` returns **nothing**. No Qt widget imports a repository. That is the project's central architectural claim and it is true.
- **Every SQL statement is parameterised.** No f-string interpolation of values anywhere in `database/`. The single ruff `S608` hit is a false positive — see §4.6.
- **The OAuth implementation is correct and current.** Authorization Code + PKCE (S256), a 96-byte `secrets.token_urlsafe` verifier, a 32-byte `state` that is actually compared (`spotify/auth_manager.py:106`), an exact-match loopback redirect on `127.0.0.1`, no client secret anywhere, and refresh-token rotation handled. That satisfies RFC 9700's requirements for a public native client. Do not "modernise" it.
- **Every outbound HTTP call has an explicit timeout.** All of them. That is rarer than it should be.
- **The threading model is genuinely hard-won.** `ui/workers.py`'s shared dispatcher, `setAutoDelete(False)`, `task_id`-only signals and the deferred native delete each exist because a shortcut segfaulted. **Do not restructure `workers.py` in this round.** Its comments get compressed (Phase 6); its code does not move.
- **The test suite is a real safety net.** 1,082 tests, 292 of them driving real Qt widgets, and a `conftest.py` that applies the real theme so UI tests render what ships.
- **`_decide_next_step` (`ui/main_window.py:606`) is a model of how to do this** — a pure function over a `_NextStepFacts` dataclass, no Qt, no I/O, trivially testable. Where Phase 7 asks you to extract logic out of widgets, this is the shape to aim for.

---

## 1. The thesis

There is one root cause behind most of what follows, and naming it makes
every individual item obvious instead of arbitrary.

**The project keeps its history in three places, and only two of them
were supposed to have it.**

`CLAUDE.md`'s own closing paragraph states the rule:

> `CLAUDE.md` (this file) holds standing facts […] kept short enough to
> read in full before starting work. `docs/HISTORY.md` holds the full
> investigation narrative […] A roadmap entry over ~8 lines belongs in
> HISTORY.md only, with a link — compress it here before moving on to
> the next item […] treat the 8-line budget as a hard ceiling, not a
> suggestion.

Measured against that rule, as it stands today:

- **89 of 113 roadmap items (79%) exceed the 8-line ceiling.** Median
  item: 13 lines. Item 114 alone: **118 lines**.
- The Roadmap section is **116,290 of 133,098 characters — 88.4% of the
  file**. The four sections a cold agent actually needs (Architecture,
  Current layout, Conventions, Commands) total **10,997 chars — 8.3%**.
- 88 roadmap entries contain the string "— done". It is not a roadmap;
  it is a changelog with two open bugs (items 63 and 70) buried in it.

And the same drift happened a level down, into the source. This is
`MainWindow.__init__` (`ui/main_window.py:1300`), abridged — 203 lines,
of which roughly 60 are code:

```python
        # Roadmap item 65 (Phase 2.2/2.3) — keyed the same as
        # busy_actions; populated by a run_worker(on_progress=...)
        # callback (via _on_activity_progress), consulted by
        # _render_activity_strip. Empty for every action wired in Phase
        # 2 itself — Phase 7's fingerprinting/duplicate-search progress
        # is the first real producer.
        self._activity_progress: dict[str, tuple[str, int, int]] = {}
```

Seven lines of provenance for one empty dict. A reader who does not know
what "Phase 2.2/2.3" refers to — which is every reader who is not you or
Kris — gets nothing from six of those seven lines except the impression
that this code is hard.

**So the rule for this whole round is one sentence:**

> A comment earns its place by telling the *next* person something the
> code cannot. A comment that tells them what *happened* belongs in
> `HISTORY.md`, which already exists for exactly that and is 785 KB
> long.

This is not "delete the comments". Several of them are the most valuable
thing in the file — `workers.py`'s explanation of why `setAutoDelete
(False)` is required is worth more than the code it sits above, because
without it someone deletes that line and reintroduces a segfault. The
test is **shelf life**, not length: *"is this still true and still
load-bearing next year, or is it a record of a decision?"*

Everything below is downstream of that thesis, plus the structural work
that 6,575 lines in one file makes necessary anyway.

---

## 2. Ordering, and why it is this order

Nine phases. **One commit per numbered item**, never per phase. The
order is chosen so that the cheapest-to-verify changes land first and the
riskiest land last, and so each phase shrinks the surface of the next.

| Phase | What | Risk |
|---|---|---|
| 0 | Baseline: capture what "no regression" means | none |
| 1 | Toolchain: ruff config, pytest config, CI | none (config only) |
| 2 | Machine-verified cleanups (ruff's own findings) | very low |
| 3 | **Security** | low, isolated |
| **3B** | **§14 — the Dock icon after close (user-reported)** | **low, isolated** |
| 4 | Layering repair: private access, `print` → logging | low |
| 5 | Deduplication: the 14 column methods and friends | low |
| 6 | **`MainWindow` decomposition** | **high** |
| 7 | Comment triage, against the now-small files | medium |
| 8 | `CLAUDE.md` and `README.md` | none |
| 9 | UX proposals — **Kris decides, you do not** | product |

Phase 5 before Phase 6 deliberately: deduplicating first means ~120
fewer lines to move in the big split. Phase 7 after Phase 6 deliberately:
triaging comments in eight 600-line files is a job; triaging them in one
6,575-line file is a slog that you will do badly by line 4,000.

---

## 3. Phase 0 — Baseline

Nothing in this round is verifiable without this. Do it first, commit the
artefacts, and quote them in every later report.

- [ ] **0.1 — Clean tree.** `git status --short` empty. Record the
  commit SHA you are starting from. If round 7 is still uncommitted,
  stop and report.

- [ ] **0.2 — The three numbers.** Run and record verbatim:
  - `uv run pytest` → the exact summary line (e.g. `1098 passed, 1 skipped in 214.03s`) **and** the name of every failure or skip.
  - `uv run mypy --strict src/` → the exact summary line.
  - `uv run ruff check src tests` → the exact count. **Measured on the real tree: 223 errors under ruff 0.16.5, 150 of them auto-fixable.** (An earlier draft of this brief said 6, measured on ruff 0.15.11 — that figure is obsolete; see the correction at the head of Phase 1.)

  These three numbers are the definition of "no regression" for the rest
  of the round. Per CLAUDE.md's own convention, the pre-existing failure
  count is a tracked number, not a label: if it moves, that is a
  regression to diagnose, never a new baseline to adopt.

- [ ] **0.3 — Visual baseline.** With the app running on the real Mac,
  screenshot **every page in both themes**: Dashboard, Search, Downloads,
  Review, Duplicates, Sharing, History, Help, Support, Settings (all
  tabs). Both populated and empty where the distinction exists. Save
  them somewhere out of the repo and keep them. Phase 6 moves thousands
  of lines of widget construction; a pixel diff against these is the only
  honest evidence it did not change anything. **A passing test suite is
  not evidence that the UI still looks right** — round 7's E2 exists
  precisely because a green sweep test skipped the broken case.

  > **AMENDED (2026-09-08), after the first pass captured 26 shots — one
  > state per screen.** "Both populated and empty" is the load-bearing
  > half of this item and it needs a mechanism, because a machine with a
  > real library cannot show you an empty Duplicates page and a machine
  > with an empty database cannot show you a populated Dashboard. **Two
  > passes, two databases.** Pass one against the real data (what you
  > already have). Pass two against a **scratch data directory** — patch
  > `application._resolve_database_path` and
  > `config_store.resolve_config_path` to a temp dir in a throwaway
  > launcher outside the repo, so the app comes up first-run-clean and
  > every page renders its genuine empty state. **Never move, rename or
  > delete the real data directory to achieve this** — that is a real
  > user file and this project's own rule forbids touching one without
  > explicit confirmation. The scratch database is reusable later: seed
  > it with invented playlist names and it becomes the source for the
  > README screenshots in §11.3.1, which must not contain real library
  > data.
  >
  > Also sweep all captured frames for blank or half-painted renders
  > rather than spot-checking a couple — a uniform-colour PNG in a
  > baseline set is silently useless six phases later, and file size or
  > a one-line colour-variance check catches it in seconds.

- [ ] **0.4 — Performance baseline, cheap version.** Time `uv run
  seeker-ui` from launch to first paint, three runs, record the median.
  Phase 6 changes construction order; if launch gets materially slower
  you want to know.

---

## 4. Phase 1 — Make the toolchain catch what review should not have to

> **CORRECTION (2026-09-08, after Phase 0 measured it).** An earlier
> draft of this section said ruff runs a default set of `E4`, `E7`,
> `E9`, `F` and finds 6 things. **That is obsolete.** Ruff **v0.16.0
> expanded the default rule set from 59 rules to 413**, pulling in
> flake8-bugbear (`B`), pyupgrade (`UP`) and Ruff's own `RUF` family
> among others, while *removing* 18 more-opinionated pycodestyle/
> pyflakes rules (E401, E402, E701–E703, E711–E714, E721, E731,
> E741–E743, F403, F405, F406, F722). The 6-error figure came from ruff
> 0.15.11, which predates that change. Phase 0 re-measured on the real
> tree with 0.16.5: **223 errors, 150 auto-fixable**, with no config
> file anywhere (independently corroborated: there is no
> `~/.config/ruff/` on this machine, so no user-level config explains
> it — the default really did move).
>
> **This changes the framing of Phase 1, not its conclusion.** The job
> is no longer "switch the linter on". It is "decide which of 413
> moving defaults this project actually keeps, and stop them from
> moving again". An explicit `[tool.ruff.lint] select` is now *more*
> important, not less: it is the only thing that makes this repo's lint
> verdict reproducible across ruff versions, and Astral's own guidance
> for projects that want version-stable behaviour is to state `select`
> explicitly rather than inherit whatever the current default happens
> to be.

`ruff` is a declared dev dependency (`ruff>=0.16.4`) with **no
configuration anywhere** — no `[tool.ruff]` in `pyproject.toml`, no
`ruff.toml`, no user-level config. `pytest` has no configuration
either. `pytest-cov` is installed and nothing measures coverage. There
is no `.github/` directory and no CI of any kind.

For a project whose README says *"code quality, structure, and test
coverage are treated as first-class goals here"*, an unconfigured linter
and no CI is the gap a reviewer notices first.

### What a real rule set finds

The table below is from ruff **0.15.11** against `src/` only, with a
broad explicit selection — **397 findings.** It is kept because the
*shape* of the distribution is what the config decisions below reason
about. **It is not the current number and must not be quoted as one:**
Phase 0's real measurement is 223 on `src tests` under 0.16.5's
defaults. Re-derive every count from your own run before deciding what
to ignore.

```
62 TRY003  raise-vanilla-args          23 PLR2004 magic-value-comparison
60 S101    assert                      20 I001    unsorted-imports
37 EM102   f-string-in-exception       12 N802    invalid-function-name
27 UP017   datetime-timezone-utc       11 PLR0913 too-many-arguments
25 EM101   raw-string-in-exception     11 PLR0915 too-many-statements
                                       11 S607    start-process-with-partial-path
```

Most of that tail is noise for this project, which is exactly why the
config matters: **an unconfigured linter and an over-configured one are
both ignored.** Enable what changes behaviour or catches bugs; suppress
the rest explicitly, with reasons, in one place.

- [ ] **4.1 — Add `[tool.ruff]` to `pyproject.toml`.** Start from this
  and justify any change you make to it:

  ```toml
  [tool.ruff]
  line-length = 79
  src = ["src", "tests"]

  [tool.ruff.lint]
  select = [
      "F",      # pyflakes — real bugs
      "E", "W", # pycodestyle
      "I",      # import sorting
      "UP",     # pyupgrade — this is a 3.13-only project
      "B",      # bugbear — real bug classes
      "A",      # builtin shadowing
      "C4",     # comprehensions
      "SIM",    # simplifications
      "RET",    # return consistency
      "PTH",    # pathlib over os.path
      "DTZ",    # naive datetimes
      "RUF",    # ruff's own
      "S",      # bandit — security
      "PLC", "PLE", "PLW",  # pylint: convention/error/warning
  ]
  ignore = [
      # Deliberately NOT enabled, each for a reason:
      # PLR    — the "too many X" family. Phase 6 fixes the real
      #          offenders structurally; a threshold that fires on
      #          MainWindow today would just get a blanket noqa.
      # TRY003/EM101/EM102 — 124 findings that would each add a module
      #          -level exception subclass or an intermediate variable.
      #          This codebase's error strings are user-facing and read
      #          well inline; churning them buys nothing.
      "COM812",  # conflicts with the existing trailing-comma style
  ]

  [tool.ruff.lint.per-file-ignores]
  # Qt overrides are camelCase by framework contract, not by choice.
  "src/seeker/ui/*" = ["N802"]
  # Tests assert; that is their job.
  "tests/*" = ["S101"]

  [tool.ruff.lint.pep8-naming]
  # Belt and braces for the same Qt point, for any file outside ui/.
  extend-ignore-names = [
      "closeEvent", "paintEvent", "changeEvent", "showEvent",
      "hideEvent", "resizeEvent", "eventFilter", "sizeHint",
      "minimumSizeHint", "setGeometry", "heightForWidth",
      "hasHeightForWidth", "expandingDirections", "itemAt", "takeAt",
      "addItem", "count", "setVisible",
  ]
  ```

  **In the same commit, pin the tools whose output is a gate.**
  `ruff>=0.16.4` has no upper bound, and ruff has just demonstrated that
  it will change its default rule set inside a minor release. Once
  Phase 1 adds CI, an unbounded ruff means the build's verdict can
  change with no commit to this repo — a red CI run nobody caused.
  Change it to `ruff>=0.16.4,<0.17` and apply the same reasoning to
  `mypy` (`>=2.3.1`, also unbounded, also a CI gate). Leave the runtime
  dependencies alone; this is specifically about tools that render a
  pass/fail judgement. Say in the commit message that this is a direct
  consequence of the 0.16.0 default-set change.

  **Sequencing trap — read before touching any `# noqa`.** Phase 0
  reports **36 `RUF100` (unused noqa)** hits. That number is a function
  of which rules are enabled, and Phase 1 is about to change which rules
  are enabled. A `# noqa: N802` reads as "unused" only while `N802` is
  off; the moment the config turns it on, that same directive becomes
  load-bearing. **Do not clean up a single `RUF100` until the config in
  4.1 has landed**, then re-run and treat whatever survives as the real
  list. Deleting them first would strip suppressions the new config
  needs and produce a wave of failures that look like the config's
  fault.

  > **SHARPENED (2026-09-08), after this bit someone during 4.8.6.**
  > The rule is stronger than "get the ordering right", and it is a
  > standing convention for CLAUDE.md: **never run `ruff --fix` with a
  > narrowed `--select`, and never narrow `--select` to `RUF100` at
  > all.** RUF100 evaluates a `# noqa` against *only the rules enabled
  > in that run* — its own message says so verbatim: `Unused 'noqa'
  > directive (non-enabled: 'N802')`. So `ruff check --fix --select
  > RUF100` marks **every** directive in the codebase unused, because
  > nothing except RUF100 is enabled, and `--fix` then deletes them all.
  > That is what stripped legitimate suppressions from seven files
  > during 4.8.6, including 4.6's own `S608` justification. A stale
  > `.ruff_cache` may have obscured it, but clearing the cache would not
  > have prevented it — only running RUF100 under the project's full
  > configured selection does. Fix the guard to match the real cause.

  Confirm the `extend-ignore-names` list against the real Qt overrides in
  `ui/flow_layout.py`, `ui/notice.py` and `ui/main_window.py` — I derived
  it from the `N802` hits, but check for ones the current selection did
  not surface. When this lands, `ui/main_window.py:456`'s `# noqa: N802`
  becomes genuinely unused (`RUF100` flags it today because `N802` is
  currently off) — resolve that in the same commit, whichever way the
  final config makes correct.

- [ ] **4.2 — Deliberately do NOT adopt `ruff format`.** This codebase
  has a consistent house style that `ruff format` does not produce:
  8-space hanging indent on multi-line `def` signatures, trailing commas
  before closing parens, ~72-column prose wrapping in comments.
  Reformatting 27,000 lines would produce a diff nobody can review,
  destroy `git blame` across the whole project, and fight every future
  hand-wrapped comment. **State this decision in `CLAUDE.md`'s
  Conventions section** so the next round does not re-litigate it. Lint
  yes; format no.

- [ ] **4.3 — line length.** ~~`line-length = 79` is nearly free.~~

  > **CORRECTED (2026-09-08).** That claim was wrong, and the error was
  > mine: I measured `src/` only (99.61% already ≤79) and quoted 106
  > lines to fix. The real figure across `src tests` is **341**, because
  > `tests/` wraps to a different habit than `src/` does. Phase 1 got
  > 175 of them rewrapped safely with a purpose-built script and
  > correctly declined to force the remaining 166.
  >
  > **166 hand-rewraps for zero behavioural gain is bad value** — it is
  > a large, churny diff that damages `git blame` across the test suite
  > right before Phase 6 starts moving those tests around. **Set
  > `line-length = 88`** (ruff's own default) instead: only 8 lines in
  > the whole tree exceed it, so E501 goes to near-zero immediately, and
  > the 175 rewraps already done stay valuable rather than wasted.
  >
  > Record in CLAUDE.md's Conventions that 72–79 remains the house
  > *habit* for hand-wrapped prose and comments, and 88 is the enforced
  > *ceiling*. An enforced limit the codebase can actually sit at beats
  > an aspirational one that leaves 166 permanent violations in the
  > gate.

- [ ] **4.4 — Add `[tool.pytest.ini_options]`.**

  ```toml
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  addopts = "--strict-markers --strict-config"
  filterwarnings = ["error::DeprecationWarning:seeker.*"]
  ```

  `filterwarnings` is the one with teeth: it turns Seeker's own
  deprecation warnings into failures, so a PySide6 or Python upgrade
  surfaces in CI rather than in a user's crash. **Scope it to `seeker.*`
  only** — third-party deprecations (librosa/numpy are noisy) must not
  fail the build. If it turns out the codebase already emits some,
  report the list rather than widening the filter to hide them.

- [ ] **4.5 — Add CI. `.github/workflows/ci.yml`.** This is the single
  highest-value-per-line item in the whole brief for the CV audience.

  ```yaml
  name: CI
  on: [push, pull_request]
  jobs:
    check:
      runs-on: macos-latest   # the only platform Qt UI tests are proven on
      steps:
        - uses: actions/checkout@v4
        - uses: astral-sh/setup-uv@v5
        - run: uv sync --all-extras --dev
        - run: uv run ruff check src tests
        - run: uv run mypy --strict src/
        - run: uv run pytest --cov=seeker --cov-report=term-missing
  ```

  **Headless Qt is the one real unknown here.** The suite uses
  `pytest-qt` and a session `qapp` fixture; on a GitHub runner you will
  likely need `QT_QPA_PLATFORM=offscreen`. Try it, and if some UI tests
  cannot run headless, **do not delete them and do not weaken them** —
  mark them with a real marker (`@pytest.mark.desktop`), deselect that
  marker in CI, and say plainly in the workflow and in the README how
  many tests CI does not cover. An honest "CI runs 1,050 of 1,082 tests;
  32 need a real display" reads far better than a green badge over a
  suite that quietly stopped testing the UI.

- [ ] **4.6 — Resolve the one `S608` properly, do not blanket-ignore it.**
  `database/repositories/local_file_repository.py:315` builds a
  `DELETE … WHERE relative_path NOT IN ({placeholders})` with an
  f-string. **It is safe**: `placeholders` is
  `", ".join("?" for _ in seen_relative_paths)` — literally only `?` and
  `,` characters — and every value goes through the parameter tuple. It
  is also the *only* place in the codebase where a query string is
  assembled at all, which makes it the one place a future edit could go
  wrong silently. Add a scoped `# noqa: S608` **with a one-line
  justification naming why it is safe**, not a file-level or config-level
  suppression.

- [ ] **4.7** Report the new ruff count after 4.1–4.6, broken down by
  rule, and how many the config chose to suppress versus fix.

### 4.8 — Get the gate to zero (added 2026-09-08, after 4.1–4.7 landed)

**Phase 1 is not closeable without this.** The first pass took ruff from
223 findings (unconfigured) to **837** (configured), then down to 662.
That is the wrong direction, and it has a concrete consequence: §4.5
committed a CI workflow whose second step is `uff run ruff check src
tests`. With 662 findings that step exits non-zero. **The headline
deliverable of this phase, on a portfolio project, is currently a
workflow that goes red the moment it is pushed.** A red badge is worse
than no badge.

The fix is almost entirely configuration, not code. A codebase that
passes `mypy --strict` cleanly and carries 1,098 green tests does not
have 662 defects; it has a rule selection that is not yet earning its
keep. §4 already states the principle — *"an unconfigured linter and an
over-configured one are both ignored"* — and the first pass landed on
the second failure mode.

> **The standing rule this establishes, and it belongs in CLAUDE.md: a
> lint configuration the project cannot sit at zero under is not a
> configuration, it is a backlog wearing one.** The number must be zero
> at the end of this phase, so that from here on *any* non-zero result
> is a real, new signal rather than something to squint past.

- [ ] **4.8.1 — `line-length = 88`.** See 4.3's correction above. Takes
  E501 from 166 to roughly nothing. Keep the 175 rewraps already done.

- [ ] **4.8.2 — `PLC0415` (127) — ignore it, but check first.**
  Deferred imports look deliberate in this codebase: circular-import
  avoidance (`TokenStore` inside `SpotifyAuthManager._load_token`,
  `webbrowser` inside `_authorize`) and keeping heavy scientific
  dependencies off the startup path — launch is 0.878 s and librosa/
  scipy/numpy are the obvious reason it is not worse. **Sample 15–20 of
  the 127 before writing the justification.** If they are mostly
  deliberate, ignore the rule with a comment saying why. If a
  meaningful share are accidental, say so and fix those instead — do
  not write a justification you have not checked, per this project's
  own standing convention on unverified claims.

- [ ] **4.8.3 — `UP017` (70) — just fix it.** Auto-fixable, and it is
  §5.4 of Phase 2 anyway. Pull it forward; there is no reason for 70
  mechanical findings to sit in the gate.

- [ ] **4.8.4 — `S105`/`S106` (25 + 34) — false positives, suppress
  narrowly.** Every one I checked flags a *name*, not a value:
  `TOKEN_URL = "https://accounts.spotify.com/api/token"`,
  `SLSKD_NETWORK_PASSWORD_ENV_VAR = "SLSKD_SLSK_PASSWORD"`,
  `TOOLTIP_NEW_SOULSEEK_PASSWORD_FIELD = "Your SoulSeek network
  password…"`. **Use `per-file-ignores` for the specific files that
  hold them, not a global `ignore`** — a genuine hardcoded credential
  appearing somewhere else later must still be caught. Confirm all 59
  are name-only before suppressing; if even one is a real value, that is
  a security finding, not a lint finding.

- [ ] **4.8.5 — `S101` (60) — decide, do not blanket-ignore.** These are
  in `src/`, not tests (my §4.1 `per-file-ignores` covered `tests/*`,
  which is why they survive). Most look like mypy-narrowing guards such
  as `assert self._tray_icon is not None`. That is a legitimate Python
  idiom, **but `python -O` strips asserts**, so any assert doing real
  runtime validation in shipped code is a latent bug. Report the split —
  how many are type-narrowing versus how many guard a real runtime
  condition — then ignore `S101` with a CLAUDE.md convention line
  ("asserts narrow types; they never validate user input or external
  responses") and convert any that fail that test into real checks.

- [ ] **4.8.6 — Triage whatever remains (~180) to zero.** Fix what is
  worth fixing, suppress the rest in `pyproject.toml` with a reason per
  entry. Report the final breakdown: fixed versus suppressed, and the
  one-line justification for each suppression.

- [ ] **4.8.7 — Push, and confirm CI is actually green.** A workflow
  file that has never run is not evidence that it works. Local
  verification under `QT_QPA_PLATFORM=offscreen` proved the *test* step;
  it proved nothing about `uv sync` on a clean `macos-latest` runner,
  the ruff step, or the mypy step. **Push and paste the real run URL and
  its result.** If it fails, that failure is Phase 1's, not Phase 2's.

- [ ] **4.8.8 — Record the flake by name.** `test_close_event_falls_
  back_to_real_close_when_no_tray` fired once and did not reproduce in
  four further runs. Not chasing it now is the right call — but this
  project's own convention is that the failure count is a tracked
  number, not a label, and a flake is that number moving. Two reasons it
  cannot just be a sentence in a report: CI now runs this suite on every
  push, and a flaky test in CI teaches everyone to ignore red; and
  **§14 is about to modify `closeEvent`, which is exactly what this test
  covers.** Add it to CLAUDE.md's open issues with the date and the
  observed frequency, so that if it fires during §14 it is a known prior
  rather than a fresh mystery. If it recurs, diagnose it — never reach
  for `pytest-rerunfailures`.

- [ ] **4.8.9 — Reconcile the count.** The report gives 837 → 662 as
  "−175 from 4.3, −1 from 4.6, −1 dead noqa from 4.1", which arrives at
  660, not 662. Probably rewrapping resolved some findings and created
  others — which is precisely why it should be reconciled rather than
  rounded. One line: what the two unaccounted findings are.

---

## 5. Phase 2 — The findings a machine already proved

Small, individually-committed, each verified by the tool that found it.
Take these before the structural work so the big diffs are not carrying
unrelated noise.

- [ ] **5.1 — The 6 unused imports.** `QEvent`, `QSize`, `QFont` and
  three others in `ui/main_window.py`. `ruff check --fix`. One commit.

- [ ] **5.2 — `application.py:244` — a bare `self.spotify` statement.**
  ruff `B018` flags it as a useless expression. It is not useless — it
  is worse than useless: it is a **property access used for its side
  effect**, and the side effect is *opening the user's web browser and
  blocking on an OAuth callback*. The comment above it even says so:

  ```python
          # Triggers the existing OAuth flow via
          # auth_manager.get_valid_token() — opens the system browser and
          # waits for the local callback.
          self.spotify
  ```

  A reader — or a linter, or an over-eager future cleanup — deletes that
  line as dead code and silently breaks first-time Spotify connect.
  Replace it with an explicit call that says what it does. The minimum
  is `self.auth_manager.get_valid_token()`; the better fix is a named
  method (`_ensure_spotify_authorized()`) that `connect_spotify` calls.
  Whichever you choose, `Application.spotify` must remain a property
  that *builds* the client — it is the lazy-construction seam the whole
  class is built on — but nothing should ever again rely on touching it
  for effect.

  > **DONE in Phase 1 (§4.8.6), and my diagnosis above was wrong in a
  > way worth recording.** I wrote that the side effect of `self.spotify`
  > *is* opening the browser. It is not. `SpotifyClient.__init__` only
  > stores `token_source` and `force_refresh` as attributes and never
  > calls them, so constructing the client triggers no authorization at
  > all. **The line was a genuine no-op and the comment above it was
  > false** — `connect_spotify()` never opened the browser, and the
  > wizard advanced past its Spotify step without the user having
  > authorized anything; OAuth fired later, from whichever background
  > worker first made a real API call.
  >
  > I repeated the comment's claim instead of checking the constructor —
  > exactly the failure CLAUDE.md's own convention about unverified
  > behavioural comments exists to prevent, committed by the person
  > citing that convention. Recorded here rather than quietly fixed.

- [ ] **5.3 — The small true positives.** One commit, or one per file:
  - `ui/formatting.py:73` — `max(int(round(seconds)), 0)`; `round()` on
    a float already returns `int` (`RUF046`).
  - `spotify/sync_service.py:96` — iterating `local_playlists` then
    indexing it on line 100; use `.items()` (`PLC0206`).
  - `ui/main_window.py:1251` — `for index, (plan, keep_path,
    delete_paths) in enumerate(...)` where `plan` is unused (`B007`).
    Rename to `_plan` or drop it from the tuple.
  - The `B904` hit — `raise ... from` inside an `except`. Chaining the
    cause is strictly better for a bug report.
  - The `B905` hit — `zip()` without `strict=`. On 3.13 this is free and
    turns a silent truncation into an error.

- [ ] **5.4 — `UP017`: 27 × `datetime.timezone.utc` → `datetime.UTC`.**
  Auto-fixable, and it is the idiomatic spelling on a project pinned to
  `>=3.13`. Cosmetic, but it is 27 lines of "this was written against an
  older Python" that a reviewer will notice.

- [ ] **5.5 — `DTZ005` is a FALSE POSITIVE. Do not "fix" it.**
  `spotify/client.py:73` calls `datetime.now()` without a timezone —
  correctly. Its only consumer is `_format_clock_time()`, which renders
  *"try again around 3:45 PM"* for a human reading their own wall clock.
  Converting it to UTC would make the message wrong for every user
  outside UTC. Suppress it with a `# noqa: DTZ005` and a one-line
  comment saying it is deliberately local because it is displayed. The
  other 27 datetime call sites are all correctly timezone-aware; this is
  the one that should not be.

- [ ] **5.6 — `PLW1510`: 5 × `subprocess.run` without `check=`.**
  `docker_setup.py:157`, `:375`, and the three in
  `ui/main_window.py:369-373` (`_open_in_file_manager`). For the file
  manager calls, "best effort, ignore failure" is the right behaviour —
  but make it explicit with `check=False` and a comment, so the reader
  knows it was decided rather than forgotten. For the `docker_setup`
  ones, check what the callers actually do with the result before
  choosing.

- [ ] **5.7** Report: ruff count before and after Phase 2, the exact test
  summary line, `mypy --strict` clean.

---

## 6. Phase 3 — Security

Kris's framing was: *"there is little that can go wrong with this app as
no sensitive user credentials are actually stored (correct me if I'm
wrong)."*

**He is wrong on both halves, and one of the findings is serious.** The
app does store credentials, and the largest exposure is not in the Python
at all — it is in `docker-compose.yml`.

Nothing here is theoretical and nothing here is a CVE-of-the-week. These
are five concrete things, in severity order.

### 6.1 — HIGH: the slskd web UI is published to the whole network with vendor-default credentials and remote configuration switched on

Three facts, each independently verified:

1. **`docker-compose.yml` publishes the web UI on every host interface.**

   ```yaml
       ports:
         - "5030:5030"     # slskd web UI (HTTP)
         - "5031:5031"     # slskd web UI (HTTPS)
         - "50300:50300"   # Soulseek network listener
   ```

   A Docker port mapping with no host address binds `0.0.0.0`. On any
   shared network — a café, a co-working space, a flat-share, a venue —
   `http://<Kris's-LAN-IP>:5030` is reachable by anyone on it.

2. **Seeker never sets the slskd web UI login.** `grep -rn
   "SLSKD_USERNAME\|SLSKD_PASSWORD" src/` returns only two *comment*
   lines in `docker_setup.py:182,189`. `bring_up_slskd()`
   (`docker_setup.py:364-372`) passes exactly four variables:
   `SLSKD_SLSK_USERNAME`, `SLSKD_SLSK_PASSWORD`, `SLSKD_API_KEY`,
   `SLSKD_DATA_DIR`. The web UI login is left at slskd's own default —
   and slskd's documentation states it plainly: *"Authentication for the
   web UI (and underlying API) is enabled by default, and the default
   username and password are both `slskd`."*

3. **Seeker explicitly enables remote configuration**, which slskd
   defaults to *off*: `docker-compose.yml` sets
   `SLSKD_REMOTE_CONFIGURATION=true`. slskd's config docs show
   `remote_configuration: false` as the default.

Together: anyone on the same network logs in with `slskd`/`slskd` and
gets a daemon they can reconfigure at will, plus visibility of the
SoulSeek account credentials and the API key it holds. The music share is
mounted `:ro`, so files cannot be written — that is the one thing
limiting the blast radius, and it is worth keeping.

- [ ] **6.1.1 — Bind the web UI to loopback only.** Seeker's own client
  only ever talks to slskd over localhost — `SLSKD_LOCAL_BASE_URL =
  "http://localhost:5030"` (`ui/wizard.py:50`) is what the wizard
  configures. Nothing needs 5030/5031 to be reachable from off-box:

  ```yaml
      ports:
        - "127.0.0.1:5030:5030"
        - "127.0.0.1:5031:5031"
        - "50300:50300"   # MUST stay open — incoming Soulseek peer
                          # connections; the P2P protocol needs it.
  ```

  **Verify, do not assume:** after the change, confirm from another
  device on the same network that `http://<mac-lan-ip>:5030` no longer
  answers, and that Seeker's search *and an actual incoming upload* both
  still work. Port 50300 must stay published or sharing breaks — say in
  the commit message that you checked this.

- [ ] **6.1.2 — Generate a real web UI password during onboarding.**
  `docker_setup.generate_api_key()` already does the right thing
  (`secrets.token_urlsafe(32)`, and the comment shows the 16–255 range
  was read from slskd's own config). Add the mirror of it: generate a
  web UI password the same way, pass `SLSKD_USERNAME`/`SLSKD_PASSWORD`
  through `bring_up_slskd`'s env dict alongside the four already there,
  add them as `${...}` entries in `docker-compose.yml`, and persist them
  in `SeekerConfig` next to `slskd_username`/`slskd_password`.

  **Two things to check before you write it:** (a) the existing comment
  at `docker_setup.py:178-190` records that these two variable pairs
  were confirmed empirically against a live container because they are
  easy to confuse — respect that, and re-confirm rather than trusting
  the comment; (b) Kris has an **existing** slskd container with
  persisted state in `slskd-data/slskd.yml`. Changing the web UI
  password on an existing install must not lock him out of a daemon he
  may be logged into. Handle the upgrade path deliberately and say what
  you chose.

- [ ] **6.1.3 — Reconsider `SLSKD_REMOTE_CONFIGURATION=true`.** Find
  what actually needs it. `SharingService.add_location_to_share`
  recreates the container with a new `SLSKD_SHARE_PATH` via
  `bring_up_slskd`, which is a *compose-level* change, not a
  remote-configuration one. If nothing in Seeker calls slskd's
  configuration API, turn it off — it is the vendor default for a
  reason. If something does need it, keep it, and put a comment in the
  compose file naming the exact call site that requires it. Report which
  you found; **do not guess.**

- [ ] **6.1.4 — Surface this in the UI, once.** The Sharing page or the
  Settings → Connection tab should state in plain words what is being
  shared and with whom, and that slskd's admin interface is local-only.
  A user running a file-sharing daemon deserves to be told what it is
  exposing. One sentence, not a wall.

### 6.2 — MEDIUM: the Spotify token file is written world-readable while the config file next to it is locked down

This is the clean, self-evident one, and the inconsistency is the proof
that it is an oversight rather than a decision.

`config_store.save_config()` (`config_store.py:117-127`) does the right
thing:

```python
    path.write_text(json.dumps(asdict(seeker_config), indent=2) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
```

`TokenStore.save()` (`spotify/token_store.py:11-20`) does not:

```python
    def save(self, token: SpotifyToken) -> None:
        self.path.write_text(json.dumps({...}))
```

Both files live in the same `platformdirs.user_data_dir("Seeker")`
directory. One is `0600`. The other lands at whatever the process umask
gives — `0644` on a default macOS account — and it contains a **refresh
token**, which is the long-lived credential: it survives restarts and can
be exchanged for access tokens until it is revoked.

- [ ] **6.2.1 — Give `TokenStore.save()` the same `0600` treatment**,
  and factor the write into one shared helper used by both so the two
  cannot drift again. `chmod` is a no-op on Windows; keep the
  `try/except OSError: pass` shape that `save_config` already
  established, and keep its comment explaining why the failure is
  tolerated.

- [ ] **6.2.2 — Make both writes atomic while you are in there.** Both
  do `write_text` straight onto the live path: a crash, a full disk or a
  power cut mid-write leaves a truncated JSON file, and for the token
  that means a silent forced re-authorization. Write to a temp file in
  the same directory, `chmod` it, then `os.replace()`. Same helper, one
  place. `load_config` already tolerates a corrupt file by returning
  defaults; `TokenStore.load()` does **not** — it will raise
  `JSONDecodeError` straight up through `get_valid_token()`. Give it the
  same tolerance: a corrupt token file should mean "no token", i.e. a
  fresh authorization, not a traceback.

- [ ] **6.2.3 — Decide on the Keychain, and write the decision down.**
  The macOS-idiomatic answer is the system Keychain, and a reviewer may
  ask why it was not used. My call: **not in this round.** It adds a
  dependency, a second platform-specific code path, and a migration for
  an existing install, to protect a file that — once 6.2.1 lands — is
  already `0600` in the user's own home directory under a per-user
  account. `0600` plus atomic writes is a defensible position for a
  personal desktop app; *silently world-readable* was not. Put that
  reasoning in `CLAUDE.md` as a standing decision so it reads as a
  choice rather than an omission — which is exactly the difference a
  reviewer is looking for.

### 6.3 — MEDIUM: the OAuth callback server can hang a worker thread forever, and carries stale state between attempts

> **PRIORITY RAISED (2026-09-08). 6.3.1 is now a companion requirement
> to a fix that has already landed, not a standalone improvement.**
> Phase 1's §4.8.6 corrected `connect_spotify()` so it really does call
> `auth_manager.get_valid_token()`. Before that fix it returned
> immediately and never blocked. **It now blocks on
> `wait_for_callback()`, which has no timeout** — so the wizard's
> first-run Spotify step, the very first thing a new user touches, can
> now hang a worker thread permanently if they close the browser tab or
> abandon the consent screen, leaving the Connect button disabled with
> no way back except restarting the app.
>
> That is not a net regression — the previous behaviour was broken too,
> just differently — but it is a worse failure mode in a worse place.
> **Do 6.3.1–6.3.3 before any `.dmg` is built or shared**, ahead of the
> rest of Phase 3 if that is the more convenient order.

`spotify/callback_server.py` is 73 lines and has three real problems.

**No timeout.** `wait_for_callback()` calls `server.handle_request()`
with no `HTTPServer.timeout` set. If the user closes the browser tab, or
never finishes the Spotify consent screen, that call blocks **forever**.
It runs on a `QThreadPool` worker (`wizard.py:209`,
`settings_window.py:743` — both correctly wrap it), so the consequence
is a permanently consumed pool thread, a "Connect" button disabled for
the rest of the session, and no way to retry without restarting the app.

**Class-level mutable state, never reset.**

```python
class SpotifyCallbackHandler(BaseHTTPRequestHandler):
    authorization_code = None
    returned_state = None
    error = None
```

These are class attributes, set on the class, and **nothing ever clears
them**. A failed authorization sets `error`; the next attempt in the same
process reads that stale `error` first (`auth_manager.py:101`) and raises
*"Spotify authorization failed"* even when the second attempt succeeded.
That is a real, reachable bug on the path a user hits precisely when they
are already having trouble.

**A single-request server that any request can consume.** `handle_
request()` serves exactly one request. Any request that is not
`/callback` gets a 404 and *still consumes the slot* — the server closes
and `wait_for_callback` returns `(None, None, None)`. A browser
requesting `/favicon.ico` first is enough.

- [ ] **6.3.1 — Add a bounded wait.** Set `server.timeout` and loop
  `handle_request()` until a real `/callback` arrives or a deadline
  passes (a few minutes — enough for a human to log in and click Allow).
  On timeout, return a distinct outcome so `_authorize()` can raise
  something the UI shows as *"Authorization timed out — try again"*
  rather than hanging. Pick the deadline as a named constant and mark it
  untuned, per this project's convention.

- [ ] **6.3.2 — Kill the class-level state.** Pass a per-run result
  object into the handler (`functools.partial`, or a handler factory
  closing over a small dataclass) so each authorization has its own. At
  minimum, reset all three to `None` before every run — but the
  per-instance version is the actual fix, and it is a dozen lines.

- [ ] **6.3.3 — Ignore non-callback requests instead of consuming the
  slot.** Keep serving until the path is `/callback`. Combined with
  6.3.1 this is one loop.

- [ ] **6.3.4 — Note, do not "fix", the fixed port.** RFC 8252 §7.3
  prefers an ephemeral loopback port for native apps, exactly because a
  fixed one can be squatted by another local process. Seeker uses a
  fixed `127.0.0.1:8888` — and **must**, because Spotify's dashboard
  requires an exact registered redirect URI and the wizard tells the
  user to paste that literal string. The residual risk is small and
  worth naming honestly in a comment: a local process squatting :8888
  first could receive the authorization *code*, but PKCE means a code
  without the verifier is useless, so the realistic outcome is a failed
  login, not a stolen account. Write that down in
  `callback_server.py`'s module docstring — it is the kind of comment
  Phase 7 is trying to make room for.

### 6.4 — LOW: `_download_album_art` reads an unbounded response from a URL held in the local database

`library/metadata_service.py:1310`:

```python
        response = httpx.get(url, timeout=15.0)
        response.raise_for_status()
        mime_type = response.headers.get("content-type", "image/jpeg")
```

The URL comes from `tracks.album_art_url`, populated from Spotify's API
at sync time — so it is trusted in practice. But it is read back out of a
local SQLite file, the whole body is loaded into memory with no size
cap, and the `Content-Type` header goes straight into the ID3 `APIC`
frame without validation.

- [ ] **6.4.1 — Cap the read** (a few MB is generous for cover art —
  named constant, marked untuned) and stream rather than buffering
  unboundedly. Reject the image and log rather than raising: art is
  optional, tagging is not.
- [ ] **6.4.2 — Validate before writing the tag.** Accept only
  `image/jpeg` and `image/png`; check the magic bytes rather than
  trusting the header. `httpx` does not follow redirects by default, so
  that part is already fine — say so in the comment so nobody "fixes" it
  by adding `follow_redirects=True`.
- [ ] **6.4.3 — `AlbumArtCache` never evicts** (`album_art_cache.py`).
  It writes a `.bin` and `.json` per unique art URL under the user cache
  directory, forever. It is in the *cache* directory, which is the right
  place and safe to clear — but a size or age cap, or an "Open cache
  folder"/"Clear cache" affordance in Settings, would close it out.
  Low priority; include it if the phase is otherwise cheap.

### 6.5 — INFORMATIONAL: `.env` was committed once, and what that does and does not mean

`git log --all -- .env` shows three commits: `a24d243` added it,
`12de30d` modified it, `9207333` removed it and added the ignore rule.
The content at `12de30d` was a real `SPOTIFY_CLIENT_ID` (`5e1d…`) and
the redirect URI. `a24d243`'s `SPOTIFY_CLIENT_SECRET` was the literal
placeholder `your_…`, never a real secret.

**Assess this correctly rather than alarmingly.** Under PKCE, the client
ID is *public by design* — it is transmitted in the authorization URL on
every login, and there is no client secret in this app at all. A leaked
PKCE client ID is not a credential compromise.

- [ ] **6.5.1 — No history rewrite.** Rewriting git history to scrub a
  value that is public by design costs every existing clone and every
  SHA referenced across 133 KB of `CLAUDE.md` and 785 KB of
  `HISTORY.md`, to gain nothing. **Decision: leave it.**
- [ ] **6.5.2 — Record the assessment** in `CLAUDE.md` in two lines, so
  that when someone runs a secret scanner over the repo and finds it,
  the answer is already written down rather than re-derived in a panic.
- [ ] **6.5.3 — One genuine follow-up:** if `SLSKD_API_KEY` in the
  current working `.env` was ever real and ever pushed anywhere, rotate
  it. `generate_api_key()` already exists. Check `git log --all -p --
  .env` for it; from what I can see it never appears in a tracked
  commit, but confirm.

### 6.6 — Not findings, but check and confirm in the report

- **`X-API-Key` over plain HTTP.** Fine over loopback. If a user points
  `SLSKD_BASE_URL` at a remote host over `http://`, the key crosses the
  network in clear. Add a validation in Settings that warns on a
  non-loopback `http://` base URL. Cheap, and it shows the threat model
  was thought about.
- **`S607` × 11 / `S603` × 7 — subprocess with a partial path.** Every
  call uses the list form; **no `shell=True` anywhere** — I checked.
  Invoking `docker`, `open`, `explorer`, `xdg-open` by bare name relies
  on `PATH`, which `ensure_full_path_environment()` (`application.py`)
  deliberately extends for GUI launches. Suppress these per-file with a
  comment explaining that; do not hardcode absolute paths, which would
  break on Homebrew-vs-Docker-Desktop installs.
- **11 × `except: pass` and 32 × `except Exception:`.** Most are
  defensible (best-effort chmod, cache writes, per-item batch failures
  that must not abort the batch). Phase 4's logging work is where they
  get revisited — a swallowed exception with a `logger.debug` is fine; a
  swallowed exception with nothing is a bug you will never hear about.
  Do not mass-edit them here.

---

## 7. Phase 4 — Layering repair

Two violations of the project's own stated architecture. Both are small
diffs and both are the kind of thing a reviewer greps for.

### 7.1 — The UI reaches into `Application`'s private attributes, twelve times, and writes to one

CLAUDE.md's Architecture section:

> Rule: presentation-layer code (CLI *or* UI) must never import or call a
> repository directly. Every CLI handler and every Qt widget goes through
> `Application` (or a service it exposes) […] If a screen or command
> needs data, add/extend a method on the service layer rather than
> reaching past it.

The letter of the rule holds — no repository imports in `ui/`. The spirit
does not:

```
ui/settings_window.py:502   config = self.application._config_store
ui/settings_window.py:703   config = self.application._config_store
ui/settings_window.py:716   config = self.application._config_store
ui/settings_window.py:756   base_url = self.application._slskd_base_url
ui/settings_window.py:757   api_key  = self.application._slskd_api_key
ui/settings_window.py:1035  config = self.application._config_store
ui/settings_window.py:1090  self.application._config_store = updated   # ← a WRITE
ui/main_window.py:5936      self.application._config_store.default_download_location_id
ui/main_window.py:6359      self.application._config_store.tray_hide_notice_shown
ui/main_window.py:6491      self.application._config_store.notify_downloads_finished
ui/main_window.py:6541      self.application._config_store.notify_needs_decision
ui/main_window.py:6560      self.application._config_store.notify_errors
```

Line 1090 is the one that matters: a Qt widget **assigns** to
`Application`'s private state. `Application` has no idea it happened and
cannot invalidate anything that depends on it.

- [ ] **7.1.1 — Give `Application` the public surface these call sites
  actually need.** A read-only `settings` property returning the current
  `SeekerConfig` (or narrow accessors — your call, but pick one and be
  consistent), and **one** mutating method — something like
  `update_settings(**changes) -> SeekerConfig` — that applies the change,
  persists it via `save_config`, updates `self._config_store`, and
  invalidates whatever cached service depends on it. That last part is
  the actual bug being prevented: `connect_spotify` already knows it
  must null `self._spotify` and `self._sync_service` when the client ID
  changes (`application.py`, the B8.1 comment). A direct write from
  `settings_window.py:1090` bypasses that reasoning entirely.
- [ ] **7.1.2 — Replace all twelve call sites**, delete nothing else,
  and add a `mypy`-visible signal that they are gone. One commit.
- [ ] **7.1.3 — Make the rule enforceable, not aspirational.** Add a
  test in the same spirit as round 7's AST sweep over `setStyleSheet`:
  walk `src/seeker/ui/**/*.py`, and fail on any `Attribute` node whose
  value is `self.application` and whose `attr` starts with `_`. That
  test is ten lines and it converts a convention into a guarantee.

### 7.2 — 70 `print()` calls in the service layer, and zero use of `logging`

```
22  soulseek/download_service.py      6  library/duplicate_service.py
13  library/metadata_service.py       3  ui/workers.py
 8  spotify/sync_service.py           3  spotify/auth_manager.py
 7  library/service.py                2  library/scanner.py
                                     +6  singly, across 6 more modules
```

`grep -rn "^import logging\|^from logging" src/` returns **nothing**.

For the CLI this is fine — `print` *is* the CLI's output channel. For a
`.app` bundle launched from Finder, stdout goes nowhere. When Kris (or a
user) hits a problem, there is no log to look at, and every one of those
70 diagnostics — including `auth_manager.py`'s *"Spotify token refresh
failed. Starting a new authorization…"*, which is exactly what you want
to see in a bug report — is discarded.

It is also a layering violation in the same family as 7.1: a service
writing to a presentation channel.

- [ ] **7.2.1 — Introduce `logging`, properly, once.** Module-level
  `logger = logging.getLogger(__name__)` in each service. Configure
  handlers in exactly two places — `main.py` (CLI) and `main_ui.py`
  (GUI) — never in library code. The GUI gets a `RotatingFileHandler`
  writing under `platformdirs.user_log_dir("Seeker")`; the CLI gets a
  `StreamHandler`.
- [ ] **7.2.2 — Convert the 70 call sites, but keep the CLI's voice.**
  Distinguish carefully: `download_service.py`'s progress narration
  ("Downloaded: X") is **user-facing CLI output** and must keep reaching
  stdout when run from the CLI; `auth_manager.py`'s "refresh failed" is
  a **diagnostic** and belongs in the log at `WARNING`. Where a message
  is both, log it *and* let the CLI print it — the clean shape is for
  the service to log and return structured results, and for `cli.py` to
  do the printing from those results. Several services already return
  result dicts, so this is less work than it sounds. **Do not blanket
  sed `print(` → `logger.info(`** — that would silently gut the CLI.
- [ ] **7.2.3 — Surface the log to the user.** The Help page already has
  an "Open Data Folder" button (`_on_open_data_folder_clicked`,
  `ui/main_window.py:2919`). Add "Open Log Folder" beside it, or include
  the log path in the existing data-locations list. A support story a
  user can actually follow.
- [ ] **7.2.4 — Revisit the silent `except: pass` sites now**, not
  before: each one that swallows an exception with no record gets a
  `logger.debug(..., exc_info=True)`. That converts eleven invisible
  failure modes into eleven diagnosable ones, and costs nothing.
- [ ] **7.2.5** Report: the exact remaining `print` count in
  non-presentation modules (target: zero), and a real log file produced
  by a real GUI run, with its path and a few lines quoted.

---

## 8. Phase 5 — Deduplication

### 8.1 — The fourteen column methods

Seven tables, each with a `_configure_*_columns()` / `_size_*_columns()`
pair. Four of them are byte-for-byte identical apart from the table
attribute name and one integer. Compare:

```python
    def _configure_review_needs_columns(self) -> None:
        header = self.review_needs_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        theme.size_action_column(self.review_needs_table, 3, [])
        theme.apply_column_floors(self.review_needs_table)
```

…against `_configure_review_upgrades_columns` (`:5391`) and
`_configure_track_columns` (`:4916`), which differ only in the attribute
name. `_configure_review_local_columns` (`:5567`) differs by one extra
column. All fourteen methods live at:

```
_configure/_size_search_columns              ui/main_window.py:2273 / :2304
_configure/_size_sharing_locations_columns   ui/main_window.py:2699 / :2711
_configure/_size_duplicates_columns          ui/main_window.py:4334 / :4383
_configure/_size_track_columns               ui/main_window.py:4916 / :4930
_configure/_size_review_needs_columns        ui/main_window.py:5284 / :5295
_configure/_size_review_upgrades_columns     ui/main_window.py:5391 / :5402
_configure/_size_review_local_columns        ui/main_window.py:5567 / :5579
```

- [ ] **8.1.1 — One declarative spec, two shared functions.** In
  `ui/theme.py`, next to the existing `size_action_column` (`:468`) and
  `apply_column_floors` (`:433`):

  ```python
  @dataclass(frozen=True)
  class ColumnLayout:
      stretch: tuple[int, ...]
      fit_content: tuple[int, ...]
      actions: int | None = None
      minimum_section: int = 40

  def configure_columns(table: QTableWidget, layout: ColumnLayout) -> None: ...
  def size_columns(table, layout, action_widgets: list[QWidget]) -> None: ...
  ```

  Each table then declares its layout once, as a module-level constant
  beside its column enum:

  ```python
  _SEARCH_COLUMNS = ColumnLayout(
      stretch=(_SearchColumn.FILENAME,),
      fit_content=(
          _SearchColumn.USERNAME, _SearchColumn.FORMAT,
          _SearchColumn.BITRATE, _SearchColumn.SIZE,
          _SearchColumn.LOCKED, _SearchColumn.SCORE,
      ),
      actions=_SearchColumn.ACTIONS,
  )
  ```

  Fourteen methods and ~120 lines become seven constants and two shared
  functions. **The behaviour must be identical** — including round 7's
  E2 contract that `configure_columns` is called at construction *and*
  again at the top of `size_columns`.

- [ ] **8.1.2 — Keep round 7's E2.4 structural test and strengthen it.**
  It asserts every `QTableWidget` has a stretch column immediately after
  construction. Extend it to assert every table's layout came from a
  `ColumnLayout` — i.e. after `configure_columns`, no column is left at
  Qt's `defaultSectionSize`. The bug class E2 fixed must stay
  structurally impossible.

- [ ] **8.1.3 — Sanity-check the two tables that already configure at
  construction** (Downloads `:2375`, History `:2406`, Sharing uploads
  `:2718`, and `settings_window.py:179-185`) and fold them into the same
  mechanism if they fit. If one genuinely does not, say why in a
  comment rather than leaving an unexplained exception.

### 8.2 — Other duplication to look for while you are in there

Not pre-diagnosed — **measure before changing**, and report what you
find. Candidates I noticed but did not quantify:

- [ ] **8.2.1 — The `_render_*` methods.** Twelve-ish of them follow
  "clear the table, loop rows, `setItem` per column, build an actions
  widget, call `_size_*_columns`". Extract a helper only if the shapes
  genuinely match — a bad abstraction over eleven slightly-different
  render loops is worse than eleven honest ones. Report the comparison
  either way.
- [ ] **8.2.2 — The `_hidden_to_tray` early-return guard**, repeated at
  seven poll/render entry points (`:1873`, `:4920`, `:5097`, `:5237`,
  `:5371`, `:5465`, `:5640` in round 7's numbering — re-derive these,
  they will have moved). A single decorator or one gate in the timer
  fan-out would replace seven copies. This interacts with Phase 6 — do
  it *as part of* the decomposition, since the poll fan-out is being
  restructured anyway.
- [ ] **8.2.3 — `build_stylesheet` (`ui/theme.py:604`, 467 lines).** It
  is one f-string. Split it by concern — base/typography, buttons,
  tables, cards, notices, progress — into named constants composed at
  the end. Do **not** change a single selector or value while doing it:
  round 5's C1 (`:last-child`, invalid Qt QSS that silently poisoned an
  entire rule) is what happens when stylesheet edits ride along with
  restructuring. Split-only commit, then a `window.grab()` pixel
  comparison against the Phase 0.3 baselines in both themes.

---

## 9. Phase 6 — Decomposing `MainWindow`

**5,277 lines. 179 methods. One class.** This is the phase that matters
most for both audiences and it is the one that can break the app, so it
gets the most process.

### 9.1 — What it is actually made of

The 179 methods group cleanly. That is the good news: this is a god class
by accretion, not by entanglement.

| Group | ~methods | What |
|---|---|---|
| Shell / navigation | 15 | `_build_ui`, `_show_page`, `_build_sidebar`, activity strip, nav badges, help menu |
| Theme | 5 | mode cycling, system-scheme subscription, `on_theme_changed` |
| Tray & lifecycle | 20 | tray icon/menu, `closeEvent`, hide-to-tray verification, notifications |
| Dashboard | 22 | playlist list, track table, next-step CTA |
| Tagging | 17 | tag/retag/art/rename controls and their results |
| Search | 9 | manual SoulSeek search and download |
| Downloads | 12 | active downloads, ETA, destination dialog |
| Review | 25 | needs-review, upgrades, local matches |
| Duplicates | 21 | fingerprints, groups, deletion, bulk resolve |
| Sharing | 10 | share status, locations, uploads |
| History | 4 | event table |
| Help / Support | 3 | static pages |
| Shared plumbing | 11 | `_run_busy_worker`, poll triggers, sync/scan/match |

### 9.2 — The target shape, and why not mixins

**Do not use mixins.** `class MainWindow(DashboardMixin, ReviewMixin,
…)` looks like a split and is not one: it is still one object with one
namespace, `self.track_table` still has no discoverable owner, mypy
cannot check attribute origins across the mixins, and nothing becomes
independently testable. It moves the problem into more files.

**The target:** `MainWindow` becomes a shell — window chrome, navigation,
timers, tray — and each page becomes its own `QWidget` subclass in its
own module, constructible and testable on its own.

```
src/seeker/ui/
├── main_window.py          # shell: nav, timers, tray, ~500-700 lines
├── pages/
│   ├── __init__.py
│   ├── context.py          # PageContext — the seam
│   ├── dashboard_page.py
│   ├── tagging_panel.py    # currently inside the Dashboard
│   ├── search_page.py
│   ├── downloads_page.py
│   ├── review_page.py
│   ├── duplicates_page.py
│   ├── sharing_page.py
│   ├── history_page.py
│   └── static_pages.py     # Help + Support
├── dialogs.py              # About, Destination, RenamePreview,
│                           #   BulkReplaceUpgrades, BulkResolveDuplicates
├── tray.py                 # tray icon, menu, notifications
├── theme.py                # (+ the 8.2.3 split)
└── …existing modules unchanged
```

**The seam.** Pages need four things from the shell. Give them exactly
those four, in one small object, and nothing else:

```python
@dataclass(frozen=True)
class PageContext:
    application: Application
    thread_pool: QThreadPool
    busy_actions: BusyActionRegistry
    navigate: Callable[[str], None]        # _show_page
    notify: Callable[[str, str], None]     # message, kind
```

Each page exposes a tiny, uniform interface — `refresh()`, `on_tick()`,
and a Qt signal per count the sidebar badges consume. `MainWindow`'s
poll timers then fan out to pages instead of calling nineteen private
methods, which is also what makes 8.2.2's `_hidden_to_tray` guard
collapse to one place.

### 9.3 — The real risk, and the migration that manages it

`tests/test_ui_smoke.py` holds **292 tests** and they reach into
`MainWindow`'s attributes by name — `window.track_table`,
`window.search_results_table`, and so on. Move those attributes onto page
widgets in one commit and you break a large fraction of the suite
simultaneously, at which point you cannot tell a real regression from a
renamed attribute. **That is the failure mode to design against.**

**The migration, per page, one page per commit:**

1. Create `pages/<name>_page.py`. **Move** the page's `_build_*`,
   `_render_*`, `_on_*` and `_poll_*` methods across **verbatim** — no
   renaming, no reformatting, no comment edits, no logic changes. The
   diff should be almost entirely "moved" lines.
2. In `MainWindow`, replace the construction with the new widget, and
   add temporary delegating properties for every attribute the tests
   currently touch:
   ```python
   @property
   def track_table(self) -> QTableWidget:
       return self._dashboard_page.track_table
   ```
3. **Run the full suite. It must be green with zero test edits.** That
   is the whole point of the delegating properties: they prove the move
   was behaviour-neutral before any test changes can mask it.
4. Only then, in a **separate commit**, update that page's tests to
   address the page widget directly, and delete the delegating
   properties for that page.
5. Screenshot the page in both themes and diff against Phase 0.3.

- [ ] **9.3.1 — Order the pages easiest-first**, so the pattern is
  proven on something cheap before it meets something hard. Suggested:
  **History** (4 methods) → **Help/Support** (3, static) → **Search** (9)
  → **Sharing** (10) → **Downloads** (12) → **Tagging panel** (17) →
  **Dashboard** (22) → **Review** (25) → **Duplicates** (21). Extract
  the five dialogs (`AboutDialog:780`, `DestinationDialog:862`,
  `RenamePreviewDialog:1022`, `BulkReplaceUpgradesDialog:1147`,
  `BulkResolveDuplicatesDialog:1206`) into `dialogs.py` first — they are
  already self-contained classes, so it is a pure file move and a good
  warm-up that immediately removes ~500 lines.
- [ ] **9.3.2 — Extract the tray into `ui/tray.py`.** The ~20
  tray/notification methods are the most self-contained group in the
  class and have the least to do with any page. **Except `closeEvent`
  and the hide-to-tray verification** (`_confirm_hidden_to_tray`,
  `_is_exposed_at_platform_level`, `_check_hidden_to_tray`,
  `_hide_request_id`) — that logic is round 7's E1, it is genuinely
  subtle, and it is about the *window*, not the tray. Keep it on
  `MainWindow`, and leave its comments alone in Phase 7.
- [ ] **9.3.3 — `MainWindow.__init__` (203 lines) shrinks to what
  remains.** As pages move out, so do their state fields. What is left
  should be shell state only. Group whatever survives into small
  dataclasses if it still reads as a pile of flags — but do not invent
  structure for its own sake.
- [ ] **9.3.4 — Split `test_ui_smoke.py` to match** (8,198 lines, 292
  tests). One test module per page module, mirroring the new layout.
  Same rule: move tests verbatim first, adapt second, separate commits.
- [ ] **9.3.5 — Hard stop condition.** If, at any page, the full suite
  cannot be made green *without editing tests*, **stop and report**. It
  means that page's code is not as separable as this plan assumes, and
  the answer is a revised plan, not a weakened test.

### 9.4 — The other long functions

Do these only if Phase 6 lands cleanly and there is room. They are
independent of the split and can slip to a later round without harm.

- [ ] **9.4.1 — `cli.py::build_parser` (350 lines)** — split per command
  group into `_add_playlist_parsers(subparsers)` etc. Mechanical.
- [ ] **9.4.2 — `cli.py::handle_library` (261 lines)** — one handler per
  subcommand, dispatched from a dict.
- [ ] **9.4.3 — `metadata_service::_tag_one_track` (316 lines)** —
  read this one before deciding. It may be a genuinely sequential
  pipeline where splitting produces eight functions that are only ever
  called in one order, which is not an improvement. If it splits, split
  along the real stages (resolve → read tags → fetch art → write →
  record); if it does not, say so and leave it.
- [ ] **9.4.4 — `download_service::poll_downloads` (216 lines)** —
  **treat with the most caution in the codebase.** This is the method
  the workers/deadlock/locked-retry saga is built around. Do not touch
  it unless the extraction is obviously safe and covered by
  `test_download_service.py`'s 94 tests, and re-run
  `tests/test_stress_e2e.py` if you do. Skipping this item entirely is
  an acceptable outcome; say so rather than half-doing it.

---

## 10. Phase 7 — Comment triage

Now, and only now, with the files small. **4,204 standalone comment lines
in `src/`.** The target is not a number — it is that every surviving
comment passes the shelf-life test in §1.

### 10.1 — The four categories

Sort every comment you touch into one of these. This is the whole method.

**KEEP — a standing fact that is still true and still load-bearing.**
The reader will write worse code without it.
> `ui/main_window.py:191-206` — why `KEEP_ALL_DUPLICATES_ID = 0` and not
> `-1`: Qt treats `addButton(button, -1)` as "auto-assign", confirmed by
> a real repro that returned `-2`. Delete this and someone uses `-1`.
> **Keep, verbatim.**

**KEEP, COMPRESSED — a real fact wrapped in its own discovery story.**
Keep the fact; move the story to `HISTORY.md` and link it.
> `ui/workers.py`'s `_emit_or_drop` docstring runs ~35 lines to establish
> one rule: *wrap the `emit()`; never check-then-act, because the gap is
> real and was proven*. Compress to that plus a `HISTORY §41` link.
> `Worker`'s class docstring (~60 lines) likewise reduces to three
> numbered invariants and a link. **These are the most valuable comments
> in the codebase — compress them, do not lose them.**

**MOVE — provenance with no forward value.**
> `config_store.py:89-93` — *"Roadmap item 100 (B7) — a config.json
> written by an earlier version may still hold a
> `write_cover_jpg_sidecars` key… Deliberately not read."* The standing
> fact is one line: *"Unknown keys are ignored, so removed fields need
> no migration."* Everything else is history.

**DELETE — restates the code, or is pure archaeology.**
> `main_window.py:1300`'s `__init__`: seven comment lines above
> `self._activity_progress: dict[...] = {}`, six of which are "Roadmap
> item 65 (Phase 2.2/2.3)" provenance. One line survives: what the dict
> is keyed by and who consumes it.

- [ ] **10.1.1 — Rule of thumb, applied consistently: a comment that
  opens with "Roadmap item N" is guilty until proven innocent.** It is
  usually answering *"why was this changed?"* — a `HISTORY.md` question
  — rather than *"why is this like this?"*, which is the only question
  an inline comment should answer. Many will still be keepers after the
  provenance prefix is stripped.

- [ ] **10.1.2 — Keep every "confirmed live" / "found live" marker.**
  CLAUDE.md's own convention says a comment asserting platform or
  framework behaviour must cite a real observation or be marked
  unverified — because round 5 and round 6 both shipped confidently
  wrong framework claims. Those markers are the guard against a third
  one. **Never strip a `confirmed live (date)` while keeping the claim
  it qualifies.**

- [ ] **10.1.3 — Every "untuned" marker stays too.** Same reason: it is
  the project's honesty convention for constants that were guessed. If
  anything, add the ones that are missing.

- [ ] **10.1.4 — Docstrings: the public seam gets one, private helpers
  mostly do not.** Every service method, repository method, model and
  module gets a short docstring saying what it does and what it
  guarantees. A private `_on_button_clicked` does not need one; a
  well-named function is its own documentation. Where a docstring
  currently runs 30+ lines, the same compress-and-link rule applies.

- [ ] **10.1.5 — Order of work.** File by file, largest comment ratio
  first, one commit per file, and **`git diff --stat` in every report**
  so the size of what you removed is visible. Start with:
  `audio_formats.py` (37 comment lines to 18 code lines — start here,
  it takes ten minutes and calibrates the judgement), `docker_setup.py`
  (73.2%), `matching.py` (62.1%), `config_store.py` (62.5%),
  `soulseek/quality.py` (50.2%), `audio_analysis.py` (53.2%),
  `soulseek/download_service.py` (42.5%), then the new `pages/*`
  modules.

- [ ] **10.1.6 — Anything you MOVE must actually land in `HISTORY.md`.**
  Not summarised, not dropped. A comment removed from the source and not
  written down anywhere is information destroyed. If `HISTORY.md`
  already covers it, link it and delete; if not, add the entry first,
  then delete. **This is the one irreversible thing in the whole round —
  treat it accordingly.**

- [ ] **10.1.7** Report: comment lines before and after, per file, plus
  three examples of each of the four categories from your actual work,
  so the judgement can be reviewed rather than trusted.

---

## 11. Phase 8 — `CLAUDE.md` and `README.md`

### 11.1 — What is wrong with `CLAUDE.md`, measured

- **133,098 chars / 2,039 lines.** The Roadmap section is **116,290
  chars — 88.4%**. The four sections a cold agent actually needs total
  **10,997 chars — 8.3%**.
- **89 of 113 roadmap items exceed the file's own 8-line ceiling.**
  Median 13 lines; item 114 is 118 lines.
- **The two genuinely open bugs are invisible.** Items **63** and **70**
  are marked `**Open, real bug…**` and sit among 88 entries containing
  "— done". Item 70 (the stress-test hang) has been carried forward for
  seven rounds without the question round 6 was asked — is it the same
  defect as the queued-`QMessageBox` hang, or separate? — ever being
  answered.
- **"Known issues / backlog" contains no known issues and no backlog.**
  Every entry is `[x] Fixed:`. A cold agent reads that heading looking
  for what is broken and finds a closed-ticket archive.
- **The layout tree is stale.** It lists `spotify/sync.py`, which does
  not exist. (`_repository.py` also appears, but that is a line-wrap
  artefact of the tree formatting, not a real error — check it.)
- **No table of contents, no `###` subheadings** anywhere in the 1,775
  roadmap lines.

### 11.2 — The restructure

The goal is a file a cold agent reads **in full** before starting, in
five minutes. Everything else moves to `HISTORY.md`, which is already
785 KB and exists for exactly this.

- [ ] **11.2.1 — Target under 25,000 characters** (from 133,098). That
  is not arbitrary: it is roughly the four keeper sections plus a
  properly-sized standing-facts section, and it is short enough to
  actually be read.

- [ ] **11.2.2 — New structure:**

  ```
  # Seeker
  What it is, who it is for, one paragraph.       (keep, near-verbatim)

  ## Architecture                                  (keep, verbatim)
  ## Current layout                                (REGENERATE from the
                                                    real tree — and add
                                                    ui/pages/* from
                                                    Phase 6)
  ## Conventions                                   (keep + extend, §11.2.4)
  ## Commands                                      (keep, verbatim)

  ## Standing facts and gotchas                    (NEW — the heart of it)
     Every genuinely load-bearing fact currently buried in the roadmap,
     restated as a present-tense rule, grouped by area:
       ### Spotify / OAuth
       ### SoulSeek / slskd
       ### Qt and threading
       ### Database and migrations
       ### Packaging
     e.g. "`get_config` is a callable, not a snapshot."
          "Spotify rotates the refresh token on every PKCE refresh."
          "Never create/connect/disconnect a QObject per worker task."
          "`slskd` has two separate credential pairs — web UI vs network."
     Each ≤3 lines, present tense, with a [HISTORY §N] link.

  ## Open issues                                   (NEW — and SHORT)
     ONLY genuinely open items. Today that is items 63 and 70. If the
     list is empty, say "None." — an empty list is information.

  ## Roadmap                                       (REPLACED)
     Actual forward-looking direction only. Item 108 (SoundCloud,
     deliberately deferred) belongs here. Nothing marked "done" does.

  ## Working agreements                            (keep — this is good)
     The two-tier doc rule, the `git stash -u` rule, the tracked-
     failure-count rule, the "confirmed live or say UNVERIFIED" rule,
     the sweep-test-skip rule. All five are hard-won and all five stay.
  ```

- [ ] **11.2.3 — Move, do not delete.** Every "— done" roadmap entry
  either already has a `HISTORY.md` counterpart (verify the link
  resolves) or gets one written before removal. Same irreversibility
  rule as 10.1.6. When you are done, `HISTORY.md` must contain
  everything `CLAUDE.md` used to.

- [ ] **11.2.4 — Add the conventions this round establishes:**
  - Ruff config is the source of truth for style; `ruff format` is
    deliberately not used, and why (§4.2).
  - Logging, not `print`, in service code; handler configuration lives
    only in `main.py` / `main_ui.py` (§7.2).
  - `ui/` never touches `Application`'s private attributes, and there is
    a test enforcing it (§7.1.3).
  - Page widgets live in `ui/pages/`, take a `PageContext`, and never
    reach into `MainWindow` (§9.2).
  - The comment shelf-life test, stated in one sentence (§1).
  - The credential-storage decision: `0600` + atomic writes, not the
    Keychain, and why (§6.2.3).
  - The `.env`-in-history assessment (§6.5.2).

- [ ] **11.2.5 — Answer item 70.** Seven rounds is enough. Either
  investigate it now, or write one honest paragraph: what is known, what
  was ruled out, and what the next concrete step is. Then move it to
  "Open issues" where it is visible. Do the same for item 63.

### 11.3 — `README.md` — the CV front door

37,367 chars, well written, technically thorough. Two problems, both
about audience.

- [ ] **11.3.1 — There is not a single screenshot.** `grep -nE "!\[|<img"
  README.md` returns nothing, for a **GUI application** that is
  explicitly a portfolio piece. This is the highest-value single change
  in the entire brief for the CV audience: add 3–5 images near the top —
  Dashboard populated, Review, Duplicates, and a dark/light pair. Put
  them in `docs/screenshots/`.

  > **CORRECTED (2026-09-08).** An earlier draft said "you already have
  > them from Phase 0.3." **Do not use the Phase 0.3 baselines here.**
  > They were captured against the real production database and contain
  > Kris's actual playlist names, library paths and potentially SoulSeek
  > usernames. They are a regression baseline living outside the repo,
  > and they must stay outside it. README screenshots get their own
  > pass, taken against the scratch demo database described in §3's 0.3
  > note, with invented playlist names — which also makes them
  > reproducible by anyone rather than a snapshot of one person's
  > library.

- [ ] **11.3.2 — Lead with the reader's first 30 seconds.** The
  structure is currently setup-first. Reorder to: name and one-line
  description → screenshots → what it does → **architecture diagram** →
  tech stack → tests/CI badge → then everything that is there today.
  The setup instructions are good and stay; they just are not what
  someone evaluating the project reads first.

- [ ] **11.3.3 — Add the numbers, once CI exists.** A CI badge, the real
  test count, and the `mypy --strict` claim. They are all true and none
  of them are currently visible.

- [ ] **11.3.4 — Fix the title.** `# seeker` → `# Seeker`. The app calls
  itself "Seeker" everywhere in the UI.

---

## 12. Phase 9 — UX proposals: Kris decides, you do not

Kris asked for suggestions. These are mine, from reading the code rather
than from using the app, and they split into two groups. **Group A is
safe to implement; Group B changes the shape of the product and needs
Kris's explicit yes first.** Do not implement anything in Group B on
your own judgement.

### Group A — no product decision required, implement if approved

- [ ] **12.1 — Window geometry is not persisted.** `grep -rn
  "QSettings\|saveGeometry\|restoreGeometry" src/` returns **nothing**.
  Every launch resets to the hardcoded `resize(1180, 760)`
  (`main_window.py:1432`). Persist size, position and the last-open page
  in `SeekerConfig` — the store already exists and already handles
  unknown-key tolerance. This is the single most-noticed missing
  desktop-app behaviour, and `_pre_fullscreen_geometry` shows the
  machinery is already half there.

- [ ] **12.2 — No table is sortable.** `setSortingEnabled` appears
  **nowhere**. Seven tables, none sortable. Sorting Duplicates by
  similarity, Downloads by progress, or History by date is what a user
  reaches for immediately. Caveat that needs real care: these tables are
  rebuilt every 2s poll tick, and round 7's R2 note records that a
  wholesale rebuild already destroyed interactive state once. Sorting
  state must survive a rebuild the same way the keep-radio and
  delete-checkbox state does — **verify against a live poll, not a
  static test.**

- [ ] **12.3 — Zero keyboard shortcuts.** No `QShortcut`, no
  `setShortcut`, no `QKeySequence` anywhere; only `returnPressed` on
  form fields. Add: ⌘1–⌘7 for the nav pages, ⌘R refresh, ⌘F focus
  search, ⌘, for Settings (use `QKeySequence.StandardKey.Preferences` so
  Qt places it correctly in the macOS app menu). Half a day, and it is
  the difference between "a Qt app" and "a Mac app".

- [ ] **12.4 — No accessible names anywhere.** `setAccessibleName` /
  `setAccessibleDescription` appear zero times. Icon-only controls — the
  theme toggle, the notice dismiss button, per-row action buttons — are
  unlabelled to VoiceOver. Add names to every icon-only control and
  every table. Small effort, and accessibility is something a
  thoughtful reviewer specifically looks for.

- [ ] **12.5 — The menu bar has only "Help".** No File, no View, no
  Window. On macOS that reads as unfinished. At minimum: **View** with
  the page list (reusing 12.3's shortcuts) and the theme toggle;
  **Window** with the standard minimise/zoom. Qt gives most of this
  nearly free.

### Group B — needs Kris's yes

- [ ] **12.6 — The Dashboard is doing four jobs.** It currently holds
  the playlist list, the track table, the tagging controls, a
  `QPlainTextEdit` results log, a status label, and two separate
  `InlineNotice` widgets — while Search, Downloads, Review, Duplicates,
  Sharing and History each do one thing. **Proposal:** move the tagging
  controls and their results to a dedicated **Library** page (they are
  library operations, not playlist operations), leaving the Dashboard as
  "pick a playlist, see its tracks, see what to do next". Cleaner
  conceptually and it makes the Dashboard page module in Phase 6
  substantially smaller. **This changes where a user finds a feature —
  Kris's call.**

- [ ] **12.7 — `tagging_results` is a scrolling text log in a GUI**
  (`QPlainTextEdit`, `setMaximumHeight(120)`, `main_window.py:2099-2101`).
  It is the CLI's stdout wearing a widget. **Proposal:** replace with a
  one-line summary ("Tagged 34 of 36 — 2 failed") plus an expandable
  details list showing per-track outcomes with the failures selectable
  and retryable. Better information in less space, and it pairs
  naturally with Phase 4's logging work.

- [ ] **12.8 — No filter on the track table.** A 200-track playlist with
  12 missing means scrolling to find them. **Proposal:** a segmented
  filter above the track table — All / Missing / Needs review /
  Untagged — reading the same `TrackStatus.state` values
  `_decide_next_step` already counts. High value, cheap, but it adds a
  control to the app's densest screen, which is why it is in Group B.

- [ ] **12.9 — Five feedback channels compete.** The activity strip
  (top), `next_step_notice`, `dashboard_notice`, `status_label`
  (bottom), and tray notifications. Each was added for a good reason;
  together a user does not know where to look. **Proposal:** a short
  written rule for which channel carries what — transient progress /
  persistent guidance / errors / background-only — then make the code
  follow it and delete whichever channel has no remaining job. This is a
  design decision, not a refactor.

- [ ] **12.10 — Nothing explains *why* a track needs review.** The
  Review page shows candidates; the score that put them there and the
  competing candidate are the information a user needs to decide, and
  the matching pipeline already computes both (`matching.py`,
  `soulseek/quality.py`). **Proposal:** show the score and the runner-up
  inline. This is the app's core value proposition — "which download is
  genuinely best" — and it is currently invisible in the UI.

---

## 13. Reporting, and what "done" means

Per this project's standing rules, which apply to every phase above:

- **One commit per numbered item.** Never per phase, never a mixed
  commit. A refactor commit contains no behaviour change; a behaviour
  change commit contains no refactor.
- **Every phase closes with all three numbers**, quoted exactly: the
  full `pytest` summary line with every failure and skip named inline,
  `mypy --strict` output, and the `ruff check` count. Never "green with
  N pre-existing failures" as a paraphrase. **If N moves, that is a
  regression to diagnose before continuing, not a new baseline.**
- **Phases 6, 7 and 8 additionally require screenshots** compared
  against the Phase 0.3 baselines, in both themes. A passing test suite
  is not evidence that the UI still looks right.
- **Every ledger item is either ticked with real evidence or explicitly
  marked NOT DONE with a reason.** Raw output, real diffs, actual
  attached images. A description of a diff is not a diff.
- **Report anything you could not run**, rather than reporting it as
  done. Several items here need a real Mac and a real display.

### The one thing that would make this round a failure

Not "some items were skipped" — skipping Phase 9's Group B entirely, or
9.4.4, or half of Phase 7, is a perfectly good outcome if it is stated.

The failure mode is **a green suite over a changed app**. Phase 6 moves
thousands of lines of widget construction. Phase 7 deletes information
permanently. Both are exactly the shape of change where a test suite
reports success while something the tests never looked at has quietly
broken — which is the specific failure this project has now hit in three
consecutive rounds (round 5 asserted a property instead of looking;
round 6 wrote an assumption as a comment; round 7's sweep test skipped
the failing case).

So: **look at the app.** Screenshot every page, in both themes, empty and
populated, and compare against Phase 0.3 with your own eyes before
calling any phase done.

---

## 14. Phase 3B — The Dock icon after close (added 2026-09-07)

**Slot this between Phase 3 (Security) and Phase 4.** It is a real
user-reported defect, it is isolated, and it touches
`ui/main_window.py` and `packaging/seeker.spec` — both of which Phase 6
rearranges, so it wants to be finished before the structural work
starts, not tangled into it.

### 14.0 — The report, verbatim

> I tested the full-screen functionality and it does close on full
> screen, but I notice that the app icon stays in the bottom dock with
> the other apps, which is confusing, as pressing the app icon from
> there does *not* open the app. One has to go to the top right icons
> section and open it through there. Trying to open it again from
> Applications also fails. Can we have the same functionality as Docker
> for instance — if you press X, the dock icon disappears, and only the
> top right small icon is left, but also being able to re-open it
> through Applications should preferably work.

So round 7's E1 landed: the fullscreen close no longer strands an empty
window. What it exposed is the next layer down.

### 14.1 — This is two separate defects behind one symptom

Diagnose them separately, because one of them is a genuine bug and the
other is macOS behaving exactly as configured.

#### Defect A — the reopen event arrives and is thrown away

Qt's Cocoa platform plugin implements the AppKit delegate method macOS
sends on a reopen. Its entire body
(`qtbase/src/plugins/platforms/cocoa/qcocoaapplicationdelegate.mm`) is:

```objc
- (BOOL)applicationShouldHandleReopen:(NSApplication *)theApplication
                    hasVisibleWindows:(BOOL)flag
{
    Q_UNUSED(theApplication);
    Q_UNUSED(flag);

    if (reflectionDelegate && [reflectionDelegate respondsToSelector:
            @selector(applicationShouldHandleReopen:hasVisibleWindows:)])
        return [reflectionDelegate applicationShouldHandleReopen:theApplication
                                              hasVisibleWindows:flag];

    QWindowSystemInterface::handleApplicationStateChanged(
        Qt::ApplicationActive, true /*forcePropagate*/);
    return YES;
}
```

Read what that does and does not do. **Qt does not show any window.** It
converts the reopen into one thing — an application-state change to
`Qt::ApplicationActive`, with `forcePropagate` set so it is emitted even
when the state is already Active — and returns `YES`, telling AppKit the
app handled it. Showing a window is the application's job, and Qt has
handed it the only notification it is going to get.

Seeker never listens for it:

```
$ grep -rn "applicationStateChanged\|ApplicationStateChange\|
           ApplicationActivate\|installEventFilter" src/seeker/
(no matches)
$ grep -rn "class .*QApplication" src/seeker/
(no matches)
```

No handler, no `QApplication` subclass, no event filter. The reopen is
received by Qt, translated, emitted, and dropped on the floor.

**This is why both of Kris's symptoms are the same bug.** macOS routes
*every* "reopen an already-running app" gesture through that one
selector: clicking the Dock icon, double-clicking the app in
Applications or Finder, launching it from Spotlight, `open -a Seeker`.
LaunchServices does not start a second instance of a running bundle — it
sends a reopen event to the one that exists. All of those paths dead-end
in the same missing handler.

#### Defect B — the Dock icon is still there because nothing has ever said otherwise

```
$ grep -rn "LSUIElement\|activationPolicy\|pyobjc\|AppKit" packaging/ src/ pyproject.toml
(no matches)
```

`packaging/seeker.spec`'s `BUNDLE(info_plist={...})` carries exactly four
keys — `NSHighResolutionCapable`, `CFBundleShortVersionString`,
`CFBundleVersion`, `NSHumanReadableCopyright`. No `LSUIElement`, and no
runtime activation-policy call anywhere.

A running app whose activation policy is
`NSApplicationActivationPolicyRegular` — the default for any normal
bundled app — always shows a Dock icon, window or no window. That is
macOS working as designed. **The Dock icon is not the bug; the dead
Dock icon is.** Fixing A alone would already leave the app in a
defensible state (a Dock icon that reopens the window, like Mail or
Messages). Fixing B on top is what gets the Docker-like behaviour Kris
asked for.

### 14.2 — Fix A first, and verify it on its own

Do this as its own commit and confirm it works **before** touching the
activation policy. The reason is not tidiness: fixing B removes the Dock
icon, which is the easiest way to test A. Lose that and you are
debugging two changes through one narrow path.

- [ ] **14.2.1 — Observe the state change and reopen on it.** In
  `MainWindow.__init__`, after `_build_tray_icon()`:

  ```python
  app = QApplication.instance()
  if app is not None:
      app.applicationStateChanged.connect(self._on_application_state_changed)
      self._app_state_connected = True
  ```

  ```python
  def _on_application_state_changed(self, state: Qt.ApplicationState) -> None:
      # macOS sends every "reopen a running app" gesture — Dock icon
      # click, double-click in Applications/Finder, Spotlight, `open -a`
      # — through NSApplicationDelegate's
      # applicationShouldHandleReopen:hasVisibleWindows:. Qt's cocoa
      # plugin handles that selector by emitting exactly this state
      # change (Qt::ApplicationActive, forcePropagate) and returning YES;
      # it never shows a window itself. Reopening is ours to do, and
      # this signal is the only notification we get.
      if state != Qt.ApplicationState.ApplicationActive:
          return
      if self.isVisible():
          return
      self._on_tray_open_seeker()
  ```

  **Two things about that guard, both deliberate:**

  `ApplicationActive` is not reopen-specific — it also fires on ordinary
  activation (⌘-Tab to the app, clicking one of its windows), and
  because Qt passes `forcePropagate=true` it fires even when the state
  was already Active. `not self.isVisible()` is what narrows it to the
  case that matters, and in every other case `_on_tray_open_seeker()`
  would have been a near-no-op anyway.

  Guard on **`isVisible()`, not `_hidden_to_tray`.** That flag is
  deliberately not set until `_check_hidden_to_tray` confirms the hide
  at the platform level (`_HIDE_TO_TRAY_VERIFY_DELAY_MS` later), and on
  the ordinary hide path it stays False for that whole window. A user
  who closes the window and immediately clicks the Dock icon must get it
  back; gating on `_hidden_to_tray` would silently ignore them for the
  first 400 ms. `_on_tray_open_seeker()` already resets the flag and
  bumps `_hide_request_id`, so a reopen landing mid-verification
  correctly invalidates the pending check — that machinery is already
  right, just never reachable from here.

- [ ] **14.2.2 — Disconnect it in `cleanup_before_quit`.** This is a
  connection to a **global** object (`QApplication`), not to this
  window, so this window's own destruction does not drop it. The
  codebase already has the exact precedent and the reasoning written
  down — `_system_scheme_connected` /
  `QGuiApplication.styleHints().colorSchemeChanged` in
  `cleanup_before_quit`. Mirror it, flag and all.

- [ ] **14.2.3 — Test what can be tested offscreen, and say what cannot.**
  A real Dock click cannot be produced under `QT_QPA_PLATFORM=offscreen`.
  What *can* be asserted is the handler's own contract, which is the
  part that would silently rot: with the window hidden, emitting
  `applicationStateChanged(Qt.ApplicationState.ApplicationActive)`
  results in a visible window; with the window already visible, it does
  not call `_on_tray_open_seeker` (assert the poll methods are not
  re-entered); with a non-Active state, nothing happens. **Do not write
  a comment claiming this proves the Dock click works** — it proves the
  handler works, and those are different sentences. Round 6's D5 is what
  happens when they get conflated.

- [ ] **14.2.4 — Real-desktop verification, all four routes.** On the
  real Mac, with a real build, from both a normal close *and* a
  fullscreen close:
  1. Click the Dock icon.
  2. Double-click Seeker in Applications.
  3. Spotlight → Seeker.
  4. `open -a Seeker` from a terminal.

  Each must restore the window, at the pre-close geometry, focused and
  in front. Report the outcome of all eight combinations individually.
  Anything you could not click is "not verified", not "done".

### 14.3 — Fix B: drop the Dock icon while hidden to the menu bar

The mechanism is `NSApplication`'s activation policy: `Regular` (Dock
icon + menu bar) while the window is up, `Accessory` (menu bar extra
only, no Dock icon) while it is hidden.

**Why not just set `LSUIElement` in the Info.plist**, which is what
Apple's own DTS engineers recommend when asked this: because
`Accessory`/`LSUIElement` means *no Dock icon **and no menu bar**,
ever* — including while the Seeker window is open and in use. The Help
menu (About Seeker, Check for updates), the application menu and ⌘Q
would all disappear. That is a much larger change than Kris asked for.
Switching dynamically gives exactly the behaviour he described: icon
while the window is up, no icon while it is not.

**Be honest about the risk in the code.** That same DTS thread exists
because programmatic `setActivationPolicy:` has reported flakiness —
icons lingering, or flashing before disappearing — when called at launch
around `NSApplicationMain`. Calling it at runtime, on the main thread, in
response to a window closing is a different situation and is the pattern
menu-bar apps normally use. **It is still a platform claim, and this
project has now been wrong about a confident unverified platform claim
twice** (round 5's C1, round 6's D5). Verify it live before writing a
comment that says it works, and write "confirmed live (date, macOS
version, PySide6 version)" or nothing.

- [ ] **14.3.1 — Choose the binding: PyObjC.** Add
  `"pyobjc-framework-Cocoa>=10.0; sys_platform == 'darwin'"` to
  `dependencies` in `pyproject.toml`, then:

  ```python
  def _set_dock_icon_visible(visible: bool) -> None:
      if sys.platform != "darwin":
          return
      from AppKit import (
          NSApp,
          NSApplicationActivationPolicyAccessory,
          NSApplicationActivationPolicyRegular,
      )
      NSApp().setActivationPolicy_(
          NSApplicationActivationPolicyRegular if visible
          else NSApplicationActivationPolicyAccessory
      )
  ```

  **The reasoning, and the fallback, because this adds a dependency to a
  project that prefers not to.** The alternative is hand-rolled
  `ctypes` against `libobjc` — no dependency, about 25 lines. It carries
  a real trap: `objc_msgSend` is variadic, and on Apple Silicon you
  **must** cast it to a correctly-typed `CFUNCTYPE` per call signature
  rather than mutating `argtypes` on the shared symbol, or arguments go
  into the wrong registers and you get silent garbage or a crash. Given
  CLAUDE.md's own "prefer the idiomatic/correct approach over the
  fastest one", and given this project's history with confidently-wrong
  platform code, the maintained binding is the right call.

  **Gate it on a measurement, though.** Report the `.dmg` size before
  and after. If PyObjC adds more than ~15 MB to the bundle, say so and
  raise the ctypes fallback with Kris rather than deciding alone. Also
  confirm PyInstaller picks it up — you will likely need
  `hiddenimports=["AppKit", "Foundation", "objc"]` in
  `packaging/seeker.spec`, and **a real `.dmg` build plus a launch from
  `/Applications` is the only thing that proves it**, not a dev-mode
  run.

- [ ] **14.3.2 — Flip to `Accessory` only once the window is genuinely
  gone, never synchronously inside `closeEvent` on the fullscreen path.**
  This is the round-7 E1 lesson applied to a new call: the fullscreen
  close is an AppKit animation running for several hundred milliseconds
  after `closeEvent` returns, and changing the process's activation
  policy mid-transition is precisely the shape of operation that
  produced the empty unclosable window in the first place.

  The codebase already owns the right witness. `_check_hidden_to_tray`
  consults `_is_exposed_at_platform_level()` — the real `QWindow`'s own
  `isExposed()`, which the platform plugin updates from actual
  show/hide/expose notifications rather than from Qt's own "did someone
  call `hide()`" bookkeeping. Hang the policy change off that:

  - **Ordinary hide path:** call `_set_dock_icon_visible(False)` from
    `_check_hidden_to_tray`, in the branch that already confirms the
    window is not exposed and sets `_hidden_to_tray = True`. No new
    timer, no new state.
  - **Fullscreen path:** this branch deliberately arms *no* verification
    timer, for reasons its own comment sets out at length, and that must
    not change. Give it a **policy-only** deferred check instead — one
    that re-reads `_is_exposed_at_platform_level()` and either flips the
    policy or reschedules once, and that **never calls `hide()` and
    never touches `_hidden_to_tray`**. It cannot manufacture the failure
    the E1.4 comment warns about because it takes no corrective action
    on the window at all. Carry `_hide_request_id` through it the same
    way, so a stale check cannot fire after a reopen.

- [ ] **14.3.3 — Flip back to `Regular` at the top of
  `_on_tray_open_seeker`, before `showNormal()`.** Order matters: the
  window needs to be shown by an app that is already `Regular`, or it
  can come up behind other applications. `_on_tray_open_seeker` already
  calls `raise_()` and `activateWindow()`; verify on the real desktop
  that those are sufficient after a policy change. **If the window comes
  back behind another app**, the known remedy is an explicit
  `NSApp().activateIgnoringOtherApps_(True)` after the policy switch —
  add it only if you actually observe the problem, and say in the
  comment that you observed it.

- [ ] **14.3.4 — Never let the app end up `Accessory` with no way back.**
  That state is unrecoverable for the user: no Dock icon, and if the
  tray icon is also missing there is no UI at all. Two guards:
  - Only ever switch to `Accessory` when `self._tray_icon is not None
    and self._tray_icon.isVisible()`. `closeEvent` already refuses to
    hide-to-tray without a real tray icon; the policy change must obey
    the same precondition.
  - Force `Regular` back in `cleanup_before_quit`, so a quit never
    leaves the process in an odd state mid-teardown.

- [ ] **14.3.5 — Check what the menu bar does across the transition.**
  `Accessory` apps have no menu bar. Confirm on the real Mac that after
  hide → reopen the Help menu is back and functional (About Seeker,
  Check for updates), and that ⌘Q still quits. Screenshot the menu bar
  after a reopen. If the menu bar does not return, **stop and report** —
  that is a blocker for 14.3 and Kris keeps the Dock icon rather than
  losing the menu.

### 14.4 — The one claim I could not verify, and what to do about it

Fix B removes the Dock icon, so after it lands the only remaining
"reopen from outside" routes are Applications, Finder, Spotlight and
`open -a`. Those all depend on this being true:

> **UNVERIFIED:** an already-running app whose activation policy is
> `Accessory` still receives `applicationShouldHandleReopen:` when the
> user launches its bundle from Finder/Applications, rather than
> LaunchServices starting a second instance.

I believe it is true — LaunchServices keys on the bundle identifier, not
on the activation policy — but I could not observe it from here, and per
CLAUDE.md's own standing convention an unmarked confident claim about
platform behaviour this project has already been wrong about twice is a
liability, not documentation.

- [ ] **14.4.1 — Test this explicitly, before 14.3 is called done.**
  With the app hidden and in `Accessory` mode, double-click Seeker in
  `/Applications`. Expected: the existing window comes back. Watch for
  the failure mode too — a *second* Seeker process starting (check
  `ps aux | grep -i seeker`, and whether two tray icons appear).
- [ ] **14.4.2 — If it turns out false, 14.3 is not shippable as
  designed.** Report it; do not work around it with a lock file or a
  single-instance guard on your own initiative. The honest fallback is
  to ship 14.2 only, keep the Dock icon, and let Kris decide — a Dock
  icon that correctly reopens the window is a perfectly good outcome and
  is what every stock Mac app does.

### 14.5 — While you are in this code: a constant that contradicts its own comment

`ui/main_window.py:6274-6284`:

```python
    # Roadmap item E1.4 (round 7, corrected after a second review) —
    # untuned: the real AppKit exit-fullscreen-then-close animation
    # measures somewhere in the 0.5-1s range (per this item's own
    # diagnosis, still not measured against real hardware from this
    # session), so this is a round number comfortably above that, not a
    # verified figure.
    _HIDE_TO_TRAY_VERIFY_DELAY_MS = 400
```

**400 ms is not "comfortably above" a 0.5–1 s range; it is below all of
it.** Either the value or the comment is wrong. It does not bite today —
the fullscreen path deliberately arms no verify timer, so this delay
only ever applies to the ordinary hide, where 400 ms is probably fine —
but it is exactly the "comment asserting behaviour that does not match
the code" pattern CLAUDE.md's own convention exists to prevent, sitting
in the code you are about to build on.

- [ ] **14.5.1 — Resolve it with a measurement, not a guess.** You are
  already going to be timing the fullscreen close transition for 14.3.2.
  Measure it (log the interval between `closeEvent` and the first
  `isExposed() == False`), pick the constant from that number, and
  rewrite the comment to state what was measured, on which macOS and
  PySide6 version. If the ordinary hide path genuinely settles in well
  under 400 ms, say that instead — but say something true.

### 14.6 — Reporting for this phase

Three commits, in this order, each verified before the next:

1. **14.2** — reopen handling. Suite green, plus the 14.2.4
   eight-combination real-desktop checklist.
2. **14.3** — activation policy. Suite green, plus a **real `.dmg`
   build installed to `/Applications`** and exercised — dev-mode runs do
   not prove the PyInstaller side of 14.3.1. Screenshots: Dock with the
   window open, Dock with the window closed (icon absent), menu bar
   after a reopen.
3. **14.5** — the constant and its comment, with the measurement quoted.

**14.4.1's result gets reported either way, explicitly**, because it
decides whether commit 2 ships at all.

---

## Appendix A — Verified file and line references

Cited against the working tree at `6b0c19c` **plus the uncommitted round-7
changes**. Line numbers in `ui/main_window.py` and `ui/theme.py` will
shift as soon as Phase 2 starts — re-derive rather than trusting these
once you have made a commit.

| Reference | Path:line |
|---|---|
| `MainWindow` class | `src/seeker/ui/main_window.py:1299` (5,277 lines, 179 methods) |
| `MainWindow.__init__` | `:1300` (203 lines) |
| Bare `self.spotify` (B018) | `src/seeker/application.py:244` |
| `TokenStore.save` (no chmod) | `src/seeker/spotify/token_store.py:11` |
| `save_config` (has chmod) | `src/seeker/config_store.py:117-127` |
| `wait_for_callback` (no timeout) | `src/seeker/spotify/callback_server.py:61-67` |
| Handler class-level state | `src/seeker/spotify/callback_server.py:13-16` |
| State comparison (correct) | `src/seeker/spotify/auth_manager.py:106` |
| `S608` false positive | `src/seeker/database/repositories/local_file_repository.py:315` |
| Private write from UI | `src/seeker/ui/settings_window.py:1090` |
| Album art fetch | `src/seeker/library/metadata_service.py:1310` |
| `generate_api_key` | `src/seeker/docker_setup.py:171` |
| `bring_up_slskd` env dict | `src/seeker/docker_setup.py:364-372` |
| slskd base URL (loopback) | `src/seeker/ui/wizard.py:50` |
| Hardcoded window size | `src/seeker/ui/main_window.py:1432` |
| `tagging_results` log widget | `src/seeker/ui/main_window.py:2099-2101` |
| `closeEvent` (fullscreen branch) | `src/seeker/ui/main_window.py:6286-6352` |
| `_check_hidden_to_tray` | `src/seeker/ui/main_window.py:6417` |
| `_is_exposed_at_platform_level` | `src/seeker/ui/main_window.py:6408` |
| `_on_tray_open_seeker` | `src/seeker/ui/main_window.py:6177` |
| `cleanup_before_quit` (disconnect precedent) | `src/seeker/ui/main_window.py:6220` |
| `_HIDE_TO_TRAY_VERIFY_DELAY_MS` (§14.5) | `src/seeker/ui/main_window.py:6284` |
| `BUNDLE(info_plist={...})` — no `LSUIElement` | `packaging/seeker.spec` |
| `setQuitOnLastWindowClosed(False)` | `src/seeker/main_ui.py:35`, `:40` |
| Two slskd credential pairs | `src/seeker/docker_setup.py:178-190` |
| `build_stylesheet` | `src/seeker/ui/theme.py:604` (467 lines) |
| `size_action_column` | `src/seeker/ui/theme.py:468` |
| `apply_column_floors` | `src/seeker/ui/theme.py:433` |
| `_decide_next_step` (the good shape) | `src/seeker/ui/main_window.py:606` |
| `DTZ005` false positive | `src/seeker/spotify/client.py:73` |
| `RUF046` | `src/seeker/ui/formatting.py:73` |
| `PLC0206` | `src/seeker/spotify/sync_service.py:96` |
| `B007` | `src/seeker/ui/main_window.py:1251` |
| `RUF100` | `src/seeker/ui/main_window.py:456` |
| `_open_in_file_manager` | `src/seeker/ui/main_window.py:358-373` |
| Port bindings | `docker-compose.yml` |

## Appendix B — Commands used to produce every number here

```bash
# size and shape
find src -name "*.py" -exec wc -l {} + | sort -rn | head -20
# comment ratio, longest functions, biggest classes: AST walk over
#   src/**/*.py counting ast.FunctionDef/ClassDef spans and lines whose
#   first non-space character is '#'
# lint (NOTE: run with the project's own ruff >= 0.16.4, not mine)
uv run ruff check src --statistics
uv run ruff check src --select E,W,F,I,N,UP,B,A,C4,SIM,RET,ARG,PTH,PL,RUF,TRY,EM,DTZ,S --ignore E501 --statistics
# layering
grep -rE "^(from|import).*(database|sqlite3|repositor)" src/seeker/ui/
grep -rn "application\._[a-z]" src/seeker/ui/
grep -rn "^\s*print(" src/seeker --include=*.py | grep -v "cli.py\|main"
grep -rn "^import logging\|^from logging" src/
# UI gaps
grep -rn "QSettings\|saveGeometry\|restoreGeometry" src/
grep -rn "setSortingEnabled" src/seeker/ui/
grep -rn "QShortcut\|setShortcut\|QKeySequence" src/seeker/ui/
grep -rn "setAccessibleName\|setAccessibleDescription" src/seeker/ui/
# secrets
git log --all --oneline -- .env
# §14 — the Dock icon
grep -rn "applicationStateChanged\|ApplicationStateChange\|installEventFilter" src/seeker/
grep -rn "LSUIElement\|activationPolicy\|pyobjc\|AppKit" packaging/ src/ pyproject.toml
# CLAUDE.md: section sizes and per-item line counts measured by splitting
#   on '^## ' and '^\d+\. ' respectively
```

External sources consulted for the security section:
slskd's own configuration documentation (web UI auth defaults, API keys,
`remote_configuration`) at
<https://github.com/slskd/slskd/blob/master/docs/config.md> and
<https://github.com/slskd/slskd/blob/master/docs/docker.md>;
RFC 9700, *Best Current Practice for OAuth 2.0 Security*, at
<https://www.rfc-editor.org/info/rfc9700/>; RFC 8252 §7.3 on loopback
redirect URIs for native apps.

For Phase 1's correction: Astral's Ruff v0.16.0 release announcement
(default set 59 → 413 rules; the 18 removed; the recommendation to state
`select` explicitly for version-stable behaviour) at
<https://astral.sh/blog/ruff-v0.16.0>, and Ruff's `BREAKING_CHANGES.md`.

For §14: Qt's own Cocoa platform plugin source,
`src/plugins/platforms/cocoa/qcocoaapplicationdelegate.mm`
(`applicationShouldHandleReopen:hasVisibleWindows:`), and QTBUG-10546
("Support applicationShouldHandleReopen in Cocoa app delegate"); Apple's
`NSApplicationDelegate` documentation for
<https://developer.apple.com/documentation/appkit/nsapplicationdelegate/applicationshouldhandlereopen(_:hasvisiblewindows:)>;
and the Apple Developer Forums thread on
`NSApplicationActivationPolicyAccessory` not reliably hiding the Dock
icon, <https://developer.apple.com/forums/thread/735682>, which is where
the DTS recommendation to prefer `LSUIElement` comes from.
