# Round 9 — CI, quit safety, window lifecycle, UX corrections

**Author:** design/review chat, 2026-09-09. **Executor:** Claude Code.
**Session map:** `docs/round9/SESSION-PLAN.md` — read your row there,
then only the §sections it points at. Do not read this file whole; it
is ~40 KB and no session needs all of it.

Everything here was verified against the real repository at
`00baaf9` before it was written. Line numbers are from that commit —
`grep -n` the named symbol rather than trusting the number after any
edit lands.

---

## §0 — Ground rules for this round

**§0.1 Read discipline is unchanged** and still binding. `docs/HISTORY.md`
(837 KB), `tests/test_ui_smoke.py`, `src/seeker/ui/main_window.py`
(2,004 lines after round 8 — much better, still not a whole-file read)
are grep-then-range only. `pytest -q`, `git diff --stat`.

**§0.2 Approval gates.** Items tagged **[ASK KRIS]** must not be
executed without an explicit yes. Do the investigation, write up what
you found and what you propose, commit nothing that changes behaviour,
and stop. Items with no tag are pre-approved.

**§0.3 Skills.** Kris installed three skill bundles that are relevant
to this round. **At the start of every session, list your available
skills and resolve the exact names** — the names below are the bundles
as Kris described them, not necessarily the skill slugs:

| Bundle | Use it for |
|---|---|
| `product-skills` | Any item that changes what the user sees or reads: dialog copy, empty states, affordances, onboarding, the Library context header, the Review splitter. |
| `improve-codebase-architecture` | §5.2 (generalising the column layout), §7 (lifting selection state out of `DashboardPage`), and any moment you are about to add a second special case instead of a seam. |
| `engineering-advanced-skills` | §1 (test races, flake diagnosis), §2.3 (a real hang), §3.1 (Qt geometry semantics). Root-cause work, not feature work. |

Use them. If a skill's guidance contradicts this brief, follow the
skill for *how* and this brief for *what*, and say so in the handoff.

**§0.4 One commit per numbered item.** Refactor commits contain no
behaviour change; behaviour commits contain no refactor. Unchanged from
round 8.

**§0.5 The three numbers** (`pytest -q`, `mypy --strict src/`,
`ruff check src tests`) get quoted at the end of every session. `ruff`
stays at 0 findings.

---

## §1 — Get CI green

CI is real, running, and **failing**. Run #9 (`34346738383`, the push of
`2b83554`) is the latest and is red: `5 failed, 1141 passed, 29 skipped`,
with ruff and mypy clean. All five failures are already tracked in
CLAUDE.md's Open issues. None is new. **All five are fixable and this
round fixes them.**

Verified 2026-09-09: **the GitHub repo is public.** The standing open
question in `docs/HANDOFF.md` and CLAUDE.md ("Is the GitHub repo
private?") is answered — delete it wherever it appears, and note that
`update_check.py`'s "a 404 means no releases yet" reasoning now rests on
a repo that really is publicly readable. (See §4.2 — that is not the
end of the update-check story.)

### §1.1 — Workflow hygiene

`.github/workflows/ci.yml`, two real problems:

1. **Node 20 deprecation warning on every run:** `actions/checkout@v4`
   and `astral-sh/setup-uv@v5` both target Node 20, which the runner is
   force-upgrading to Node 24. Bump to `actions/checkout@v5` and
   `astral-sh/setup-uv@v6`. Read each action's release notes before
   bumping — `setup-uv@v6` changed its default caching behaviour, and
   this workflow relies on `uv sync --all-extras --dev` working from a
   cold cache.
2. **`runs-on: macos-latest` is a moving target** while §1.2–§1.4
   diagnose macOS-specific failures. Pin it to the concrete image
   (`macos-15`, or whatever `macos-latest` currently resolves to —
   check the run log's "Runner Image" section, do not guess). Leave a
   comment saying it is pinned *for diagnosis* and naming the condition
   under which it goes back to `latest`.

Nothing else in the workflow changes. The `QT_QPA_PLATFORM: offscreen`
env and the `brew install chromaprint` step are both correct and
load-bearing.

### §1.2 — `test_callback_server.py`: three CI-only ConnectTimeouts

**This is the highest-value item in the round, because the fix is not a
test fix — it closes a real production bug.**

**What fails.** On CI only, three tests in `tests/test_callback_server.py`
fail with `httpx.ConnectTimeout` connecting to their own local
`HTTPServer`:

- `test_wait_for_callback_parses_code_and_state_from_real_request`
- `test_wait_for_callback_captures_error_param`
- `test_callback_handler_returns_404_but_keeps_waiting_for_the_real_callback`

Reproduced identically across at least four real runs. The other two
tests in the file pass: `..._times_out_when_nothing_ever_arrives` (never
opens a client connection) and `test_two_consecutive_runs_do_not_leak_
state_between_them` (opens one, but runs last).

**What has already been ruled out.** A naive thread-startup race — an
earlier session confirmed a too-early connection is refused instantly,
not timed out at five seconds. Do not re-litigate that; it is in
HISTORY §117. The standing hypothesis (macOS blocking an unsigned
process's loopback listener in a non-interactive session) is
**unverified and not actionable from `gh`**.

**The production bug that the same code contains.** In
`src/seeker/spotify/auth_manager.py` around line 95:

```
webbrowser.open(authorization_url)
code, returned_state, error, timed_out = wait_for_callback()
```

The browser is launched **before** anything is listening on
`127.0.0.1:8888`. `wait_for_callback()` (`src/seeker/spotify/
callback_server.py`) constructs `HTTPServer(("127.0.0.1", port), ...)`
as its *first* statement — so the listening socket does not exist until
after the browser has already been handed the URL. For a user who has
already granted Seeker access on a previous run, Spotify redirects
straight back with no consent screen to slow it down, and the callback
can land before the socket is up. The user sees a browser error page and
Seeker sits waiting for a request that already happened, for the full
300-second timeout.

**It is worse than a bare race**, because of what `HTTPServer.server_bind()`
does. `http.server.HTTPServer.server_bind()` calls
`socket.getfqdn(host)` — a **reverse DNS lookup on 127.0.0.1** — and in
`socketserver.TCPServer.__init__` that runs *before* `server_activate()`
calls `listen()`. On a machine with slow or absent reverse DNS the
socket sits bound-but-not-listening for the whole lookup. That widens
the production race from microseconds to potentially seconds, and it is
a plausible contributor to the CI symptom too.

**The fix — split binding from serving.** In `callback_server.py`:

- Add a small `HTTPServer` subclass that overrides `server_bind()` to
  do `socketserver.TCPServer.server_bind(self)` and then set
  `self.server_name`/`self.server_port` directly from
  `self.server_address`, **skipping `socket.getfqdn()` entirely**.
  Comment it with exactly why (the reverse-DNS stall above); this is a
  real behaviour change to a stdlib class and must not read as
  cargo-cult.
- Split `wait_for_callback()` into two public functions:
  `create_callback_server(port=CALLBACK_PORT) -> HTTPServer` (constructs
  and therefore binds+listens, returns the server) and
  `serve_until_callback(server, timeout_seconds=CALLBACK_TIMEOUT_SECONDS)
  -> tuple[str | None, str | None, str | None, bool]` (the existing
  deadline loop, `server_close()` in its own `finally`).
- Keep `wait_for_callback()` as a thin
  `serve_until_callback(create_callback_server(port), timeout)` wrapper
  so nothing outside this module breaks in the same commit.
- Then, in a **separate commit**, change `auth_manager._authorize()` to
  create the server *first*, `webbrowser.open()` *second*, and
  `serve_until_callback()` third. That ordering is the production fix.

**Then the tests.** `create_callback_server(port=0)` binds an ephemeral
port; read the real port back from `server.server_address[1]`. Each of
the four connecting tests becomes: create the server **on the test's own
thread** (so it is provably listening before any client exists), start
only `serve_until_callback` in the background thread, connect to the
real port. This removes the fixed ports 18881–18885 entirely — no
collision risk, no reuse-across-tests risk — and removes the readiness
race as a variable, whatever the CI symptom turns out to be.

**Verification.** Local green is necessary but proves nothing here; the
failure is CI-only. **Push and read the real run.** If the three tests
now pass, say so with the run id and move on.

**If they still fail** — the cause is environmental, not code, and the
next step is bounded: add a temporary diagnostic step to the workflow
that, before pytest, runs a ten-line Python script binding a loopback
listener and connecting to it, printing the exception. That tells you in
one run whether loopback listening works at all on that runner. Report
the result. Do **not** silently mark the tests skipped to get a green
tick; if gating them behind a `requires_loopback_server` marker is the
only remaining option, that is **[ASK KRIS]** — it trades away real
coverage of the one code path that stands between a user and a working
Spotify login.

### §1.3 — `test_view_menu_focus_search_navigates_and_focuses_the_search_field`

Fails on CI on two consecutive runs, passes locally every time. CLAUDE.md
records the next thing to try as `activateWindow()`. **There is a more
reliable fix and it should be preferred.**

`QWidget.hasFocus()` is true only when the widget has the focus *and its
window is the active window*. Under `QT_QPA_PLATFORM=offscreen` there is
no window manager, so no window is ever activated, so `hasFocus()` can be
false even though Qt's focus really did move to the right widget. Locally
the tests run against a platform plugin where activation happens for
free, which is exactly why this is CI-only.

Assert on `window.focusWidget() is <the search field>` instead — that is
the property the feature actually promises ("the search field receives
focus") and it does not depend on window activation. If you also want to
keep an activation-sensitive assertion, guard it, do not delete it
silently.

**Check for the same pattern elsewhere before you finish:** `grep -n
"hasFocus()" tests/` and fix every instance the same way, in the same
commit. One CI-only focus flake almost never travels alone.

### §1.4 — `test_history_refresh_button_refetches` — time-boxed

A ~1-in-8 to 1-in-10 timeout, locally and on CI. A real cause was found
and fixed once (pytest-qt's teardown not flushing Qt's deferred
deletion, letting a prior test's live `MainWindow` react to a later
test's `applicationStateChanged`), confirmed closed with a weakref/gc
probe — **and it recurred anyway**. Full history: CLAUDE.md Open issues
and HISTORY §116.

**Time-box this to one third of your session.** The concrete next step
CLAUDE.md already names is instrumenting `_run_busy_worker`/`QThreadPool`
timing directly. Do that: on timeout, dump the thread pool's active
thread count, the pending `_callbacks` / `_progress_callbacks` registry
contents from `ui/workers.py`, and how long the worker had been in
flight. Run the full suite in a loop until it fires, capture that dump,
and write what it says into HISTORY.

If the box expires with no reproduction, **say so plainly and stop.**
An honest "ran it 40 times, did not fire, here is the instrumentation
now permanently in place" is a real result. Do not reach for
`pytest-rerunfailures` — that prohibition is standing and absolute.

### §1.5 — The always-skipped test: the answer

Kris asked which test is always skipped and whether it can pass. **This
is already fully answered in the codebase; the item is to make the
answer visible rather than to change anything.**

The skip is `tests/test_stress_e2e.py`, gated by
`requires_stress_opt_in` (`tests/test_stress_e2e.py:74`) on
`SEEKER_RUN_STRESS_TEST != "1"`.

**Why it is skipped, and why that is correct:** it drives the whole real
pipeline — real Spotify, real slskd, the real X9 Pro library — for real
wall-clock minutes, and it **mutates the production database**. The file's
own docstring explains it. A test like that must never run because
someone happened to have the infrastructure connected. The opt-in gate is
the right design and must stay.

**Can it pass?** Yes, and it is designed to: run
`SEEKER_RUN_STRESS_TEST=1 uv run pytest tests/test_stress_e2e.py` on
Kris's Mac with the X9 Pro mounted, Spotify configured and slskd up. It
then applies four further real-infrastructure skips
(`test_stress_e2e.py:265–274`) and runs for `DEFAULT_DURATION_SECONDS`
(300s, overridable via `SEEKER_STRESS_DURATION_SECONDS`). **This is a
Kris action, not a Code action** — see §1.5b.

**The 29-vs-1 skip count is also already explained** and is not a defect:
on CI, 29 = 28 `@requires_x9_pro` tests (no such drive on a GitHub
runner) + 1 `@requires_stress_opt_in`. On a real machine with the drive
mounted, 1 = the opt-in stress test alone. Exact arithmetic match.

**§1.5a — do this:** add a short "Why one test always skips" entry to
CLAUDE.md's Standing facts (three sentences, linking the docstring) so
the next person asking gets the answer without a code dive. That is the
whole item.

**§1.5b — for Kris, not Code:** run the stress test deliberately once
this round, per its own docstring's "re-run this after any change to
worker/timer/connection lifecycle code" instruction. §2 and §3 of this
brief change exactly that code. Report the result into the handoff.

---

## §2 — Quit correctness

### §2.1 — Establish the ground truth first [no code changes]

Kris asked what happens to partially downloaded tracks when Seeker is
quit mid-download. **Do not write a dialog until you can answer that
from real behaviour**, because the dialog's whole job is to tell the
user the truth.

From the architecture, the expected answer is: transfers are performed
by **slskd** in its own Docker container, not by Seeker. Seeker enqueues
them through the slskd API and `DownloadService.poll_downloads()`
(`src/seeker/soulseek/download_service.py:818`) reconciles state on a
timer. So quitting Seeker should stop the *reconciliation*, not the
*transfer*: slskd keeps downloading, partial files stay in slskd's own
incomplete directory, and the post-download pipeline (moving into the
library, tagging, review-candidate handling, the upgrade cascade) does
not run until Seeker is next opened, at which point `poll_downloads()`
picks the state back up.

**Verify that, live, before relying on it.** Start a real download, quit
Seeker, confirm from slskd's own UI/API whether the transfer continued,
then reopen Seeker and confirm it reconciles. Write the confirmed answer
into HISTORY and into CLAUDE.md's Standing facts. This is a
"verify against real behaviour" item in the strictest sense — the
project's own working principle, and the dialog copy in §2.2 is
downstream of it.

Note also what happens if the answer is *not* what is expected — e.g. if
`docker-compose` is brought down with the app, or if slskd is configured
to stop on disconnect. That changes §2.2's copy completely.

### §2.2 — Quit-while-downloading confirmation

**Only after §2.1.** Add a confirmation when a real quit is requested
while transfers are in flight.

**Where.** `MainWindow.cleanup_before_quit()` is the wrong place — it
runs on `aboutToQuit`, which is too late to cancel. The quit routes are:
the tray's `_on_tray_quit()` (`src/seeker/ui/tray.py:327`, which calls
`QApplication.quit()`), and the real ⌘Q / Dock "Quit Seeker". Find the
one seam both pass through and gate there. If there is no single seam,
say so in the handoff rather than bolting the check onto one route and
leaving the other silent — a confirmation that only fires half the time
is worse than none.

**The count** comes from the service layer, never the database:
`DashboardService.get_active_downloads()` already exists and
`downloads_page.active_downloads_count` already tracks it. UI → service,
as always.

**The copy** is the deliverable here, and it is a `product-skills` item.
It must state what actually happens (per §2.1), not a generic scare.
Shape, not final wording:

> **N downloads are still in progress.**
> Seeker hands transfers to SoulSeek, which keeps running after you
> quit — but Seeker won't file the finished tracks into your library
> until you open it again.
> [Quit anyway] [Keep Seeker open]

Rules for the final wording: name the real number; say what survives and
what does not; do not use the word "lose" unless §2.1 proves something
is actually lost; default button is the safe one. No dialog at all when
the count is zero — an "are you sure" on an idle app is noise.

### §2.3 — The "not responding" hang after close-then-quit

**Reported once**, unreproduced: Kris closed the window (which correctly
hid to the menu bar and removed the Dock icon), then quit from the
menu-bar icon, and the app reappeared in the Dock marked "not
responding". Treat this as a real defect with an unknown cause, not a
one-off — a hang at quit is exactly the shape of bug that shows up
rarely and then eats a user's data.

**Reproduce first.** Vary: whether a background worker is in flight at
quit (a scan, a fingerprint, a poll), whether downloads are active,
whether the window was closed normally or from fullscreen. The single
most likely trigger is *quitting while a worker is running*, so bias the
attempts that way.

**Three candidate mechanisms, in the order to check them:**

1. **`QThreadPool` blocking at exit.** `cleanup_before_quit()`
   (`main_window.py:1719`) stops `poll_timer` and `backend_poll_timer`
   but does nothing about in-flight `Worker` runnables
   (`ui/workers.py:83`). Qt's thread pool waits for its runnables at
   shutdown. A worker blocked in a 10-second httpx call, or a librosa
   analysis measured in minutes, will hang the quit for exactly as long
   — and a hung, Dock-hidden app is precisely what macOS re-surfaces as
   "not responding". Check `QThreadPool.globalInstance().activeThreadCount()`
   at the top of `cleanup_before_quit`.
2. **Disk I/O on the quit path.** `cleanup_before_quit` →
   `_persist_window_geometry()` → `application.update_settings()`, which
   does a `load_config` + `save_config` round trip. Small, but it is
   real synchronous I/O inside `aboutToQuit`.
3. **A deleted window receiving `aboutToQuit`.** `MainWindow.__init__`
   sets `WA_DeleteOnClose` **True** (`main_window.py:304`); `tray.py:180`
   sets it back to **False**, but only inside `_build_tray_icon`, i.e.
   only when a tray icon really gets built. If tray creation ever fails
   or is unavailable, closing the window destroys it while
   `qt_app.aboutToQuit.connect(window.cleanup_before_quit)`
   (`main_ui.py`) still holds a bound method on the dead object — a
   `RuntimeError` raised inside an `aboutToQuit` slot. That is not the
   reported path (a tray icon clearly existed), but it is a real latent
   bug in the same code and **should be fixed regardless**: make the
   attribute's value follow from one decision in one place rather than
   being set true and conditionally unset later.

**Diagnostics that will actually tell you something:** while the app is
hung, `sample Seeker 10 -f /tmp/seeker-hang.txt` from Terminal gives the
stuck stack directly. Also read `seeker.log` (see
`main_ui._configure_logging` / `resolve_log_dir`) around the quit.

**The fix**, once the cause is known, is likely: cancel or wait-with-
timeout on in-flight workers before quitting, and give
`cleanup_before_quit` a hard bound so no quit path can block
indefinitely. Do not add a bare `QThreadPool.waitForDone()` with no
timeout — that is the same hang with a different stack.

If it will not reproduce, say so, land the §2.3.3 `WA_DeleteOnClose`
fix and the instrumentation, and leave it in Open issues with what was
ruled out. Do not close it as "one-off".

---

## §3 — Window lifecycle

### §3.1 — The window does not reopen at its saved size

**Confirmed by Kris on a real Mac:** the app reopens at the default size,
not the size it was closed at. The Dock-icon half of the same round-8
item works correctly.

**Establish which half is broken, first, in one step.** Read the
persisted config (`resolve_config_path()`, `config_store.py:73`) after a
real quit and check whether `window_geometry` holds a value. That splits
the problem cleanly: no value means the save path is broken; a value
present means the restore path is.

**The most likely cause is the restore path, and it is an ordering bug.**
`main_window.py:444–452`:

```
self.setWindowTitle("Seeker")
self.resize(1180, 760)
self.setMinimumSize(960, 640)
self._restore_window_geometry()
self._build_ui()
```

`restoreGeometry()` runs **before** the central widget and layout exist.
When `_build_ui()` then installs the layout, layout activation on first
show can resize the window to the layout's own size hint, discarding the
restored geometry — which lands the user on something very close to the
1180×760 default, exactly as reported. **Move `_restore_window_geometry()`
to after `_build_ui()`.** Confirm the Qt semantics from the docs before
committing rather than taking this brief's word for it.

**There is a second, independent weakness on the save path.**
`_persist_window_geometry()` (`main_window.py:777`) is called from
`cleanup_before_quit()` and nowhere else. In Kris's actual flow the
window is **already hidden to the tray** by then, so `saveGeometry()`
runs against a non-visible window. Also: a crash or a force-quit saves
nothing at all.

**Fix both:** persist in `closeEvent`, immediately *before* hiding to the
tray, so the captured geometry always comes from a visible window; keep
the quit-time call as a backstop for the quit-without-closing route. Make
the backstop skip an already-hidden window rather than overwriting a good
value with a hidden-window one.

**Acceptance test** (offscreen Qt can carry this): build a window, resize
it to a distinctive non-default size, drive the close-to-tray path, drive
the quit path, construct a fresh window against the same config, assert
the size round-tripped. Round 8 already has
`test_reopening_after_a_fullscreen_close_restores_prior_geometry` — put
the new test beside it and check whether that existing test was passing
for the wrong reason.

Then hand it back to Kris for a real-Mac confirmation; offscreen Qt is
what let this ship broken in the first place.

### §3.2 — Start Seeker at login

Kris asked for this. **Note the premise correction in §4.2 before writing
the justification anywhere** — the app does *not* currently poll for
updates in the background, so "it checks for upgrades anyway" is not a
reason. Sharing is a real reason: if the user has opted into sharing,
Seeker being up is what makes their library reachable.

**Scope: macOS only.** The app ships as a PyInstaller bundle
(`packaging/seeker.spec`) and `pyobjc-framework-Cocoa` is already a
darwin dependency.

**Two mechanisms, pick deliberately and write down why:**

- `SMAppService.mainAppService.register()` (macOS 13+) — the modern,
  Apple-blessed path. Appears under System Settings → General → Login
  Items, user-revocable there. Needs `pyobjc-framework-ServiceManagement`,
  which is **not currently a dependency** — adding it is part of the item.
  Requires a real `.app` bundle, so it will not work under `uv run` from
  source, and the setting must degrade honestly in that case rather than
  silently no-op.
- A `~/Library/LaunchAgents/*.plist` with `RunAtLoad` — no new
  dependency, works from source, but it is the legacy path, it writes a
  file into the user's home directory, and macOS surfaces it as an
  opaque background item.

Recommendation: `SMAppService`, with a clear "only available in the
packaged app" state when running from source. **[ASK KRIS]** if you
conclude otherwise, or if adding the dependency is contentious.

**Two things this item must include, not just the toggle:**

1. **A "start hidden in the menu bar" companion option.** An app that
   launches at login and throws a window in your face at every boot is a
   worse experience than one that does not launch at all. Default it on
   when launch-at-login is enabled. `is_hidden_to_tray` already exists in
   `PageContext`, and `main_ui.main()` already chooses whether to `show()`
   — this is a small change at that seam.
2. **Honest state reporting.** If the user revokes the login item in
   System Settings, Seeker's own checkbox must not keep claiming it is
   on. Read the real status (`SMAppService.status`) when the Settings
   page renders; do not trust a mirrored boolean in `config.json`.

Settings page placement and copy: `product-skills`. `settings_window.py`
is 1,233 lines — grep for the existing section builders and follow the
established pattern rather than inventing a new one.

---

## §4 — Onboarding and updates

### §4.1 — Remove the support page from the wizard

Kris: "no point in having it before the user actually experiences the
app." Agreed, and the codebase already has the right home for it.

**What to remove:** the support row in `OnboardingWizard._build_done_page`
(`src/seeker/ui/wizard.py:730–741`) — the `DONE_PAGE_SUPPORT_PROMPT`
label and the generated "Support on {name}" buttons. The rest of the done
page (title, body, Continue) stays.

**What must NOT be removed** — there are three support surfaces and only
one is in scope:

- The real **Support page** in the sidebar (`ui/pages/static_pages.py`,
  `help_text.SUPPORT_PAGE_*`, roadmap item 64) — **keep**. This is the
  "after the user has experienced the app" placement Kris is asking for
  and it already exists.
- **AboutDialog's** support-links row (`ui/dialogs.py:42–52`) — **keep**.
- `help_text.SUPPORT_LINKS` and `is_real_support_link()` — **keep**, both
  other surfaces read them.

**Cleanup that follows:** `DONE_PAGE_SUPPORT_PROMPT` (`help_text.py:1142`)
becomes unused — delete it, and check `tests/test_help_text.py` for a
coverage assertion over help-text constants before you do. Check whether
`webbrowser` is still used elsewhere in `wizard.py`; if not, the import
goes, or ruff will tell you.

**Tests to update:** `tests/test_wizard.py:60–75` asserts the buttons
exist. Invert it — assert the done page contains **no** "Support on"
buttons, so the removal is protected against being reintroduced. Leave
`tests/pages/test_static_pages.py` and `tests/pages/test_dialogs.py`
alone; those cover the surfaces that stay.

**One stale comment to fix while you are in there:** `wizard.py:731`
says "Real URLs aren't ready yet; see help_text.SUPPORT_LINKS's own
placeholder-URL warning." `SUPPORT_LINKS` now holds two real URLs
(Revolut, PayPal). The comment dies with the code it annotates, but
`dialogs.py:125` carries a similar claim — check it and correct it if it
is also stale.

### §4.2 — How update checking actually works, and what is wrong with it

Kris asked whether this is a daily cron job. **It is not. There is no
automatic check of any kind.**

`src/seeker/update_check.py` is called from exactly one place:
`MainWindow._on_check_for_updates_clicked` (`main_window.py:1252`), wired
to Help → "Check for updates…". The module's own docstring is explicit:
*never called automatically, never on a timer or at startup*. It makes
one unauthenticated GET to
`https://api.github.com/repos/KristiyanDDimitrov/Seeker/releases/latest`,
subject to GitHub's 60-requests-per-hour-per-IP anonymous limit.

**There is a real defect underneath that. Verified 2026-09-09: the
repository has no published releases at all.** `/releases/latest`
therefore returns 404 for every user, every time, and "Check for
updates…" is a feature that cannot currently succeed. Whatever the 404
branch reports today, it is reporting it about a repo that has nothing
to report.

**Two things to do:**

**§4.2a [pre-approved]** — make the 404 branch honest. Read what
`_check_for_update()` currently says for a 404 and make sure a user
reads something true and un-alarming ("No releases have been published
yet") rather than something that implies a network or configuration
fault. Add a test pinning that branch.

**§4.2b [ASK KRIS]** — two decisions, neither of which Code should make
alone:

1. **Cut a real release.** Until `v0.1.0` exists on GitHub, §4.2a is
   cosmetic and the feature stays dead. That is a Kris decision (it
   implies a versioning and artefact story: does the release carry the
   PyInstaller `.app`?).
2. **Make the check automatic.** Kris assumed it already was. Making it
   so is reasonable *and* runs against this project's standing caution
   about live external dependencies on timers. If yes, the shape that
   respects both: check at most once per 24 hours, at startup only,
   against a `last_update_check_at` timestamp in `config.json`, off the
   UI thread, failing completely silently — with a Settings toggle,
   default **off**, so nobody gets background network traffic they did
   not ask for. Do not implement any of this without a yes.

---

## §5 — Table sorting is broken on widget-only columns

Kris: the Dashboard's Progress ordering does nothing, and Actions
ordering does nothing either. **Both confirmed in code; both are the
same root cause.**

Round 8 §12.2 turned on click-to-sort for every table
(`theme.apply_table_defaults`, `theme.py:446`). Qt sorts
`QTableWidgetItem`s. The Dashboard track table has four columns —
`["Track", "Status", "Progress", "Actions"]`
(`dashboard_page.py:312`) — and columns 2 and 3 **never get an item at
all**, only a cell widget:

- `dashboard_page.py:756` — `setCellWidget(row, 2, wrap_progress_bar(...))`
- `dashboard_page.py:760` — `setCellWidget(row, 2, QWidget())` for rows
  with no active transfer
- `dashboard_page.py:764` — `setCellWidget(row, 3, track_actions)`

With no items in the sort column, every row compares equal and the sort
is a no-op. The header still shows a sort indicator, so the control
looks live and does nothing — the worst of both.

### §5.1 — Make Progress genuinely sortable

Set a real sort-key item on column 2 **in addition to** the cell widget
(Qt allows both on one cell; the widget is what is drawn, the item is
what is compared). `ui/table_sort.py` already has exactly the right tool:
`SortKeyItem(text, sort_key)`.

- Sort key: the transfer's **fraction complete** (`bytes_transferred /
  total_bytes`), not the raw byte count — the column shows progress, so
  it must order by progress. Two tracks at 50% sort together regardless
  of file size.
- Rows with no active transfer need an explicit sentinel (`-1.0`), never
  `None` — `SortKeyItem`'s docstring already forbids `None`.
- Display text stays empty; the progress bar is the display.
- Everything happens inside the existing `with preserving_sort_order(
  self.track_table):` block, so the user's chosen order survives the
  rebuild.

**Then check the Downloads page for the same defect** —
`downloads_page.py:260` is another `setCellWidget` progress column. If it
has the same hole, fix it in the same commit; if it already sets an
item, say so.

### §5.2 — An Actions column must never be sortable

Sorting by a column of buttons is meaningless. The fix is not to give it
a sort key — it is to remove the affordance.

**The hook already exists.** `theme.ColumnLayout` (`theme.py:563`)
already carries `actions: int | None`, and the Dashboard's
`_TRACK_COLUMNS` (`dashboard_page.py:79`) already declares `actions=3`.
So `theme.configure_columns()` already knows which column is the actions
column for every table in the app, with no new field to add.

In `configure_columns`, when `layout.actions is not None`, veto sorting
on that section: connect to `header.sectionClicked` and, for the actions
section, restore the previous sort indicator instead of sorting. Give
the section no sort indicator so it does not advertise a behaviour it
does not have.

**This is the `improve-codebase-architecture` moment in this round.** Do
it once, in the shared helper, for every table — not as a Dashboard
special case. Every other table with an actions column (Review ×3,
Downloads, Search, Sharing, Settings locations) gets the fix for free,
and the next table to be added gets it by default. If the mechanism turns
out to need per-table opt-in, that is a signal the seam is wrong — stop
and say so rather than adding a second parameter.

### §5.3 — Audit every table for the same hole

`grep -n "setCellWidget" src/seeker/ui/` returns ten call sites across
seven files. For each: is that column's cell also given a
`QTableWidgetItem`? If not, the column is silently unsortable. Classify
each as **needs a sort key** (Progress-like: real data, wrong
presentation) or **must never sort** (Actions-like), and apply §5.1 or
§5.2 accordingly.

Two known exceptions to leave alone: the Duplicates table turns sorting
off entirely right after `apply_table_defaults` (grouped via `setSpan()`,
would corrupt visually), and Search results deliberately arrive in
`rank_candidates()` order with `setSortIndicator(-1, ...)` so no sort is
applied until the user asks.

Write the audit table into HISTORY. It is the artefact that stops this
being rediscovered next round.

---

## §6 — Review page: resizable panes

Kris wants the three Review sections resizable against each other: enlarge
one, the others give up space proportionally.

**Current structure** (`ui/pages/review_page.py:110–161`): a plain
`QVBoxLayout` with three `[QLabel, theme.make_card(QTableWidget)]` pairs
stacked — needs-review (`review_needs_table`), downloaded upgrades
(`review_upgrades_table`, which has its own header row with the
"Replace all" button), and local matches (`review_local_table`).

**The fix is a `QSplitter(Qt.Orientation.Vertical)`**, which gives Kris's
described behaviour natively — dragging a handle redistributes space
between neighbours, and `setStretchFactor` controls how the rest
respond. Do not hand-roll the arithmetic.

Requirements:

- Wrap each of the three sections (its header row *and* its card) in a
  single `QWidget` so a section moves as a unit. The upgrades section's
  header row must travel with its table.
- `setChildrenCollapsible(False)` and a real `minimumHeight` per section,
  so no pane can be dragged to nothing and become unrecoverable.
- **Persist the splitter state**, or the feature is annoying rather than
  useful. Use the same pattern `window_geometry` already uses: base64 of
  `splitter.saveState()` in `config_store.SeekerConfig`, guarded
  idempotent config migration, restore tolerant of a missing/corrupt
  value. `config_store.py:59–65` is the model to copy — including its
  comment discipline.
- Restore **after** the splitter's children exist. See §3.1; it is the
  identical failure mode and it would be embarrassing to ship it twice
  in one round.
- Sensible first-run proportions rather than three equal thirds. Needs-
  review is the section a user acts on most; give it the most room by
  default. `product-skills` for that judgement.

Screenshot both themes and check the splitter handles are visible
against the card backgrounds — a handle you cannot see is a feature
nobody finds.

---

## §7 — Library page: say which playlist it is acting on

Kris: "Library section is currently confusing — it doesn't say which
playlist it's acting upon." **Confirmed, and the cause is structural.**

`ui/pages/library_page.py` (whole file, 67 lines) owns no selection state.
Its docstring says so outright: *"Library has no selection state of its
own: it operates on whatever playlist/track selection is currently live
on the Dashboard page, via `LibraryHost`."* So the page renders "Tag
playlist" / "Fix cover art" / "Sync tracks" buttons that act on a
playlist chosen on a **different page**, with nothing on screen naming
it. `tagging_panel.py:345–421` reads `get_selected_playlist()` at click
time and shows "Select a playlist first." only on failure.

This is the round's real architecture item. **Two parts, in order.**

### §7.1 — Lift the selection into a shared, observable seam

Today `LibraryHost` reaches into `DashboardPage`'s private selection
through callables. That is a read-only workaround, and it cannot support
"change the playlist from here" — Library would have to *write* into
another page's internals.

Introduce a small selection object — the current playlist, the selected
track ids, and a change signal — owned by the shell and handed to pages
through `PageContext` (`ui/pages/context.py`), which is already the
declared seam for exactly this ("a page module never reaches past it to
call MainWindow directly"). Dashboard writes it on selection; Dashboard
and Library both read it; both re-render on its signal.

`PageContext` is a frozen dataclass whose docstring records that every
field was added only when a real page needed it. This is such a moment —
add the field, and add the one-line note saying which page needed it, in
the established style.

**Do §7.1 as a pure refactor commit with no visible change**, prove the
suite green, and only then build §7.2 on top. Same discipline round 8's
Phase 6 used, and the reason it worked.

### §7.2 — The context header and the picker

`product-skills` owns the design; the requirements are:

- A persistent header on the Library page naming the playlist being acted
  on, and how many tracks are in scope. It must be visible without
  scrolling and it must be near the buttons that use it.
- A way to change it from Library. An inline picker is likely right
  (Dashboard already has a playlist list to model it on); a modal is
  likely wrong for something this frequent. Changing it here changes the
  shared selection, so the Dashboard reflects it too — one selection, two
  views, never two truths.
- A real empty state for "no playlist selected" that offers the picker
  rather than only reporting the problem. This replaces the current
  behaviour of finding out by clicking a button and getting a warning.
- Per-track actions that operate on the multi-select must keep saying so
  — do not let the new header imply everything is playlist-scoped when
  "Tag selected" is not.

Screenshot both themes, populated and empty.

---

## §8 — Found during review — all [ASK KRIS]

Found while reviewing round 8 for this brief. None is scheduled. Each
needs an explicit yes before any work starts.

**§8.1 — Cut a `v0.1.0` GitHub release.** See §4.2. Until one exists,
"Check for updates…" cannot succeed for anybody. Implies decisions about
versioning and whether the release carries the packaged `.app`.

**§8.2 — `docs/HISTORY.md` is 837 KB and growing.** The never-read-whole
rule is holding, but every `grep -n` over it costs more each round, and a
single file that can never be opened is a warning sign. Consider
splitting into `docs/history/round-N.md` with an index — `grep` gets
cheaper and cross-round references keep working. Deliberately not
scheduled: it touches the one file this project's read discipline is
built around, and getting it wrong is expensive.

**§8.3 — Three registered library locations nest inside each other and
double-index ~3,450 real files.** Already in CLAUDE.md's Open issues
(HISTORY §93) as a real user decision left open. Flagged again because it
is still true and it silently inflates every count the Dashboard shows.
`add_location`/`add_location_from_path` check exact path-string
uniqueness only; a containment check is a small change. The data cleanup
is the part that needs Kris.

**§8.4 — The Dashboard↔Library host coupling.** §7.1 fixes the playlist
selection specifically. `DashboardHost` also carries three callables
reaching *into* Library's TaggingPanel (round 8 §12.6) — the same
coupling in the other direction. Worth one look after §7 lands to see
whether the new seam absorbs those too, or whether they are genuinely
different.

**§8.5 — Geometry is persisted only at quit.** §3.1 adds a persist on
close-to-tray, which covers the reported bug. A crash or force-quit still
saves nothing. A debounced persist on resize/move would close that, at
the cost of periodic config writes. Probably not worth it — recorded so
the decision is explicit rather than forgotten.

---

## §9 — How to end a session

Unchanged from round 8, four steps:

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your row in `docs/round9/SESSION-PLAN.md`.
4. **Rewrite `docs/HANDOFF.md`** — the commit you ended on, the three
   numbers, what landed, what is next, and anything you found that
   changes a later row. Under ~120 lines. Delete what is no longer true.

**One addition for this round.** Several items here end in "push and read
the real CI run." When your session's work is pushed, **record the run id
and its result in the handoff**, pass or fail. Round 8 lost time twice by
re-deriving CI state that a previous session already knew.
