from seeker.application import Application
from seeker.docker_setup import (
    DockerState,
    SlskdHealthCheckResult,
    SlskdHealthStatus,
)
from seeker.ui import help_text
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


def test_wizard_controls_have_tooltips(qtbot, tmp_path, monkeypatch):
    # Task 1 — every clickable control across the wizard's three pages
    # gets a setToolTip(), regardless of which step is currently shown
    # (all three pages are constructed up front by QStackedWidget).
    application = make_application(tmp_path, monkeypatch)
    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    for widget in (
            wizard.client_id_field,
            wizard.connect_button,
            wizard.soulseek_username_field,
            wizard.soulseek_password_field,
            wizard.bring_up_button,
    ):
        assert widget.toolTip() != ""


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


# --- Real click-handler wiring — a genuine coverage gap closed here,
# not thin-by-design glue. Every prior test above only exercises which
# step the wizard resumes at; none of them ever click a real button.
# Settings' equivalent actions (connect_spotify, credential update) are
# already tested this same way (tests/test_settings_window.py) — the
# wizard's own action handlers had no equivalent coverage at all.

def test_connect_spotify_button_calls_connect_spotify_and_advances(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)
    monkeypatch.setattr("seeker.application.config.SPOTIFY_CLIENT_ID", None)
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_REDIRECT_URI", None,
    )

    application = make_application(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        application, "connect_spotify", lambda client_id: calls.append(client_id),
    )

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    assert wizard.stack.currentIndex() == 0

    wizard.client_id_field.setText("real-client-id")
    wizard.connect_button.click()

    qtbot.waitUntil(lambda: calls != [], timeout=2000)
    assert calls == ["real-client-id"]

    qtbot.waitUntil(lambda: wizard.stack.currentIndex() == 1, timeout=2000)
    assert wizard.spotify_status_label.text() == "Connected."


def test_choose_library_folder_registers_location_and_advances(
        qtbot, tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QFileDialog

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

    chosen_path = tmp_path / "music"
    chosen_path.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(chosen_path),
    )

    application = make_application(tmp_path, monkeypatch)
    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    assert wizard.stack.currentIndex() == 1

    # on_path_picked fires synchronously, before the worker-routed
    # add_location() call completes.
    wizard._on_choose_library_folder_clicked()
    assert wizard.library_path_label.text() == str(chosen_path)

    qtbot.waitUntil(lambda: wizard.stack.currentIndex() == 2, timeout=2000)
    locations = application.library_service.list_locations()
    assert [loc.name for loc, _ in locations] == ["Library"]
    assert locations[0][0].path == str(chosen_path)


def test_bring_up_soulseek_requires_username_and_password(
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
        lambda: DockerState.RUNNING,
    )
    calls = []
    monkeypatch.setattr(
        "seeker.ui.wizard.bring_up_slskd",
        lambda **kwargs: calls.append(kwargs),
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    wizard.bring_up_button.click()

    assert calls == []
    assert "username" in wizard.soulseek_status_label.text().lower()


def test_bring_up_soulseek_calls_bring_up_slskd_with_real_values(
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
        lambda: DockerState.RUNNING,
    )

    class FakeResult:
        returncode = 0
        stderr = ""

    calls = []

    def fake_bring_up(**kwargs):
        calls.append(kwargs)
        return FakeResult()

    monkeypatch.setattr("seeker.ui.wizard.bring_up_slskd", fake_bring_up)
    monkeypatch.setattr(
        "seeker.ui.wizard.slskd_data_dir", lambda: tmp_path / "slskd-data",
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    # This wizard instance resumed directly at step 3 (both Spotify and
    # a library location already existed before construction) rather
    # than navigating there via _advance_from_library() in this same
    # session — per the wizard's own resumability design (see its
    # docstring), that combination is real code the app itself would
    # never actually reach (onboarding_complete would already be true,
    # so main_ui.py routes straight to the dashboard and never
    # constructs the wizard at all), but the resumed-step-3 STATE it
    # produces is still real and worth testing on its own. Set
    # directly, matching what a genuine _advance_from_library() call
    # would have set in the reachable version of this flow.
    wizard._library_location_path = str(tmp_path)

    # _docker_state is set asynchronously by the real _refresh_docker_state()
    # worker triggered on step-3 entry — _on_bring_up_clicked's own guard
    # requires it to already be RUNNING.
    qtbot.waitUntil(
        lambda: wizard._docker_state == DockerState.RUNNING, timeout=2000,
    )

    wizard.soulseek_username_field.setText("realuser")
    wizard.soulseek_password_field.setText("realpass")
    wizard.bring_up_button.click()

    qtbot.waitUntil(lambda: calls != [], timeout=2000)
    assert calls[0]["soulseek_username"] == "realuser"
    assert calls[0]["soulseek_password"] == "realpass"

    qtbot.waitUntil(
        lambda: wizard.soulseek_status_label.text()
        == "Waiting for SoulSeek to connect...",
        timeout=2000,
    )
    # A real health-poll timer is now running — stop it so it doesn't
    # keep firing real (unmocked) network calls after this test ends.
    wizard._stop_health_poll()


def test_health_result_healthy_persists_config_and_advances_to_dashboard(
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
        lambda: DockerState.RUNNING,
    )
    monkeypatch.setattr(
        "seeker.ui.wizard.slskd_data_dir", lambda: tmp_path / "slskd-data",
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    persist_calls = []
    monkeypatch.setattr(
        application,
        "persist_soulseek_config",
        lambda *args: persist_calls.append(args),
    )

    completed = []
    wizard = OnboardingWizard(
        application, on_complete=lambda: completed.append(True),
    )
    qtbot.addWidget(wizard)

    wizard.soulseek_username_field.setText("realuser")
    wizard.soulseek_password_field.setText("realpass")
    wizard._slskd_api_key = "real-api-key"

    wizard._handle_health_result(
        SlskdHealthCheckResult(SlskdHealthStatus.HEALTHY)
    )

    assert len(persist_calls) == 1
    assert persist_calls[0][1] == "real-api-key"
    assert persist_calls[0][3] == "realuser"
    assert persist_calls[0][4] == "realpass"
    assert completed == [True]


def test_health_result_bad_credentials_shows_real_detail_and_stays(
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
        lambda: DockerState.RUNNING,
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    completed = []
    wizard = OnboardingWizard(
        application, on_complete=lambda: completed.append(True),
    )
    qtbot.addWidget(wizard)

    wizard._handle_health_result(
        SlskdHealthCheckResult(
            SlskdHealthStatus.BAD_CREDENTIALS,
            detail="invalid username or password",
        )
    )

    assert "invalid username or password" in wizard.soulseek_status_label.text()
    assert completed == []
    assert wizard.stack.currentIndex() == 2


def test_bring_up_soulseek_blocked_when_docker_not_running(
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
    calls = []
    monkeypatch.setattr(
        "seeker.ui.wizard.bring_up_slskd",
        lambda **kwargs: calls.append(kwargs),
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)
    wizard._library_location_path = str(tmp_path)

    qtbot.waitUntil(
        lambda: wizard._docker_state == DockerState.NOT_INSTALLED,
        timeout=2000,
    )

    wizard.soulseek_username_field.setText("realuser")
    wizard.soulseek_password_field.setText("realpass")
    wizard.bring_up_button.click()

    assert calls == []
    assert wizard.soulseek_status_label.text() == "Docker isn't running yet."


def test_bring_up_soulseek_blocked_when_no_library_location(
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
        lambda: DockerState.RUNNING,
    )
    calls = []
    monkeypatch.setattr(
        "seeker.ui.wizard.bring_up_slskd",
        lambda **kwargs: calls.append(kwargs),
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)
    # _library_location_path deliberately left None — the resumed-at-
    # step-3 scenario this represents.

    qtbot.waitUntil(
        lambda: wizard._docker_state == DockerState.RUNNING, timeout=2000,
    )

    wizard.soulseek_username_field.setText("realuser")
    wizard.soulseek_password_field.setText("realpass")
    wizard.bring_up_button.click()

    assert calls == []
    assert "library location" in wizard.soulseek_status_label.text().lower()


def test_bring_up_soulseek_real_compose_failure_surfaces_stderr(
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
        lambda: DockerState.RUNNING,
    )
    monkeypatch.setattr(
        "seeker.ui.wizard.slskd_data_dir", lambda: tmp_path / "slskd-data",
    )

    class FakeFailedResult:
        returncode = 1
        stderr = "real docker compose error text"

    monkeypatch.setattr(
        "seeker.ui.wizard.bring_up_slskd",
        lambda **kwargs: FakeFailedResult(),
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)
    wizard._library_location_path = str(tmp_path)

    qtbot.waitUntil(
        lambda: wizard._docker_state == DockerState.RUNNING, timeout=2000,
    )

    wizard.soulseek_username_field.setText("realuser")
    wizard.soulseek_password_field.setText("realpass")
    wizard.bring_up_button.click()

    qtbot.waitUntil(
        lambda: "real docker compose error text"
        in wizard.soulseek_status_label.text(),
        timeout=2000,
    )


def test_health_poll_timeout_shows_message_after_elapsed_threshold(
        qtbot, tmp_path, monkeypatch,
):
    from seeker.ui.wizard import HEALTH_POLL_TIMEOUT_SECONDS
    from seeker.docker_setup import SlskdHealthStatus

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

    wizard._health_poll_elapsed = HEALTH_POLL_TIMEOUT_SECONDS

    wizard._handle_health_result(
        SlskdHealthCheckResult(SlskdHealthStatus.NOT_READY)
    )

    assert "didn't finish connecting" in wizard.soulseek_status_label.text()


def test_render_docker_state_not_installed_offers_download_link(
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

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    qtbot.waitUntil(
        lambda: wizard.docker_state_label.text() == "Docker isn't installed.",
        timeout=2000,
    )
    assert wizard.docker_action_button.text() == "Download Docker Desktop"
    # isHidden() reflects the widget's own explicit hide/show state,
    # unlike isVisible() which also requires the whole ancestor chain
    # to be shown — this wizard is never .show()n in this test.
    assert not wizard.docker_action_button.isHidden()


def test_render_docker_state_installed_not_running_offers_launch(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_CLIENT_ID", "already-set",
    )
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_REDIRECT_URI",
        "http://127.0.0.1:8888/callback",
    )
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.INSTALLED_NOT_RUNNING,
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    qtbot.waitUntil(
        lambda: wizard.docker_state_label.text()
        == "Docker is installed but not running.",
        timeout=2000,
    )
    assert wizard.docker_action_button.text() == "Launch Docker Desktop"


def test_launch_docker_clicked_success_updates_status_and_button(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_CLIENT_ID", "already-set",
    )
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_REDIRECT_URI",
        "http://127.0.0.1:8888/callback",
    )
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.INSTALLED_NOT_RUNNING,
    )
    subprocess_calls = []
    monkeypatch.setattr(
        "seeker.ui.wizard.subprocess.run",
        lambda *a, **k: subprocess_calls.append(a),
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    qtbot.waitUntil(
        lambda: wizard.docker_action_button.text() == "Launch Docker Desktop",
        timeout=2000,
    )

    wizard._on_launch_docker_clicked()

    assert subprocess_calls
    assert "Launching Docker Desktop" in wizard.soulseek_status_label.text()
    assert wizard.docker_action_button.text() == "Check again"


def test_launch_docker_clicked_failure_shows_manual_instructions(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_CLIENT_ID", "already-set",
    )
    monkeypatch.setattr(
        "seeker.application.config.SPOTIFY_REDIRECT_URI",
        "http://127.0.0.1:8888/callback",
    )
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.INSTALLED_NOT_RUNNING,
    )

    def raise_oserror(*a, **k):
        raise OSError("no such app")

    monkeypatch.setattr("seeker.ui.wizard.subprocess.run", raise_oserror)

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    qtbot.waitUntil(
        lambda: wizard.docker_action_button.text() == "Launch Docker Desktop",
        timeout=2000,
    )

    wizard._on_launch_docker_clicked()

    assert "manually" in wizard.soulseek_status_label.text().lower()
