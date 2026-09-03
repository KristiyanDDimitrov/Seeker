import pytest


@pytest.fixture(autouse=True)
def _force_dev_build_identity(monkeypatch):
    """Roadmap item RR1.2 — a real local packaging build leaves
    src/seeker/_build_info_generated.py behind (gitignored, never
    tracked — see _build_info.py's own docstring), which makes
    seeker._build_info.GIT_SHA/GIT_DESCRIBE/BUILT_AT read the real
    build's SHA/timestamp instead of the committed "dev" fallback.
    That's exactly what broke test_main_window_constructs_without_
    crashing and test_about_dialog_shows_build_identity in round 3 —
    both asserted the literal "dev" on the wrong assumption that "this
    test never runs against a real packaged build" (true) meant it was
    also safe from a build having happened at some point on the same
    machine (false, since the generated file just sits there
    afterward). Forced back to "dev" for every test in the whole
    suite, unconditionally — a developer's own local build must never
    be able to change what this suite reports, on this machine or
    anyone else's.
    """
    monkeypatch.setattr("seeker._build_info.GIT_SHA", "dev")
    monkeypatch.setattr("seeker._build_info.GIT_DESCRIBE", "dev")
    monkeypatch.setattr("seeker._build_info.BUILT_AT", "dev")
