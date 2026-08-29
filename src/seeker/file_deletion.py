from pathlib import Path


def delete_file(path: Path) -> str | None:
    """Deletes a single file from disk. Returns `None` on success, or a
    short error message on failure (permission denied, already gone,
    ...) — never raises, so a caller processing a batch of these can
    report a per-item failure without the exception aborting the rest
    (same "one bad item must not abort a batch" precedent as
    `tag_tracks`/`compute_fingerprints`).

    Shared by `DownloadService.apply_upgrade_decision` (deleting a
    superseded local file after an upgrade replace, roadmap item 26)
    and `DuplicateService.delete_local_files` (deleting a duplicate
    group's lower-ranked copies, roadmap item 40) — one real deletion
    primitive, not two independently-drifting copies, matching this
    codebase's own "shared thing lives in exactly one place" precedent
    (`matching.py`, `quality_tier_for_format`, `download_dedup.py`).
    """
    try:
        path.unlink()
        return None
    except OSError as error:
        return str(error)
