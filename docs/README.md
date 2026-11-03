# Seeker documentation

Every document in the repository, then where to start.

## Living documents

- [`../README.md`](../README.md) — what Seeker is, features, install,
  quick start, a short architecture summary.
- [`architecture.md`](architecture.md) — the layers and the rule
  between them, the tech stack, the one canonical module map, the data
  flow, the download state machine, the threading model, where data
  lives.
- [`cli.md`](cli.md) — every `seeker` command, configuring without the
  wizard, running slskd by hand, which screen covers each command, and
  `seeker-ui --smoke-test`.
- [`packaging.md`](packaging.md) — building the `.app` and `.dmg` for
  Apple silicon and Intel Macs, the smoke test, the Windows installer;
  signing; what was verified on which hardware (Windows and Linux:
  written, never verified on real hardware).
- [`../CHANGELOG.md`](../CHANGELOG.md) — what each release added or
  changed, in Keep a Changelog format.
- [`../RELEASING.md`](../RELEASING.md) — cutting a release: build,
  verify, tag, publish, check for updates, roll back.
- [`../SECURITY.md`](../SECURITY.md) — reporting a vulnerability.
- [`../CLAUDE.md`](../CLAUDE.md) — architecture, conventions, and an
  index of the topic `CLAUDE.md` files beside the code that hold the
  standing facts and gotchas. Present tense only.
- [`status.md`](status.md) — accepted risks, open issues, roadmap.
- [`HANDOFF.md`](HANDOFF.md) — the baton between Claude Code sessions:
  state, next row, blockers. Overwritten every session.
- [`history/`](history/README.md) — the full investigation log,
  numbered `§N`, split by range; its README indexes every entry.
  `grep -n` for the section, never read a whole file.
  `HISTORY.md` is a stub pointing there.
- [`screenshots/`](screenshots/) — the README's images, written by
  `uv run python tools/screenshots.py --readme`.
- [`design/visual-direction.md`](design/visual-direction.md) — the
  visual refresh's two rendered directions ("Booth", "Harmonic"):
  tokens, WCAG contrast numbers, icon set, recommendation, and Kris's
  decision, which S31–S36 build on.
- [`../tools/screenshots.py`](../tools/screenshots.py) — renders every
  screen and wizard step, both themes, at 1280×820 and 960×640, over
  one invented dataset: `uv run python tools/screenshots.py` (into the
  gitignored `tools/.screens/`; `--page NAME` and `--theme` narrow it).
  Review a UI change against these before committing it.
- [`../tools/window_checks.py`](../tools/window_checks.py) — measures
  the three window-reopen paths on a real Mac against a running
  packaged app, for release acceptance.

## Shipped with the app

- [`../packaging/Read Me First.txt`](../packaging/Read%20Me%20First.txt)
  — on the `.dmg` volume: opening an app that isn't notarized.
- [`../packaging/fonts/OFL.txt`](../packaging/fonts/OFL.txt) — the
  licence of the bundled Barlow Semi Condensed.
- [`../packaging/icons/lucide/SOURCE.txt`](../packaging/icons/lucide/SOURCE.txt)
  — where the vendored Lucide icons come from.

## Phases

Development is grouped into phases of rounds. Each round's brief is
the task text a session executed; a session plan is its budgeted
row-by-row map.

- [`phase-01/`](phase-01/README.md) — rounds 01–12, from the first
  build to the v0.1.0 release (macOS on Apple silicon). Closed
  2026-10-14; its README lists every round.
- [`phase-02/`](phase-02/README.md) — rounds 13–15: Intel Macs
  (v0.2.0), then Windows (v0.3.0). Planned 2026-10-17; its
  [platform audit](phase-02/AUDIT.md) holds the findings (`PF-NN`).
  - [`autodev`](phase-02/autodev/SESSION-PLAN.md) — the plan the rest
    of the phase runs from (2026-11-03), status in its `tasks.json`.
  - [`round-13`](phase-02/round-13/BRIEF.md) — Intel Macs, released
    as v0.2.0; [session plan](phase-02/round-13/SESSION-PLAN.md).
  - [`round-14`](phase-02/round-14/BRIEF.md) — Windows readiness from
    the Mac and CI; [session plan](phase-02/round-14/SESSION-PLAN.md).
  - [`round-15`](phase-02/round-15/BRIEF.md) — Windows on real
    hardware, released as v0.3.0 (provisional);
    [session plan](phase-02/round-15/SESSION-PLAN.md).

[`rounds/README.md`](rounds/README.md) resolves the old
`docs/rounds/…` paths that HISTORY entries and commits still name.

## Reading orders

- **A Claude Code session:** `HANDOFF.md` → your row in the current
  round's `SESSION-PLAN.md` → that brief's §0 plus your row's § (and,
  in phase 02, each `AUDIT.md` finding it names) → `../CLAUDE.md`.
  Nothing else until the task needs it.
- **A new contributor:** `../README.md` → `architecture.md` →
  `../CLAUDE.md` (Conventions, then its topic files) → the current phase's
  [`AUDIT.md`](phase-02/AUDIT.md) for known weak spots → `history/`
  entries as `CLAUDE.md` links them.
- **A portfolio reviewer:** `../README.md` → `architecture.md` →
  `../CLAUDE.md` → the round-11
  [`AUDIT.md`](phase-01/round-11/AUDIT.md) (an honest whole-repo
  audit) → any one round's brief next to its `history/` entries, to
  see diagnosis turn into a fix → [`phase-02/`](phase-02/README.md),
  to see a platform port planned from evidence.
