# seeker — roadmap history

Full, verbatim narrative for every numbered roadmap entry in `CLAUDE.md`.
`CLAUDE.md`'s own roadmap section keeps only a condensed, few-line summary
of each entry — what changed and any standing behavioral fact/gotcha that
matters for future code — with a pointer back here. Nothing here is
summarized or trimmed; this is the full bug-hunt/verification narrative:
which hypotheses were checked and ruled out, exact byte counts and
timestamps from real verification runs, the blow-by-blow of each
investigation. If you're trying to understand *why* a fix looks the way
it does, or want the full evidence behind a "verified live" claim, this
is the file to read — `CLAUDE.md` deliberately does not repeat it.

Numbered entries match `CLAUDE.md`'s roadmap items exactly (currently
1-55, with a few lettered sub-addenda for follow-on fixes to an
existing item). The "Known issues / backlog" section below mirrors
`CLAUDE.md`'s own section of the same name, one slugged heading per
bullet, for the handful of early fixes that predate the numbered
roadmap.

---

## Known issues / backlog

### CLI bypassed Application for playlist listing

`cli.py::handle_playlists` instantiated `PlaylistRepository` directly
instead of going through `Application`, violating this project's own
layering rule (presentation code must never call a repository
directly). Fixed to go through `application.sync_service`/
`application.download_service` exclusively, matching every other CLI
handler. Exact point of the fix is uncertain — it was already correct
by the time the polish pass (item 15) audited the CLI layer, likely
folded into an earlier phase's cleanup rather than done as its own
dedicated change.

### matcher and quality fuzzy-matching logic drifted apart twice

`library/matcher.py` and `soulseek/quality.py` each had their own copy
of the artist/title fuzzy-matching logic (`artist_matches`, title
scoring, `normalize_filename_text`), and the two copies drifted apart
twice — same root cause as the `AUDIO_EXTENSIONS` duplication (item 2's
scanner/quality split), just not caught as early.

**First drift.** `quality.py` was fixed to score artist+title combined
instead of title-only (item 5, the 62.5-on-a-clean-match discovery);
`matcher.py` never got that fix, so a real download
(`3AMDISCO - Get Back.wav`, untagged WAV, `240KM/H` playlist) stayed
unmatched even once indexed.

**Second drift, found investigating the first.** `matcher.py`'s
`artist_matches(track.artist, candidate.tag_artist)` hard-gated on
`tag_artist` with no filename fallback — `tag_artist is None` (routine
for WAVs; mutagen extracted no tags at all here) rejected the
candidate outright before title scoring ever ran, whereas `quality.py`
never had this problem because `SoulseekFile` has no tag concept at
all — it always passed the normalized filename itself as the "local
artist" for containment-checking.

**Fix.** Consolidated both into `seeker/matching.py` (`artist_matches`,
`score_title`, `resolve_text_source`, `normalize_filename_text`,
`AUTO_MATCH_THRESHOLD`, `NEEDS_REVIEW_THRESHOLD`) —
`resolve_text_source(tag_value, filename)` gives both call sites
(artist and title) the same tag-or-filename-stem fallback, so
`matcher.py` now falls back to filename-containment for a null
`tag_artist` exactly like `quality.py` already did. Applying
`quality.py`'s combined-scoring fix naively to `matcher.py` caused a
*new* regression, caught by the existing
`test_close_match_scores_at_least_90_and_lands_in_auto` test: a clean,
correctly-tagged match (`tag_title` with no artist in it, e.g.
"Blinding Lights") scored *worse* combined (73.2) than title-only
(100), because the combined fix was specifically compensating for
artist-prefixed filenames, not clean tags. Fixed `score_title` to
compute both title-only and combined scores and take the max — robust
to either shape without needing to know which one `local_title_source`
actually is.

**Verified against real data:** `seeker library match` auto-matches
`3amdisco - Get Back` at score 94.44 against the real untagged WAV
(`local_file_id` 3218), and `seeker check` reflects it as matched
instead of unmatched. See
`tests/test_matcher.py::test_untagged_file_matches_via_filename_alone`.

### Spotify field-name history: get_current_user_playlists

`SpotifyClient.get_current_user_playlists` was reading
`playlist["tracks"]["total"]`. Live `/me/playlists` responses never
contain a `tracks` key — the per-playlist total is under
`playlist["items"]["total"]` instead (confirmed against all 214 real
playlists synced in item 1's real run, 0 had `tracks`). This code path
had never actually run against the live API before (blocked on Spotify
dev quota), so the earlier "fix" to `tracks` was never live-verified
and was wrong. Fixed for real once quota reset;
`tests/test_spotify_client.py` updated to match.

### Spotify field-name and endpoint history: get_playlist_tracks

`SpotifyClient.get_playlist_tracks` was reading `item.get("item")`
instead of `item.get("track")` — the reverse of what turned out to be
correct, discovered through two rounds of live verification rather
than one lucky guess.

**Endpoint path.** Originally `/playlists/{id}/items`, changed to
`/playlists/{id}/tracks` based on pre-migration docs, then a live 403
plus current Spotify developer community reports confirmed Spotify's
Feb 2026 API migration deprecated `/playlists/{id}/tracks` in favor of
`/playlists/{id}/items` — so the path is back to `/playlists/{id}/items`
for real.

**Per-entry field, same root cause, second symptom.** Originally read
each entry's payload from `entry["track"]`, "corrected" to
`entry["item"]` when the endpoint path was first fixed, but that
field-name change was never live-verified — the switch to `/items`
silently swapped `seeker sync-tracks` to the `/items` endpoint but the
parsing logic still read `"track"`, so every entry was skipped and
playlists synced "0 tracks" for real playlists with real tracks (found
live against `240KM/H`, playlist `1xfPRHLLuGBLlB3bIo5kA5`, 3 real
tracks). A raw unparsed GET confirmed: the paging envelope's `items`
array is fine (3 entries, `total: 3`, `next: null`), but no entry has
a `"track"` key at all — the per-track payload now lives under
`entry["item"]`, and the old `"track"` key is repurposed as a
*boolean* type-discriminator field living inside that `item` dict
(`item["track"] == True` for tracks, presumably `False` for podcast
episodes) alongside `item["type"] == "track"`.

**Fix.** Field name resolved to `item` for real this time, with an
explicit `track_data.get("type") != "track"` filter added as a
defensive skip for non-track entries, using the real discriminator
field rather than relying only on empty `artists` as an incidental
signal. `tests/test_spotify_client.py` updated to match the real live
entry shape and to cover the non-track skip.

---

