# Round 12 — session plan

**Purpose: keep each Claude Code session inside a predictable token
budget.** This file is the index. The task text is in
`docs/rounds/round-12/BRIEF.md`, and the security findings will be in
`AUDIT.md`, which S6 writes. Nothing here repeats them.

**Budget: 150 K ceiling, ~120 K target.** Rounds 9–11 kept to it with
three rules, which still apply:

1. **A row is one cohesive change.** Approval to do several items is
   not approval to do them in one session.
2. **Stop at your row's boundary**, even if budget is left.
3. **If a row overruns, stop at its named split point.** Commit, and
   say exactly where you stopped (the handoff's "Files in progress"
   field).

The order: Kris's walkthrough fixes first, because they are small,
visible and independent. Then the security audit, before any new
feature adds surface. Then the features. Then a QA sweep over the
finished UI. Then the release rows carried from round 11. The round
can pause after any row without leaving the codebase worse than it
found it.

---

## Session map

`§` points into this round's `BRIEF.md`. **[ASK]** rows start only
after Kris's explicit yes.

| # | Session | Executes | Est. | Split point if overrunning |
|---|---|---|---|---|
| **Phase A — Kris's walkthrough** | | | | |
| ☐ S1 | Commit the round-12 docs; theme colours: dark selection, light amber | §1 | ~100 K | After §1.1 (selection) |
| ☐ S2 | "Follow system" applies at once; spin-box arrows in dark | §2 | ~90 K | After §2.1 |
| ☐ S3 | Review's tooltips survive the 2 s poll (render only on change) | §3 | ~110 K | After the Review page; the other pages' audit can follow |
| ☐ S4 | Status columns sort by progress (Dashboard, Downloads, others) | §4 | ~90 K | After the Dashboard |
| ☐ S5 | Support page: new email; "Support the artists" | §5 | ~70 K | None |
| **Phase B — Security and code health** | | | | |
| ☐ S6 | Security re-audit, read-only → `AUDIT.md` | §6 | ~130 K | After the threat model and items 1–6 |
| ☐ S7 | **[ASK]** Security fixes I: `urllib3`, a dependency audit in CI, packaging | §7 | ~90 K | After §7.2 |
| ☐ S8 | **[ASK]** Security fixes II: application findings | §8 | ~130 K | After the critical and high findings |
| ☐ S9 | Code health: the two radon-D functions; the two undiagnosed tests | §9 | ~120 K | After §9.2 |
| **Phase C — Features** | | | | |
| ☐ S10 | Daily sweep I: config, service, `sweep_due`, CLI | §10 | ~120 K | After §10.3 |
| ☐ S11 | Daily sweep II: Settings toggle, scheduler, tray summary | §11 | ~110 K | After §11.2 |
| ☐ S12 | X2: Retry and Cancel on Downloads (live cancel needs Kris's yes) | §12 | ~120 K | After Retry |
| ☐ S13 | X1: Clean up leftover slskd downloads | §13 | ~110 K | After the listing (no delete) |
| ☐ S14 | Automatic app-update check (R11 §40) | §14 | ~90 K | None |
| **Phase D — Fresh-eyes QA** | | | | |
| ☐ S15 | QA sweep over all 78 screens; small fixes, the rest listed | §15 | ~120 K | After the planning-time findings |
| **Phase E — Release (carried)** | | | | |
| ☐ S16 | Release engineering (R11 §39; bundle ID decided) | §16 | ~110 K | After R11 §39.2 |
| ☐ S17 | Release-candidate acceptance (**Kris and Code**) | §17 | ~70 K | — |
| ☐ S18 | Publish v0.1.0 (Kris approves the outward actions); close rounds 11 and 12 | §18 | ~60 K | — |

### Why this order

- **Phase A first.** The fixes are small, Kris can see them at once,
  and each one is independent. S1 goes before S2 because both edit
  `theme.py`'s palette and QSS. S3 goes before S4 because both touch
  table rebuilds and sort keys, and S4's sort keys must survive S3's
  render-on-change.
- **The audit (S6) before any feature.** Features add surface: a
  timer, a cancel endpoint, a delete action. Auditing first means
  S10–S13 are written against the audit's rules, and S6 does not
  audit code that is still moving.
- **S7/S8 are [ASK]** only so that Kris reads `AUDIT.md` first. A fix
  that changes behaviour Kris relies on needs a yes. A pure
  hardening fix doesn't, once the row is approved.
- **S9 before the features** so that the new code does not land next
  to two radon-D functions and two known flakes.
- **S10 before S11:** the service and CLI are testable without Qt;
  the UI then only schedules and reports. **S14 after S11** reuses
  its due-check pattern.
- **S15 after every UI change**, so the sweep sees the finished UI
  once.
- **Phase E last**, acceptance (S17) before publishing (S18), as in
  round 11.

---

## Skills: resolve these at the start of every session

List your available skills and resolve their real names first.

| Rows | Reach for |
|---|---|
| S1, S2, S5, S15 | `frontend-design` (critique screenshots, keep a quality floor) |
| S2–S4, S9–S13 | `tdd` (failing test first); `focused-fix` for S3 |
| S6 | `security-review`, `security-pen-testing`, `dependency-auditor`, `adversarial-reviewer` |
| S7, S8 | `tdd`, `env-secrets-manager`; `adversarial-reviewer` before each close-out |
| S9 | `tech-debt-tracker` (show the radon counts drop) |
| S10, S11 | `observability-designer` (what the sweep logs and reports) |
| S16–S18 | `changelog-generator`, `runbook-generator`, `ship-gate` |
| Any row, optional | `self-eval` before close-out |

If a skill contradicts the brief, follow the skill for **how** and
the brief for **what**, and record the divergence in the handoff.

---

## Session protocol

Unchanged from round 11 (`docs/rounds/round-11/SESSION-PLAN.md` →
"Session protocol" and "The handoff contract"). In short:

**Starting.** Read, in this order and nothing else:
1. `docs/HANDOFF.md`
2. this file, **your row only**
3. `BRIEF.md` §0 (and R11 §0, which it points at), plus your row's §
4. `CLAUDE.md`, plus `src/seeker/ui/CLAUDE.md` for any UI row

**Working.** One commit per numbered item, a failing test first,
files read by range, real data read-only.

**Ending.** Append a HISTORY entry (`docs/history/181-210.md`, from
§193) and its index line. Commit and quote the three numbers. Tick
your box here. Rewrite `docs/HANDOFF.md` to the nine-field contract.
Push, and record the CI run id and result.

**S1 only:** the round's first commit is this file, `BRIEF.md`, the
round-11 plan's carried-rows note, the docs index line, CLAUDE.md's
roadmap line and the rewritten `docs/HANDOFF.md`. Planning left them
uncommitted.

---

## Waiting on Kris

**Answered at planning (2026-10-08):** the daily sweep is opt-in and
defaults off; the status order is closest to done first; the bundle ID
is `io.github.kristiyanddimitrov.seeker`; X1 and X2 are both in. See
BRIEF §0.11.

**Approval gates:**
- [ ] **S6 → S7/S8:** read `AUDIT.md`; say yes to the fix rows and
      to any finding that changes behaviour.
- [ ] **S5:** veto or edit the "Support the artists" wording, if you
      want to, after seeing it on screen.
- [ ] **S12:** the first live slskd Cancel, with you at the keyboard.
- [ ] **S13:** the first real leftover-file cleanup is yours to click.
- [ ] **S18:** the exact `git tag` and `gh release create` commands and
      the release notes.

**Real-desktop checks:** R11's list (its session plan → "Waiting on
Kris"), all still open, plus BRIEF §17's additions. S17 consolidates
them into one checklist.

---

## Exit criteria

Measured in S18's close-out. Each one is a number or a yes/no.

- Each of Kris's nine walkthrough items is fixed with a test, or for
  the sweep, built.
- Every `AUDIT.md` finding is fixed or accepted with a written
  reason. `pip-audit` runs in CI and reports 0.
- CI is green on the release commit, and branch coverage is at or
  above the floor.
- `mypy --strict` is clean and `ruff check` reports 0.
- `uvx radon cc -n D -s src/seeker` reports nothing.
- R11's remaining exit criteria (its plan → "Exit criteria") hold:
  v0.1.0 is published with its DMG and SHA-256, and "Check for
  updates…" returns up to date.
