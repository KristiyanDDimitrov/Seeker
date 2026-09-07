# Brief for Claude Code — round 8, Phase 3 + 3B:
# security hardening and the macOS Dock icon

You are starting cold. This file is self-contained — you do not need to
read anything else to begin, though `docs/BRIEF-2026-09-08-refactor.md`
in this repo is the full nine-phase plan this is Phase 3 and 3B of, and
it has the wider context if you want it.

---

## 0. What this project is

**Seeker** — a personal DJ music library manager, at
`~/PycharmProjects/Seeker`. It syncs Spotify playlists into a local
SQLite cache, scans a local music library across multiple drives,
matches tracks against files already owned, searches and downloads what
is missing over SoulSeek (through a self-hosted `slskd` instance in
Docker), and normalises file metadata. It ships a CLI (`seeker`) and a
macOS desktop GUI (`seeker-ui`, PySide6) over one shared service layer.

Python 3.13, `uv`, SQLite, httpx, mutagen, librosa, PySide6.
`CLAUDE.md` at the repo root holds the standing architectural facts and
`docs/HISTORY.md` the full investigation narratives. Read `CLAUDE.md`
before you start; it is the project's standing brief.

**It has two goals at once, and both are real:** it is a genuinely
useful tool for its owner, and it is a portfolio project attached to a
CV. Code quality is a deliverable, not a nicety.

### The working agreements you are held to

These are the project's own, and this round has already added to them:

- **One commit per numbered ledger item.** Never per phase. A refactor
  commit contains no behaviour change; a behaviour change commit
  contains no refactor.
- **Every phase closes with three numbers, quoted exactly:** the full
  `uv run pytest` summary line with every failure *and skip* named
  inline, `uv run mypy --strict src/`, and `uv run ruff check src
  tests`. Never "green with N pre-existing failures" as a paraphrase.
  **The failure count is a tracked number, not a label — if it moves,
  diagnose it before continuing.**
- **A comment asserting platform or framework behaviour must cite a real
  observation or be explicitly marked UNVERIFIED.** This project has
  shipped confidently-wrong platform claims twice (an invalid Qt QSS
  selector; a false claim about macOS tray-icon click routing). Write
  "confirmed live (date, macOS version, PySide6 version)" when it is
  real, or say UNVERIFIED plainly.
- **Verify against live behaviour, not documentation or assumption.**
  Spotify's API and slskd's env-var naming have both broken previously
  "confirmed" assumptions here.
- **Races get closed, not narrowed.** A fix that reduces reproduction
  rate rather than eliminating the mechanism is not accepted.
- **Never modify, move or delete a real user file without explicit
  confirmation first.** This matters in §6.2 below.
- **Any `continue`/`skip` inside a sweep test must be justified in a
  comment naming what it excludes and why that exclusion cannot hide the
  bug the test exists for.** A skip derived from the state a bug
  corrupts is a blindfold, not a guard.
- **Never run `ruff --fix` with a narrowed `--select`, and never narrow
  to `RUF100` at all.** RUF100 evaluates a `# noqa` against only the
  rules enabled in that run, so a narrowed selection marks every
  directive in the codebase unused and `--fix` deletes them. This cost
  real suppressions earlier this round.
- **Checking whether a failure is pre-existing: always `git stash -u`,
  never a bare `git stash`** — a bare stash cannot see untracked files.
- **Fix discovered issues in-pass.** No backlog-building.

---

## 1. Where the repository is right now

**HEAD: `9a55761`** — "Fix §6.3.1-6.3.3: bounded OAuth callback wait,
per-run state, ignore stray requests". Working tree clean.

**Verified numbers at this commit:**

| | |
|---|---|
| `uv run pytest` | 1102 passed, 1 skipped |
| the 1 skip | `tests/test_stress_e2e.py` — opt-in only, `SEEKER_RUN_STRESS_TEST=1`; real infra and real mutations, never runs in the normal suite |
| `uv run mypy --strict src/` | clean, 85 source files |
| `uv run ruff check src tests` | **0 findings** |
| `src/seeker/ui/main_window.py` | 6,649 lines |

**`ruff check` exits zero and must continue to.** Phase 1 established
the standing rule: *a lint configuration the project cannot sit at zero
under is not a configuration, it is a backlog wearing one.* Every
suppression in `pyproject.toml` carries a written justification. If your
work needs a new one, justify it the same way — and if you find yourself
wanting a broad ignore, that is a signal the code should change instead.

Relevant config facts you will bump into: `line-length = 88`;
`src/seeker/ui/*` ignores `N802` (Qt overrides are camelCase by
framework contract); `src/seeker/ui/main_window.py`, `wizard.py`,
`sharing_service.py` and `audio_fingerprint.py` ignore `S603`/`S607`
because every subprocess call uses the list form with no `shell=True`
and bare-name invocation is deliberate (`ensure_full_path_environment()`
extends `PATH` for GUI launches).

### What has already been done this round

**Phase 0** — baseline captured. 52 screenshots live at
`~/seeker-baselines/2026-09-08/` (real data) and
`~/seeker-baselines/2026-09-08-empty/` (scratch database, genuine empty
states). Launch-to-first-paint median 0.878 s. **These are outside the
repo and stay outside it** — the real-data set contains actual playlist
names and library paths.

**Phase 1** — toolchain. `[tool.ruff]` and
`[tool.pytest.ini_options]` added; `ruff`/`mypy` pinned with upper
bounds; `.github/workflows/ci.yml` added; 0 lint findings reached.

**Already pulled forward from this brief's own Phase 3:** §6.3
(the OAuth callback server) is **done** at `9a55761` —
`wait_for_callback()` now bounds the whole wait against a real deadline
(`CALLBACK_TIMEOUT_SECONDS = 300.0`, marked untuned), returns a fourth
`timed_out` outcome, builds a fresh per-call handler class so no
class-level state leaks between attempts, and ignores non-`/callback`
requests instead of letting a stray `/favicon.ico` consume the single
request slot. **Do not redo it.**

### The one open item carried in from Phase 1

- [ ] **0.1 — Push, and confirm CI actually ran green.** `origin/main`
  is **6 commits behind `HEAD`**. `.github/workflows/ci.yml` has never
  been observed running. A workflow file that has never executed is not
  evidence that it works — local verification under
  `QT_QPA_PLATFORM=offscreen` proved the *test* step and nothing about
  `uv sync` on a clean `macos-latest` runner, the ruff step or the mypy
  step. Push, then report the run URL and its result. **If it fails,
  that failure belongs to Phase 1 and is fixed before anything below
  starts.**

  Note: the repository appears to be **private** (anonymous requests to
  `github.com/KristiyanDDimitrov/Seeker/actions` return 404). Worth
  confirming with the owner, because if so, `update_check.py`'s
  `/releases/latest` call returns 404 for every user regardless of
  releases — and that module's own comment reasons a 404 safely means
  "no releases published yet" *because the repo constant is
  known-good*, which only holds once the repo is public. Report it; do
  not change the repo's visibility.

---

## 2. What you are doing, and in what order

Two parts, both isolated, both requiring real-desktop verification.

**Part A — §6: security.** The owner's own assumption was *"there is
little that can go wrong with this app as no sensitive user credentials
are actually stored."* That is wrong in two specific ways, and the
larger exposure is not in the Python at all.

**Part B — §14: the macOS Dock icon.** A live user-reported defect.

Do Part A first — §6.1 is the highest-severity item in the whole round
and it is mostly a two-line change to `docker-compose.yml` plus
verification. Part B carries more risk and touches `main_window.py`,
which later phases rearrange.

---

## 3. Part A — §6.1: the slskd web UI is exposed to the whole network
## with vendor-default credentials and remote configuration switched on

**Severity: HIGH.** Three facts, each independently verified against
this repository, still true at `9a55761`.

**1. `docker-compose.yml` publishes the web UI on every host
interface.**

```yaml
    ports:
      - "5030:5030"     # slskd web UI (HTTP)
      - "5031:5031"     # slskd web UI (HTTPS)
      - "50300:50300"   # Soulseek network listener
```

A Docker port mapping with no host address binds `0.0.0.0`. On any
shared network — a café, a co-working space, a flat-share, a venue —
`http://<host-LAN-IP>:5030` is reachable by anyone on it.

**2. Seeker never sets the slskd web UI login.** `grep -rn
"SLSKD_USERNAME\|SLSKD_PASSWORD" src/` returns only two *comment* lines
in `docker_setup.py`. `bring_up_slskd()` passes exactly four variables:
`SLSKD_SLSK_USERNAME`, `SLSKD_SLSK_PASSWORD`, `SLSKD_API_KEY`,
`SLSKD_DATA_DIR`. The web UI login is left at slskd's own default, and
slskd's documentation states it plainly: *"Authentication for the web UI
(and underlying API) is enabled by default, and the default username and
password are both `slskd`."*

**3. Seeker explicitly enables remote configuration**, which slskd
defaults to *off*: `docker-compose.yml` sets
`SLSKD_REMOTE_CONFIGURATION=true`; slskd's config docs show
`remote_configuration: false` as the default.

Together: anyone on the same network logs in with `slskd`/`slskd` and
gets a daemon they can reconfigure at will, plus visibility of the
SoulSeek account credentials and the API key it holds. The music share
is mounted `:ro`, so files cannot be written — that is the one thing
limiting the blast radius, and it stays.

- [ ] **6.1.1 — Bind the web UI to loopback only.** Seeker's own client
  only ever talks to slskd over localhost — `SLSKD_LOCAL_BASE_URL =
  "http://localhost:5030"` (`src/seeker/ui/wizard.py:50`) is what the
  wizard configures. Nothing needs 5030/5031 reachable from off-box:

  ```yaml
      ports:
        - "127.0.0.1:5030:5030"
        - "127.0.0.1:5031:5031"
        - "50300:50300"   # MUST stay open — incoming Soulseek peer
                          # connections; the P2P protocol needs it.
  ```

  > **Gotcha, check this before you declare it working.** Docker binds
  > `127.0.0.1:5030:5030` on **IPv4 only**, while macOS resolves
  > `localhost` to both `::1` and `127.0.0.1` — and `getaddrinfo`
  > commonly returns `::1` first. An httpx request to
  > `http://localhost:5030` may therefore try IPv6, get connection
  > refused, and fall back — working, but with a per-request delay, or
  > failing outright depending on the client's retry behaviour. **Time a
  > real search before and after the change.** If there is a regression,
  > the clean fixes are to publish `"[::1]:5030:5030"` as well, or to
  > change `SLSKD_LOCAL_BASE_URL` to `http://127.0.0.1:5030`. Pick one,
  > and say which and why.

  **Verify, do not assume:** after the change, confirm from a second
  device on the same network that `http://<mac-lan-ip>:5030` no longer
  answers, and that Seeker's search **and a real incoming upload** both
  still work. Port 50300 must stay published or sharing breaks — state
  in the commit message that you checked this.

- [ ] **6.1.2 — Generate a real web UI password during onboarding.**
  `docker_setup.generate_api_key()` already does the right thing
  (`secrets.token_urlsafe(32)`, with a comment showing the 16–255 range
  was read from slskd's own config). Add the mirror: generate a web UI
  password the same way, pass `SLSKD_USERNAME`/`SLSKD_PASSWORD` through
  `bring_up_slskd`'s env dict alongside the four already there, add
  them as `${...}` entries in `docker-compose.yml`, and persist them in
  `SeekerConfig` next to `slskd_username`/`slskd_password`.

  **Two things to settle before you write it.** (a) The existing comment
  in `docker_setup.py` records that these two variable pairs were
  confirmed empirically against a live container because they are easy
  to confuse — `SLSKD_USERNAME`/`SLSKD_PASSWORD` is the **web UI** login
  and `SLSKD_SLSK_USERNAME`/`SLSKD_SLSK_PASSWORD` is the **Soulseek
  network** login. Respect that, and re-confirm rather than trusting the
  comment. (b) **The owner has an existing slskd container with
  persisted state in `slskd-data/slskd.yml`.** Changing the web UI
  password on an existing install must not lock him out of a daemon he
  may currently be logged into, and `slskd-data/` is real user state —
  the "never modify a real user file without confirmation" rule applies.
  Design the upgrade path deliberately, say what you chose, and surface
  the new credentials to the user somewhere they can find them.

- [ ] **6.1.3 — Reconsider `SLSKD_REMOTE_CONFIGURATION=true`.** Find
  what actually needs it. `SharingService.add_location_to_share`
  recreates the container with a new `SLSKD_SHARE_PATH` via
  `bring_up_slskd` — that is a *compose-level* change, not a
  remote-configuration one. If nothing in Seeker calls slskd's
  configuration API, turn it off; it is the vendor default for a reason.
  If something does need it, keep it and put a comment in the compose
  file naming the exact call site that requires it. **Report which you
  found. Do not guess.**

- [ ] **6.1.4 — Tell the user, once, in the UI.** The Sharing page or
  Settings → Connection should state in plain words what is being shared
  and with whom, and that slskd's admin interface is local-only. Someone
  running a file-sharing daemon deserves to know what it exposes. One
  sentence, not a wall.

---

## 4. Part A — §6.2: the Spotify token file is written world-readable
## while the config file beside it is locked down

**Severity: MEDIUM**, and the inconsistency is what proves it is an
oversight rather than a decision.

`config_store.save_config()` does the right thing:

```python
    path.write_text(json.dumps(asdict(seeker_config), indent=2) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
```

`TokenStore.save()` (`src/seeker/spotify/token_store.py:11-20`,
unchanged this round) does not:

```python
    def save(self, token: SpotifyToken) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "access_token": token.access_token,
                    "refresh_token": token.refresh_token,
                    "expires_at": token.expires_at,
                }
            )
        )
```

Both files live in the same `platformdirs.user_data_dir("Seeker")`
directory. One is `0600`. The other lands at whatever the process umask
gives — `0644` on a default macOS account — and it holds a **refresh
token**, the long-lived credential: it survives restarts and can be
exchanged for access tokens until revoked.

- [ ] **6.2.1 — Give `TokenStore.save()` the same `0600` treatment**,
  and factor the write into one shared helper both call, so the two
  cannot drift apart again. `chmod` is a no-op on Windows; keep the
  `try/except OSError: pass` shape `save_config` already established,
  and keep its comment explaining why the failure is tolerated.

- [ ] **6.2.2 — Make both writes atomic while you are there.** Both do
  `write_text` straight onto the live path: a crash, a full disk or a
  power cut mid-write leaves truncated JSON, and for the token that
  means a silent forced re-authorization. Write to a temp file in the
  same directory, `chmod` it, then `os.replace()`. Same helper, one
  place.

  **And close the asymmetry in the read path too:** `load_config`
  already tolerates a corrupt file by returning defaults;
  `TokenStore.load()` does **not** — it raises `JSONDecodeError` straight
  up through `get_valid_token()`. Give it the same tolerance. A corrupt
  token file should mean "no token" — i.e. a fresh authorization — not a
  traceback.

- [ ] **6.2.3 — Decide on the Keychain, and write the decision down.**
  The macOS-idiomatic answer is the system Keychain, and a reviewer may
  ask why it was not used. **The decision is: not in this round**, and
  the reasoning belongs in `CLAUDE.md` as a standing decision rather
  than being left as a silent omission. It adds a dependency, a second
  platform-specific code path, and a migration for an existing install,
  to protect a file that — once 6.2.1 lands — is already `0600` in the
  user's own home directory under a per-user account. `0600` plus atomic
  writes is a defensible position for a personal desktop app; *silently
  world-readable* was not. Written down, that reads as a choice; left
  out, it reads as an oversight — and that difference is exactly what a
  reviewer is looking for.

---

## 5. Part A — §6.4: `_download_album_art` reads an unbounded response
## from a URL held in the local database

**Severity: LOW.** `src/seeker/library/metadata_service.py`, in
`_download_album_art`:

```python
        response = httpx.get(url, timeout=15.0)
        response.raise_for_status()
        mime_type = response.headers.get("content-type", "image/jpeg")
```

The URL comes from `tracks.album_art_url`, populated from Spotify's API
at sync time, so it is trusted in practice. But it is read back out of a
local SQLite file, the whole body is loaded into memory with no size
cap, and the `Content-Type` header goes straight into the ID3 `APIC`
frame without validation.

- [ ] **6.4.1 — Cap the read.** A few MB is generous for cover art —
  named constant, marked untuned per this project's convention. Stream
  rather than buffering unboundedly. On rejection, log and continue
  rather than raising: art is optional, tagging is not.
- [ ] **6.4.2 — Validate before writing the tag.** Accept only
  `image/jpeg` and `image/png`, and check the **magic bytes** rather
  than trusting the header. `httpx` does not follow redirects by
  default, so that part is already correct — say so in the comment, so
  nobody "improves" it later by adding `follow_redirects=True`.
- [ ] **6.4.3 — `AlbumArtCache` never evicts.** It writes a `.bin` and a
  `.json` per unique art URL under the user *cache* directory, forever.
  The location is right and safe to clear, but a size or age cap, or a
  "Clear cache" affordance in Settings, would close it out. Lowest
  priority in this brief — include it only if the rest lands cleanly,
  and skip it explicitly rather than half-doing it.

---

## 6. Part A — §6.5 and §6.6: assessments to write down, not code

- [ ] **6.5.1 — `.env` was committed once; record the assessment.**
  `git log --all -- .env` shows three commits: `a24d243` added it,
  `12de30d` modified it, `9207333` removed it and added the ignore rule.
  The content at `12de30d` was a real `SPOTIFY_CLIENT_ID` and the
  redirect URI. `a24d243`'s `SPOTIFY_CLIENT_SECRET` was the literal
  placeholder `your_…`, never a real secret.

  **Assess this correctly rather than alarmingly.** Under PKCE the
  client ID is *public by design* — it is transmitted in the
  authorization URL on every login, and this app has no client secret at
  all. A leaked PKCE client ID is not a credential compromise.
  **Decision: no history rewrite.** Rewriting history to scrub a value
  that is public by design would cost every existing clone and every SHA
  referenced across `CLAUDE.md` and `HISTORY.md`, to gain nothing.
  Record that reasoning in `CLAUDE.md` in two lines, so that when
  someone runs a secret scanner over the repo and finds it, the answer
  is already written down instead of re-derived in a panic.

- [ ] **6.5.2 — One genuine follow-up:** if `SLSKD_API_KEY` in the
  current working `.env` was ever real *and* ever pushed anywhere,
  rotate it — `generate_api_key()` already exists. From inspection it
  never appears in a tracked commit; confirm with `git log --all -p --
  .env` and report either way.

- [ ] **6.6.1 — Warn on a non-loopback `http://` slskd base URL.**
  `SoulseekClient` sends `X-API-Key` over whatever `base_url` is
  configured. Over loopback that is fine. If a user points
  `SLSKD_BASE_URL` at a remote host over plain `http://`, the key
  crosses the network in clear. Add a validation in Settings that warns
  on that combination. Cheap, and it demonstrates the threat model was
  thought about rather than assumed away.

- [ ] **6.6.2 — Revisit the silent exception swallows — but only to
  observe, not to mass-edit.** There are roughly eleven `except: pass`
  sites and thirty-odd `except Exception:`. Most are defensible
  (best-effort chmod, cache writes, per-item batch failures that must
  not abort a batch). **This round only:** count them, list them, and
  note which swallow with no record at all. The real fix is Phase 4's
  logging work, which does not exist yet — a swallowed exception with a
  `logger.debug(..., exc_info=True)` is fine; one with nothing is a bug
  you will never hear about. Do not convert them now.

---

## 7. Part B — §14: the Dock icon after close

### 7.1 The report, verbatim

> I tested the full-screen functionality and it does close on full
> screen, but I notice that the app icon stays in the bottom dock with
> the other apps, which is confusing, as pressing the app icon from
> there does *not* open the app. One has to go to the top right icons
> section and open it through there. Trying to open it again from
> Applications also fails. Can we have the same functionality as Docker
> for instance — if you press X, the dock icon disappears, and only the
> top right small icon is left, but also being able to re-open it
> through Applications should preferably work.

### 7.2 This is two separate defects behind one symptom

Diagnose them separately: one is a genuine bug and the other is macOS
behaving exactly as configured.

#### Defect A — the reopen event arrives and is thrown away

Qt's Cocoa platform plugin implements the AppKit delegate method macOS
sends on a reopen. Its entire body
(`qtbase/src/plugins/platforms/cocoa/qcocoaapplicationdelegate.mm`) is:

```objc
- (BOOL)applicationShouldHandleReopen:(NSApplication *)theApplication
                    hasVisibleWindows:(BOOL)flag
{
    Q_UNUSED(theApplication);
    Q_UNUSED(flag);

    if (reflectionDelegate && [reflectionDelegate respondsToSelector:
            @selector(applicationShouldHandleReopen:hasVisibleWindows:)])
        return [reflectionDelegate applicationShouldHandleReopen:theApplication
                                              hasVisibleWindows:flag];

    QWindowSystemInterface::handleApplicationStateChanged(
        Qt::ApplicationActive, true /*forcePropagate*/);
    return YES;
}
```

Read what that does and does not do. **Qt does not show any window.** It
converts the reopen into one thing — an application-state change to
`Qt::ApplicationActive`, with `forcePropagate` set so it is emitted even
when the state is already Active — and returns `YES`, telling AppKit the
app handled it. Showing a window is the application's job, and Qt has
handed it the only notification it will get.

Seeker never listens for it. Confirmed at `9a55761`:

```
$ grep -rn "applicationStateChanged\|ApplicationStateChange\|
           ApplicationActivate\|installEventFilter" src/seeker/
(no matches)
$ grep -rn "class .*QApplication" src/seeker/
(no matches)
```

No handler, no `QApplication` subclass, no event filter. The reopen is
received by Qt, translated, emitted, and dropped.

**This is why both reported symptoms are one bug.** macOS routes *every*
"reopen an already-running app" gesture through that one selector:
clicking the Dock icon, double-clicking in Applications or Finder,
Spotlight, `open -a Seeker`. LaunchServices does not start a second
instance of a running bundle — it sends a reopen event to the one that
exists. All those paths dead-end in the same missing handler.

#### Defect B — the Dock icon is there because nothing has said otherwise

```
$ grep -rn "LSUIElement\|activationPolicy\|pyobjc\|AppKit" packaging/ src/ pyproject.toml
(no matches)
```

`packaging/seeker.spec`'s `BUNDLE(info_plist={...})` carries exactly
four keys — `NSHighResolutionCapable`,
`CFBundleShortVersionString`, `CFBundleVersion`,
`NSHumanReadableCopyright`. No `LSUIElement`, and no runtime
activation-policy call anywhere.

A running app whose activation policy is
`NSApplicationActivationPolicyRegular` — the default for a normal
bundled app — always shows a Dock icon, window or no window. That is
macOS working as designed. **The Dock icon is not the bug; the dead Dock
icon is.** Fixing A alone already leaves the app defensible (a Dock icon
that reopens the window, like Mail or Messages). Fixing B on top gets
the Docker-like behaviour that was asked for.

### 7.3 Fix A first, and verify it on its own

Its own commit, confirmed working **before** touching the activation
policy — because fixing B removes the Dock icon, which is the easiest
way to test A.

- [ ] **14.2.1 — Observe the state change and reopen on it.** In
  `MainWindow.__init__`, after `_build_tray_icon()`:

  ```python
  app = QApplication.instance()
  if app is not None:
      app.applicationStateChanged.connect(self._on_application_state_changed)
      self._app_state_connected = True
  ```

  ```python
  def _on_application_state_changed(self, state: Qt.ApplicationState) -> None:
      # macOS sends every "reopen a running app" gesture — Dock icon
      # click, double-click in Applications/Finder, Spotlight, `open -a`
      # — through NSApplicationDelegate's
      # applicationShouldHandleReopen:hasVisibleWindows:. Qt's cocoa
      # plugin handles that selector by emitting exactly this state
      # change (Qt::ApplicationActive, forcePropagate) and returning YES;
      # it never shows a window itself. Reopening is ours to do, and
      # this signal is the only notification we get.
      if state != Qt.ApplicationState.ApplicationActive:
          return
      if self.isVisible():
          return
      self._on_tray_open_seeker()
  ```

  **Two things about that guard, both deliberate.**

  `ApplicationActive` is not reopen-specific — it also fires on ordinary
  activation (⌘-Tab, clicking a window), and because Qt passes
  `forcePropagate=true` it fires even when the state was already Active.
  `not self.isVisible()` narrows it to the case that matters; in every
  other case `_on_tray_open_seeker()` would have been a near-no-op
  anyway.

  Guard on **`isVisible()`, not `_hidden_to_tray`.** That flag is
  deliberately not set until `_check_hidden_to_tray` confirms the hide
  at the platform level (`_HIDE_TO_TRAY_VERIFY_DELAY_MS = 400` later),
  so on the ordinary hide path it stays False for that whole window. A
  user who closes the window and immediately clicks the Dock icon must
  get it back; gating on `_hidden_to_tray` would ignore them for the
  first 400 ms. `_on_tray_open_seeker()` already resets the flag and
  bumps `_hide_request_id`, so a reopen landing mid-verification
  correctly invalidates the pending check — that machinery is already
  right, just never reachable from here.

- [ ] **14.2.2 — Disconnect it in `cleanup_before_quit`.** This is a
  connection to a **global** object (`QApplication`), not to this
  window, so this window's own destruction does not drop it. The
  codebase already has the precedent and the reasoning written down —
  `_system_scheme_connected` /
  `QGuiApplication.styleHints().colorSchemeChanged`, torn down in
  `cleanup_before_quit`. Mirror it, flag and all.

- [ ] **14.2.3 — Test what can be tested offscreen, and say what
  cannot.** A real Dock click cannot be produced under
  `QT_QPA_PLATFORM=offscreen`. What *can* be asserted is the handler's
  own contract: with the window hidden, emitting
  `applicationStateChanged(Qt.ApplicationState.ApplicationActive)`
  results in a visible window; with the window already visible, it does
  not call `_on_tray_open_seeker` (assert the poll methods are not
  re-entered); with a non-Active state, nothing happens. **Do not write
  a comment claiming this proves the Dock click works** — it proves the
  handler works, and those are different sentences.

- [ ] **14.2.4 — Real-desktop verification, all four routes, both close
  paths.** On the real Mac, with a real build, from both a normal close
  *and* a fullscreen close: (1) click the Dock icon, (2) double-click
  Seeker in Applications, (3) Spotlight → Seeker, (4) `open -a Seeker`.
  Each must restore the window at its pre-close geometry, focused and in
  front. **Report all eight combinations individually.** Anything you
  could not click is "not verified", never "done".

### 7.4 Fix B: drop the Dock icon while hidden to the menu bar

The mechanism is `NSApplication`'s activation policy: `Regular` (Dock
icon + menu bar) while the window is up, `Accessory` (menu bar extra
only, no Dock icon) while it is hidden.

**Why not just set `LSUIElement` in the Info.plist**, which is what
Apple's own DTS engineers recommend when asked this: because
`Accessory`/`LSUIElement` means *no Dock icon **and no menu bar**, ever*
— including while the Seeker window is open and in use. The Help menu
(About Seeker, Check for updates), the application menu and ⌘Q would all
disappear. That is a much larger change than was asked for. Switching
dynamically gives exactly the described behaviour: icon while the window
is up, none while it is not.

**Be honest about the risk in the code.** That DTS thread exists because
programmatic `setActivationPolicy:` has reported flakiness — icons
lingering, or flashing before disappearing — when called at launch
around `NSApplicationMain`. Calling it at runtime, on the main thread,
in response to a window closing is a different situation and is the
pattern menu-bar apps normally use. **It is still a platform claim, and
this project has been wrong about confident unverified platform claims
twice.** Verify live before writing a comment that says it works.

- [ ] **14.3.1 — Choose the binding: PyObjC.** Add
  `"pyobjc-framework-Cocoa>=10.0; sys_platform == 'darwin'"` to
  `dependencies` in `pyproject.toml`, then:

  ```python
  def _set_dock_icon_visible(visible: bool) -> None:
      if sys.platform != "darwin":
          return
      from AppKit import (
          NSApp,
          NSApplicationActivationPolicyAccessory,
          NSApplicationActivationPolicyRegular,
      )
      NSApp().setActivationPolicy_(
          NSApplicationActivationPolicyRegular if visible
          else NSApplicationActivationPolicyAccessory
      )
  ```

  **The reasoning, and the fallback.** The alternative is hand-rolled
  `ctypes` against `libobjc` — no dependency, about 25 lines. It carries
  a real trap: `objc_msgSend` is variadic, and on Apple Silicon you
  **must** cast it to a correctly-typed `CFUNCTYPE` per call signature
  rather than mutating `argtypes` on the shared symbol, or arguments go
  into the wrong registers and you get silent garbage or a crash. Given
  `CLAUDE.md`'s own "prefer the idiomatic/correct approach over the
  fastest one", and this project's history with confidently-wrong
  platform code, the maintained binding is the right call.

  **Gate it on a measurement.** Report the `.dmg` size before and after.
  If PyObjC adds more than ~15 MB, say so and raise the ctypes fallback
  with the owner rather than deciding alone. Confirm PyInstaller picks
  it up — you will likely need `hiddenimports=["AppKit", "Foundation",
  "objc"]` in `packaging/seeker.spec` — and **a real `.dmg` build
  launched from `/Applications` is the only thing that proves it**, not
  a dev-mode run.

  Note the deferred import inside the function is deliberate and must
  carry a scoped `# noqa: PLC0415` with a reason, matching how the three
  genuine heavy-dependency deferrals in `src/` are already handled.

- [ ] **14.3.2 — Flip to `Accessory` only once the window is genuinely
  gone, never synchronously inside `closeEvent` on the fullscreen
  path.** This is the round-7 lesson applied to a new call: the
  fullscreen close is an AppKit animation running for several hundred
  milliseconds *after* `closeEvent` returns, and changing the process's
  activation policy mid-transition is precisely the shape of operation
  that produced an empty, unclosable window in round 6.

  The codebase already owns the right witness. `_check_hidden_to_tray`
  consults `_is_exposed_at_platform_level()` — the real `QWindow`'s own
  `isExposed()`, updated by the platform plugin from actual
  show/hide/expose notifications rather than from Qt's own "did someone
  call `hide()`" bookkeeping. Hang the policy change off that:

  - **Ordinary hide path:** call `_set_dock_icon_visible(False)` from
    `_check_hidden_to_tray`, in the branch that already confirms the
    window is not exposed and sets `_hidden_to_tray = True`. No new
    timer, no new state.
  - **Fullscreen path:** this branch deliberately arms *no* verification
    timer, for reasons its own comment sets out at length, and that must
    not change. Give it a **policy-only** deferred check instead — one
    that re-reads `_is_exposed_at_platform_level()` and either flips the
    policy or reschedules once, and that **never calls `hide()` and
    never touches `_hidden_to_tray`**. It cannot manufacture the failure
    that comment warns about because it takes no corrective action on
    the window at all. Carry `_hide_request_id` through it the same way,
    so a stale check cannot fire after a reopen.

- [ ] **14.3.3 — Flip back to `Regular` at the top of
  `_on_tray_open_seeker`, before `showNormal()`.** Order matters: the
  window must be shown by an app that is already `Regular`, or it can
  come up behind other applications. `_on_tray_open_seeker` already
  calls `raise_()` and `activateWindow()`; verify on the real desktop
  that those suffice after a policy change. **If the window comes back
  behind another app**, the known remedy is an explicit
  `NSApp().activateIgnoringOtherApps_(True)` after the switch — add it
  only if you actually observe the problem, and say in the comment that
  you observed it.

- [ ] **14.3.4 — Never let the app end up `Accessory` with no way
  back.** That state is unrecoverable for the user: no Dock icon, and if
  the tray icon is also missing, no UI at all. Two guards:
  - Only switch to `Accessory` when `self._tray_icon is not None and
    self._tray_icon.isVisible()`. `closeEvent` already refuses to
    hide-to-tray without a real tray icon; the policy change must obey
    the same precondition.
  - Force `Regular` back in `cleanup_before_quit`, so a quit never
    leaves the process in an odd state mid-teardown.

- [ ] **14.3.5 — Check what the menu bar does across the transition.**
  `Accessory` apps have no menu bar. Confirm on the real Mac that after
  hide → reopen the Help menu is back and functional (About Seeker,
  Check for updates) and ⌘Q still quits. Screenshot the menu bar after a
  reopen. **If the menu bar does not return, stop and report** — that is
  a blocker for 14.3, and the owner keeps the Dock icon rather than
  losing the menu.

### 7.5 The one claim I could not verify

Fix B removes the Dock icon, so afterwards the only remaining
"reopen from outside" routes are Applications, Finder, Spotlight and
`open -a`. Those all depend on this being true:

> **UNVERIFIED:** an already-running app whose activation policy is
> `Accessory` still receives `applicationShouldHandleReopen:` when the
> user launches its bundle from Finder/Applications, rather than
> LaunchServices starting a second instance.

It is probably true — LaunchServices keys on the bundle identifier, not
the activation policy — but it was not observed, and an unmarked
confident claim about platform behaviour this project has already been
wrong about twice is a liability.

- [ ] **14.4.1 — Test this explicitly before 14.3 is called done.** With
  the app hidden and in `Accessory` mode, double-click Seeker in
  `/Applications`. Expected: the existing window comes back. Watch for
  the failure mode too — a *second* Seeker process starting (`ps aux |
  grep -i seeker`, and whether two tray icons appear).
- [ ] **14.4.2 — If it is false, 14.3 is not shippable as designed.**
  Report it; do not work around it with a lock file or a single-instance
  guard on your own initiative. The honest fallback is to ship 14.2
  only, keep the Dock icon, and let the owner decide — a Dock icon that
  correctly reopens the window is what every stock Mac app does.

### 7.6 While you are in this code: a constant that contradicts its comment

`src/seeker/ui/main_window.py:6342-6352`:

```python
    # Roadmap item E1.4 (round 7, corrected after a second review) —
    # untuned: the real AppKit exit-fullscreen-then-close animation
    # measures somewhere in the 0.5-1s range (per this item's own
    # diagnosis, still not measured against real hardware from this
    # session), so this is a round number comfortably above that, not a
    # verified figure.
    _HIDE_TO_TRAY_VERIFY_DELAY_MS = 400
```

**400 ms is not "comfortably above" a 0.5–1 s range; it is below all of
it.** Either the value or the comment is wrong. It does not bite today —
the fullscreen path deliberately arms no verify timer, so this delay
only applies to the ordinary hide, where 400 ms is probably fine — but
it is exactly the "comment asserting behaviour that does not match the
code" pattern this project's convention exists to prevent, sitting in
the code you are about to build on.

- [ ] **14.5.1 — Resolve it with a measurement, not a guess.** You will
  already be timing the fullscreen close transition for 14.3.2. Measure
  it — log the interval between `closeEvent` and the first
  `isExposed() == False` — pick the constant from that number, and
  rewrite the comment to state what was measured, on which macOS and
  PySide6 version. If the ordinary hide path settles well under 400 ms,
  say that instead. Say something true.

---

## 8. Reporting

**Ordering:** 0.1 (push + CI) → §6.1 → §6.2 → §6.4 → §6.5/§6.6 →
§14.2 → §14.3 → §14.5.

**Commit discipline:** one commit per numbered item. §14 in particular
is three separable commits — reopen handling, activation policy, the
constant — each verified before the next.

**Every item closes with the three numbers**, quoted exactly, with the
skip named. `ruff check src tests` must stay at **0**.

**§14.3 additionally requires a real `.dmg` build installed to
`/Applications` and exercised** — dev-mode runs do not prove the
PyInstaller side of 14.3.1. Screenshots: Dock with the window open, Dock
with the window closed (icon absent), menu bar after a reopen.

**§6.1.1 requires a second device on the same network** to confirm the
port is actually closed. If you cannot get one, say so and mark it not
verified rather than inferring it from the compose file.

**Report 14.4.1's result explicitly either way**, because it decides
whether 14.3 ships at all.

### The failure mode to design against

Not "some items were skipped" — skipping §6.4.3, or §14.3 if 14.4.1
comes back false, is a perfectly good outcome when stated. The failure
mode is **a green suite over a changed app**, and §14 touches
`closeEvent` and the tray, which no headless test can fully cover. Look
at the app. Click the four reopen routes yourself.

One related caution: `test_close_event_falls_back_to_real_close_when_no_
tray` flaked once during Phase 1 and did not reproduce in four further
runs; it is recorded in `CLAUDE.md`'s open issues. **It covers exactly
the code §14 modifies.** If it fires during this work it is a known
prior, not a fresh mystery — and it is a reason to look harder, not to
reach for `pytest-rerunfailures`.

---

## Appendix — verified line references at `9a55761`

Re-derive these after your first commit; they move.

| Reference | Path:line |
|---|---|
| `MainWindow.__init__`, `_hide_request_id` init | `src/seeker/ui/main_window.py:1401` |
| `_build_tray_icon` | `src/seeker/ui/main_window.py:6107` |
| `_on_tray_open_seeker` | `src/seeker/ui/main_window.py:6245` |
| `cleanup_before_quit` (disconnect precedent) | `src/seeker/ui/main_window.py:6288` |
| `_HIDE_TO_TRAY_VERIFY_DELAY_MS` | `src/seeker/ui/main_window.py:6352` |
| `closeEvent` (fullscreen branch inside) | `src/seeker/ui/main_window.py:6354` |
| `_show_tray_hide_notice_once` | `src/seeker/ui/main_window.py:6419` |
| `_confirm_hidden_to_tray` | `src/seeker/ui/main_window.py:6437` |
| `_is_exposed_at_platform_level` | `src/seeker/ui/main_window.py:6476` |
| `_check_hidden_to_tray` | `src/seeker/ui/main_window.py:6485` |
| `TokenStore.save` (no chmod) | `src/seeker/spotify/token_store.py:11-20` |
| `save_config` (has chmod) | `src/seeker/config_store.py` |
| slskd base URL (loopback) | `src/seeker/ui/wizard.py:50` |
| `generate_api_key` | `src/seeker/docker_setup.py:171` |
| Two slskd credential pairs | `src/seeker/docker_setup.py:178-190` |
| `bring_up_slskd` env dict | `src/seeker/docker_setup.py:364-372` |
| Album art fetch | `src/seeker/library/metadata_service.py`, `_download_album_art` |
| Port bindings, remote configuration | `docker-compose.yml:15-22` |
| `BUNDLE(info_plist={...})` — no `LSUIElement` | `packaging/seeker.spec` |

## Appendix — external sources

- slskd configuration documentation (web UI auth defaults, API keys,
  `remote_configuration`):
  <https://github.com/slskd/slskd/blob/master/docs/config.md> and
  <https://github.com/slskd/slskd/blob/master/docs/docker.md>
- RFC 9700, *Best Current Practice for OAuth 2.0 Security*:
  <https://www.rfc-editor.org/info/rfc9700/>; RFC 8252 §7.3 on loopback
  redirect URIs for native apps
- Qt's Cocoa platform plugin source,
  `src/plugins/platforms/cocoa/qcocoaapplicationdelegate.mm`
  (`applicationShouldHandleReopen:hasVisibleWindows:`); QTBUG-10546
- Apple's `NSApplicationDelegate` documentation for
  `applicationShouldHandleReopen(_:hasVisibleWindows:)`
- Apple Developer Forums on `NSApplicationActivationPolicyAccessory` not
  reliably hiding the Dock icon:
  <https://developer.apple.com/forums/thread/735682> — the source of the
  DTS recommendation to prefer `LSUIElement`
