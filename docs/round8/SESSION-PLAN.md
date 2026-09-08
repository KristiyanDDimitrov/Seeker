# Round 8 — session plan

**Purpose: keep each Claude Code session under ~150 K tokens.** Sessions
have been running 300–700 K. This file is the index that chunks the
existing briefs into session-sized slices; it does not restate their
tasks. The task text lives in:

- `docs/BRIEF-2026-09-08-refactor.md` — the full nine-phase plan
- `docs/BRIEF-2026-09-09-security.md` — Phase 3 + 3B (complete)

**No existing task has been changed.** Section numbers below refer to
those files. Only §S1.N items are new, appended from Phase 3B's report.

---

## Why sessions were expensive, measured

| File | Size | ≈ tokens, one full read |
|---|---|---|
| `docs/HISTORY.md` | 807 KB | **~215 K** |
| `tests/test_ui_smoke.py` | 8,688 lines | **~95 K** |
| `src/seeker/ui/main_window.py` | 6,882 lines | **~78 K** |
| `CLAUDE.md` | 148 KB | **~40 K** |
| `docs/BRIEF-2026-09-08-refactor.md` | 115 KB | **~31 K** |

Two conclusions drive everything below.

**First: `main_window.py` + `test_ui_smoke.py` read whole is ~173 K
tokens — over budget before a single edit.** Phase 6 decomposes exactly
those two files. It is not doable in one session, and it is not doable
at all if files are read whole. Hence one page-module per session, with
ranged reads.

**Second: CLAUDE.md is a ~40 K tax on every session, and it is
growing** — 133 KB when this round started, 148 KB now, while the plan
that says to shrink it sits unexecuted. Phase 8 is 88% changelog that
belongs in HISTORY.md. **Cutting it first pays for itself roughly ten
times over** across the remaining sessions, so Phase 8 has been split
and its size-reduction half moved to the front.

That reordering, plus the read discipline in `docs/HANDOFF.md`, is the
whole optimisation. Nothing else about the plan changes.

---

## Session map

Tick a box when that session's work is committed and its three numbers
are recorded. One session per row; if a session overruns, stop at the
named split point rather than pushing through.

| # | Session | Executes | Est. |
|---|---|---|---|
| ☑ S1 | Close-out + shrink CLAUDE.md | §S1 below, then §11.2 (8a only) | ~90 K |
| ☑ S2 | Layering: private access | §7.1 | ~70 K |
| ☑ S3 | Layering: logging | §7.2 | ~120 K |
| ☐ S4 | Deduplication | §8.1, §8.2 | ~110 K |
| ☐ S5 | Phase 6 prep + dialogs + static pages | §9.2, §9.3.1 (dialogs, History, Help/Support) | ~110 K |
| ☐ S6 | Search + Sharing pages | §9.3.1 | ~110 K |
| ☐ S7 | Downloads + Tagging panel | §9.3.1 | ~120 K |
| ☐ S8 | Dashboard page | §9.3.1 | ~110 K |
| ☐ S9 | Review page | §9.3.1 | ~120 K |
| ☐ S10 | Duplicates page | §9.3.1 | ~120 K |
| ☐ S11 | Tray extraction + `MainWindow` close-out | §9.3.2, §9.3.3, §9.3.4 | ~110 K |
| ☐ S12 | Comment triage, pass 1 | §10.1 (small files: `audio_formats`, `docker_setup`, `matching`, `config_store`, `quality`, `audio_analysis`) | ~100 K |
| ☐ S13 | Comment triage, pass 2 | §10.1 (`download_service`, the new `ui/pages/*`) | ~120 K |
| ☐ S14 | CLAUDE.md 8b + README | §11.2.4, §11.2.5, §11.3 | ~90 K |
| ☐ S15 | UX Group A — **only if Kris approves** | §12.1–§12.5 | ~120 K |

§12.6–§12.10 (UX Group B) are product decisions for Kris and are not
scheduled. §9.4 (the other long functions) is optional; fold individual
items into a session that finishes early, or skip and say so.

---

## S1 — new tasks, appended from Phase 3B's report

These are the only genuinely new items. Everything else in this file is
a pointer.

- [x] **S1.1 — Push, and confirm CI.** `origin/main` is 17 commits
  behind. `.github/workflows/ci.yml` has still never been observed
  running. Push, then report the run URL and result. If it fails, that
  is Phase 1's failure and it is fixed before S1 continues.

  **Done, with a caveat CI itself cannot be blamed for:** already
  pushed and up to date at session start. `gh run list` shows CI has
  never completed a real run — both recorded runs failed/cancelled
  before any check started, root cause a GitHub billing block on
  Kris's account ("recent account payments have failed"). Not a code
  defect; needs Kris. [HISTORY §117](../HISTORY.md#117)

- [x] **S1.2 — Settings displays a slskd web UI credential that does not
  work. Fix it.** §6.1.2 generates a web UI login and shows it in
  Settings → Connection. On this machine it is **inert**: the login was
  already customised (username `sinthesis`) before Seeker ever touched
  it, and slskd will not let an env var override an already-set login.
  So Settings now shows a username and password that will not log
  anyone in.

  That is worse than showing nothing — a user reads it, writes it down,
  fails to log in, and has no idea why. **At minimum, do not display a
  credential that is not in effect:** detect whether the env var
  actually took (query slskd, or read the persisted `slskd.yml`) and
  show the generated credential only when it did; otherwise say plainly
  that an existing login is in place and Seeker did not change it.

  `slskd-data/slskd.yml` is **real user state** — read it if you need
  to, but the "never modify a real user file without explicit
  confirmation" rule applies in full. Do not rewrite it to force the
  new credential.

- [x] **S1.3 — Confirm §6.1.2 actually works on a fresh install.** The
  inert-credential case above means the feature has only ever been
  exercised against a container that already had a login. The case it
  was *written* for — a brand-new install with no existing credential —
  is untested. Bring up a throwaway container against a scratch data
  directory, confirm the generated login really is what slskd accepts,
  and report it. Never touch the real `slskd-data/`.

  **Done.** Genuinely disposable `docker run` throwaway container,
  fresh scratch data dir, distinct ports — real production `slskd`
  never touched. Generated credential returned a real `200` from
  `POST /api/v0/session`; a wrong password on the same container
  returned a real `401`. Cleaned up and confirmed removed.
  [HISTORY §117](../HISTORY.md#117)

- [x] **S1.4 — Re-assess §6.1's severity in CLAUDE.md, honestly.** The
  finding was written as HIGH on the assumption the web UI sat at the
  vendor default `slskd`/`slskd`. On *this* machine it did not — Kris
  had already changed it, so his personal exposure was lower than
  assessed. **The fix is still correct and still necessary**, because a
  fresh install of Seeker by anyone else would have landed on the
  default. Record both facts in the same sentence. Do not quietly
  downgrade the finding, and do not leave the overstated version
  standing either.

- [x] **S1.5 — Then do §11.2, size-reduction half only ("Phase 8a").**
  This is the token payoff and it is why S1 exists. Execute §11.2.1,
  §11.2.2 and §11.2.3 from the main brief — target under 25,000
  characters, restructure into the named sections, move every "— done"
  roadmap entry to `HISTORY.md` (writing the HISTORY entry *first* where
  one does not exist; §11.2.3's move-don't-delete rule is absolute).

  **Deferred to S14, deliberately:** §11.2.4's new conventions (they
  depend on Phases 4–7 landing) and the regenerated layout tree (it
  depends on Phase 6's `ui/pages/`). Do not attempt those now.

  **Also fold in while you are there**, since they are one-line edits to
  a file you are already rewriting:
  - The read-discipline rules from `docs/HANDOFF.md` become a
    Conventions entry — they need to survive in the standing brief, not
    only in a file that gets overwritten.
  - The `ruff --fix` / `--select` rule, if Phase 1 did not already land
    it.
  - §11.2.5: answer roadmap items 63 and 70, or write the honest
    paragraph — what is known, what was ruled out, what the next
    concrete step is — and move them into the "Open issues" section
    where they are visible.
  - The `pyproject.toml` suppression justifications are excellent in
    substance but the `S101` entry alone runs ~25 lines. Same two-tier
    rule as everything else: keep the standing fact, move the
    investigation narrative to HISTORY, link it.

- [x] **S1.6 — Report the before/after size of CLAUDE.md in
  characters.** It is the measurement this whole session is justified
  by.

  **Done.** 147,842 → 24,939 chars after §11.2.1–§11.2.3
  (commit `0e18dd6`); a further 179 chars added by S1.3/S1.4 CLAUDE.md
  edits this session, current size 25,260 chars — still comfortably
  under the ~25,000-target and far under the old ~40 K-token tax.

---

## Session protocol

Identical every time. Four steps.

**Starting.** Read, in this order and nothing else:

1. `docs/HANDOFF.md` (~2 KB)
2. This file, your row only
3. The named section of the brief your row points at
4. `CLAUDE.md` — **after S1 lands, this is ~20 KB rather than 148 KB**

That is your whole context budget spent on orientation: roughly 15 K
tokens after S1, versus roughly 75 K before it.

**Working.** One commit per numbered ledger item. A refactor commit
contains no behaviour change; a behaviour change commit contains no
refactor. Read files by range, never whole — see `docs/HANDOFF.md`.

**Stopping.** Stop at your row's boundary even if there is budget left.
Do not start the next session's work "since it's small" — that is how a
150 K session becomes a 400 K one. If you are running out of budget
mid-row, stop at the last completed ledger item, commit, and say
exactly where you stopped.

**Ending.** The four steps in `docs/HANDOFF.md`'s own closing section:
commit, quote the three numbers, tick your box here, rewrite
`docs/HANDOFF.md`.

### What a handoff must contain

The next session is a stranger. It needs exactly four things, and
nothing else fits in a baton:

1. The commit it starts from, and that the tree is clean.
2. The three numbers, so a regression is detectable.
3. Which row is next.
4. Anything discovered that changes a later row — a wrong assumption, a
   blocked item, a new defect. **This is the part that gets dropped and
   matters most.** If you found something the plan does not know about,
   write it into `docs/HANDOFF.md`'s "Open questions", or the next
   session will rediscover it at full price.

Do not summarise what you did — the commits and `HISTORY.md` already
hold that, and a stranger does not need it.

---

## Phase 6 — the part that needs the most care

Sessions S5–S11 are the `MainWindow` decomposition. Read §9 of the main
brief once, in S5, and rely on this summary thereafter.

The mechanism per page, unchanged from §9.3:

1. Create `src/seeker/ui/pages/<name>_page.py`. **Move** the page's
   `_build_*`, `_render_*`, `_on_*` and `_poll_*` methods across
   **verbatim** — no renaming, no reformatting, no comment edits, no
   logic changes.
2. In `MainWindow`, construct the new widget and add temporary
   delegating properties for every attribute the tests touch.
3. **Run the full suite. It must be green with zero test edits.** That
   is what proves the move was behaviour-neutral, before any test change
   can mask it.
4. Only then, in a **separate commit**, point that page's tests at the
   page widget directly and delete the delegating properties.
5. Screenshot the page in both themes, diff against the Phase 0
   baselines at `~/seeker-baselines/2026-09-08/` and
   `.../2026-09-08-empty/`.

**Hard stop:** if the suite cannot be made green *without editing
tests*, stop and report. That means the page is not as separable as the
plan assumes, and the answer is a revised plan, not a weakened test.

**Token discipline specific to these sessions.** Do not read
`main_window.py` or `test_ui_smoke.py` whole — that is 173 K tokens and
the session is over. `grep -n` for the method names in your row's group,
read those ranges, move them. The method-group table in §9.1 tells you
which methods belong to which page; use it to build the grep, not to
guess.
