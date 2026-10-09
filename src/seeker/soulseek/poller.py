"""Reconciling Seeker's download requests with slskd: each poll reads
every in-flight transfer's state, places a finished settled download,
cascades a rejected upgrade to its next shortlisted candidate, and
retries locked requests on an exponential backoff."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from seeker.config_store import SeekerConfig
from seeker.database.connection import Database
from seeker.database.repositories.download_request_repository import (
    DownloadRequestRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.download_dedup import candidate_key, most_recent_per_candidate
from seeker.models.download_request import (
    DownloadRequest,
    DownloadRole,
    DownloadStatus,
)
from seeker.models.download_result import PollResult
from seeker.soulseek.client import (
    SlskdUnreachableError,
    SoulseekClient,
    SoulseekDownloadError,
    TransferStatus,
    is_recognized_rejection,
)
from seeker.soulseek.placement import DownloadPlacement

logger = logging.getLogger(__name__)


# Bounds the locked retry loop: a production storm once retried one row
# 300+ times in ~18 minutes, cause still unknown, and this caps that
# shape regardless (HISTORY §63, §66). All three untuned —
# real numbers to revisit once real usage data exists, same convention
# as every other threshold in this codebase.
LOCKED_RETRY_BASE_SECONDS = 60
LOCKED_RETRY_MAX_SECONDS = 3600
LOCKED_RETRY_MAX_ATTEMPTS = 8

# Soulseek.TransferStates is a [Flags] enum — slskd reports it as a
# comma-joined string (e.g. "Completed, Succeeded"). Check failure markers
# first since a transfer can be "Completed" without having succeeded.
FAILED_STATE_MARKERS = (
    "Cancelled",
    "TimedOut",
    "Errored",
    "Rejected",
    "Aborted",
)

# The label a failed transfer's reason starts with, by state flag.
# "Rejected" is absent: a rejection is the peer's decision, and
# describe_rejection() words it as one.
_FAILED_STATE_LABELS = (
    ("TimedOut", "Timed out"),
    ("Errored", "Transfer error"),
    ("Cancelled", "Cancelled"),
    ("Aborted", "Aborted"),
)

_REJECTION_PREFIX = "transfer rejected:"


def describe_rejection(text: str | None) -> str:
    """A peer's rejection as a user reads it: slskd's own words, minus
    its "Transfer rejected:" framing ("Peer rejected: file not
    shared")."""
    detail = (text or "").strip()

    if detail.lower().startswith(_REJECTION_PREFIX):
        detail = detail[len(_REJECTION_PREFIX):].strip()

    detail = detail.rstrip(".")

    if not detail:
        return "Peer rejected the transfer"

    return f"Peer rejected: {detail[0].lower()}{detail[1:]}"


def describe_transfer_failure(state: str, exception_text: str | None) -> str:
    """Why a transfer slskd reports as failed (any FAILED_STATE_MARKERS
    flag) failed, from its state and its `exception` text."""
    if "Rejected" in state:
        return describe_rejection(exception_text)

    label = next(
        (label for marker, label in _FAILED_STATE_LABELS if marker in state),
        "Transfer failed",
    )

    return f"{label}: {exception_text}" if exception_text else label


def _in_flight_status(state: str) -> DownloadStatus:
    return (
        DownloadStatus.QUEUED if state == "Requested"
        else DownloadStatus.DOWNLOADING
    )


class DownloadPoller:
    def __init__(
            self,
            database: Database,
            soulseek: Callable[[], SoulseekClient],
            placement: DownloadPlacement,
            download_request_repository: DownloadRequestRepository,
            track_match_repository: TrackMatchRepository,
            get_config: Callable[[], SeekerConfig],
    ):
        self.database = database
        # A callable, not a client: the download service's own accessor,
        # so polling while SoulSeek is unconfigured raises its error.
        self._soulseek = soulseek
        self.placement = placement
        self.download_requests = download_request_repository
        self.track_matches = track_match_repository
        self._get_config = get_config

    def poll_downloads(self) -> PollResult:
        # A timestamped call-frequency trace for the still-open
        # locked-retry storm (HISTORY §63, §66); SEEKER_DEBUG_POLL=1
        # turns this logger's DEBUG on at startup.
        logger.debug(
            "[poll_downloads] %s called", datetime.now(UTC).isoformat(),
        )

        # Checked here, not just in the UI's own timer, so pausing is
        # authoritative regardless of caller: no real slskd network
        # call (status poll, locked-retry, upgrade cascade) happens at
        # all while paused (HISTORY §90). Read fresh via
        # self._get_config() (the same not-a-snapshot discipline every
        # other config read in this class already uses), never cached,
        # so a resume takes effect on the very next call.
        if self._get_config().downloads_paused:
            return PollResult()

        with self.database.transaction() as connection:
            pending = self.download_requests.get_pending(connection)
            locked = self.download_requests.get_locked(connection)

        logger.debug(
            "[poll_downloads] pending=%d locked=%d", len(pending), len(locked),
        )

        counts = PollResult()

        for request in pending:
            # Loaded from the DB via get_pending() above, so .id is set —
            # only a not-yet-persisted DownloadRequest has id=None, and
            # nothing here ever is one.
            assert request.id is not None

            # Same principle as download_playlist(): one bad request (a
            # network blip talking to slskd, anything) must not silently
            # stop every request after it in this run from being polled.
            try:
                if request.transfer_id is None:
                    counts.count_in_flight(request.status)
                    continue

                transfer_status = self._soulseek().get_download_status(
                    request.username,
                    request.transfer_id,
                )
                state = transfer_status.state

                if any(marker in state for marker in FAILED_STATE_MARKERS):
                    # A rejection isn't progress — progress fields stay
                    # unset here rather than zeroed, whether or not any
                    # bytes happened to move before the rejection (a
                    # rejected-before-any-bytes-moved transfer reports
                    # bytesTransferred=0, but recording that would
                    # misleadingly imply a real 0%-complete attempt
                    # rather than "never really started").
                    #
                    # Lock-pattern classification applies regardless of
                    # role: retry-worthiness is a property of the
                    # REJECTION, not of why the download was requested
                    # — a needs-review candidate confirmed as
                    # role='settled' can still be a genuinely locked
                    # file (HISTORY §26). Only the upgrade cascade below
                    # stays role-specific, since the shortlist/cascade
                    # mechanism is an upgrade-only concept.
                    status, reason = self._classify_failed_transfer(
                        transfer_status,
                    )
                    self._update_status(
                        request.id, status, failure_reason=reason,
                    )

                    if status == DownloadStatus.FAILED:
                        counts.failed += 1

                    if request.role == DownloadRole.UPGRADE:
                        # Try the next shortlisted candidate for this
                        # track immediately, in this same run, regardless
                        # of why this one was rejected — the exact same
                        # candidate has already failed either way, so
                        # there's no reason to wait a day before trying
                        # the next best one. Scoped to role=='upgrade'
                        # only — 'settled' has no shortlist concept, and
                        # get_next_shortlisted() isn't itself
                        # role-scoped, so calling this for a 'settled'
                        # rejection could incorrectly activate an
                        # unrelated upgrade-role shortlist entry for the
                        # same track.
                        self._cascade_upgrade(request.track_id, counts)

                    continue

                # Genuinely in progress or just succeeded — real
                # bytes-so-far/total are available either way (on a
                # completed transfer, confirmed live: bytes_transferred
                # == size). Every request reaching this point came from
                # `pending` (queued/downloading only) at the top of this
                # run, so this never fires for a locked/shortlisted/
                # superseded row.
                self._update_progress(
                    request.id,
                    transfer_status.bytes_transferred,
                    transfer_status.size,
                )

                if "Succeeded" not in state:
                    new_status = _in_flight_status(state)

                    if new_status != request.status:
                        self._update_status(request.id, new_status)

                    counts.count_in_flight(new_status)
                    continue

                if request.role == DownloadRole.UPGRADE:
                    # Leave the file in slskd's own download dir — it
                    # only moves once the user confirms the replacement
                    # below.
                    self._update_status(request.id, DownloadStatus.READY_FOR_REVIEW)
                    self._supersede_others_for_track(
                        request.track_id, request.id,
                    )
                    continue

                if self._track_already_has_a_matched_file(request.track_id):
                    # A safety net (HISTORY §56): closes
                    # the gap the dedup guard alone can't (a candidate
                    # requested before that guard existed, or matched by
                    # some other path in the meantime). By definition
                    # this settled download is now an upgrade candidate.
                    self._update_status(request.id, DownloadStatus.READY_FOR_REVIEW)
                    self._supersede_others_for_track(
                        request.track_id, request.id,
                    )
                    continue

                move_result = self.placement.move_completed_file(request)

                if move_result is not None:
                    self._update_status(request.id, DownloadStatus.COMPLETED)
                    counts.completed += 1
                    self.placement.index_and_match(
                        request, move_result, counts,
                    )
                else:
                    counts.count_in_flight(request.status)
            except httpx.TransportError as error:
                # slskd itself is down, not this request: every later
                # request would fail the same way, and none of them
                # has failed as far as the user is concerned.
                raise SlskdUnreachableError(self._soulseek().base_url) from error
            except Exception as error:
                counts.failed += 1
                logger.warning(
                    "Failed to poll '%s': %s", request.filename, error,
                )

        # Re-issue request_download for every request that was already
        # 'locked' before this run started (not ones that just became
        # locked above, or via the cascade below — those wait for the
        # next run). Same exact username+filename each time — retrying
        # access to the same candidate, not a fresh search; the daily
        # sweep (sweep.py) is what searches again (HISTORY §202).
        for request in locked:
            # Same principle as above — one bad retry must not stop the
            # rest of the locked shortlist from being retried this run.
            try:
                self._retry_locked_request(request, counts)
            except httpx.TransportError as error:
                raise SlskdUnreachableError(self._soulseek().base_url) from error
            except Exception as error:
                logger.warning(
                    "Failed to retry locked '%s': %s",
                    request.filename, error,
                )

        counts.ready_for_review = len(self._get_ready_for_review())
        counts.locked = len(self._get_locked())
        counts.shortlisted = len(self._get_shortlisted())
        counts.superseded = len(self._get_superseded())
        counts.unavailable = len(self._get_unavailable())

        return counts

    @staticmethod
    def _classify_failed_transfer(
            transfer: TransferStatus,
    ) -> tuple[DownloadStatus, str | None]:
        """'locked' (no reason: it is retried) for a recognized
        rejection, otherwise 'failed' with a reason a user can read."""
        if (
                "Rejected" in transfer.state
                and is_recognized_rejection(transfer.exception)
        ):
            return DownloadStatus.LOCKED, None

        return (
            DownloadStatus.FAILED,
            describe_transfer_failure(transfer.state, transfer.exception),
        )

    def _cascade_upgrade(self, track_id: str, counts: PollResult) -> None:
        # Sequential, not simultaneous: try one candidate, and only move
        # to the next once this one is confirmed unavailable — never
        # multiple in-flight requests for the same track at once. The
        # Soulseek protocol doesn't swarm-download the way BitTorrent
        # does, so firing every shortlisted candidate at once would just
        # be needless load on multiple peers for a track that only needs
        # one to succeed (HISTORY §14).
        while True:
            with self.database.transaction() as connection:
                next_entry = self.download_requests.get_next_shortlisted(
                    track_id, connection,
                )

            if next_entry is None:
                return

            # Loaded from the DB via get_next_shortlisted() above.
            assert next_entry.id is not None

            status = self._activate_shortlisted_entry(next_entry)

            if status == DownloadStatus.FAILED:
                counts.failed += 1
                continue

            if status == DownloadStatus.LOCKED:
                continue

            if status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING):
                counts.count_in_flight(status)
                return

            if status == DownloadStatus.READY_FOR_REVIEW:
                self._supersede_others_for_track(track_id, next_entry.id)
                return

    def _activate_shortlisted_entry(
            self,
            request: DownloadRequest,
    ) -> DownloadStatus:
        # Submit a fresh request_download for a NEW candidate (never
        # tried before), so a rejection's reason still matters: it gets
        # properly classified locked-vs-failed, exactly like a
        # first-time request in the main poll_downloads loop.
        #
        # Both loaded from the DB by every real caller (_cascade_upgrade
        # fetches via get_next_shortlisted, which only returns persisted
        # rows; size is always set at creation time in
        # _request_and_record/_record_shortlisted).
        assert request.id is not None
        assert request.size is not None

        try:
            transfer_id = self._soulseek().request_download(
                request.username,
                request.filename,
                request.size,
            )
        except SoulseekDownloadError as error:
            # request_download raises this for both rejection shapes —
            # the synchronous one (e.g. peer offline, a 404 straight off
            # the enqueue POST) as well as the asynchronous one (e.g.
            # file not shared, which instead raises nothing here and
            # only shows up via the status check below) — see client.py's
            # RECOGNIZED_REJECTION_PATTERNS.
            if is_recognized_rejection(str(error)):
                self._update_status(request.id, DownloadStatus.LOCKED)
                return DownloadStatus.LOCKED

            self._update_status(
                request.id, DownloadStatus.FAILED,
                failure_reason=describe_rejection(error.reason or str(error)),
            )
            return DownloadStatus.FAILED

        # An async-shape rejection doesn't raise from request_download
        # itself (confirmed live, HISTORY §13) — it shows up almost
        # immediately via the status endpoint instead, so check right
        # away rather than waiting a full poll cycle to find out it
        # failed again. A sync-shape rejection (peer offline) never
        # reaches this point at all — it's already handled above.
        transfer = self._soulseek().get_download_status(
            request.username, transfer_id,
        )
        state = transfer.state

        reason = None

        if any(marker in state for marker in FAILED_STATE_MARKERS):
            status, reason = self._classify_failed_transfer(transfer)
        elif "Succeeded" in state:
            status = DownloadStatus.READY_FOR_REVIEW
        else:
            status = _in_flight_status(state)

        with self.database.transaction() as connection:
            self.download_requests.update_transfer_id_and_status(
                request.id, transfer_id, status, connection,
                failure_reason=reason,
            )

        return status

    def _supersede_others_for_track(
            self,
            track_id: str,
            keep_id: int,
    ) -> None:
        with self.database.transaction() as connection:
            self.download_requests.supersede_other_active_for_track(
                track_id, keep_id, connection,
            )

    def _track_already_has_a_matched_file(self, track_id: str) -> bool:
        """A safety net (HISTORY §56): before an automatic
        completion moves a settled download into place, check whether
        track_matches already points at a real local file for this
        track. By definition, a settled download landing after that is
        now an upgrade candidate, not a first arrival — an upgrade is
        never auto-moved, so this reuses that same rule for a settled
        download that turns out to be redundant. Deliberately NOT
        applied to apply_upgrade_decision's own replace action — a
        human explicitly clicking "Replace" is the one place
        overwriting an existing match is exactly the point, not a bug
        to prevent.
        """
        with self.database.transaction() as connection:
            existing_match = self.track_matches.get_by_track_id(
                track_id, connection,
            )

        return (
            existing_match is not None
            and existing_match.local_file_id is not None
        )

    def _retry_locked_request(
            self, request: DownloadRequest, counts: PollResult,
    ) -> None:
        # Reactivate an already-'locked' request. Unlike
        # _activate_shortlisted_entry above, a rejection's specific
        # reason doesn't matter here: this candidate is already
        # confirmed locked, so ANY rejection on the retry (any reason)
        # just means stay 'locked' and try again next run — only a real
        # success or in-progress state moves it out of the retry cycle.
        assert request.id is not None
        assert request.size is not None

        current = self._still_locked(request)

        if current is None or not self._retry_is_due(current):
            return

        if current.retry_count >= LOCKED_RETRY_MAX_ATTEMPTS:
            self._mark_retries_exhausted(request.id)
            return

        attempt = self._attempt_locked_retry(request, current.retry_count)

        if attempt is None:
            return  # Rejected again at the batch level — stays locked.

        transfer_id, state = attempt
        status = self._classify_retry_state(request, state, counts)
        self._persist_retry_outcome(
            request, transfer_id, status, current.retry_count,
        )

    def _still_locked(
            self, request: DownloadRequest,
    ) -> DownloadRequest | None:
        """The row as it stands now, or None when it should not be
        retried.

        `locked` (the list the retry loop runs over) is fetched once at
        the start of poll_downloads(), before the main loop runs — if a
        DIFFERENT entry for the same track succeeds during that loop
        and supersedes this one, this row is no longer really 'locked'
        by the time we get here. Re-check its current status first
        rather than blindly reactivating (and potentially overwriting
        'superseded' back to 'locked'/'queued') a stale snapshot.
        """
        assert request.id is not None

        with self.database.transaction() as connection:
            current = self.download_requests.get_by_id(request.id, connection)

        if current is None or current.status != DownloadStatus.LOCKED:
            return None

        if self._supersede_stale_duplicates(current):
            # A more recent row for the exact same candidate already
            # exists and just absorbed this one's spot — no point
            # issuing a real, redundant request_download for a stale
            # duplicate against the same real peer.
            return None

        return current

    @staticmethod
    def _retry_is_due(current: DownloadRequest) -> bool:
        # The retry cadence is independent of the poll cadence: a row
        # isn't due for another real attempt until its own
        # next_retry_at (exponential backoff) has passed, however often
        # poll_downloads() itself runs (HISTORY §63, §66).
        if current.next_retry_at is None:
            return True

        return datetime.now(UTC) >= datetime.fromisoformat(
            current.next_retry_at,
        )

    def _mark_retries_exhausted(self, request_id: int) -> None:
        # Exhausted every real attempt — the file exists but this peer
        # won't give it up. Terminal, distinct from 'failed' (the
        # candidate itself was real), and deliberately excluded from
        # get_requests_blocking_redownload() so a later
        # download_playlist() run can look for the same track from a
        # different peer.
        with self.database.transaction() as connection:
            self.download_requests.mark_status(
                request_id, DownloadStatus.UNAVAILABLE, connection,
                failure_reason=(
                    "Peer kept refusing after "
                    f"{LOCKED_RETRY_MAX_ATTEMPTS} attempts"
                ),
            )

    def _attempt_locked_retry(
            self, request: DownloadRequest, retry_count: int,
    ) -> tuple[str, str] | None:
        """Re-requests the same file from the same peer: its transfer id
        and slskd's state for it, or None when the peer rejected it
        at the batch level (the retry budget already advanced)."""
        assert request.size is not None

        try:
            transfer_id = self._soulseek().request_download(
                request.username,
                request.filename,
                request.size,
            )
        except SoulseekDownloadError:
            # Covers both recognized rejection shapes now that
            # request_download wraps the synchronous one too (see
            # client.py's RECOGNIZED_REJECTION_PATTERNS) — a peer that's
            # offline right now hits this branch exactly the same way a
            # file-not-shared rejection always did.
            self._advance_locked_retry(request, retry_count)
            return None
        except httpx.TransportError:
            # slskd is down; the peer was never asked, so this is not
            # an attempt against the retry budget.
            raise
        except Exception:
            # Live-caught, not theoretical: an unrecognized error
            # (client.py's own request_download deliberately re-raises
            # anything that isn't a known rejection pattern "loud")
            # must still advance the retry budget — otherwise this
            # exact failure shape retries forever with no bound.
            # Seen live from real production slskd: a `500 Internal
            # Server Error` on /api/v0/transfers/downloads/batches
            # (HISTORY §66).
            # Re-raised unchanged so poll_downloads()'s own outer
            # per-request try/except still prints its diagnostic; this
            # is additive bookkeeping, not a change to what's reported.
            self._advance_locked_retry(request, retry_count)
            raise

        try:
            state = self._soulseek().get_download_status(
                request.username, transfer_id,
            ).state
        except httpx.TransportError:
            raise
        except Exception:
            # Same reasoning as the request_download branch above —
            # get_download_status (client.py) has no exception wrapping
            # of its own at all, so any real failure here (a timeout, a
            # non-404 HTTP error) must still count against the retry
            # budget rather than silently never advancing it.
            self._advance_locked_retry(request, retry_count)
            raise

        return transfer_id, state

    def _classify_retry_state(
            self, request: DownloadRequest, state: str, counts: PollResult,
    ) -> DownloadStatus:
        """What a retried transfer's slskd state makes of the row; a
        success is placed here, before the status is persisted."""
        if any(marker in state for marker in FAILED_STATE_MARKERS):
            return DownloadStatus.LOCKED

        if "Succeeded" not in state:
            return _in_flight_status(state)

        # role='upgrade' still needs a human's confirmation via
        # ready_for_review, exactly as before. role='settled' is only
        # reachable here at all via a human-confirmed needs-review
        # candidate that turned out to be locked
        # (find_best_needs_review_candidate never filters on lock
        # status — HISTORY §26) — that candidate was already
        # human-confirmed once, so it auto-moves into the library like
        # an ordinary settled success, not a second confirmation via
        # ready_for_review.
        if request.role == DownloadRole.UPGRADE:
            return DownloadStatus.READY_FOR_REVIEW

        if self._track_already_has_a_matched_file(request.track_id):
            # Same safety net as the main poll_downloads() loop
            # (HISTORY §56): even a role='settled' row that's
            # already human-confirmed once must not silently create a
            # second file for a track something else already matched in
            # the meantime.
            return DownloadStatus.READY_FOR_REVIEW

        # Mirror poll_downloads()'s own main-loop pattern: only persist
        # 'completed' if the file is genuinely found and moved. If not,
        # fall back to 'downloading' — the real transfer stays reported
        # as Succeeded by slskd on every future poll, so the next run's
        # main pending loop retries the move instead of this row
        # silently claiming a completion that never actually happened.
        move_result = self.placement.move_completed_file(request)

        if move_result is None:
            return DownloadStatus.DOWNLOADING

        counts.completed += 1
        # Same indexing gap as poll_downloads()'s main loop (see
        # DownloadPlacement.index_and_match's own docstring) — this
        # branch reaches 'completed' for a role='settled' row too, so it
        # needs the identical fix, not a second copy of it.
        self.placement.index_and_match(request, move_result, counts)
        return DownloadStatus.COMPLETED

    def _persist_retry_outcome(
            self,
            request: DownloadRequest,
            transfer_id: str,
            status: DownloadStatus,
            retry_count: int,
    ) -> None:
        assert request.id is not None

        with self.database.transaction() as connection:
            self.download_requests.update_transfer_id_and_status(
                request.id, transfer_id, status, connection,
            )

        if status == DownloadStatus.LOCKED:
            # Real attempt made, still locked — advance the backoff
            # schedule. Left alone (not reset) when status moves on to
            # anything else: those rows leave the retry cycle entirely,
            # so their retry_count/next_retry_at stop being consulted.
            self._advance_locked_retry(request, retry_count)

        if status == DownloadStatus.READY_FOR_REVIEW:
            self._supersede_others_for_track(request.track_id, request.id)

    def _advance_locked_retry(
            self, request: DownloadRequest, current_retry_count: int,
    ) -> None:
        # Called once per real retry attempt that ends up staying
        # 'locked' (whether rejected at the batch level or via the
        # async status check), regardless of which of the two call
        # sites made the attempt. current_retry_count is the count
        # BEFORE this attempt — used as the exponent so the first
        # attempt (0) backs off LOCKED_RETRY_BASE_SECONDS (60s, then
        # 120s, then 240s, ...).
        assert request.id is not None

        new_retry_count = current_retry_count + 1
        backoff_seconds = min(
            LOCKED_RETRY_BASE_SECONDS * (2 ** current_retry_count),
            LOCKED_RETRY_MAX_SECONDS,
        )
        next_retry_at = (
            datetime.now(UTC) + timedelta(seconds=backoff_seconds)
        ).isoformat()

        with self.database.transaction() as connection:
            self.download_requests.update_retry_state(
                request.id, new_retry_count, next_retry_at, connection,
            )

    def _supersede_stale_duplicates(self, request: DownloadRequest) -> bool:
        """Collapses stale duplicate rows for the same candidate before
        a retry re-issues a real request_download against the same
        peer — without this, the retry loop would hit slskd
        independently, every poll cycle, for every stale duplicate of
        the same candidate (get_locked() has no per-track/per-candidate
        collapsing of its own; HISTORY §25). Mirrors
        `download_dedup.most_recent_per_candidate`'s exact
        grouping/tiebreak rule rather than reinventing one — the same
        rule DashboardService.get_active_downloads() already uses on the
        read side, so display and mutation never drift onto two
        different notions of "duplicate."

        Returns True if `request` itself lost to a more recent sibling
        (already marked 'superseded' — the caller must not retry it).
        Returns False if `request` IS the most recent (or the only) row
        for its candidate — every OTHER sibling in the group gets
        marked 'superseded' here, so a group converges to one survivor
        within a single poll_downloads() run regardless of which row
        this method happens to be called for first.
        """
        assert request.id is not None

        with self.database.transaction() as connection:
            group = self.download_requests.get_active_candidates(
                request.track_id, request.role, request.username,
                request.filename, connection,
            )

        winner = most_recent_per_candidate(group).get(
            candidate_key(request)
        )

        if winner is not None and winner.id != request.id:
            self._update_status(request.id, DownloadStatus.SUPERSEDED)
            return True

        for sibling in group:
            if sibling.id != request.id:
                assert sibling.id is not None
                self._update_status(sibling.id, DownloadStatus.SUPERSEDED)

        return False

    def _get_ready_for_review(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_ready_for_review(connection)

    def _get_locked(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_locked(connection)

    def _get_shortlisted(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_shortlisted(connection)

    def _get_superseded(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_superseded(connection)

    def _get_unavailable(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_unavailable(connection)

    def _update_status(
            self,
            request_id: int,
            status: DownloadStatus,
            failure_reason: str | None = None,
    ) -> None:
        with self.database.transaction() as connection:
            self.download_requests.mark_status(
                request_id, status, connection, failure_reason=failure_reason,
            )

    def _update_progress(
            self,
            request_id: int,
            bytes_transferred: int | None,
            total_bytes: int | None,
    ) -> None:
        with self.database.transaction() as connection:
            self.download_requests.update_progress(
                request_id, bytes_transferred, total_bytes, connection,
            )
