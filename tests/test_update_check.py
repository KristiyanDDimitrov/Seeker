import httpx
import pytest

from seeker.update_check import UpdateStatus, check_for_update


class FakeResponse:
    def __init__(self, status_code: int, data: dict | None = None):
        self.status_code = status_code
        self._data = data

    def json(self):
        if self._data is None:
            raise ValueError("not JSON")
        return self._data


@pytest.fixture(autouse=True)
def fake_installed_version(monkeypatch):
    # Every test in this file cares about GitHub's response shape, not
    # the installed-version lookup itself — pinned to a fixed value so
    # UP_TO_DATE/UPDATE_AVAILABLE comparisons are deterministic
    # regardless of pyproject.toml's own current version.
    monkeypatch.setattr(
        "seeker.update_check.version", lambda name: "1.2.0",
    )


def test_up_to_date_when_latest_tag_equals_installed_version(monkeypatch):
    def fake_get(url, timeout=None):
        assert url == (
            "https://api.github.com/repos/KristiyanDDimitrov/Seeker/"
            "releases/latest"
        )
        return FakeResponse(
            200,
            {"tag_name": "v1.2.0", "html_url": "https://example.com/v1.2.0"},
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_for_update()

    assert result.status == UpdateStatus.UP_TO_DATE
    assert result.latest_version == "v1.2.0"
    assert result.reason is None


def test_update_available_when_latest_tag_is_newer(monkeypatch):
    def fake_get(url, timeout=None):
        return FakeResponse(
            200,
            {"tag_name": "v1.3.0", "html_url": "https://example.com/v1.3.0"},
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_for_update()

    assert result.status == UpdateStatus.UPDATE_AVAILABLE
    assert result.latest_version == "v1.3.0"
    assert result.release_url == "https://example.com/v1.3.0"


def test_up_to_date_when_latest_tag_is_older(monkeypatch):
    # A real, if unusual, case (e.g. a hotfix branch/older republished
    # tag) — must not report UPDATE_AVAILABLE for a strictly-older tag.
    def fake_get(url, timeout=None):
        return FakeResponse(200, {"tag_name": "v1.0.0"})

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_for_update()

    assert result.status == UpdateStatus.UP_TO_DATE


def test_real_404_shape_reports_no_releases_published(monkeypatch):
    # The exact real shape confirmed live against
    # https://api.github.com/repos/KristiyanDDimitrov/Seeker/releases/latest
    # on 2026-09-01: status 404, body
    # {"message": "Not Found", "documentation_url": "...", "status": "404"}
    def fake_get(url, timeout=None):
        return FakeResponse(
            404,
            {
                "message": "Not Found",
                "documentation_url": (
                    "https://docs.github.com/rest/releases/releases"
                    "#get-the-latest-release"
                ),
                "status": "404",
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_for_update()

    # Round 9 §4.2a — its own status, not UNAVAILABLE: a repo with
    # nothing published yet isn't a fault. See NO_RELEASES_PUBLISHED's
    # own docstring.
    assert result.status == UpdateStatus.NO_RELEASES_PUBLISHED
    assert result.reason == "No releases have been published yet."


def test_403_rate_limit_reports_unavailable(monkeypatch):
    def fake_get(url, timeout=None):
        return FakeResponse(403, {"message": "API rate limit exceeded"})

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_for_update()

    assert result.status == UpdateStatus.UNAVAILABLE
    assert "rate-limited" in result.reason.lower()


def test_timeout_reports_unavailable(monkeypatch):
    def fake_get(url, timeout=None):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_for_update()

    assert result.status == UpdateStatus.UNAVAILABLE
    assert "timed out" in result.reason.lower()


def test_connection_error_reports_unavailable(monkeypatch):
    def fake_get(url, timeout=None):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_for_update()

    assert result.status == UpdateStatus.UNAVAILABLE
    assert "couldn't reach github" in result.reason.lower()


def test_unparseable_latest_tag_reports_unavailable(monkeypatch):
    def fake_get(url, timeout=None):
        return FakeResponse(200, {"tag_name": "not-a-version"})

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_for_update()

    assert result.status == UpdateStatus.UNAVAILABLE
    assert "couldn't parse" in result.reason.lower()


def test_non_json_response_reports_unavailable(monkeypatch):
    def fake_get(url, timeout=None):
        return FakeResponse(200, None)

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_for_update()

    assert result.status == UpdateStatus.UNAVAILABLE
    assert "valid json" in result.reason.lower()


def test_missing_tag_name_field_reports_unavailable(monkeypatch):
    def fake_get(url, timeout=None):
        return FakeResponse(200, {"html_url": "https://example.com"})

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_for_update()

    assert result.status == UpdateStatus.UNAVAILABLE
    assert "missing" in result.reason.lower()


def test_unexpected_status_code_reports_unavailable(monkeypatch):
    def fake_get(url, timeout=None):
        return FakeResponse(500, {})

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_for_update()

    assert result.status == UpdateStatus.UNAVAILABLE
    assert "500" in result.reason


def test_no_installed_version_reports_unavailable(monkeypatch):
    from importlib.metadata import PackageNotFoundError

    def raise_not_found(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(
        "seeker.update_check.version", raise_not_found,
    )

    result = check_for_update()

    assert result.status == UpdateStatus.UNAVAILABLE
    assert "installed version" in result.reason.lower()


def test_check_for_update_never_raises_even_on_a_genuinely_unexpected_error(
        monkeypatch,
):
    # The "never raises" contract is unconditional, not scoped to just
    # the anticipated httpx/parsing failures above — this runs from a
    # manual Help menu click and must never take the app down with it.
    def fake_get(url, timeout=None):
        raise RuntimeError("something genuinely unexpected")

    monkeypatch.setattr(httpx, "get", fake_get)

    result = check_for_update()

    assert result.status == UpdateStatus.UNAVAILABLE
    assert "unexpected error" in result.reason.lower()
