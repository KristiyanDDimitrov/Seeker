# Round 9 — session plan

**Purpose, unchanged from round 8: keep each Claude Code session inside a
predictable token budget.** This file is the index. The task text lives in
`docs/BRIEF-2026-09-09-round9.md`; nothing is restated here.

---

## The budget, with round 8's evidence

Round 8 targeted ~150 K per session. Measured outcome across 23 sessions:
most rows landed **90–120 K**, and the one row that blew past it (S16, at
~300 K) did so for one identifiable reason — five approved items were
bundled into a single session, against this file's own one-item pacing.

So **150 K stays the ceiling, and ~120 K is the target.** The number was
never the problem; bundling was. Two rules follow, and they matter more
than the number:

1. **A row is one cohesive change.** If Kris approves several items at
   once, that is approval to *do* them, not to do them in one session.
2. **Stop at your row's boundary even with budget left.** Starting the
   next row "since it's small" is exactly how S16 happened.

Rows below are estimates. If a row overruns, stop at its named split
point, commit, and say precisely where you stopped.

---

## Session map

| # | Session | Executes | Est. | Split point if overrunning |
|---|---|---|---|---|
| ☒ S1 | CI part 1 — workflow + callback server | §1.1, §1.2 | ~110 K | After §1.1 lands and is pushed |
| ☒ S2 | CI part 2 — the two Qt flakes + the skip answer | §1.3, §1.4, §1.5a | ~130 K | After §1.3; §1.4 is time-boxed by design |
| ☐ S3 | Table sorting correctness | §5.1, §5.2, §5.3 | ~120 K | After §5.2; the audit can stand alone |
| ☐ S4 | Quit semantics + confirmation dialog | §2.1, §2.2 | ~110 K | After §2.1 — the finding alone is worth a commit |
| ☐ S5 | The quit hang | §2.3 | ~120 K | Reproduction attempt is the box; report either way |
| ☐ S6 | Window geometry + wizard support page + update-check honesty | §3.1, §4.1, §4.2a | ~130 K | After §3.1 |
| ☐ S7 | Start at login | §3.2 | ~120 K | After the mechanism decision is written down |
| ☐ S8 | Review page — resizable panes | §6 | ~110 K | After the splitter works, before persistence |
| ☐ S9 | Library — lift the selection seam (pure refactor) | §7.1 | ~110 K | Hard stop: no visible change in this row |
| ☐ S10 | Library — context header + playlist picker | §7.2 | ~110 K | After the header; the picker can stand alone |

**Why this order.**

- **S1–S2 first, non-negotiable.** A red CI makes every later session's
  "is this green?" ambiguous. Five known failures is five places a real
  regression can hide.
- **S3 next** because it is self-contained, high user-visible value, and
  touches one shared helper — a clean win between two harder blocks.
- **S4–S5** before the window-lifecycle work: §2.3 and §3.1 both touch
  the quit path, and diagnosing a hang is easier before that path has
  been edited for another reason.
- **S9 before S10, always.** S9 is a refactor with no behaviour change;
  S10 is behaviour built on it. Merging them loses the property that
  makes the refactor safe.
- **§8 is not in the map.** Every §8 item is [ASK KRIS] and unscheduled.

---

## Skills — resolve these at the start of every session

Kris installed three bundles. **List your available skills and resolve
the real names before starting** — the names below are how Kris refers
to them, not necessarily the slugs.

| Row | Reach for |
|---|---|
| S1, S2, S5 | `engineering-advanced-skills` — races, flakes, a real hang. Root-cause work. |
| S3, S9 | `improve-codebase-architecture` — the shared column-layout seam, lifting selection state out of a page. |
| S4, S6, S7, S8, S10 | `product-skills` — dialog copy, settings placement, splitter proportions, the Library context header and empty state. |

Where a row spans both kinds (S4 is a real investigation *and* a piece
of copy; S7 is a platform API *and* a settings surface), use both. If a
skill's guidance contradicts the brief, follow the skill for **how** and
the brief for **what**, and record the divergence in the handoff.

---

## Session protocol

Identical to round 8. Four steps.

**Starting.** Read, in this order and nothing else:

1. `docs/HANDOFF.md`
2. This file — **your row only**
3. The §sections your row points at in `docs/BRIEF-2026-09-09-round9.md`
4. `CLAUDE.md` (~33 KB)

That is the whole orientation budget: roughly 15 K tokens.

**Working.** One commit per numbered item. A refactor commit contains no
behaviour change; a behaviour commit contains no refactor. Read files by
range, never whole.

**Stopping.** At your row's boundary, or its named split point.

**Ending.** Commit; quote the three numbers; tick your box here; rewrite
`docs/HANDOFF.md`.

**New this round:** when your work is pushed, **record the CI run id and
its result in the handoff**, pass or fail. Round 8 lost time twice
re-deriving CI state a previous session already had.

### What a handoff must contain

The next session is a stranger. Four things:

1. The commit it starts from, and that the tree is clean.
2. The three numbers, plus the CI run id and result.
3. Which row is next.
4. **Anything discovered that changes a later row.** This is the part
   that gets dropped and matters most. Write it into "Open questions" or
   the next session pays full price to rediscover it.

Do not summarise what you did — the commits and `HISTORY.md` hold that.

---

## Waiting on Kris

Carried forward, plus what this round adds. None blocks S1.

**Approval gates — no work starts without a yes:**

- [ ] **§4.2b** — cut a `v0.1.0` GitHub release, and/or make the update
      check automatic (opt-in, daily, default off). Until a release
      exists, "Check for updates…" cannot succeed for anyone.
- [ ] **§3.2** — confirm `SMAppService` over a `LaunchAgent` plist for
      start-at-login, which adds `pyobjc-framework-ServiceManagement` as
      a dependency.
- [ ] **§1.2 fallback only** — if the callback-server fix does not make
      CI green, gating those three tests behind a
      `requires_loopback_server` marker trades away real coverage of the
      Spotify login path. Not without a yes.
- [ ] **§8.1–§8.5** — all unscheduled, all need a yes. §8.2 (splitting
      `HISTORY.md`) and §8.3 (nested library locations double-indexing
      ~3,450 files) are the two worth reading first.

**Real-desktop checks Code cannot do:**

- [ ] **§1.5b** — run the stress test once this round:
      `SEEKER_RUN_STRESS_TEST=1 uv run pytest tests/test_stress_e2e.py`,
      X9 Pro mounted, Spotify and slskd up. §2 and §3 change exactly the
      worker/timer/connection lifecycle code its docstring says to re-run
      it after.
- [ ] **§3.1** — after the geometry fix lands, confirm on a real Mac that
      resize → close to menu bar → quit → reopen restores the size.
      Offscreen Qt is what let this ship broken.
- [ ] **§2.3** — if the hang recurs before S5 runs, capture it:
      `sample Seeker 10 -f /tmp/seeker-hang.txt` while it is stuck. That
      one file is worth more than a session of guessing.
- [ ] Carried from round 8, still open: click through the Library page
      and the Dashboard status filter on a real display; the Review
      page's Runner-up column; the Dock-icon reopen after a fullscreen
      close; and the LAN port check from a second device
      (`http://<mac-lan-ip>:5030` must not answer).

**Answered this round, no action needed:** the repo is public
(confirmed 2026-09-09) — delete that open question wherever it appears.
