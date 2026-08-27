import re
from pathlib import Path

from rapidfuzz import fuzz


# Shared by library/matcher.py (Spotify track vs. scanned local file) and
# soulseek/quality.py (Spotify track vs. Soulseek search result) — both
# sides fuzzy-match a Spotify artist/title against some local text source
# and need the exact same answer. This used to be two independently
# maintained copies; they drifted apart twice (once on artist-null
# handling, once on title-only vs. artist+title scoring) before being
# consolidated here — same root cause, same fix, as the earlier
# AUDIO_EXTENSIONS consolidation.

# Fuzzy match score cutoffs (rapidfuzz's 0-100 scale, from score_title()
# below). Untuned starting guesses, not derived from any real precision/
# recall measurement — revisit once real match data exists.
#   score >= AUTO_MATCH_THRESHOLD:   confident enough to match without a
#                                     human — used directly, no review.
#   NEEDS_REVIEW_THRESHOLD <= score
#                    < AUTO_MATCH_THRESHOLD: plausible but not confident
#                                     enough to trust unattended — surfaced
#                                     for a human to confirm/reject.
#   score < NEEDS_REVIEW_THRESHOLD:  not a match at all.
AUTO_MATCH_THRESHOLD = 90.0
NEEDS_REVIEW_THRESHOLD = 70.0

TRACK_NUMBER_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s*[-.]\s*")
TRAILING_SEPARATOR_RE = re.compile(r"[\s\-–—.]+$")
WHITESPACE_RE = re.compile(r"\s+")
WATERMARK_SUBSTRINGS = (".com", ".org", ".net")


def normalize_filename_text(text: str) -> str:
    text = TRACK_NUMBER_PREFIX_RE.sub("", text)

    tokens = text.split()

    if tokens and any(
            substring in tokens[-1].lower()
            for substring in WATERMARK_SUBSTRINGS
    ):
        tokens = tokens[:-1]

    text = " ".join(tokens).lower()
    text = TRAILING_SEPARATOR_RE.sub("", text)
    text = WHITESPACE_RE.sub(" ", text)

    return text.strip()


def resolve_text_source(tag_value: str | None, filename: str) -> str:
    # Tags win when present; otherwise fall back to the filename itself
    # (stem, extension stripped) — WAV files in particular routinely
    # carry no tags at all, so this fallback is the normal case for them,
    # not an edge case.
    if tag_value:
        return tag_value

    return Path(filename).stem


def artist_matches(spotify_artist: str, local_artist: str | None) -> bool:
    if local_artist is None:
        return False

    normalized_local_artist = normalize_filename_text(local_artist)

    # spotify_artist may credit multiple artists joined with ", " (e.g.
    # "MK, Dom Dolla") — a local tag or filename crediting only one of
    # them (e.g. just "MK") should still count as a match, so pass if
    # ANY one name is contained, not all of them.
    spotify_artist_names = [
        name.strip() for name in spotify_artist.split(",") if name.strip()
    ]

    return any(
        normalize_filename_text(name) in normalized_local_artist
        for name in spotify_artist_names
    )


def score_title(
        spotify_artist: str,
        spotify_title: str,
        local_title_source: str,
) -> float:
    # local_title_source may be a clean tag (no artist in it — e.g. a
    # well-tagged "Blinding Lights") or a filename fallback that's
    # conventionally "Artist - Title" (e.g. "3AMDISCO - Get Back", or
    # any Soulseek filename). Scoring against the bare title tanks the
    # ratio for the filename case (measured: 59.3 vs. 94.4 combined on a
    # real match); scoring against artist+title combined tanks it for
    # the clean-tag case instead (measured: 100 title-only vs. 73.2
    # combined on a real match) — so score both and take the better one
    # rather than guessing which shape the source is.
    #
    # spotify_artist may also credit multiple artists joined with ", "
    # (e.g. "MK, Dom Dolla"), while the local source often credits only
    # one of them — combining the FULL multi-artist string dilutes the
    # ratio even when the credited one matches perfectly (measured: 92.9
    # combined-with-"MK" vs. 71.8 combined-with-"MK, Dom Dolla" against
    # the same "mk - rhyme dust" filename). So also try each individual
    # artist name combined with the title, not just the joined string.
    normalized_local = normalize_filename_text(local_title_source)

    artist_variants = [spotify_artist] + [
        name.strip() for name in spotify_artist.split(",") if name.strip()
    ]

    scores = [
        fuzz.token_sort_ratio(
            normalize_filename_text(spotify_title),
            normalized_local,
        )
    ]

    for artist_variant in artist_variants:
        scores.append(
            fuzz.token_sort_ratio(
                normalize_filename_text(f"{artist_variant} {spotify_title}"),
                normalized_local,
            )
        )

    return max(scores)
