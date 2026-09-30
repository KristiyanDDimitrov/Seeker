import pytest

from seeker.models.library_result import MatchResult, ScanResult


def test_scan_results_add_field_by_field():
    total = ScanResult(added=1, updated=2, removed=3, unchanged=4) + ScanResult(
        added=10, updated=20, removed=30, unchanged=40,
    )

    assert total == ScanResult(added=11, updated=22, removed=33, unchanged=44)


def test_match_result_counts_each_method_in_its_own_bucket():
    result = MatchResult()

    for method in ("auto", "needs_review", None, None):
        result.count(method)

    assert result == MatchResult(auto=1, needs_review=1, unmatched=2)


def test_match_result_refuses_an_unknown_method():
    with pytest.raises(ValueError, match="'manual' is not a match method"):
        MatchResult().count("manual")
