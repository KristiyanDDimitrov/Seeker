# Roadmap item R1 — .aiff/.aif added (previously invisible to the whole
# app: library/scanner.py filters on this set, so an unlisted extension
# is never indexed into local_files at all). .aifc (AIFF-C) is included
# here too so it's at least indexed/visible, but deliberately excluded
# from quality.LOSSLESS_EXTENSIONS — AIFF-C is a *container* that can
# hold genuinely compressed audio, and mutagen's own AIFF reader
# (confirmed live, mutagen 1.48.1) doesn't decode the COMM chunk's
# compressionType field at all, so a compressed .aifc's derived bitrate/
# lossless status can't be trusted the way an uncompressed .aiff/.aif
# can. Untuned judgement call, same discipline as every other flagged
# constant in this codebase.
AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".aiff", ".aif", ".aifc",
}

# Roadmap item 94 (B5) — what Seeker will FETCH from SoulSeek. Narrower
# than AUDIO_EXTENSIONS on purpose: AUDIO_EXTENSIONS stays permissive so
# a file you already own is never made invisible to the app (R1's own
# lesson), but downloading a NEW file in a format nothing downstream can
# finish processing just produces a stuck, "format_unsupported" file —
# the real, measured consequence (a lone real .ogg in this project's own
# library, the exact file `format_unsupported: album art isn't supported
# for this file format` was reported against).
#
# Derived from metadata.py's real tag-writing dispatch, not hand-picked:
# ID3 -> mp3/wav/aiff/aif, FLAC -> flac, MP4 -> m4a. Judgement calls,
# stated rather than assumed:
#   - .mp4 is deliberately OUT even though mutagen's MP4 class could
#     read it: an audio .mp4 from SoulSeek is rare and a VIDEO .mp4 is
#     common, and .m4a is the audio container Rekordbox/Serato actually
#     expect. .m4a stays in.
#   - .aac (raw ADTS) is OUT — no reliable tag container, and this
#     project's own real library (3,400+ files) has zero of them.
#   - .aifc is OUT, matching AUDIO_EXTENSIONS' own comment above (a
#     compressed AIFF-C's bitrate/lossless status can't be trusted, and
#     downloading a NEW one adds an unknown rather than indexing one
#     already owned).
#   - .ogg/.opus/.wma/.ape/.wv are OUT. mutagen COULD tag Vorbis
#     comments in .ogg — this is a scoping decision (DJ software rarely
#     reads .ogg, and this project's real library has exactly one, kept
#     but not further invested in), not a hard technical limit.
DOWNLOADABLE_EXTENSIONS = {".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a"}

assert DOWNLOADABLE_EXTENSIONS <= AUDIO_EXTENSIONS, (
    "DOWNLOADABLE_EXTENSIONS must never include a format the scanner "
    "wouldn't even index afterward"
)


def is_downloadable_extension(extension: str) -> bool:
    """`extension` is bare, no leading dot (e.g. SoulseekFile.extension,
    already stored this way — see soulseek/quality.py's own convention).
    One shared predicate for every entry point that can request a NEW
    file from SoulSeek (roadmap item 94/B5.3): quality._score_candidate
    (auto/needs-review tiers), rank_candidates (Search page + CLI raw
    results), and download_manual's explicit chosen= pick — three call
    sites, one implementation, so the allowlist can't drift on any one
    of them the way item 2's AUDIO_EXTENSIONS split once did."""
    return f".{extension.lower()}" in DOWNLOADABLE_EXTENSIONS
