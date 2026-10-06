import re

from seeker.models.download_result import PlaylistDownloadResult, TrackFailure
from seeker.models.location_merge import LocationMergeSummary
from seeker.models.location_removal import LocationRemovalSummary
from seeker.ui import help_text
from seeker.ui.help_text import SHARING_FRAMING_BODY


def test_sharing_framing_states_slskd_admin_ui_is_local_only():
    # Roadmap item 116 (round 8, §6.1.4) — someone running a
    # file-sharing daemon deserves to be told plainly what it's
    # exposing and that its admin interface is local-only.
    assert "read-only" in SHARING_FRAMING_BODY
    assert "bound to this machine only" in SHARING_FRAMING_BODY


def test_remove_location_confirm_body_names_everything_it_forgets():
    summary = LocationRemovalSummary(
        location_name="Music",
        files_forgotten=3454,
        matches_cleared=12,
        confirmed_matches_cleared=3,
        playlists_affected=2,
        was_default=False,
    )

    assert help_text.format_remove_location_confirm_body(summary) == (
        "Remove 'Music'? Seeker forgets 3,454 indexed files and 12 "
        "matches (3 you confirmed). 2 playlists download here and will "
        "need a new destination. Files on disk are not touched."
    )


def merge_summary(merged_name: str, **counts) -> LocationMergeSummary:
    fields = {
        "files_merged": 0,
        "files_forgotten": 0,
        "matches_moved": 0,
        "matches_cleared": 0,
        "analyses_kept": 0,
        "playlists_moved": 0,
        "playlists_cleared": 0,
        "was_default": False,
    }
    fields.update(counts)

    return LocationMergeSummary(
        merged_name=merged_name, kept_name="Music", **fields,
    )


def test_merge_confirm_body_totals_every_location_merged():
    summaries = [
        merge_summary(
            "x9-pro",
            files_merged=3452,
            files_forgotten=5,
            matches_moved=37,
            analyses_kept=2663,
            playlists_moved=1,
            was_default=True,
        ),
        merge_summary("Test", files_merged=9, matches_moved=6),
    ]

    assert help_text.format_merge_locations_confirm_body(
        "Music", summaries,
    ) == (
        "Keep 'Music' and merge 'x9-pro' and 'Test' into it? 3,461 of "
        "their files are also indexed under 'Music': 43 matches move "
        "there, and 2,663 files gain analysis 'Music' lacked. Seeker "
        "forgets the other 5 indexed files and 0 matches. 1 playlist "
        "keeps downloading into the same folder through 'Music'. The "
        "default download location is among them and will be cleared. "
        "Files on disk are not touched."
    )


def test_merge_result_names_what_changed():
    summaries = [merge_summary("Test", matches_moved=1, playlists_cleared=2)]

    assert help_text.format_merge_locations_result("Music", summaries) == (
        "Merged 'Test' into 'Music': moved 1 match, kept analysis for 0 "
        "files, forgot 0 indexed files and 0 matches. 2 playlists need a "
        "new destination."
    )


def test_download_result_message_lists_each_failed_track_with_its_reason():
    result = PlaylistDownloadResult(
        requested=1,
        total=3,
        failures=[
            TrackFailure("A - One", "Couldn't reach slskd."),
            TrackFailure("B - Two", "Search timed out."),
        ],
    )

    message = help_text.format_download_result_message(result)

    assert "2 failed" in message
    assert "A - One: Couldn't reach slskd." in message
    assert "B - Two: Search timed out." in message


def test_download_result_message_caps_the_failure_list():
    failures = [TrackFailure(f"Artist - Title {n}", "Oops.") for n in range(7)]

    message = help_text.format_download_result_message(
        PlaylistDownloadResult(total=7, failures=failures),
    )

    assert "Artist - Title 4" in message
    assert "Artist - Title 5" not in message
    assert "and 2 more" in message


def _module_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _module_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _module_strings(item)


def test_no_help_text_constant_carries_development_history():
    # Tooltips, labels and help pages are user-facing copy; a roadmap
    # or round number means nothing to the person reading it.
    history = re.compile(
        r"[Rr]oadmap item|[Rr]ound [0-9]|item [0-9]|§[0-9]|HISTORY"
    )

    leaks = [
        f"{name}: {match.group(0)}"
        for name, value in vars(help_text).items()
        if name.isupper()
        for text in _module_strings(value)
        for match in [history.search(text)]
        if match
    ]

    assert leaks == []
