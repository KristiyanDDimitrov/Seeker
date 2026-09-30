# .aifc is indexed (visible) but excluded from quality.LOSSLESS_EXTENSIONS:
# mutagen's own AIFF reader (confirmed live, mutagen 1.48.1) never decodes
# the COMM chunk's compressionType field, so a compressed .aifc's derived
# bitrate/lossless status can't be trusted the way an uncompressed .aiff/
# .aif can. Untuned judgement call. HISTORY §85.
AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".aiff", ".aif", ".aifc",
}

# Narrower than AUDIO_EXTENSIONS on purpose: a file already owned should
# never be made invisible to the app (that's AUDIO_EXTENSIONS' own job),
# but downloading a NEW file in a format nothing downstream can finish
# processing just produces a stuck, "format_unsupported" file. Judgement
# calls: .mp4 is OUT (video-file collision risk, .m4a is what Rekordbox/
# Serato expect); .aac is OUT (no reliable tag container, zero real
# instances in this project's library); .aifc is OUT (see AUDIO_EXTENSIONS'
# own comment above); .ogg/.opus/.wma/.ape/.wv are OUT (DJ software rarely
# reads them). HISTORY §94.
# In the order a message lists them.
DOWNLOADABLE_EXTENSIONS_IN_ORDER = (".mp3", ".flac", ".wav", ".aiff", ".aif", ".m4a")
DOWNLOADABLE_EXTENSIONS = set(DOWNLOADABLE_EXTENSIONS_IN_ORDER)

assert DOWNLOADABLE_EXTENSIONS <= AUDIO_EXTENSIONS, (
    "DOWNLOADABLE_EXTENSIONS must never include a format the scanner "
    "wouldn't even index afterward"
)


def downloadable_formats_text() -> str:
    """"mp3, flac, wav, aiff, aif and m4a" — for a sentence."""
    names = [extension.lstrip(".") for extension in DOWNLOADABLE_EXTENSIONS_IN_ORDER]

    return f"{', '.join(names[:-1])} and {names[-1]}"


def is_downloadable_extension(extension: str) -> bool:
    """`extension` is bare, no leading dot (e.g. SoulseekFile.extension,
    already stored this way — see soulseek/quality.py's own convention).
    One shared predicate for every entry point that can request a NEW
    file from SoulSeek: quality._score_candidate (auto/needs-review
    tiers), rank_candidates (Search page + CLI raw results), and
    download_manual's explicit chosen= pick — three call sites, one
    implementation, so the allowlist can't drift on any one of them."""
    return f".{extension.lower()}" in DOWNLOADABLE_EXTENSIONS
