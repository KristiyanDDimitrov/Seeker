# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** this session's tick/handoff commit, on top of `da31263` —
  "S12: comment triage — audio_analysis.py" (S12's six per-file commits
  land before it).
- **Working tree:** clean. `origin/main`: not re-checked this session —
  ask before pushing regardless.
- **pytest:** 1149 passed, 1 skipped — identical to every S10–S11.7
  number, confirmed after all six S12 commits.
- **mypy --strict src/:** clean, 99 files. **ruff check src tests: 0
  findings.**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map: `docs/round8/
SESSION-PLAN.md` — **read that, not the full 115 KB brief.**

- **Done:** Phase 0–6 (through S11.7), and now **S12** (Phase 7,
  comment triage pass 1 — §10.1's six small files: `audio_formats.py`,
  `docker_setup.py`, `matching.py`, `config_store.py`,
  `soulseek/quality.py`, `audio_analysis.py`).
- **Next: S13** (Comment triage, pass 2 — §10.1, `soulseek/
  download_service.py` plus the new `ui/pages/*` modules). Read §10 of
  the main brief fresh if you didn't just do S12 — the four-category
  method (KEEP / KEEP-COMPRESSED / MOVE / DELETE) is short, re-read it
  rather than relying on this summary.

## S12 report (§10.1.7)

Comment lines before -> after per file (bare `#` lines; docstring lines
counted separately since some `#` blocks became docstrings under
§10.1.4's public-seam rule):

| File | `#` before -> after | docstring before -> after |
|---|---|---|
| `audio_formats.py` | 37 -> 14 | 8 -> 7 |
| `docker_setup.py` | 143 -> 67 | 50 -> 43 |
| `matching.py` | 82 -> 80 | 17 -> 17 |
| `config_store.py` | 69 -> 48 | 0 -> 0 |
| `soulseek/quality.py` | 112 -> 108 | 24 -> 21 |
| `audio_analysis.py` | 50 -> 43 | 10 -> 10 |

One commit per file (`7a0b0b3`, `c5556d4`, `946f188`, `1b9bedc`,
`9a6dc85`, `da31263`). `matching.py`/`audio_analysis.py` moved least —
both were already close to house style (real measured numbers,
`confirmed live`/`untuned` markers), matching the brief's own
prediction that those markers are the valuable comments.

**Examples, from actual work:** KEEP verbatim — `matching.py`'s
`FS_SUBSTITUTION_RE`/`DOT_RE`/`FEAT_CLAUSE_RE` comments, each citing a
real BMTH track and a measured ratio. KEEP-COMPRESSED —
`audio_formats.py`'s `.aifc`-excluded-from-`LOSSLESS_EXTENSIONS`
reasoning: kept the mutagen-COMM-chunk fact + `confirmed live` marker,
dropped the "Roadmap item R1" framing (HISTORY §85 link added). MOVE —
`audio_formats.py`'s `DOWNLOADABLE_EXTENSIONS` comment had a `.ogg`/
`format_unsupported` anecdote **not yet in HISTORY**; added to §94
first, then deleted from source (§10.1.6's "add before delete," not
skipped). DELETE — `docker_setup.py::compose_file_path()`'s "Same
reasoning/home as `slskd_data_dir()`" preamble restated what the
function below already shows; trimmed to one clause.

**Real gaps found, not just comment moves:** `docker_setup.py::
KICKED_LOG_PATTERNS` cited "docs/HISTORY.md item 8" — real entry is
**§52**, fixed. `matching.py::evaluate_match` cited "CLAUDE.md item
56" — CLAUDE.md has no numbered items; real entry is **HISTORY §56**.
Two vague "see CLAUDE.md" pointers replaced with real HISTORY links
(§5, §11).

All six commits pass `ruff`/`mypy --strict` individually; full suite
re-run once at the end (numbers above), since none of this touches
behavior.

## Read discipline — this is why sessions were costing 300–700 K tokens

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't re-read a file you just edited. Don't read a brief for a
phase you aren't doing.

## Waiting on Kris — real-world actions Code cannot do

- [ ] Click the Dock icon after a normal close and after a fullscreen
      close; confirm the window returns. Reopen via Spotlight too.
- [ ] From a second device, confirm `http://<mac-lan-ip>:5030` no
      longer answers.
- [ ] Push the unpushed commits to `origin/main` (or say go ahead) —
      check `git log origin/main..HEAD` fresh, not re-verified now.

## Open questions

- **Is the GitHub repo private?** `github.com/KristiyanDDimitrov/
  Seeker/actions` 404s anonymously — if so, `update_check.py`'s 404-
  means-"no releases" assumption only holds once the repo is public.
- **`open -a Seeker` focus artifact** (§14, observed once, unconfirmed).
  S9's skip-count mismatch (29 vs. everyone else's 1) — same status.
- **Three round-8 flakes in CLAUDE.md's Open Issues, plus the
  fullscreen-close pair (firing noticeably more often across
  S11.2–S11.7)** — diagnose any recurrence directly, never
  `pytest-rerunfailures`.
- **S12 found two wrong HISTORY citations** in comments (a plain
  number-typo, and "CLAUDE.md item N" where CLAUDE.md has no numbered
  items). S13 should spot-check a few `item \d+`/`§` references against
  the real HISTORY.md section rather than assume every citation in the
  files it touches is correct.
- **`soulseek/download_service.py`/`ui/pages/*` didn't exist as
  separate modules when the brief's §10.1.5 file list was written** —
  treat that list as a pointer to "the pages," not a literal path list.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
