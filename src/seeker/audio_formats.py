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
