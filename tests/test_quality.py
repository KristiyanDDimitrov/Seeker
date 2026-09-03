import numpy as np
import pytest
import soundfile as sf

from seeker.models.soulseek_file import SoulseekFile
from seeker.models.track import Track
from seeker.soulseek.quality import (
    analyze_local_file_quality,
    filter_candidates,
    find_best_needs_review_candidate,
    quality_tier_for_format,
    select_downloads,
)


def make_track(**overrides) -> Track:
    defaults = dict(
        id="track1",
        title="Rhyme Dust",
        artist="Dom Dolla",
        album="Rhyme Dust",
        duration_ms=215_000,
    )
    defaults.update(overrides)
    return Track(**defaults)


def make_file(**overrides) -> SoulseekFile:
    defaults = dict(
        username="some_seeder",
        filename=(
            "@@1a2b3c\\Music\\Dom Dolla\\Rhyme Dust\\"
            "Dom Dolla - Rhyme Dust.flac"
        ),
        extension="flac",
        size=34_567_890,
        queue_length=2,
        upload_speed=1_048_576,
        has_free_upload_slot=True,
        length=215,
        bit_rate=None,
        bit_depth=16,
        sample_rate=44_100,
        is_variable_bitrate=None,
    )
    defaults.update(overrides)
    return SoulseekFile(**defaults)


def test_filter_candidates_excludes_non_audio_extension():
    track = make_track()
    cover_art = make_file(
        filename="@@1a2b3c\\Music\\Dom Dolla\\Rhyme Dust\\cover.jpg",
        extension="jpg",
        size=204_800,
        bit_rate=None,
        bit_depth=None,
        sample_rate=None,
    )

    assert filter_candidates(track, [cover_art]) == []


def test_filter_candidates_excludes_wrong_artist():
    track = make_track()
    wrong_artist = make_file(
        filename="@@1a2b3c\\Private\\Some Other Artist - Rhyme Dust.mp3",
        extension="mp3",
        bit_rate=320,
        is_variable_bitrate=False,
        bit_depth=None,
    )

    assert filter_candidates(track, [wrong_artist]) == []


def test_filter_candidates_excludes_mashup_contamination():
    track = make_track()
    mashup = make_file(
        filename=(
            "@@1a2b3c\\Private\\Dom Dolla vs Some Other Artist - "
            "Rhyme Dust X Another Song (Mashup).mp3"
        ),
        extension="mp3",
        bit_rate=320,
        is_variable_bitrate=False,
        bit_depth=None,
    )

    assert filter_candidates(track, [mashup]) == []


def test_filter_candidates_keeps_clean_match():
    track = make_track()
    clean = make_file()

    assert filter_candidates(track, [clean]) == [clean]


def test_filter_candidates_matches_multi_artist_track_crediting_only_one():
    # track.artist may credit multiple artists joined with ", " (e.g.
    # "MK, Dom Dolla") — a Soulseek filename crediting only one of them
    # should still pass.
    track = make_track(artist="MK, Dom Dolla", title="Rhyme Dust")
    single_credit = make_file(
        filename="@@1a2b3c\\Music\\MK - Rhyme Dust.flac",
    )

    assert filter_candidates(track, [single_credit]) == [single_credit]


def test_select_downloads_prefers_shorter_queue_on_quality_tie():
    # Two real, equal-tier/bitrate candidates (both flac, no reported
    # bit_rate — real search data for lossless files) differing only in
    # queue length — previously this tie fell through to incidental list
    # order rather than genuinely preferring the shorter queue.
    track = make_track()
    slow_flac = make_file(
        filename="@@seeder1\\Dom Dolla - Rhyme Dust.flac",
        extension="flac",
        queue_length=50,
    )
    fast_flac = make_file(
        filename="@@seeder2\\Dom Dolla - Rhyme Dust.flac",
        extension="flac",
        queue_length=5,
    )

    # Input order deliberately puts the slow one first, so a pass would
    # only happen via the real tiebreak, not incidental list order.
    settled, _, _ = select_downloads(track, [slow_flac, fast_flac])

    assert settled is fast_flac


def test_select_downloads_returns_none_settled_when_nothing_matches():
    track = make_track()
    wrong_artist = make_file(
        filename="Some Other Artist - Rhyme Dust.mp3",
        extension="mp3",
        bit_rate=320,
        is_variable_bitrate=False,
        bit_depth=None,
    )

    settled, upgrade_shortlist, _ = select_downloads(track, [wrong_artist])

    assert settled is None
    assert upgrade_shortlist == []


def test_select_downloads_returns_no_upgrade_when_top_pick_is_practical():
    track = make_track()
    practical_flac = make_file(queue_length=2)

    settled, upgrade_shortlist, _ = select_downloads(track, [practical_flac])

    assert settled is practical_flac
    assert upgrade_shortlist == []


def test_select_downloads_returns_practical_settled_and_impractical_upgrade():
    track = make_track()

    impractical_flac = make_file(
        filename="Dom Dolla - Rhyme Dust.flac",
        extension="flac",
        queue_length=500,
    )
    practical_mp3 = make_file(
        filename="Dom Dolla - Rhyme Dust.mp3",
        extension="mp3",
        bit_rate=320,
        is_variable_bitrate=False,
        bit_depth=None,
        queue_length=2,
    )

    settled, upgrade_shortlist, _ = select_downloads(
        track, [impractical_flac, practical_mp3]
    )

    assert settled is practical_mp3
    assert upgrade_shortlist == [impractical_flac]


def test_select_downloads_falls_back_to_phase_one_when_none_practical():
    track = make_track()

    impractical_flac = make_file(
        filename="Dom Dolla - Rhyme Dust.flac",
        extension="flac",
        queue_length=500,
    )
    impractical_mp3 = make_file(
        filename="Dom Dolla - Rhyme Dust.mp3",
        extension="mp3",
        bit_rate=320,
        is_variable_bitrate=False,
        bit_depth=None,
        queue_length=800,
    )

    settled, upgrade_shortlist, _ = select_downloads(
        track, [impractical_flac, impractical_mp3]
    )

    assert settled is impractical_flac
    assert upgrade_shortlist == []


def test_select_downloads_never_settles_on_a_locked_candidate():
    # A locked file with an empty queue would otherwise look "practical"
    # — but locked is a harder blocker than a long queue, so it must
    # never become settled even when nothing else is available.
    track = make_track()
    locked_flac = make_file(
        filename="Dom Dolla - Rhyme Dust.flac",
        extension="flac",
        queue_length=0,
        locked=True,
    )

    settled, upgrade_shortlist, _ = select_downloads(track, [locked_flac])

    assert settled is None
    assert upgrade_shortlist == [locked_flac]


def test_select_downloads_locked_upgrade_takes_precedence_when_higher_quality():
    # A locked flac (genuinely higher quality) outranks a merely
    # impractical mp3 for the upgrade slot — the settled pick still
    # falls back to the impractical-but-unlocked mp3 (downloadable,
    # just slow), not the locked one (not downloadable at all).
    track = make_track()
    locked_flac = make_file(
        filename="Dom Dolla - Rhyme Dust.flac",
        extension="flac",
        queue_length=0,
        locked=True,
    )
    impractical_mp3 = make_file(
        filename="Dom Dolla - Rhyme Dust.mp3",
        extension="mp3",
        bit_rate=320,
        is_variable_bitrate=False,
        bit_depth=None,
        queue_length=800,
    )

    settled, upgrade_shortlist, _ = select_downloads(
        track, [locked_flac, impractical_mp3]
    )

    assert settled is impractical_mp3
    assert upgrade_shortlist == [locked_flac]


def test_select_downloads_prefers_unlocked_over_locked_on_quality_tie():
    # Equal quality (same tier, same bitrate) — locked must NOT win a
    # tie over an otherwise-equal unlocked, practical candidate; ties go
    # to whichever is actually downloadable right now.
    track = make_track()
    locked_mp3 = make_file(
        filename="Dom Dolla - Rhyme Dust (locked copy).mp3",
        extension="mp3",
        bit_rate=320,
        is_variable_bitrate=False,
        bit_depth=None,
        queue_length=0,
        locked=True,
    )
    practical_mp3 = make_file(
        filename="Dom Dolla - Rhyme Dust.mp3",
        extension="mp3",
        bit_rate=320,
        is_variable_bitrate=False,
        bit_depth=None,
        queue_length=2,
    )

    settled, upgrade_shortlist, _ = select_downloads(
        track, [locked_mp3, practical_mp3]
    )

    assert settled is practical_mp3
    assert upgrade_shortlist == []


def test_select_downloads_shortlist_capped_at_three_and_ranked():
    track = make_track()

    settled_practical = make_file(
        filename="Dom Dolla - Rhyme Dust.mp3",
        extension="mp3",
        bit_rate=192,
        is_variable_bitrate=False,
        bit_depth=None,
        queue_length=2,
    )
    # Four locked candidates, all genuinely better quality (flac beats
    # mp3 on tier) than settled — locked so none of them could become
    # settled themselves — in a deliberately scrambled input order. The
    # shortlist must come back ranked best-first (shortest queue wins
    # among the resulting ties) and capped at MAX_UPGRADE_SHORTLIST (3),
    # dropping the 4th-best even though it's still better than settled.
    # Filenames stay clean (no descriptive suffix) since any extra text
    # dilutes the fuzzy title match below AUTO_MATCH_THRESHOLD, same
    # class of issue as the "mashup contamination" test above — queue
    # length (via a distinct peer id) is enough to tell candidates apart.
    rank_candidates = [
        make_file(
            filename=f"@@peer{i}\\Dom Dolla - Rhyme Dust.flac",
            extension="flac",
            queue_length=queue_length,
            locked=True,
        )
        for i, queue_length in enumerate([300, 10, 200, 50])
    ]

    settled, upgrade_shortlist, _ = select_downloads(
        track, [settled_practical, *rank_candidates]
    )

    assert settled is settled_practical
    assert len(upgrade_shortlist) == 3
    assert [f.queue_length for f in upgrade_shortlist] == [10, 50, 200]


# Real search data captured live (2026-08-27) for two of the real "Test"
# playlist's unmatched tracks — both genuinely landed in the 70-89
# needs_review band, real DJ-pool filename noise ("(Clean) 4A 87",
# "(Original Mix)") diluting an otherwise-correct match below
# AUTO_MATCH_THRESHOLD. (A third real candidate, for "Jade Venom - Scared
# Now? - DIVERGENCE VI", scored 90.9 — genuinely auto-tier, just locked —
# so it belongs to the upgrade-shortlist path fixed separately, not this
# tier; see test_download_service.py's
# test_download_playlist_requests_locked_only_candidate_as_upgrade.)
REAL_PRDK_CANDIDATE = SoulseekFile(
    username="musicmasterrdjpool",
    filename=(
        "DJPOOLS\\2026\\MONTHS\\FEB\\20\\The Mash Up 20 FEB\\"
        "Prdk - One More Night (Clean) 4A 87.mp3"
    ),
    extension="mp3",
    size=9_251_601,
    queue_length=67_376,
    upload_speed=143_109,
    has_free_upload_slot=False,
    length=227,
    bit_rate=320,
    bit_depth=None,
    sample_rate=None,
    is_variable_bitrate=False,
)

REAL_ZIGI_SC_CANDIDATE = SoulseekFile(
    username="musicmasterrdjpool",
    filename=(
        "DJPOOLS\\2026\\MONTHS\\AUG\\18\\"
        "Beatport Best of Independent Artist [July 2026]\\"
        "A-Cray, Zigi SC - Bit Perfect (Original Mix).mp3"
    ),
    extension="mp3",
    size=12_424_929,
    queue_length=67_377,
    upload_speed=143_109,
    has_free_upload_slot=False,
    length=306,
    bit_rate=320,
    bit_depth=None,
    sample_rate=None,
    is_variable_bitrate=False,
)


def test_find_best_needs_review_candidate_classifies_real_prdk_data():
    track = make_track(id="prdk1", title="ONE MORE NIGHT", artist="Prdk")

    # Never auto-tier: the DJ-pool suffix keeps it out of filter_candidates.
    assert filter_candidates(track, [REAL_PRDK_CANDIDATE]) == []

    result = find_best_needs_review_candidate(track, [REAL_PRDK_CANDIDATE])

    assert result is not None
    file, score = result
    assert file is REAL_PRDK_CANDIDATE
    assert 70.0 <= score < 90.0

    settled, upgrade_shortlist, needs_review = select_downloads(
        track, [REAL_PRDK_CANDIDATE]
    )
    assert settled is None
    assert upgrade_shortlist == []
    assert needs_review == result


def test_find_best_needs_review_candidate_classifies_real_zigi_sc_data():
    track = make_track(
        id="zigi1", title="Bit Perfect", artist="Zigi SC, A-Cray",
    )

    assert filter_candidates(track, [REAL_ZIGI_SC_CANDIDATE]) == []

    result = find_best_needs_review_candidate(
        track, [REAL_ZIGI_SC_CANDIDATE]
    )

    assert result is not None
    file, score = result
    assert file is REAL_ZIGI_SC_CANDIDATE
    assert 70.0 <= score < 90.0

    settled, upgrade_shortlist, needs_review = select_downloads(
        track, [REAL_ZIGI_SC_CANDIDATE]
    )
    assert settled is None
    assert upgrade_shortlist == []
    assert needs_review == result


# --- Step 8: threshold overrides ------------------------------------
#
# filter_candidates/find_best_needs_review_candidate/select_downloads
# stay pure plain functions with no config awareness at all (see
# CLAUDE.md item 28) — DownloadService is the one real caller that
# resolves config-or-default and passes the numbers in explicitly.
# These tests exercise the override parameter directly, using the same
# real Prdk/Zigi SC-A-Cray data the needs_review tier was built and
# verified against, since a lowered auto_match_threshold is exactly
# what should move them from needs_review into the auto tier.

def test_filter_candidates_unchanged_default_behavior_without_override():
    track = make_track()
    clean = make_file()

    assert filter_candidates(track, [clean]) == [clean]


def test_filter_candidates_real_prdk_data_passes_with_lowered_threshold():
    track = make_track(id="prdk1", title="ONE MORE NIGHT", artist="Prdk")

    # Confirmed above: 70.4 at the default AUTO_MATCH_THRESHOLD=90 stays
    # needs_review-only. A threshold at or below its real score moves it
    # into the auto tier — proving the override parameter, not just its
    # default, actually changes classification.
    assert filter_candidates(
        track, [REAL_PRDK_CANDIDATE], auto_match_threshold=70.0,
    ) == [REAL_PRDK_CANDIDATE]


def test_find_best_needs_review_candidate_unchanged_default_without_override():
    track = make_track(id="prdk1", title="ONE MORE NIGHT", artist="Prdk")

    result = find_best_needs_review_candidate(track, [REAL_PRDK_CANDIDATE])

    assert result is not None
    assert result[0] is REAL_PRDK_CANDIDATE


def test_find_best_needs_review_candidate_respects_narrowed_band():
    # Zigi SC/A-Cray's real score is 73.2 — raising needs_review_threshold
    # above it excludes it from the tier entirely, using the override.
    track = make_track(
        id="zigi1", title="Bit Perfect", artist="Zigi SC, A-Cray",
    )

    result = find_best_needs_review_candidate(
        track, [REAL_ZIGI_SC_CANDIDATE], needs_review_threshold=74.0,
    )

    assert result is None


def test_select_downloads_real_prdk_data_settles_with_lowered_threshold():
    track = make_track(id="prdk1", title="ONE MORE NIGHT", artist="Prdk")

    settled, upgrade_shortlist, needs_review = select_downloads(
        track, [REAL_PRDK_CANDIDATE], auto_match_threshold=70.0,
    )

    assert settled is REAL_PRDK_CANDIDATE


# --- Local-file quality analysis (roadmap item 5) ------------------------

def test_quality_tier_for_format_matches_lossless_lossy_unknown():
    assert quality_tier_for_format("flac") == 2
    assert quality_tier_for_format(".WAV") == 2
    assert quality_tier_for_format("mp3") == 1
    assert quality_tier_for_format(".M4A") == 1
    assert quality_tier_for_format("xyz") == 0


def test_quality_tier_for_format_aiff_is_lossless_aifc_is_not():
    # Roadmap item R1.2/R1.3 — .aiff/.aif are genuinely uncompressed
    # PCM; .aifc is a container that CAN hold compressed audio, so it
    # deliberately stays out of LOSSLESS_EXTENSIONS (scores unknown/0
    # rather than falsely claiming a lossless tier).
    assert quality_tier_for_format("aiff") == 2
    assert quality_tier_for_format(".AIF") == 2
    assert quality_tier_for_format("aifc") == 0


def _write_wav(
        path,
        samples: np.ndarray,
        sample_rate: int = 44_100,
        subtype: str = "PCM_16",
) -> None:
    sf.write(str(path), samples, sample_rate, subtype=subtype)


def test_analyze_local_file_quality_reports_lossless_tier_and_real_format_info(
        tmp_path,
):
    path = tmp_path / "test.wav"
    samples = (np.sin(np.linspace(0, 100, 44_100)) * 0.1).astype(np.float32)
    _write_wav(path, samples)

    result = analyze_local_file_quality(path)

    assert result.tier == 2
    assert result.sample_rate == 44_100
    assert result.bit_depth == 16
    # Confirmed live, not assumed: mutagen DOES report a real bitrate
    # for uncompressed WAV PCM (sample_rate * bit_depth * channels =
    # 44100 * 16 * 1 = 705,600 bps = 705 kbps) — an initial draft of
    # this test wrongly assumed lossless meant "no bitrate concept."
    assert result.bitrate_kbps == 705


def test_analyze_local_file_quality_reports_lossless_tier_for_real_aiff(
        tmp_path,
):
    # Roadmap item R1.4 — live-verified (see docs/HISTORY.md item R1):
    # mutagen 1.48.1's AIFFInfo already computes
    # bitrate = channels * sample_size * sample_rate internally, so no
    # AIFF-specific derivation branch was needed in
    # analyze_local_file_quality — this is that verification made a
    # permanent regression test, same shape as the WAV test above.
    path = tmp_path / "test.aiff"
    samples = (np.sin(np.linspace(0, 100, 44_100)) * 0.1).astype(np.float32)
    _write_wav(path, samples)

    result = analyze_local_file_quality(path)

    assert result.tier == 2
    assert result.sample_rate == 44_100
    assert result.bit_depth == 16
    assert result.bitrate_kbps == 705


def test_analyze_local_file_quality_detects_real_clipping(tmp_path):
    path = tmp_path / "clipped.wav"
    full_scale = np.iinfo(np.int16).max
    # Half the samples pinned to full-scale (genuinely clipped), half a
    # quiet, unclipped tone.
    clipped_half = np.full(22_050, full_scale, dtype=np.int16)
    quiet_half = (np.sin(np.linspace(0, 100, 22_050)) * 1000).astype(
        np.int16
    )
    samples = np.concatenate([clipped_half, quiet_half])
    _write_wav(path, samples)

    result = analyze_local_file_quality(path)

    assert result.clipping_ratio == pytest.approx(0.5, abs=0.01)


def test_analyze_local_file_quality_reports_near_zero_clipping_when_clean(
        tmp_path,
):
    path = tmp_path / "clean.wav"
    samples = (np.sin(np.linspace(0, 100, 44_100)) * 0.1).astype(np.float32)
    _write_wav(path, samples)

    result = analyze_local_file_quality(path)

    assert result.clipping_ratio < 0.01


def test_analyze_local_file_quality_measures_real_integrated_loudness(
        tmp_path,
):
    path = tmp_path / "loud_enough.wav"
    # pyloudnorm's gated ITU-R BS.1770 measurement needs a real-enough
    # signal (long/loud enough) to produce a value at all — a few
    # seconds of an audible tone, not silence.
    duration_seconds = 5
    t = np.linspace(0, duration_seconds, 44_100 * duration_seconds)
    samples = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)
    _write_wav(path, samples)

    result = analyze_local_file_quality(path)

    assert result.integrated_loudness_lufs is not None
    assert isinstance(result.integrated_loudness_lufs, float)


def test_analyze_local_file_quality_returns_none_loudness_for_silence(
        tmp_path,
):
    path = tmp_path / "silence.wav"
    samples = np.zeros(44_100, dtype=np.float32)
    _write_wav(path, samples)

    result = analyze_local_file_quality(path)

    assert result.integrated_loudness_lufs is None
