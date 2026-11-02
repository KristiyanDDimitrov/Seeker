# seeker — `database/` rules

Standing facts for the database and its repositories, moved here from
the root `CLAUDE.md` so it stays short. Same rules as the root: present
tense, each fact linked to the HISTORY entry holding its investigation;
`docs/history/README.md` resolves any `§N`.

## Database

- `local_files`' analysis columns (`bpm`, `camelot_key`,
  `key_confidence`, `fingerprint*`) are excluded from
  `upsert()`'s `ON CONFLICT DO UPDATE`: a scan never wipes analysis.
  [§11](../../../docs/history/001-024.md#11), [§39](../../../docs/history/032-046.md#39)
- **`local_files.has_art` is NULL until a read succeeds, never a
  guessed 0.** The scan reads it and re-reads an unchanged file whose
  value is NULL; tagging and Fix missing cover art set it only when
  they embedded a picture. [§185](../../../docs/history/181-210.md#185)
- `track_matches.confirmed_at` protects a human-confirmed match from a
  later `match_all()`, but only while its `local_file_id` is set.
  [§56](../../../docs/history/047-071.md#56)
- **A match pointing at no file is unmatched.** Every `local_files`
  delete goes through `LocalFileRepository` (`delete_by_id(s)`,
  `delete_all_for_location`), which resets dependent matches in the
  same transaction; never raw SQL (`ON DELETE SET NULL` leaves a
  score and confirmation pointing nowhere). Removing a location also clears
  playlist destinations (no `ON DELETE` on that FK) and, via
  `Application`, the default. [§139](../../../docs/history/121-150.md#139)
- **A Review Reject is permanent, per track**
  (`rejected_local_matches`, `rejected_soulseek_candidates`);
  `match_all` and `download_playlist` fall through to the next best.
  A `manual:` track is saved just before its first download request,
  and `_migrate` deletes any without one. [§144](../../../docs/history/121-150.md#144)
- **A `download_requests` row is dismissed, never deleted:** a failed
  or unavailable row carries a readable `failure_reason` (pass
  `failure_reason=` on every such transition) until "Clear finished"
  sets `dismissed_at`. [§145](../../../docs/history/121-150.md#145)
- **Library locations never nest:** adding one inside or around another is
  refused, by resolved path and on-disk identity (APFS is
  case-insensitive). `LibraryService.merge_location` merges a nested pair:
  rows pair only for the same physical file (`same_file`), analysis moves
  only into an empty group of equal size and mtime, then removal's own
  deletes run. [§171](../../../docs/history/151-180.md#171),
  [§172](../../../docs/history/151-180.md#172)
- Delete a local file: DB row, then disk. Rename: disk, then DB row.
  [§40](../../../docs/history/032-046.md#40), [§67](../../../docs/history/047-071.md#67)
- **No slow work inside a write transaction.**
  `Database.transaction()` opens a connection per call (thread-safe,
  [§22](../../../docs/history/001-024.md#22)). Walks, tag reads and fuzzy
  passes run outside it; writes go in short batches that re-check what
  changed meanwhile. One `?` per row is capped at 32,766 parameters:
  chunk (`delete_by_ids`). [§142](../../../docs/history/121-150.md#142)
- A fingerprint is read only through
  `get_all_for_location_with_fingerprints`; the default `local_files`
  getters leave those columns out (the polls read ~32 MB otherwise).
  [§165](../../../docs/history/151-180.md#165)
