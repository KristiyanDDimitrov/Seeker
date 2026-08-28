from seeker.application import Application
from seeker.docker_setup import DockerState
from seeker.ui.wizard import OnboardingWizard


def _fake_user_data_dir(data_dir):
    def fake(appname, **kwargs):
        return str(data_dir)

    return fake


def make_application(tmp_path, monkeypatch) -> Application:
    monkeypatch.chdir(tmp_path)
    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )
    return Application()


def test_wizard_starts_at_spotify_step_when_nothing_configured(
        qtbot, tmp_path, monkeypatch,
):
    # Both the frozen config.* constants AND the live env vars must be
    # cleared — migrate_legacy_env_config reads os.environ live (via
    # os.getenv), independent of the config.* module constants, so this
    # process's real .env would otherwise leak a real SPOTIFY_CLIENT_ID
    # into the store during Application() construction. Same isolation
    # gap Task 1 already hit once for the SLSKD_* fields.
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)
    monkeypatch.setattr("seeker.application.config.SPOTIFY_CLIENT_ID", None)
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_REDIRECT_URI", None,
    )

    application = make_application(tmp_path, monkeypatch)
    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    assert wizard.stack.currentIndex() == 0


def test_wizard_resumes_at_library_step_when_spotify_already_configured(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_CLIENT_ID", "already-set",
    )
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_REDIRECT_URI",
        "http://127.0.0.1:8888/callback",
    )

    application = make_application(tmp_path, monkeypatch)
    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    assert wizard.stack.currentIndex() == 1


def test_wizard_resumes_at_soulseek_step_when_spotify_and_library_done(
        qtbot, tmp_path, monkeypatch,
):
    # The real resumability scenario per the task's own spec: Spotify
    # done, library done, SoulSeek not — must land directly on step 3,
    # not restart from step 1.
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_CLIENT_ID", "already-set",
    )
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_REDIRECT_URI",
        "http://127.0.0.1:8888/callback",
    )
    # Docker detection would otherwise run for real on step-3 entry —
    # stub it so this test doesn't depend on the host's real Docker
    # state.
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.NOT_INSTALLED,
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    assert wizard.stack.currentIndex() == 2


def test_wizard_soulseek_step_checks_real_docker_state_on_entry(
        qtbot, tmp_path, monkeypatch,
):
    # Resumability for step 3 itself: never assume Docker's state —
    # always re-check live on entry, so a docker compose up that
    # already succeeded in a prior session is reflected immediately
    # rather than blindly repeated.
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_CLIENT_ID", "already-set",
    )
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_REDIRECT_URI",
        "http://127.0.0.1:8888/callback",
    )
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.RUNNING,
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    qtbot.waitUntil(
        lambda: wizard.docker_state_label.text() == "Docker is running.",
        timeout=2000,
    )


def test_wizard_skip_soulseek_advances_to_dashboard_without_credentials(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_CLIENT_ID", "already-set",
    )
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_REDIRECT_URI",
        "http://127.0.0.1:8888/callback",
    )
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.NOT_INSTALLED,
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    completed = []
    wizard = OnboardingWizard(
        application, on_complete=lambda: completed.append(True),
    )
    qtbot.addWidget(wizard)

    assert wizard.stack.currentIndex() == 2

    wizard._on_skip_soulseek_clicked()

    assert completed == [True]
