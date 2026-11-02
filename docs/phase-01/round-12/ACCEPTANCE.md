# Round 12 — release-candidate acceptance (S17)

The single checklist for S17: BRIEF §17, R11 §41, and every live check
carried in the handoffs. Tick a box and write what you saw beside it;
a failure becomes a fix row before S18 (never shipped around).

## The candidate

The second candidate (S17g, HISTORY §242), built from the fixed tree
after S17a–S17o. The first, `e10aa87` (SHA-256 `b373f7ae…`), is
superseded: the 2026-10-12 run's six failures are fixed in this one.

| | |
|---|---|
| Commit | `6f49319` (untagged by decision, 2026-10-11; S18 tags and rebuilds) |
| Disk image | `dist/Seeker.dmg`, 111,784,988 bytes |
| SHA-256 | `b203e98dd9764b3d27ddbb0a5707148fb555ed28bbe1db4e2a215871febeda07` |
| Help → Build should read | `6f49319 — built` and 2026-10-14, about 13:52 local (10:52 UTC) |

## Code checked (2026-10-14, without launching the app)

- [x] RELEASING.md steps 1 and 3 on `6f49319`: CI green on it (run
      `38549671669`); `2417 passed, 1 skipped`, `mypy --strict` clean,
      `ruff` 0; `Identifier=io.github.kristiyanddimitrov.seeker`,
      `Signature=adhoc`; `codesign --verify --deep --strict` ok; `spctl`
      rejects (expected); version `0.1.0` twice; build identity
      `6f49319`, not `-dirty`; tree clean after the build; `shasum -c`
      OK (beside the image).
- [x] The bundle carries `libqsvg`/`libqsvgicon`, the Barlow fonts and
      42 licence folders.

## Kris: the six failures first (2026-10-12's run, on this candidate)

They failed in the test account; re-run them there, or on your own
account with the candidate installed into `/Applications` from the
DMG (no other copy exists; its first launch runs the
`tracks.last_searched_at` migration). Each line names the fix row and
its HISTORY entry.

- [ ] **S17a:** "Scan library", and while it runs the Dashboard's next
      step shows no "missing" count; the real count once the scan and
      match finish (§223).
- [ ] **S17b:** Find duplicates over the ~3,611 fingerprints runs past
      3589 to the end, reporting its last stage (§224: 582 s → 4.7 s
      measured on a copy).
- [ ] **S17c (and S17h–S17k):** quit while Compute fingerprints runs,
      and while Find duplicates runs: the app exits within seconds, no
      beach ball (§226, §233). Veto, or let stand, "quitting stops a
      running scan, fingerprint run or duplicate search; what finished
      stays".
- [ ] **S17d, S17k:** fullscreen and back on Dashboard, Library and
      Duplicates: no slow, jerky resize, no overlapping tables (§225,
      §234).
- [ ] **S17e:** in fullscreen, open the tray menu: it stays open. If it
      closes, §237 says how to bring the trace back.
- [ ] **S17f:** Review → "Confirm all" in each section, with its
      question (§235, §236). Veto, or let stand, one button per
      section.

Then the rest below, as before.

## Code checked on the first candidate (`e10aa87`, 2026-10-11)

- [x] RELEASING.md step 3: `Identifier=io.github.kristiyanddimitrov.seeker`,
      `Signature=adhoc`; `codesign --verify --deep --strict` ok; `spctl`
      rejects (expected, not notarized); version `0.1.0` twice; tree
      clean after the build; `shasum -c` OK.
- [x] The bundle carries `libqsvg`/`libqsvgicon`, the Barlow fonts and
      42 licence folders (presence only; rendering is below).
- [x] The per-user Compose copy passes `docker compose config` with
      every variable set, and refuses without `SLSKD_DATA_DIR` or
      `SLSKD_SHARE_PATH`. It predates the digest pin (seeded
      2026-09-29, never re-seeded by design), but the running image is
      the pinned digest `ecd4026d…`.
- [x] The live container (created 2026-10-11 15:30 UTC, the app-data
      default as `/app`, the empty share read-only) publishes 5030/5031
      on `127.0.0.1` only and 50300 on every interface.

## Kris, in a fresh macOS user account

Docker Desktop in the other account may hold ports 5030/5031/50300
(UNVERIFIED); quit it there first if the bring-up fails on a port.

- [ ] Download `Seeker.dmg` in a browser (so it is quarantined), check
      it with `shasum -a 256 -c`, open it. Walk Gatekeeper's Open
      Anyway flow; note which `Read Me First.txt` steps are true on
      macOS 26.
- [ ] The wizard end to end: Spotify, the library, SoulSeek with Docker
      (the portable template's live test). Is the share checkbox
      better ticked by default?
- [ ] Sync, scan, a real download, tag, rename.

## Kris, on your own account

Install the candidate into `/Applications` from the DMG, unless the
six failures above already did.

**The app**
- [ ] Help → Build reads the line above.
- [ ] Settings → General → "Start Seeker at login" on again (the bundle
      ID changed from `com.seeker.app`); log out and in; then with
      "start hidden".
- [ ] Settings → General → Updates on; relaunch. No tray notice is
      expected while no release exists.
- [ ] Theme → Follow system, from Light and from Dark, while macOS
      shows the other scheme: it changes at once.
- [ ] A Review tooltip held for 10 s or more stays.
- [ ] The daily sweep on (Settings), then a day's wait: one tray
      summary, and `last_sweep_at` set in `config.json`. (Code checked:
      no option points the app at a scratch config.)
- [ ] `uv run --no-project tools/window_checks.py /Applications/Seeker.app`
      with Seeker open: three paths, PASS or FAIL each (it asks for
      the clicks it cannot make). Then one real Dock-icon click after a
      close.
- [ ] Settings, Review's splitter and Library's header on the real
      display, both themes; icons (SVG) and Barlow in the packaged app;
      Support's links; keyboard focus and VoiceOver.

**slskd and the library**
- [ ] Downloads: the first live Retry and Cancel; then "Clean up
      leftover files…", the first real cleanup.
- [ ] Sharing: a real upload (sharing is now opt-in).
- [ ] From a second device, `http://<mac-lan-ip>:5030` does not
      answer.
- [ ] With the X9 Pro mounted: Settings → Library → Fix…, keeping
      `Music`; compare with HISTORY §172's rehearsal (43 matches kept,
      0 lost).
- [ ] A Scan re-matches the two Denzel Curry tracks left in limbo.
- [ ] `SEEKER_RUN_STRESS_TEST=1 uv run pytest tests/test_stress_e2e.py`
      with the X9 Pro mounted and Spotify and slskd up. It mutates the
      real database; your call when.

## Vetoes (silence keeps the current wording)

- Support: "Support the artists" (S5).
- The wordmark's brows over "ee" (`9ff777b`).
- Library's header, "2 of its 8 tracks are in your library" (S15).
- "Available"/"Not found", and the faint ring for an unplugged drive.
- Review's tooltip and Runner-up text ("scored 64.0, from peer").
- S8's visible change to peer filenames (control and bidi characters
  removed at placement).

## Results

Record failures here with what you saw; each becomes a fix row.

**2026-10-12, Kris, the test account** (the `dist/` build of
2026-10-12 12:10, whose SHA-256 `3ef4365e…` is not the candidate's
`b373f7ae…` above, so the tested build is a rebuild). Six failures,
fix rows S17a–S17f (BRIEF §17a–§17f):

1. **S17a:** after "Scan library", the next step showed every track
   as missing until the scan finished, then the real count.
2. **S17f** (a request, not a failure): Review needs "Confirm all"
   for a section, with a confirmation.
3. **S17d:** fullscreen and back is slow and jerky; tables resize and
   overlap during the transition. New since the previous build.
4. **S17b:** Find duplicates over 3611 fingerprints stopped at 3589
   of 3611, twice, at the same point.
5. **S17c:** quitting beach-balled at least three times.
6. **S17e:** in fullscreen, the tray menu closes as soon as it opens.

The wizard, sync, scan and the rest of this section's boxes stay
unticked until S17g's candidate.

**2026-10-14, Kris, the `6f49319` candidate: accepted for release.**
Kris ran the checks he judged most important (not itemized) and
reported no failure; the unticked boxes above are waived for v0.1.0,
not passed, and stay open as post-release checks. The stress run
(`SEEKER_RUN_STRESS_TEST=1`) ran the same day: its body passed, its
teardown error was the test's docker guard, fixed in HISTORY §243.
Silence kept every veto's wording, S17c's and S17f's included. S18
releases from the tagged rebuild; the commits since `6f49319` change
only tests and docs.
