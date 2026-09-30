from seeker.models.tag_result import FixArtResult, TagResult
from seeker.ui.tag_result_panel import (
    summarize_fix_art_result,
    summarize_tag_result,
)


def test_fix_art_summary_counts_a_wav_fix_in_the_total():
    # A WAV fix is its own bucket, not part of `fixed`, so the total
    # has to add it separately or the track vanishes from "of N".
    result = FixArtResult(fixed=1, fixed_wav_rarely_supported=1)

    assert summarize_fix_art_result(result) == "Fixed 1 of 2"


def test_tag_summary_does_not_double_count_the_art_subsets():
    result = TagResult(
        tagged=2, tagged_without_art=1,
        tagged_art_rarely_supported_format=1, skipped_no_match=1,
    )

    assert summarize_tag_result(result) == "Tagged 2 of 3"
