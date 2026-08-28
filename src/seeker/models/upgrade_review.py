from dataclasses import dataclass

from seeker.models.track import Track


@dataclass
class UpgradeReviewDetails:
    """Read-only display info for one ready_for_review upgrade request —
    built once by DownloadService.get_upgrade_review_details() and used
    to render both the CLI's two input() prompts and the Review
    screen's UI without either caller needing to re-derive the
    track/current-file lookups itself."""
    request_id: int
    track: Track
    quality_descriptor: str | None
    current_description: str
    # None if there's no current local file to replace (or its location
    # can't be resolved) — the UI's second "delete old file?" control
    # only ever appears when this is set, exactly mirroring the CLI's
    # own guard around its second input() prompt.
    old_file_path: str | None
