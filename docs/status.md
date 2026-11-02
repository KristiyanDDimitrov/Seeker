# Seeker — status

Accepted risks, open issues and the roadmap, moved here from the
root `CLAUDE.md` so it stays short. Present tense only; what
happened is in [`history/`](history/README.md).

## Accepted risks

Each accepted in round 12's audit, with Kris's decision and the full
reason under its finding in `docs/phase-01/round-12/AUDIT.md`
([§200](history/181-210.md#200)). Revisit any of them if Seeker
stops being a single-user desktop app.

- **Peer files reach native decoders unsandboxed** (S-03): libsndfile
  for analysis, ffmpeg for fingerprints. No content-against-extension
  check, by decision. `docs/packaging.md` → "Native libraries" tracks
  their open advisories; a fix is taken at the next release.
- **No size cap on slskd, Spotify or GitHub JSON bodies** (S-09);
  only album art streams with one.
- **slskd's secrets sit in its container's environment** (S-10):
  reading them needs the Docker socket, and `config.json` holds the
  same values at 0600.
- **`docker`, `ffmpeg`, `open` and libchromaprint resolve from
  Homebrew prefixes** (S-11): planting one needs same-user access.

## Open issues

Genuinely open only, checked against every CI run on record (187, to
2026-10-08) in [§192](history/181-210.md#192).

- **Item 63, a locked-file retry storm** against production slskd
  (300+ retries of one row in ~18 min), cause unknown; locked rows, a
  zero-locked baseline and heavy load are ruled out. Lead: one `500`
  on `/api/v0/transfers/downloads/batches` with the storm's error
  text. The backoff bounds it. [§63](history/047-071.md#63)
- **Item 70, a stress-test hang at production scale (~3,100
  files)**, cause unknown: 3/3 at scale after sync/scan/match, on
  Duplicates' Compute Fingerprints; 0/2 isolated; `faulthandler`
  silent (GIL starvation?). Not item 105's pytest stall.
  Lead (UNVERIFIED): until S22 the 2 s Dashboard and 20 s history
  polls read all ~32 MB of fingerprints and the Dashboard rebuilt
  every row each tick; S41's stress run tests it.
  [§70](history/047-071.md#70), [§165](history/151-180.md#165),
  [§166](history/151-180.md#166)
- **Item 125, a quit hang: every task on `MainWindow.thread_pool`
  now stops within the bound or is listed as short** (the sweep
  above); what is left is outside that pool or past a timeout. A
  slskd bring-up is waited for by design, never killed mid-recreate
  (up to Compose's 120 s; the quit confirmation says so,
  `Application.is_starting_slskd()`, and the wizard asks the same).
  The wizard alone keeps its own `QThreadPool`, outside the bounded
  wait, whose destructor holds the exit (measured); a quit cancels
  its login wait (`stop_for_quit()`). A hung (not down) slskd holds a quit up to a REST
  call's 10 s timeout (UNVERIFIED that it ever hangs). The window
  stays on screen during the wait: on Cocoa a `hide()`, even with one
  `processEvents()`, shows only once the loop keeps turning
  (observed). [§125](history/121-150.md#125),
  [§226](history/211-240.md#226), [§231](history/211-240.md#231),
  [§232](history/211-240.md#232), [§233](history/211-240.md#233),
  [§240](history/211-240.md#240), [§241](history/241-270.md#241)
- **The real DB still holds three nested locations** (`Music`⊂`X9
  Pro`, `Test`⊂`X9 Pro`, `Test`⊂`Music`; ~3,450 files double-indexed).
  With the X9 Pro mounted, Kris runs Settings → Library → Fix…,
  keeping `Music` (rehearsed: 43 matches kept, 0 lost).
  [§172](history/151-180.md#172)

## Roadmap

Forward-looking only; everything shipped is in `docs/history/`.

- **v0.1.0 is released** (2026-10-14, [§245](history/241-270.md#245));
  phase 01 (rounds 01–12, `docs/phase-01/`) is closed. Kris's waived
  acceptance checks stay open as post-release checks
  (`docs/phase-01/round-12/ACCEPTANCE.md`); every document:
  `docs/README.md`.
- **v0.1.1 is released** (2026-10-26, [§247](history/241-270.md#247)):
  a security release (certifi, setuptools), nothing else.
- **Phase 02 is planned (2026-10-17): Intel Macs, then Windows**
  ([docs/phase-02/README.md](phase-02/README.md), findings
  `PF-NN` in its `AUDIT.md`). Round 13 (Intel, v0.2.0) is next; round
  14 makes Windows ready from the Mac and CI; round 15 (provisional)
  tests on real Windows hardware and releases v0.3.0.
- **Windows and Linux packaging: written, never run on real
  hardware** until rounds 14–15; Linux stays out of scope, and no
  Linux installer format is scoped
  ([docs/packaging.md](packaging.md)).
- **SoundCloud: deferred.** Its API needs a paid Artist Pro account
  and a confidential `client_secret`, which a `.dmg` cannot hold. If
  picked up: bring-your-own credentials, a Dashboard source toggle.
