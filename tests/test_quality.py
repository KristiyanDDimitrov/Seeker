from seeker.models.soulseek_file import SoulseekFile
from seeker.models.track import Track
from seeker.soulseek.quality import (
    filter_candidates,
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
    settled, _ = select_downloads(track, [slow_flac, fast_flac])

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

    settled, upgrade_shortlist = select_downloads(track, [wrong_artist])

    assert settled is None
    assert upgrade_shortlist == []


def test_select_downloads_returns_no_upgrade_when_top_pick_is_practical():
    track = make_track()
    practical_flac = make_file(queue_length=2)

    settled, upgrade_shortlist = select_downloads(track, [practical_flac])

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

    settled, upgrade_shortlist = select_downloads(
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

    settled, upgrade_shortlist = select_downloads(
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

    settled, upgrade_shortlist = select_downloads(track, [locked_flac])

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

    settled, upgrade_shortlist = select_downloads(
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

    settled, upgrade_shortlist = select_downloads(
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

    settled, upgrade_shortlist = select_downloads(
        track, [settled_practical, *rank_candidates]
    )

    assert settled is settled_practical
    assert len(upgrade_shortlist) == 3
    assert [f.queue_length for f in upgrade_shortlist] == [10, 50, 200]
