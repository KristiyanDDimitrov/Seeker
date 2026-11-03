# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 2 K tokens: a baton, not
a log. The log is `docs/history/` (short tier: `docs/history/README.md`,
grep it, never read it whole). **The plan is
`docs/phase-02/round-13/SESSION-PLAN.md`**, with status in `tasks.json`
beside it. Every document: `docs/README.md`.

---

## 1. Current state

- **Released: v0.1.1** (2026-10-26, §247).
- **HEAD is the handoff commit on `826608b`, pushed.** Untracked: Kris's
  PDF only. (`ci.yml` cancels an in-progress run on a new push.)
  No worktrees; local `r13/*` branches deleted. `origin` still has
  `r13/S7` and `r13/S7c` (merged; the auto-mode classifier refused the
  delete: `git push origin --delete r13/S7 r13/S7c` is Kris's).
- **The three numbers (Cocoa):** pytest `2572 passed, 1 skipped`; mypy
  `--strict src/` clean, 149 files; ruff 0.
- **CI:** green on `235f795` (`41546314860`: `check` 2542 passed, 29
  skipped, 94.73 %; `check-intel` 2540 passed, 31 skipped, 25 m; `audit`).
  `build.yml` green on `main`, push and dispatch (`41547216451`). **Run
  `41550884285` on `826608b`: `check` green (2544 passed, 29 skipped);
  `check-intel` FAILED, `1 failed, 2541 passed, 31 skipped`:
  `tests/pages/test_sharing_page.py::test_quit_stops_the_wait_for_a_new_share`
  (a 2 s `qtbot.waitUntil` for a worker's finished handler, line 638).**
  S4b's error did not recur, but this is a second timing flake on the
  Intel runner (2 failures in 5 runs, different tests): row S4c.

## 2. Where we are

Round 13: waves 0 to 3 done; wave 4: S7, S7c, S8, S8b, S4b done
(§262 to §264). **S9's Code half is half done:** the Apple silicon
candidate is built from `826608b` (untagged) and RELEASING step 3 passed
(ad-hoc signed, `spctl` rejects, versions 0.1.1, thin arm64, smoke test
exit 0, cold 3.49 s, warm 0.035 s); `dist/Seeker.dmg` SHA-256
`df191247696631decfb90a401d6ba3fd8f2102316fc94e59e537583608fa7c0e`.
The Help check (a GUI launch reads Kris's real data) is Kris's.

## 3. Next steps

1. **Blocker:** the Intel candidate needs a local libchromaprint. The
   classifier refused me `packaging/build_chromaprint.sh` (it downloads
   and compiles a tarball). Kris runs, once (`.chromaprint/` is
   gitignored and persists): `! packaging/build_chromaprint.sh "$PWD/.chromaprint"`.
2. Then (RELEASING steps 2-3): `SEEKER_CHROMAPRINT_DIR="$PWD/.chromaprint/lib"
   .venv-x86_64/bin/python packaging/build_dmg.py`, step 3 with
   `ARCH=x86_64` (the build replaces `dist/Seeker.app`; the arm64 app
   was checked first), then both checksums.
3. Write `docs/phase-02/round-13/ACCEPTANCE.md`: both SHA-256s, then
   Kris's checklist (BRIEF §9, already corrected). Commit, push; Kris's
   gate; then S10 (solo, `[ASK]`).
4. **S4c** (a worker, before S10: the blocking Intel job must be
   dependable): the Intel runner's 2 s `waitUntil`s on worker handlers
   flake (§264 and run `41550884285`). Sweep the suite's short worker
   waits for the same shape, fix the cause (`settle_workers`-style), not
   by raising a timeout blindly. A green re-run proves little: it is a
   race; the push that follows this handoff gives a 6th sample.

## 4. Key context

- A fresh worker on an existing branch: `git checkout -B r13/S<n> main`.
  Workers' suites run offscreen; the lead's Cocoa check runs alone.
- Never `cmd | tail && git commit`: a pipe hides the gate's exit code
  (I committed past a ruff error once and amended it).
- `dist/` held v0.1.1's images; a copy of `Seeker.dmg` and its checksum
  is in the previous session's scratchpad (also on the release page).
- S10: un-gate the README (`From 0.2.0`, `Download (from 0.2.0)`,
  `Until 0.2.0 is published…`), resolve nothing else pending
  (`grep -rn S7-PENDING docs` is empty).

## 5. Decisions made

- Kris (2026-11-02): the Intel bundle ships libchromaprint (`f19ad82`);
  arm64 stays on Homebrew's.
- The lead, for Kris's review: Homebrew builds no Intel bottles, so
  libchromaprint is built from a pinned source (`build_chromaprint.sh`,
  one revert undoes it); `SEEKER_CHROMAPRINT_DIR` and `.chromaprint/`
  (not `build/`, which `--clean` empties); the ffmpeg-free Intel runner
  skips 2 more tests (§262).

## 6. Blockers

The Intel libchromaprint build (3.1).

## 7. Files in progress

None. `dist/` and `.chromaprint/` hold gitignored build outputs.

## 8. Waiting on Kris

- Run the libchromaprint command (3.1); the Help check and the rest of
  BRIEF §9 later.
- README's licence paragraph names libchromaprint's upstream source and
  an "LGPL 2.1" label (the vendored text says "2.1", Homebrew
  "-or-later"): confirm the wording.
- Before the final Intel release: an asset-aware update check, or a
  notice in the release notes (RELEASING §7).
- FYI: six Settings tests POSTed a login to the real slskd on
  127.0.0.1:5030 until S4b (§264); fixed, effect on slskd unknown.
- #1, #5, #7, #8 are still open though their changes are on `main`.

## 9. Open questions

- Without ffmpeg a non-audio file reads `error`, with it
  `decode_unsupported` (pinned as documented, §262): which is right?
- PyInstaller's Intel-only libomp SDK warning (§262); where numba's cache
  lives; Module map lacks `ui/row_actions.py`, `soulseek/sweep.py`,
  `soulseek/leftovers.py` (older than round 13).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. **Ending:** the plan's "Session protocol".
