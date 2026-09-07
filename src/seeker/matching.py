import re
from dataclasses import dataclass
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

# evaluate_match()'s cap for a title-only match whose artist couldn't be
# confirmed against any real evidence (no contradicting tag either) — one
# point below AUTO_MATCH_THRESHOLD so it can still land in needs_review
# but can never silently auto-match without a human confirming the
# artist. Untuned, same as the two thresholds above.
ARTIST_UNCONFIRMED_SCORE_CAP = AUTO_MATCH_THRESHOLD - 1

TRACK_NUMBER_PREFIX_RE = re.compile(r"^\s*\d{1,3}\s*[-.]\s*")
TRAILING_SEPARATOR_RE = re.compile(r"[\s\-–—.]+$")
WHITESPACE_RE = re.compile(r"\s+")
WATERMARK_SUBSTRINGS = (".com", ".org", ".net")

# aggressive=True only (library/matcher.py) — soulseek/quality.py keeps
# aggressive=False (its default, unchanged behavior) throughout this
# module, verified by re-running its existing test suite unmodified.
#
# Filesystem-illegal characters get substituted on write, so a Spotify
# title's literal "/" routinely survives only as "-" or "_" in the local
# tag/filename that was ripped from it. Real case that motivated this:
# Bring Me The Horizon's "a bulleT w/ my namE On" (Spotify) tagged
# locally as "a bulleT w- my namE On". Mapped to a shared space (not
# dropped) so "w/" and "w-" still tokenize the same way.
FS_SUBSTITUTION_RE = re.compile(r"[/\\:*?\"<>|_-]")
# A second, independently-real source of drift, also aggressive-only:
# Spotify's own stylization for two other real BMTH tracks on the same
# album uses letter-spacing dots ("R.i.p.", "p.u.s.s.-e") that the local
# rip's own tag/filename drops entirely ("Rip", "puss-e"). Stripped
# rather than mapped to space so "R.i.p." and "Rip" tokenize identically
# instead of leaving a stray gap that would itself cost ratio points.
DOT_RE = re.compile(r"\.")
# A Spotify title's "(feat. X)"/"[feat. X]" clause is routinely absent
# from a local rip's own tag/filename — real case: BMTH's
# "a bulleT w/ my namE On (feat. Underoath)" vs. the locally-tagged
# "a bulleT w- my namE On" (no featured-artist credit at all). Tried as
# an ADDITIONAL scoring variant in score_title() below, never replacing
# the full-title variant, so a title that genuinely does carry this text
# isn't penalized either way.
FEAT_CLAUSE_RE = re.compile(r"\s*[\(\[]feat\.?\s+.*?[\)\]]", re.IGNORECASE)


def normalize_filename_text(text: str, *, aggressive: bool = False) -> str:
    text = TRACK_NUMBER_PREFIX_RE.sub("", text)

    tokens = text.split()

    if tokens and any(
            substring in tokens[-1].lower()
            for substring in WATERMARK_SUBSTRINGS
    ):
        tokens = tokens[:-1]

    text = " ".join(tokens).lower()
    text = TRAILING_SEPARATOR_RE.sub("", text)

    if aggressive:
        text = FS_SUBSTITUTION_RE.sub(" ", text)
        text = DOT_RE.sub("", text)

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


def artist_matches(
        spotify_artist: str,
        local_artist: str | None,
        *,
        aggressive: bool = False,
) -> bool:
    if local_artist is None:
        return False

    normalized_local_artist = normalize_filename_text(
        local_artist, aggressive=aggressive
    )

    # spotify_artist may credit multiple artists joined with ", " (e.g.
    # "MK, Dom Dolla") — a local tag or filename crediting only one of
    # them (e.g. just "MK") should still count as a match, so pass if
    # ANY one name is contained, not all of them.
    spotify_artist_names = [
        name.strip() for name in spotify_artist.split(",") if name.strip()
    ]

    return any(
        normalize_filename_text(name, aggressive=aggressive)
        in normalized_local_artist
        for name in spotify_artist_names
    )


def score_title(
        spotify_artist: str,
        spotify_title: str,
        local_title_source: str,
        *,
        aggressive: bool = False,
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
    normalized_local = normalize_filename_text(
        local_title_source, aggressive=aggressive
    )

    artist_variants = [spotify_artist] + [
        name.strip() for name in spotify_artist.split(",") if name.strip()
    ]

    # aggressive-only: also try the title with any "(feat. X)"/"[feat. X]"
    # clause stripped, as an ADDITIONAL variant — never replacing the
    # full-title variant, so a title that genuinely does carry that text
    # isn't penalized either way. When aggressive=False this list always
    # has exactly one element, so quality.py's behavior is unchanged.
    title_variants = [spotify_title]

    if aggressive:
        feat_stripped = FEAT_CLAUSE_RE.sub("", spotify_title).strip()

        if feat_stripped and feat_stripped != spotify_title:
            title_variants.append(feat_stripped)

    scores = []

    for title_variant in title_variants:
        scores.append(
            fuzz.token_sort_ratio(
                normalize_filename_text(title_variant, aggressive=aggressive),
                normalized_local,
            )
        )

        for artist_variant in artist_variants:
            scores.append(
                fuzz.token_sort_ratio(
                    normalize_filename_text(
                        f"{artist_variant} {title_variant}",
                        aggressive=aggressive,
                    ),
                    normalized_local,
                )
            )

    return max(scores)


@dataclass
class MatchEvaluation:
    # None means a hard rejection (a real, populated local artist tag
    # actively disagreed with the Spotify artist) — distinct from a real
    # low score, same "no signal at all" contract find_best_match's
    # caller already relies on elsewhere in this codebase.
    score: float | None
    artist_confirmed: bool


def evaluate_match(
        spotify_artist: str,
        spotify_title: str,
        local_artist_source: str,
        local_artist_from_tag: bool,
        local_title_source: str,
) -> MatchEvaluation:
    """The single entry point library/matcher.py uses instead of calling
    artist_matches()/score_title() directly (soulseek/quality.py keeps
    doing that, unaffected by this function's existence).

    Softens the old hard artist gate: previously, ANY artist_matches()
    == False rejected a candidate outright, at every threshold — real
    bug, confirmed live against three real Bring Me The Horizon files
    whose artist tag matched perfectly but whose TITLE text drifted from
    Spotify's own stylization enough to land in needs_review or below
    (see CLAUDE.md item 56). This function narrows that: the gate is
    still hard when a real, populated tag actively disagrees (genuine
    negative evidence), but a merely-unconfirmable fallback source (no
    tag existed, and nothing in the filename/path names the artist
    either) still gets a real title score, capped below
    AUTO_MATCH_THRESHOLD so a human confirms it rather than either
    silently discarding it or silently auto-matching on title alone.
    """
    confirmed = artist_matches(
        spotify_artist, local_artist_source, aggressive=True
    )

    if confirmed:
        score = score_title(
            spotify_artist, spotify_title, local_title_source,
            aggressive=True,
        )
        return MatchEvaluation(score=score, artist_confirmed=True)

    if local_artist_from_tag:
        # A real, populated tag that simply doesn't name this artist is
        # genuine negative evidence — keep the hard reject.
        return MatchEvaluation(score=None, artist_confirmed=False)

    raw_score = score_title(
        spotify_artist, spotify_title, local_title_source, aggressive=True,
    )
    capped_score = min(raw_score, ARTIST_UNCONFIRMED_SCORE_CAP)

    return MatchEvaluation(score=capped_score, artist_confirmed=False)
