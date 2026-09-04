from pathlib import Path


def same_file(path_a: Path, path_b: Path) -> bool:
    """True only when both paths resolve to the SAME real file on disk
    (same inode) — a plain string/Path equality check would say two
    differently-cased paths (macOS's default APFS volume is case-
    insensitive) or two different location-relative paths pointing at
    one physically shared/nested-location file are different when the
    filesystem doesn't. False whenever either path doesn't exist, so a
    caller never has to check existence separately first.

    Shared by `library/metadata_service.py` (a case-only rename of
    itself is never a real collision) and
    `library/duplicate_service.py` (roadmap item 93/R3.3 — a duplicate
    group spanning two overlapping registered library locations can
    produce two `local_files` rows for ONE real file; deleting either
    while "keeping" the other would delete the kept file too).
    """
    if not path_a.exists() or not path_b.exists():
        return False
    try:
        return path_a.samefile(path_b)
    except OSError:
        return False


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
