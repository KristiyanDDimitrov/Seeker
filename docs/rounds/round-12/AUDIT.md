# Round 12 — security re-audit (S6)

**Author:** Claude Code, round 12 S6, 2026-10-09. **Base:** `eaf9d86`.
**Mode:** read-only on `src/`. Every finding cites what was read, run
or measured. Anything not observed is marked UNVERIFIED. Nothing was
fixed in this row. The fix rows are S7 (dependencies, CI, packaging),
S8 (application) and S16 (release engineering).

**Kris reads this before S7 starts.** Rows marked **[ASK]** change
behaviour Kris can see. They need a yes, or a written acceptance.

---

## Summary

**No critical or high findings.** Round 11's hardening (R11 §9, §10)
holds wherever this audit re-read it: the 0600 credential writes,
the token-refresh lock, the quoted slskd path segments, the album-art
host allowlist and its 10 MB stream cap, the OAuth state and PKCE,
plain-text rendering of peer strings, SQL parameters, loopback-only
web UI ports, and SHA-pinned actions.

What is left is one dependency fix that gates the release, a class
of risk that no tool reports (peer files reach memory-unsafe
decoders), a licence-compliance gap in the DMG, and a set of low
and informational items.

| ID | Sev. | Finding | Fix row |
|---|---|---|---|
| S-01 | Medium | `urllib3 2.7.0`: three advisories (unreachable in Seeker's flows) | S7 §7.1 |
| S-02 | Medium | CI has no dependency audit, and `pip-audit` cannot see bundled native libraries | S7 §7.2 |
| S-03 | Medium | Peer-supplied files reach native decoders (libsndfile 1.2.2, ffmpeg) without isolation | S8 (accept + track) **[ASK]** |
| S-04 | Medium | The DMG ships GPL/LGPL code with no licence texts | S16 **[ASK]** |
| S-05 | Low | The OAuth callback trusts `error` before it checks `state` | S8 |
| S-06 | Low | A peer's basename is placed unsanitized (leading dot, control and bidi characters) | S8 **[ASK]** |
| S-07 | Low | Data, log and download dirs take the umask (world-readable on Linux) | S8 |
| S-08 | Low | The slskd image is pinned by tag, not digest | S7 §7.3 |
| S-09 | Low | No response-size cap on slskd, Spotify and GitHub JSON bodies | S8 (accept, or cap slskd's search body) |
| S-10 | Low | slskd secrets live in the container's environment | Accept (written below) |
| S-11 | Info | `docker`, `ffmpeg`, `open` and libchromaprint resolve from user-writable Homebrew prefixes | Accept |
| S-12 | Info | `test_plain_text.py`'s sweeps have three blind spots (current code is clean) | S8 |
| S-13 | Info | CI checkout persists its token; `brew install chromaprint` is unpinned | S7 §7.3 |
| S-14 | Info | Ad-hoc signed, no hardened runtime; bundle ID still `com.seeker.app` | S16 |
| S-15 | Info | Defaults: listeners and outbound calls, checked; S14 must keep the update check disclosed | S14 |

Severity scale. **Critical:** remote code execution, or credential
theft without user action. **High:** either one given a plausible
precondition. **Medium:** real exposure with a hard precondition, or
a release gate. **Low:** defence in depth. **Info:** recorded, no
change needed.

**Status.** Fixed in S7 (HISTORY §199): S-01 (`d2dc571`), S-02
(`4fbcd8e`, `34ce3a3`), S-08 (`c67b589`), S-13 (`06319a1`).
**Kris's decisions (2026-10-09):** S7 and S8's hardening (S-05,
S-07, S-12) approved. S-06: sanitize at placement. S-03: accept and
track, (a) and (b) only, with no format/extension check. S-09: accept
for slskd, Spotify and GitHub alike, with no cap. S-04 (the GPL
wording) is still open for S16.
**Fixed in S8 (HISTORY §200):** S-05 (`e3c0154`), S-07 (`17b67c0`),
S-12 (`7123da0`), S-06 (`a4baed4`). **Accepted in writing in S8:**
S-03 (a)+(b), S-09, S-10 and S-11, each under its finding below and
in CLAUDE.md → "Accepted risks". Open: S-04 and S-14 (S16), S-15
(S14).

---

## 1. Threat model

**Assets.**
- **Spotify token cache** (`spotify_token.json`; the refresh token
  rotates, PKCE, scope `playlist-read-private`).
- **slskd API key and both logins** (Soulseek network and web UI), in
  `config.json` and in the slskd container's environment.
- **Music files** in the library locations, and the downloads.
- **The database** (`seeker.db`: playlists, paths, match history;
  no credentials, by schema) and its `.bak-*` copies.
- **Logs** (`~/Library/Logs/Seeker/seeker.log`).

**Trust boundaries,** from least trusted:
1. **Remote Soulseek peers.** They control filenames, file bytes,
   usernames and search-result metadata. They reach Seeker only
   through slskd's REST API, and through files slskd writes.
2. **The LAN.** Only slskd's peer port `50300` is published on every
   interface. Seeker itself listens on nothing that faces the LAN.
3. **Spotify, GitHub and the Spotify image CDN.** Reached over TLS
   (httpx defaults: certificates verified, redirects not followed).
4. **slskd and Docker.** Local, but slskd relays peer data.
   `127.0.0.1:5030`, authenticated with `X-API-Key`.
5. **Other local users.** Separated by file permissions (S-07).
6. **The local user and their processes.** Fully trusted. A
   same-user attacker can already read every asset, so findings that
   need one are Info.

**Entry points.** slskd JSON (search results, transfer states, logs,
shares); files slskd writes, which Seeker locates, moves, tags,
analyses and fingerprints; Spotify API JSON and album-art bytes;
GitHub's `/releases/latest` JSON; the OAuth callback on
`127.0.0.1:8888` while an authorization waits; `config.json`, `.env`
in dev, and the CLI's arguments.

---

## 2. Subprocess calls (brief item 2)

There are 12 call sites, all argument lists. Re-read in full:
`ui/pages/static_pages.py:41-45` (`open`/`explorer`/`xdg-open`
`<path>`), `ui/wizard.py:590-597` (`open -a Docker`; `cmd /c start ""
"Docker Desktop"`, constant strings), `soulseek/docker_setup.py:39`
(`/usr/libexec/path_helper -s`, absolute), `:121`/`:133` (`docker
--version`/`info`), `:381` (`docker compose -f <compose> up -d`),
`soulseek/sharing_service.py:313`/`:596` (`docker inspect <name>
--format …`), and `audio/fingerprint.py:378` (`ffmpeg -v error -i
<path> …`).

- No `shell=True`. No user- or peer-controlled executable. Every
  `docker` call has a timeout. The two `open` calls and `ffmpeg` have
  none: the `open`s return at once, and `ffmpeg` is read as a stream.
- **`ffmpeg -i <path>` with a peer-named file:** `str(path)` is an
  absolute library path, so it never starts with `-` and cannot be
  read as an option. ffmpeg does interpret `protocol:` prefixes, but
  an absolute path starts with `/` and is not one. Clean.
- **PATH.** `ensure_full_path_environment()` puts `path_helper`'s
  PATH first, then the inherited PATH, then `/opt/homebrew/bin` and
  `/usr/local/bin`. `docker`, `ffmpeg` and `open` resolve through it.
  See S-11.

## 3. Network calls (brief item 3)

Every call is a module-level `httpx` function, so TLS is verified
and redirects are not followed (httpx defaults), and every call sets
an explicit timeout (10–15 s; 120 s only for `compose up`, which is a
subprocess).

| Call | Where | Body cap |
|---|---|---|
| Spotify API | `spotify/client.py:165` | none (S-09) |
| Spotify token | `spotify/auth.py:55,82` | none (S-09) |
| Album art | `library/metadata_service.py:1303` | 10 MB, streamed; host allowlist; MIME sniffed from bytes |
| slskd | `soulseek/client.py`, `docker_setup.py:245,257,325` | none (S-09) |
| GitHub | `update_check.py:128` | none (S-09) |

**The update check's trust in GitHub.** It downloads nothing and
runs nothing. It reads `tag_name` (parsed as `packaging.Version`; a
malformed one becomes UNAVAILABLE) and `html_url`, which is offered
only when it starts with `https://github.com/KristiyanDDimitrov/Seeker/`
(`_trusted_release_url`; the trailing slash rules out a
`Seeker-evil` sibling). The dialog is `PlainText`, and its one
rich-text branch `html.escape`s both values (`main_window.py:961-983`).
A compromised GitHub account could point the link at a malicious
release, but nothing in Seeker can verify a release when the
releases are themselves ad-hoc signed (S-14). Accepted while it
offers a link, never a download.

## 4. The filesystem (brief item 4)

- **Placement** (`soulseek/placement.py`). The remote filename's
  separators are normalised (`\` to `/`). The basename is refused
  when it is empty, `.` or `..`. Its parent is used only as a single
  path component under the download dir. The destination is
  `<location>/<validated subfolder>/<basename>`, so traversal is
  closed. The basename is otherwise placed **verbatim**: S-06.
- **Extensions** come from the filename (`client.derive_extension`)
  and gate downloads (`is_downloadable_extension`). A file's
  *contents* are not checked, and decoders sniff content: S-03.
- **Collisions.** `resolve_collision` runs just before `shutil.move`.
  There is a check-then-move window, but the only writer that could
  race it is Seeker itself, and the move is serialised per poll.
  Accepted.
- **Delete** (`files/deletion.py`). `Path.unlink` removes a symlink,
  never its target. `same_file` (inode equality) guards duplicate
  deletes. Clean.
- **Temp files** (`files/atomic.py`). `O_CREAT|O_EXCL`, created 0600
  for credentials, fsync'd, renamed, and unlinked on any failure.
  Clean.
- **Permissions, measured on Kris's Mac (stat only).**
  `config.json` and `spotify_token.json` are `-rw-------`.
  `seeker.db` and both `.bak-*` copies are `-rw-r--r--`.
  `Seeker/`, `slskd-data/` and `~/Library/Logs/Seeker/` are
  `drwxr-xr-x`, and `seeker.log` is `-rw-r--r--`. These are
  protected only because `~/Library/Application Support` and
  `~/Library/Logs` are `drwx------`. See S-07 for other platforms.

## 5. Secrets (brief item 5)

- **Kris's real log** (`seeker.log`, 12 KB, the only file; read-only)
  has **0** lines matching `api[_-]?key|token|password|secret|bearer|
  authorization|refresh`, and 0 matching `code=|state=|X-API-Key|
  access_token`.
- **Source.** One logger call mentions a token, and it carries no
  value (`auth_manager.py:85`). `config_store._checked_value` logs a
  type, never the value. The only f-string with a secret builds the
  `Authorization` header (`client.py:168`). `httpx.HTTPStatusError`
  text carries the URL, and no URL here carries a secret (the slskd
  key is a header; Spotify's are in the POST body).
- **`SlskdBringUpError`** carries `docker compose`'s stderr. Compose
  names an unset variable, not a value (UNVERIFIED for every compose
  error shape). Low enough not to rank.
- **Generation.** The API key and web password use
  `secrets.token_urlsafe(32)`, the PKCE verifier 96 bytes, and the
  state 32 bytes.

## 6. Qt rendering (brief item 6)

`tests/test_plain_text.py`: **9 passed**. Its exclusions, read per
working agreement 5:
- `plain_text.py` itself is skipped. It is the one module that sets
  formats, and it is tested directly.
- `continue` on non-`FunctionDef` nodes, and on calls with too few
  arguments. Both are structural, and neither can hide a sink.

**Read by hand, every `RichLabel(...)` call site in `ui/`
(11):** ten take a `help_text` constant. The About body
(`dialogs.py:90-101`) `html.escape`s the version and build identity.
The one `RichText` message box escapes both of its values. The
elided-text tooltip goes through `plain_tooltip`. No `setHtml`,
`QTextEdit`, `QTextBrowser`, `setMarkdown` or `ToolTipRole` writer
exists in `src/`. Tray `showMessage` takes Seeker's own counts.
Clean. The blind spots are S-12.

## 7. SQL (brief item 7)

Every f-string SQL statement was read. The interpolated fragments
are only:
- module constants (`_COLUMNS`, `_OLD_ROW_JOIN`, `_SAME_CONTENT`,
  the column groups of `location_merge_repository.py`);
- `_status_in(...)` over `DownloadStatus` sets, which emits `?`
  placeholders;
- `', '.join('?' …)` (`local_file_repository.py:332`);
- `_add_column_if_missing`'s table, column and type, all literals at
  its 11 call sites (`connection.py:66-81`).

Every value is a parameter. **Clean.**

## 8. Docker and Compose (brief item 8)

- **Template and per-user copy.** Kris's copy differs from the
  template only in a comment. Ports: `127.0.0.1:5030`,
  `127.0.0.1:5031`, and `50300` on every interface (peers need it).
  Mounts: `/app` read-write, the share `:ro`.
  `SLSKD_REMOTE_CONFIGURATION=false`. The image is
  `slskd/slskd:0.26.0`.
- **Advisories.** `gh api repos/slskd/slskd/security-advisories`
  returns none, and the GitHub advisory database has no `slskd`
  entry. 0.26.0 is upstream's latest release (2026-07-19).
- **Mounting is not sharing.** slskd 0.26.0's Dockerfile sets no
  shared-directory default (read at the tag). Whether slskd's own
  built-in config shares anything by default is UNVERIFIED; checking
  it needs a fresh container, never Kris's.
- **Image pin:** S-08. **Secrets in the environment:** S-10.

## 9. Packaging (brief item 9)

Inspected `dist/Seeker.app`, built 2026-10-08 13:46 (read-only).
- **Absent, as required:** `.env*`, `CLAUDE.md`, `test_*.py`, any
  `*.db`, `config.json` and token files.
- **Signature:** `flags=0x2(adhoc)`, `Signature=adhoc`, no
  TeamIdentifier, no hardened runtime, no entitlements.
  `CFBundleIdentifier` is `com.seeker.app`. See S-14.
- **Bundled versions:** Python 3.13 with OpenSSL 3.5.7 and SQLite
  3.53.1; PySide6/Qt 6.11.2; libsndfile 1.2.2 (soundfile 0.14.0);
  librosa 1.0.0; numba 0.67.0; mutagen 1.48.1; httpx 0.28.1;
  `certifi`'s CA bundle. libchromaprint is not bundled: it loads
  from Homebrew.
- **Licence texts:** none for Qt, PySide6, mutagen or soxr: S-04.

## 10. Dependencies (brief item 10)

`uvx pip-audit -r <(uv export --no-dev --locked --no-hashes)`, 119
packages: **3 known vulnerabilities in 1 package**, all `urllib3
2.7.0` (PYSEC-2026-4175/4176/4177, fixed in 2.8.0). Dev
dependencies: **none**.

**Licences** (`pip-licenses`, runtime environment). Everything is
permissive except:

| Package | Licence | Bundled? |
|---|---|---|
| PySide6, shiboken6 (Qt) | LGPL-3.0 / GPL-2.0 / GPL-3.0 | yes, dynamically linked |
| mutagen | GPL-2.0-or-later | yes |
| soxr | LGPL-2.1-or-later | yes |
| pyinstaller | GPL-2.0 with the bootloader exception | the bootloader only |
| libchromaprint | LGPL-2.1-or-later | no (Homebrew) |
| slskd | AGPL-3.0 | no (pulled by Docker) |

## 11. Defaults (brief item 11)

**Listening.** The OAuth callback binds `127.0.0.1`, and only while
an authorization waits (at most 300 s). slskd listens on `5030`/`5031`
(loopback) and `50300` (every interface). Nothing else.

**Off the machine without asking: nothing.** The timers (2 s
display, 20 s backend, the wizard's 2 s health poll) reach only
local slskd. Spotify is called on Sync, Ctrl+R or the Dashboard's
next-step action. Album art is fetched while tagging. GitHub is
called only from Help → "Check for updates…". **S14 changes that
last one**: see S-15.

---

## Findings

### S-01 — `urllib3 2.7.0` has three advisories · Medium

**Evidence.** §10's `pip-audit` run. The chain is `requests` ←
`pooch` ← `librosa`. Nothing in `src/` imports `requests`,
`urllib3` or `pooch`, or calls `librosa.ex` (grep, 0 hits), so the
vulnerable code is unreachable in Seeker's flows. It is ranked
Medium only because the round's exit criterion is `pip-audit`
reporting 0.

**Exploit sketch.** It needs Seeker to make urllib3 requests to an
attacker's server. It never does.

**Fix (S7 §7.1).** Lock `urllib3>=2.8.0` (`uv lock
--upgrade-package urllib3`, or a constraint if `requests` caps it).
The failing check first: `pip-audit` reporting the three IDs.

### S-02 — No dependency audit in CI; native libraries are invisible to it · Medium

**Evidence.** `.github/workflows/ci.yml` runs ruff, mypy and pytest
only. `pip-audit` reads Python package metadata, so it cannot see
libsndfile inside soundfile's wheel, Qt inside PySide6, or the OpenSSL
and SQLite inside Python (§9).

**Fix (S7 §7.2).** Add the brief's job: `pip-audit` over `uv export
--no-dev --locked`, failing on any finding, with an ignore list whose
entries each carry an expiry date. Then record the native versions
(§9) in `docs/packaging.md`, so that S16 compares them at each
release: a human check, written down.

### S-03 — Peer files reach memory-unsafe decoders without isolation · Medium **[ASK]**

**Evidence.** A downloaded file is opened by mutagen (pure Python)
for tags, by libsndfile 1.2.2 for BPM, key and loudness, and by
`ffmpeg` (Homebrew 9.0.1) for fingerprints. The extension gate
checks the *name*, but libsndfile and ffmpeg detect format from
content, so a peer's `.flac` or `.wav` can carry any format they
parse. Distribution trackers list decode-side issues open against
libsndfile 1.2.2: CVE-2026-37555 (IMA ADPCM; impact unstated),
CVE-2025-56226 (an mpeg_l3 memory leak), and CVE-2024-50612
(ogg_vorbis, an out-of-bounds read whose function is encoder-side).
No newer libsndfile release exists for soundfile to ship (UNVERIFIED
past soundfile 0.14.0's wheel).

**Exploit sketch.** A peer answers a common search with a crafted
file. Kris downloads it and analysis runs, which at best crashes
Seeker's worker. Memory corruption leading to code execution would
need an unpublished bug.

**Fix (S8, [ASK]).** No cheap complete fix exists: decoding in a
sandboxed subprocess is real work with a real cost. Proposed:
(a) **accept**, with the reason written here and in CLAUDE.md: a
single-user tool, and Kris chooses each download;
(b) S-02's version record, so that a libsndfile or ffmpeg fix is
taken promptly;
(c) optionally, refuse to analyse a file whose sniffed container
does not match its extension (`soundfile.info().format` against
the name). That changes which files are analysed, so it needs
Kris's yes.

**Status (S8): accepted, (a) and (b); no (c), by Kris's decision.**
The reason: Seeker is a single-user desktop tool, Kris chooses each
download and its peer, and the one complete fix (decoding in a
sandboxed subprocess) costs more than the exposure, which today is a
crashed analysis worker. Tracking: `docs/packaging.md` → "Native
libraries" lists the advisories open against libsndfile 1.2.2; the
first soundfile wheel or ffmpeg release that fixes one is taken at the
next release.

### S-04 — The DMG ships GPL/LGPL code with no licence texts · Medium **[ASK]**

**Evidence.** §9 and §10. The bundle contains mutagen
(GPL-2.0-or-later), Qt/PySide6 (LGPL-3.0) and soxr (LGPL-2.1+), but
no `COPYING` or `LICENSE` for any of them. Only numpy's,
`_soundfile_data`'s and Lucide's licence files are in the bundle.
The About dialog names the licences (`help_text.py:1450`) but does
not carry their texts. Seeker's own source is MIT. A binary that
combines it with mutagen is distributed under the GPL's terms, which
require the licence text and an offer of the corresponding source.
The LGPL requires Qt's text, and that a user can replace the
library, which one-folder mode allows. This is not legal advice.

**Fix (S16, [ASK]).** Ship a `licenses/` folder in the bundle (the
full GPL-2.0, LGPL-3.0 and LGPL-2.1 texts, plus each package's own
notice). State in the README and the release notes that the macOS
binary is distributed under GPL-2.0-or-later as a combined work,
with its source at the tagged commit. Kris decides the wording.

### S-05 — The OAuth callback trusts `error` before it checks `state` · Low

**Evidence.** `spotify/callback_server.py:97-103`: the first GET to
`/callback` ends the wait, whatever it carries.
`auth_manager.py:149-157` raises `"Spotify authorization failed:
{error}"` **before** it compares `state`.

**Exploit sketch.** During the up-to-5-minute wait, any web page
Kris has open (an `<img>` to `http://127.0.0.1:8888/callback?error=…`)
or any local process can end the authorization, and put its own
sentence into Seeker's error message. That is a denial of the login
plus a social-engineering line. `state` still blocks code
injection.

**Fix (S8).** Check `state` first. A request without the expected
`state` gets a 400 and does **not** end the wait. Only a matching
request's `error` is shown. Test first: a wrong-state `error=`
request followed by a good callback still succeeds.

**Status: fixed in S8 (`e3c0154`).**

### S-06 — A peer's basename is placed unsanitized · Low **[ASK]**

**Evidence.** `placement.py:250-256` builds the destination name from
the remote basename as-is. CLAUDE.md routes every *Seeker-built* name
through `clean_path_component`. A peer-built name skips it.

**Exploit sketch.** A peer names a file `.hidden.mp3` (it lands
invisible in Finder), or uses U+202E to make `song[RLO]3pm.exe` read
as a different extension. macOS will not run an `.mp3`, and the
extension gate holds, so this is disguise and confusion, not
execution. A name over 255 bytes fails the move (an OSError, which is
reported).

**Fix (S8, [ASK]: it renames downloads).** At placement, pass the
basename through `clean_path_component`, or a peer-name variant of
it that strips control and bidi characters and a leading dot, while
`_locate_completed_file` keeps matching the raw name slskd wrote.
Test first, with the three names above.

**Status: fixed in S8 (`a4baed4`)** through `files/naming.py::
clean_peer_filename`. APFS took a 504-byte name (its limit counts
characters, observed), so a long name reaches slskd's folder on a Mac
and failed only on an ext4 or ExFAT destination.

### S-07 — Data, log and download dirs take the umask · Low

**Evidence.** §4: everything except the two credential files is
created at the umask (`022`). On macOS the parent `~/Library/...`
dirs are 0700 (measured), so nothing is exposed. On Linux,
`platformdirs` puts the data under `~/.local/share/Seeker`, whose
parents are usually 0755 (UNVERIFIED, no Linux host): another local
user could read the DB (paths, playlists), the logs and the
downloads. slskd's image sets `SLSKD_UMASK=0022` for what it writes
(read in its Dockerfile).

**Fix (S8).** Create Seeker's data and log dirs 0700 (`mkdir(mode=)`
plus a `chmod` of an existing dir) where they are first made. Test
first on a temp dir. The DB file itself can stay at the umask behind
a 0700 dir.

**Status: fixed in S8 (`17b67c0`)**, the album-art cache dir too.

### S-08 — The slskd image is pinned by tag, not digest · Low

**Evidence.** `docker-compose.yml`: `image: slskd/slskd:0.26.0`. A
tag is mutable on Docker Hub. A fresh install pulls whatever the tag
points at then.

**Fix (S7 §7.3).** `slskd/slskd:0.26.0@sha256:<digest>`, the digest
read with `docker buildx imagetools inspect` (registry metadata only;
never touch the running container). Extend
`tests/test_compose_template.py` to require `@sha256:`. Add the
`docker` ecosystem to `dependabot.yml`, if Dependabot can bump a
compose image there (UNVERIFIED). The per-user copy is never
re-seeded (§140), so an existing install keeps its own line, which
is correct.

### S-09 — No response-size cap on JSON bodies · Low

**Evidence.** §3. Only album art streams with a cap. slskd's search
body is bounded by slskd's own per-search response and file limits
(UNVERIFIED defaults for 0.26.0), not by Seeker. Spotify and GitHub
are TLS-authenticated.

**Exploit sketch.** It needs a hostile slskd or a TLS-terminating
attacker. It is a memory denial of service, nothing more.

**Fix (S8, optional).** Accept for Spotify and GitHub, in writing.
For slskd's `includeResponses` fetch, optionally stream it with a cap
(say 64 MB) and treat an overflow as a failed search. Kris's call on
whether it is worth a commit.

**Status (S8): accepted for all three hosts, no cap, by Kris's
decision.** The reason: Spotify and GitHub are reached over
authenticated TLS. slskd is Kris's own loopback daemon, and a hostile
one already holds the Soulseek login and every download, so a large
body is the least it could do. The worst outcome is a memory denial
of service of a desktop app that Kris can restart.

### S-10 — slskd secrets live in the container's environment · Low (accept)

**Evidence.** `docker_setup.py:370-389` passes the network password,
API key and web login as environment variables. Compose writes them
into the container's config, where `docker inspect slskd` shows
them.

**Accepted, with this reason:** reading them needs the Docker socket,
which on Docker Desktop for Mac is the user's own (UNVERIFIED on
Linux, where the `docker` group is root-equivalent anyway). The same
values are in `config.json` at 0600. Moving them into an `slskd.yml`
at 0600 would need a migration of every existing install, to protect
against an attacker who already has the socket.

**Status:** written into CLAUDE.md → "Accepted risks" in S8.

### S-11 — Binaries and libraries resolve from Homebrew prefixes · Info (accept)

`docker`, `ffmpeg` and `open` resolve through the merged PATH, and
libchromaprint loads from `/opt/homebrew/lib` or `/usr/local/lib`
(`fingerprint.py:114-154`). These directories are user-writable, so
planting a binary there needs same-user access, which is outside the
threat model (§1). Accepted. `open` could be `/usr/bin/open`
outright, as a nicety, not a fix.

**Status:** written into CLAUDE.md → "Accepted risks" in S8.

### S-12 — The plain-text sweeps have blind spots · Info

The message-box sweep passes a function that calls `setTextFormat`
*anywhere*, even in one branch. `RichLabel(<dynamic>)` is not
checked for `html.escape`. Only `ui/` is scanned. Today all three
are clean by hand (§6).

**Fix (S8, cheap).** Add one sweep: a `RichLabel` argument is a
constant, or a name assigned only from constants and
`html.escape(...)` within the same function, else it fails. Also add
`main_ui.py` to the scanned files.

**Status: fixed in S8 (`7123da0`).** The message-box blind spot (a
`setTextFormat` in one branch) and a later `setText` stay, written in
the test module's docstring.

### S-13 — CI checkout persists its token; chromaprint is unpinned · Info

`actions/checkout` defaults to `persist-credentials: true`, which
leaves the job token in `.git/config` for later steps. The job has
only `contents: read`, and runs on `push`/`pull_request`, not on
`pull_request_target`. `brew install chromaprint` takes whatever
Homebrew ships. CI's chromaprint is never shipped.

**Fix (S7 §7.3).** `persist-credentials: false`. Leave brew as it
is, with a comment.

### S-14 — Ad-hoc signed, no hardened runtime · Info

This is already the documented state ("ad-hoc signed, not
notarized"). Same-user library injection is outside the model. For
S16: the bundle ID is still `com.seeker.app`, and BRIEF §0.11
decides `io.github.kristiyanddimitrov.seeker`. If a Developer ID
ever arrives, the hardened runtime will need JIT entitlements for
numba (UNVERIFIED).

### S-15 — Defaults: S14 must keep outbound calls disclosed · Info

§11 finds nothing sent unasked today. S14's automatic update check
will send Kris's IP address and User-Agent to GitHub on a timer, and
GitHub's unauthenticated limit is 60 requests an hour per IP (HISTORY
§55). **For S14:** make the check opt-in, or a disclosed default
with a Settings toggle. Keep `_trusted_release_url` and the
`PlainText` dialog. Never download or run anything. At most once a
day.

---

## Remediation order

| Order | Row | Findings | Changes behaviour? |
|---|---|---|---|
| 1 | S7 | S-01, S-02, S-08, S-13 | No |
| 2 | S8 | S-05, S-07, S-12 | No (S-05 only ignores forged callbacks) |
| 3 | S8 | S-06, S-03(c), S-09 | **Yes: [ASK]** |
| 4 | S8 | S-03(a), S-10, S-11: acceptances written into CLAUDE.md | No |
| 5 | S14 | S-15 | Designs the new feature |
| 6 | S16 | S-04, S-14 | **S-04 wording: [ASK]** |

## Method

Read by range (`grep -n`, then `sed -n`): every `subprocess` and
`httpx` call site, `placement.py`, `files/atomic.py`,
`files/deletion.py`, `update_check.py`, the OAuth modules, every
f-string SQL statement, `test_plain_text.py`, `seeker.spec` and
`ci.yml`. Run: `pytest tests/test_plain_text.py`, `pip-audit`
(runtime and dev), `pip-licenses`, `codesign -dvvv`, `find` over
`dist/Seeker.app`, `stat` over Kris's data dirs, and a grep of his
log. Queried: slskd's advisories and releases (`gh api`), its
Dockerfile at `0.26.0`, and a web search for libsndfile 1.2.2.
Skills: `security-pen-testing` gave the report shape (scope,
ranked findings, remediation matrix).
