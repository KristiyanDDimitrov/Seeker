# seeker — `soulseek/` rules

Standing facts for SoulSeek and slskd, moved here from the root
`CLAUDE.md` so it stays short. Same rules as the root: present tense,
each fact linked to the HISTORY entry holding its investigation;
`docs/history/README.md` resolves any `§N`.

## SoulSeek / slskd

- **Quitting Seeker mid-download stops only the reconciliation.**
  slskd transfers in its own container; Seeker enqueues over REST and
  reconciles in `poll_downloads()`. Observed: a transfer finished with
  no Seeker running and was placed on the next poll.
  [§123](../../../docs/history/121-150.md#123)
- Two credential pairs: `SLSKD_SLSK_USERNAME`/`PASSWORD` is the
  **Soulseek network** login, `SLSKD_USERNAME`/`PASSWORD` the **web
  UI** login. [§23](../../../docs/history/001-024.md#23)
- `GET /api/v0/searches/{id}` returns `responses` only with
  `?includeResponses=true`; without it `isComplete` is real and
  `responses` silently empty. [§4](../../../docs/history/001-024.md#4)
- **Rejections come in three shapes:** a locked file's `request_download`
  succeeds and the rejection surfaces later in `get_download_status` as
  `"Completed, Rejected"`; a peer gone offline is a synchronous 404 at
  enqueue; bad credentials or a kick shows only in `/api/v0/logs`
  (`ServerState` has no reason field), so `check_slskd_health` reads the
  logs with a `since:` filter. `is_recognized_rejection()` applies to
  every `download_requests.role`. [§13](../../../docs/history/001-024.md#13)
- Exponential backoff plus a terminal `unavailable` after 8 attempts
  bounds any retry storm, whatever its cause (item 63).
  [§66](../../../docs/history/047-071.md#66)
- **A finished download is never guessed and never lands on an
  existing file.** slskd writes `<remote parent>/<basename>`, or
  `<stem>_<UtcNow.Ticks><suffix>` on a clash; `_locate_completed_file`
  accepts only the request's exact byte size and refuses an ambiguous
  match. Placement and renames share one collision rule,
  `files.placement.resolve_collision`. [§138](../../../docs/history/121-150.md#138)
- **A destination subfolder is validated, never rewritten:**
  `validate_destination_subfolder` takes `/`-joined sanitized names
  and rejects `..`, absolute paths and unsafe names; `set_destination`,
  resolution and the dialog's preview all use it. Every Seeker-built
  name goes through `clean_path_component` (never a leading dot); a
  peer's basename too, at placement, through `clean_peer_filename`
  (no control or bidi character, 255 bytes), while the lookup still
  matches slskd's raw name. [§143](../../../docs/history/121-150.md#143)
- **One bring-up: `Application.start_slskd(..., persist=)`**, for the
  wizard (saves after its health poll), Settings (saves at once) and
  `restart_slskd()` (the live share and saved login, else
  `SlskdStartRefusedError`, never a guess). Sharing's recreate calls
  `docker_setup.bring_up_slskd` directly, reusing the saved key and
  login. The app runs only the per-user Compose copy
  (`compose_file_path()`), seeded once, never re-seeded, never the
  tracked template; a recreate keeps the live `/app` data dir. A
  refusal Settings → Connections' Start slskd form resolves is a
  `SlskdSetupNeededError`, and its notice offers Open Settings; a
  named data folder is never created (but the per-user default). The
  share is optional: none mounts Seeker's empty `slskd_empty_share_dir()`.
  [§140](../../../docs/history/121-150.md#140), [§217](../../../docs/history/211-240.md#217),
  [§218](../../../docs/history/211-240.md#218)
- **slskd down is an outage, never a per-request failure.**
  `poll_downloads` turns any `httpx.TransportError` into
  `SlskdUnreachableError` and aborts: no row changed or counted
  failed, no locked-retry budget spent (a retry re-raises before
  `_advance_locked_retry`). A new slskd call in the poll
  keeps `except httpx.TransportError` ahead of `except Exception`.
  The UI reads `SlskdStatus` (`PageContext.slskd_status`), written only by the
  backend poll and edge-triggered: one tray notice per outage, the
  first good poll clears them all. [§151](../../../docs/history/151-180.md#151),
  [§152](../../../docs/history/151-180.md#152)
- **The daily sweep (`soulseek/sweep.py`) is the only re-search.** It
  runs `search_and_request`, `download_playlist`'s own per-track step,
  over loaded playlists with a destination: ≤ 50 searches, least
  recently searched first (`tracks.last_searched_at`, stamped before
  every search). An outage, a pause or its `stop` event stops it and
  records no `last_sweep_at`. Every search skips a (peer, file) that
  went `failed` or `unavailable` for that track within 30 days, a
  cancel included (`FAILED_CANDIDATE_COOLDOWN`). The GUI runs it
  from `ui/sweep_scheduler.py`: after the first poll that reaches
  slskd, then hourly, one at a time (`busy_actions`), stopped on quit
  (the pool's destructor would wait out a ~40 min sweep).
  [§202](../../../docs/history/181-210.md#202), [§203](../../../docs/history/181-210.md#203)
- **slskd's cancel answers `204` whatever the transfer's state**
  (unknown, finished or live), so `cancel_download` reads the state
  afterwards: a `Succeeded` transfer is left to the poll. A cancel
  supersedes the other rows of its role (backups too), never cascades.
  [§204](../../../docs/history/181-210.md#204), [§205](../../../docs/history/181-210.md#205)
- **A settled file falls back; a role never crosses.** Up to three
  unlocked backups ride behind it as `shortlisted` settled rows (ranks
  2–4). A failed or locked settled row, refused at enqueue too,
  activates the next one at once (`_cascade(track_id, role)`; the
  locked row keeps its retry loop); the first settled file placed
  supersedes the rest. An upgrade cascades only to upgrades. A
  person's choice gets no backups. A cascade slskd interrupts (busy,
  down) resumes on the next poll (`get_interrupted_fallbacks`); an
  entry whose enqueue errors otherwise fails, never waits.
  [§206](../../../docs/history/181-210.md#206),
  [§207](../../../docs/history/181-210.md#207), [§238](../../../docs/history/211-240.md#238)
- **slskd runs two enqueues at once and answers a third `429`.**
  `SoulseekClient` sends one at a time per process (a module-level
  lock), sends a `429` again after 0.5, 1 and 2 s, then raises
  `SlskdBusyError`: no peer was asked, so no locked-retry budget is
  spent. [§238](../../../docs/history/211-240.md#238)
- **A leftover is a file no claim names, and slskd must answer.**
  `LeftoverService` claims the basename of every `UNRESOLVED` request
  and every live slskd transfer (letters and digits only, `_<ticks>`
  stripped), holds back a file written in the last 10 minutes, and
  refuses a download folder not named `downloads` beside `slskd.yml`.
  A cleanup re-lists and deletes only unchanged confirmed files.
  [§208](../../../docs/history/181-210.md#208)
- **Every slskd URL path segment is `quote(…, safe="")`d:** a
  username comes from a remote peer, and a raw `?`, `#` or `../`
  reaches another endpoint. [§146](../../../docs/history/121-150.md#146)
- **The web UI binds to loopback only** (`127.0.0.1:5030`/`5031`);
  `50300` stays published on every interface for incoming peers;
  `SLSKD_REMOTE_CONFIGURATION=false`. A fresh install otherwise
  exposes slskd's vendor-default `slskd`/`slskd` login. A generated
  web login takes effect only on a fresh install (an existing one
  answers it `401`, observed), so `check_slskd_web_login()` checks it
  and Settings shows a credential only once confirmed.
  [§116](../../../docs/history/108-120.md#116), [§117](../../../docs/history/108-120.md#117)
