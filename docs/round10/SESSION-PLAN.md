# Round 10 — session plan

**Purpose (unchanged): keep each Claude Code session inside a
predictable token budget.** This file is the index. The task text is in
`docs/BRIEF-2026-09-23-round10.md`; nothing here repeats it.

**Budget: 150 K ceiling, ~120 K target.** Round 9 held this across all
ten rows by keeping to one cohesive change per row. The same two rules
apply:

1. **A row is one cohesive change.** Approving several items is
   approval to *do* them, not to do them in one session.
2. **Stop at your row's boundary even with budget left.**

If a row overruns, stop at its named split point, commit, and say
exactly where you stopped.

---

## Session map

| # | Session | Executes | Est. | Split point if overrunning |
|---|---|---|---|---|
| ☑ S1 | Review: focus traversal, visible errors, worker logging, diagnose the stuck candidate | §1.1–§1.4 | ~120 K | After §1.2 (§1.1 + §1.2 alone fix what Kris sees) |
| ☐ S2 | Review: make Confirm work for the cause S1 found | §2 | ~110 K | After the slskd endpoint is verified live and recorded |
| ☐ S3 | Stress test: repoint stale handles + default-run guard | §3 | ~90 K | None; small row. Do not pull S4 in |
| ☐ S4 | CI: the worker-thread-counter test race, repro + audit | §4.1–§4.3 | ~130 K | After §4.2 (the two known tests fixed and pushed) |
| ☐ S5 | Reopen after a fullscreen close: fill the screen, windowed | §5 | ~130 K | After the Dock-reopen path works; relaunch persistence can stand alone |
| ☐ S6 | Fullscreen-close test pair: find the real caller, isolate | §6 | ~100 K | After the caller is identified and written down |
| ☐ S7 | HISTORY backfill, round 9 S7–S10 | §7 | ~80 K | After two of the four entries |

**Why this order.**

- **S1 first.** It is what Kris hit, and §1.2 also removes the
  Review-page half of the CI race (it rewrites that test to wait on the
  notice). §1.4 has to come before S2, because S2's branch depends on
  its answer.
- **S3 before S4 and S5.** It is cheap, and it gives Kris a working
  stress test early. §5 changes the close/reopen lifecycle that the
  stress test exercises.
- **S4 before S5.** A red CI makes every later "is this green?"
  ambiguous. Round 9 carried a red CI through four sessions; do not
  repeat that.
- **S5 before S6.** S5 rewrites the geometry half of the flaky pair.
  S6 diagnoses whatever is left against the new code, not the old.
- **S7 last.** It is docs only. Every other row writes its own HISTORY
  entry this round (brief §0.6), so S7 is only round 9's debt.

---

## Skills: resolve these at the start of every session

List your available skills and resolve the real names before starting.

| Row | Reach for |
|---|---|
| S1 (§1.4), S4, S6 | `engineering-advanced-skills`: races, test-order leaks, root-cause work. |
| S2, S5 | Engineering first (a live API shape; Qt window-state semantics). The notice copy in S2 is small: write it in `help_text.py` in the existing tone, without a skill. Round 9 S10 found `product-skills` routes small copy decisions into a heavyweight discovery framework. |
| S3 | `improve-codebase-architecture`, lightly: the `_resolve_handles` seam. |

If a skill contradicts the brief, follow the skill for **how** and the
brief for **what**, and record the divergence in the handoff.

---

## Session protocol (unchanged from round 9, plus one step)

**Starting.** Read, in this order and nothing else:

1. `docs/HANDOFF.md`
2. This file, **your row only**
3. The §sections your row points at in `docs/BRIEF-2026-09-23-round10.md`,
   plus §0
4. `CLAUDE.md`

**Working.** One commit per numbered item. Failing test first (brief
§0.4). Read files by range, never whole.

**Stopping.** At your row's boundary or its named split point.

**Ending.** Append your HISTORY entry (new, brief §0.6). Commit, quote
the three numbers, tick your box here, and rewrite `docs/HANDOFF.md`.
If you pushed, record the CI run id and result.

**S1 only:** the first commit of the round is these three docs files
(`docs/BRIEF-2026-09-23-round10.md`, `docs/round10/SESSION-PLAN.md`,
the updated `docs/HANDOFF.md`). They were written by the design chat
and are not yet committed.

### What a handoff must contain

1. The commit it starts from, and that the tree is clean.
2. The three numbers, plus the CI run id and result.
3. Which row is next.
4. **Anything discovered that changes a later row.** S1 → S2 is the
   obvious one: §1.4's root cause decides S2's branch. Write it as a
   root-cause statement with the raw evidence.

---

## Waiting on Kris

**Real-desktop checks Code cannot do:**

- [ ] **After S1:** if §1.4's read-only checks do not settle it, click
      Confirm once on the stuck Review candidate. The notice now shows
      the real error, and `~/Library/Logs/Seeker/seeker.log` gets the
      traceback.
- [ ] **After S3:** run the stress test,
      `SEEKER_RUN_STRESS_TEST=1 uv run pytest tests/test_stress_e2e.py`,
      with the X9 Pro mounted and Spotify and slskd up. This is still
      the round-9 §1.5b check.
- [ ] **After S5:** fullscreen → close → Dock icon: fills the screen,
      windowed. Resize → close → Dock icon: same size. Fullscreen →
      close → quit from menu bar → relaunch: fills the screen, windowed.
- [ ] Carried from round 9: the Review splitter (S8) and the Library
      header and picker (S10) on a real display, both themes; the LAN
      port check from a second device (`http://<mac-lan-ip>:5030` must
      not answer).

**Approval gates, still open from round 9 and not scheduled here:**
§4.2b (v0.1.0 release / automatic update check), §8.1–§8.5.
