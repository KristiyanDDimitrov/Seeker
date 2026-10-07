import threading

from fakes import wait_for_workers
from seeker.application import Application
from seeker.models.slskd_start import SlskdStartResult
from seeker.soulseek.docker_setup import (
    DockerState,
    SlskdBringUpError,
    SlskdHealthCheckResult,
    SlskdHealthStatus,
)
from seeker.spotify.callback_server import AuthorizationCancelledError
from seeker.ui import status_lamp
from seeker.ui.plain_text import plain_tooltip
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
    # No container: start_slskd reads the live /app mount, and a test
    # must never reach the real `docker inspect`.
    monkeypatch.setattr(
        "seeker.soulseek.sharing_service._get_live_container_mounts",
        lambda container_name: {},
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


def test_done_page_has_no_support_buttons(qtbot, tmp_path, monkeypatch):
    # Round 9 §4.1 — Kris: "no point in having it before the user
    # actually experiences the app." The done page's own support row
    # was removed; the real Support page (sidebar,
    # ui/pages/static_pages.py) and AboutDialog are the surfaces that
    # keep it. Inverted from the round-8 test this replaces, which
    # asserted the buttons existed — this asserts they can't come back.
    from PySide6.QtWidgets import QPushButton

    application = make_application(tmp_path, monkeypatch)
    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    wizard.stack.setCurrentIndex(3)
    done_page = wizard.stack.currentWidget()
    buttons = [
        widget
        for widget in done_page.findChildren(QPushButton)
        if widget.text().startswith("Support on")
    ]
    assert buttons == []


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
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)

    application = make_application(tmp_path, monkeypatch)
    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    assert wizard.stack.currentIndex() == 0


def test_wizard_resumes_at_library_step_when_spotify_already_configured(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

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
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
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
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.RUNNING,
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    qtbot.waitUntil(
        lambda: wizard.docker_chip.text() == "Docker is running",
        timeout=2000,
    )
    assert wizard.docker_chip.lamp == status_lamp.PLAY


def test_wizard_skip_soulseek_advances_to_dashboard_without_credentials(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
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

    # Skipping now lands on the wizard's own "you're all set" page
    # (Task 3's support-link placement) rather than closing immediately
    # — on_complete only fires once that page's own Continue button is
    # clicked.
    assert wizard.stack.currentIndex() == 3
    assert completed == []

    wizard.continue_button.click()

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
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)

    application = make_application(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        application,
        "connect_spotify",
        lambda client_id, **kwargs: calls.append(client_id),
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


# --- Roadmap item 95 (B1.1): Enter submits the Spotify step ------------

def test_client_id_return_pressed_connects_when_field_is_non_empty(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)

    application = make_application(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        application,
        "connect_spotify",
        lambda client_id, **kwargs: calls.append(client_id),
    )

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    wizard.client_id_field.setText("real-client-id")
    assert wizard.connect_button.isEnabled()

    wizard.client_id_field.returnPressed.emit()

    qtbot.waitUntil(lambda: calls != [], timeout=2000)
    assert calls == ["real-client-id"]


def test_client_id_return_pressed_does_nothing_when_field_is_empty(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)

    application = make_application(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        application,
        "connect_spotify",
        lambda client_id, **kwargs: calls.append(client_id),
    )

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    assert wizard.client_id_field.text() == ""
    assert not wizard.connect_button.isEnabled()

    wizard.client_id_field.returnPressed.emit()
    wait_for_workers(wizard)

    assert calls == []
    assert wizard.stack.currentIndex() == 0


# --- Roadmap item 95 (B1.2): Enter submits the SoulSeek step -----------

def test_soulseek_username_return_pressed_triggers_bring_up_validation(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.RUNNING,
    )
    calls = []
    monkeypatch.setattr(
        "seeker.application.bring_up_slskd",
        lambda **kwargs: calls.append(kwargs),
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    # Empty fields — Enter must reach _on_bring_up_clicked's own
    # validation and produce the same message a click would, not
    # silence.
    wizard.soulseek_username_field.returnPressed.emit()

    assert calls == []
    assert "username" in wizard.soulseek_status_label.text().lower()


def test_soulseek_password_return_pressed_calls_bring_up_slskd(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.RUNNING,
    )

    class FakeResult:
        returncode = 0
        stderr = ""

    calls = []
    monkeypatch.setattr(
        "seeker.application.bring_up_slskd",
        lambda **kwargs: (calls.append(kwargs), FakeResult())[1],
    )
    monkeypatch.setattr(
        "seeker.application.slskd_data_dir", lambda: tmp_path / "slskd-data",
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    # See test_bring_up_soulseek_calls_bring_up_slskd_with_real_values'
    # own comment: this resumed-at-step-3 combination isn't reachable
    # from the app's own real flow, but the state it produces is real
    # and worth testing directly.
    wizard._library_location_path = str(tmp_path)
    qtbot.waitUntil(
        lambda: wizard._docker_state == DockerState.RUNNING, timeout=2000,
    )

    wizard.soulseek_username_field.setText("real-username")
    wizard.soulseek_password_field.setText("real-password")

    wizard.soulseek_password_field.returnPressed.emit()

    qtbot.waitUntil(lambda: calls != [], timeout=2000)
    assert calls[0]["soulseek_username"] == "real-username"
    assert calls[0]["soulseek_password"] == "real-password"


def test_choose_library_folder_registers_location_and_advances(
        qtbot, tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
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
    # Name comes from the picked folder's own basename now — no name
    # field anywhere in this flow, wizard included (roadmap item 5).
    assert [loc.name for loc, _ in locations] == ["music"]
    assert locations[0][0].path == str(chosen_path)
    # Both destination checkboxes default checked (roadmap item 6 §5) —
    # a first-time user should now be unable to reach the "no
    # destination configured" dead end at all.
    assert application._config_store.default_download_location_id == (
        locations[0][0].id
    )
    assert (
        application._config_store.default_download_subfolder_per_playlist
        is True
    )


def test_library_folder_step_destination_checkboxes_default_checked(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    application = make_application(tmp_path, monkeypatch)
    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    assert wizard.download_into_library_checkbox.isChecked()
    assert wizard.subfolder_per_playlist_checkbox.isChecked()
    assert not wizard.subfolder_per_playlist_checkbox.isHidden()

    wizard.download_into_library_checkbox.setChecked(False)
    assert wizard.subfolder_per_playlist_checkbox.isHidden()


def test_unchecking_download_into_library_skips_the_default_destination(
        qtbot, tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
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

    wizard.download_into_library_checkbox.setChecked(False)
    wizard._on_choose_library_folder_clicked()

    qtbot.waitUntil(lambda: wizard.stack.currentIndex() == 2, timeout=2000)
    assert application._config_store.default_download_location_id is None


def test_unchecking_subfolder_per_playlist_persists_false(
        qtbot, tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
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

    wizard.subfolder_per_playlist_checkbox.setChecked(False)
    wizard._on_choose_library_folder_clicked()

    qtbot.waitUntil(lambda: wizard.stack.currentIndex() == 2, timeout=2000)
    assert application._config_store.default_download_location_id is not None
    assert (
        application._config_store.default_download_subfolder_per_playlist
        is False
    )


def test_bring_up_soulseek_requires_username_and_password(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.RUNNING,
    )
    calls = []
    monkeypatch.setattr(
        "seeker.application.bring_up_slskd",
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
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
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

    monkeypatch.setattr("seeker.application.bring_up_slskd", fake_bring_up)
    monkeypatch.setattr(
        "seeker.application.slskd_data_dir", lambda: tmp_path / "slskd-data",
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
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.RUNNING,
    )
    monkeypatch.setattr(
        "seeker.application.slskd_data_dir", lambda: tmp_path / "slskd-data",
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
    wizard._slskd_started = SlskdStartResult(
        api_key="real-api-key",
        download_dir=str(tmp_path / "slskd-data" / "downloads"),
    )

    wizard._handle_health_result(
        SlskdHealthCheckResult(SlskdHealthStatus.HEALTHY)
    )

    assert len(persist_calls) == 1
    assert persist_calls[0][1] == "real-api-key"
    assert persist_calls[0][2] == str(tmp_path / "slskd-data" / "downloads")
    assert persist_calls[0][3] == "realuser"
    assert persist_calls[0][4] == "realpass"
    assert wizard.slskd_chip.lamp == status_lamp.PLAY
    assert wizard.slskd_chip.text() == "SoulSeek is connected"
    # Same done-page indirection as the skip path — on_complete fires
    # only once the done page's own Continue button is clicked.
    assert wizard.stack.currentIndex() == 3
    assert completed == []

    wizard.continue_button.click()

    assert completed == [True]


def _build_wizard_at_soulseek_step(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
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

    return wizard, completed


# Roadmap item 8 — one test per real _handle_health_result mode,
# mirroring the existing HEALTHY/timeout coverage's own shape.

def test_health_result_bad_credentials_existing_account_mode(
        qtbot, tmp_path, monkeypatch,
):
    wizard, completed = _build_wizard_at_soulseek_step(
        qtbot, tmp_path, monkeypatch,
    )
    # Default radio state — "I already have a SoulSeek account".
    assert wizard.existing_account_radio.isChecked()
    wizard.soulseek_username_field.setText("realuser")

    wizard._handle_health_result(
        SlskdHealthCheckResult(
            SlskdHealthStatus.BAD_CREDENTIALS,
            detail="invalid username or password",
        )
    )

    text = wizard.soulseek_status_label.text()
    assert "rejected that username and password" in text
    assert "case-sensitive" in text
    # The username field is untouched in this mode — nothing about
    # "wrong password on my own account" implies the username itself
    # was the problem.
    assert wizard.soulseek_username_field.text() == "realuser"
    # The real, raw detail is never dropped — available on hover
    # regardless of which branch's copy is shown.
    assert wizard.soulseek_status_label.toolTip() == plain_tooltip(
        "invalid username or password"
    )
    assert wizard.slskd_chip.lamp == status_lamp.FAULT
    assert completed == []
    assert wizard.stack.currentIndex() == 2


def test_health_result_bad_credentials_new_account_mode(
        qtbot, tmp_path, monkeypatch,
):
    wizard, completed = _build_wizard_at_soulseek_step(
        qtbot, tmp_path, monkeypatch,
    )
    wizard.new_account_radio.setChecked(True)
    wizard.soulseek_username_field.setText("takenusername")
    wizard.soulseek_password_field.setText("mypassword")

    wizard._handle_health_result(
        SlskdHealthCheckResult(
            SlskdHealthStatus.BAD_CREDENTIALS,
            detail="invalid username or password",
        )
    )

    text = wizard.soulseek_status_label.text()
    assert "'takenusername'" in text
    assert "already taken" in text
    # Username cleared so the user can pick a different one; password
    # kept — only the username was the problem here. The code also
    # calls setFocus() on the field (confirmed by reading
    # _handle_bad_credentials directly) — not re-asserted via
    # hasFocus() here, since window-activation-dependent focus state
    # is not reliably observable under the offscreen QPA platform this
    # suite runs under.
    assert wizard.soulseek_username_field.text() == ""
    assert wizard.soulseek_password_field.text() == "mypassword"
    assert wizard.soulseek_status_label.toolTip() == plain_tooltip(
        "invalid username or password"
    )
    assert completed == []


def test_health_result_kicked_shows_distinct_message(
        qtbot, tmp_path, monkeypatch,
):
    wizard, completed = _build_wizard_at_soulseek_step(
        qtbot, tmp_path, monkeypatch,
    )

    real_detail = (
        "Disconnected from the Soulseek server: another client logged "
        "in using the same username"
    )
    wizard._handle_health_result(
        SlskdHealthCheckResult(SlskdHealthStatus.KICKED, detail=real_detail)
    )

    text = wizard.soulseek_status_label.text()
    assert "already logged in" in text
    assert text != real_detail  # plain-language, not the raw log line
    assert wizard.soulseek_status_label.toolTip() == plain_tooltip(real_detail)
    assert wizard.slskd_chip.lamp == status_lamp.FAULT
    assert completed == []


def test_bring_up_soulseek_blocked_when_docker_not_running(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.NOT_INSTALLED,
    )
    calls = []
    monkeypatch.setattr(
        "seeker.application.bring_up_slskd",
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


def test_bring_up_rejects_username_with_leading_or_trailing_whitespace(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.RUNNING,
    )
    calls = []
    monkeypatch.setattr(
        "seeker.application.bring_up_slskd",
        lambda **kwargs: calls.append(kwargs),
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)
    wizard._library_location_path = str(tmp_path)

    wizard.soulseek_username_field.setText(" realuser")
    wizard.soulseek_password_field.setText("realpass")
    wizard.bring_up_button.click()

    assert calls == []
    assert "leading or trailing spaces" in wizard.soulseek_status_label.text()


def test_soulseek_account_mode_radios_default_to_existing_account(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    application = make_application(tmp_path, monkeypatch)
    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    assert wizard.existing_account_radio.isChecked()
    assert not wizard.new_account_radio.isChecked()


def test_bring_up_soulseek_blocked_when_no_library_location(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.RUNNING,
    )
    calls = []
    monkeypatch.setattr(
        "seeker.application.bring_up_slskd",
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
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.RUNNING,
    )
    monkeypatch.setattr(
        "seeker.application.slskd_data_dir", lambda: tmp_path / "slskd-data",
    )

    def failing_bring_up(**kwargs):
        raise SlskdBringUpError(
            "docker compose up failed: real docker compose error text"
        )

    monkeypatch.setattr(
        "seeker.application.bring_up_slskd", failing_bring_up,
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
    assert wizard.slskd_chip.lamp == status_lamp.FAULT
    assert wizard.soulseek_progress.isHidden()


def test_health_poll_timeout_shows_message_after_elapsed_threshold(
        qtbot, tmp_path, monkeypatch,
):
    from seeker.soulseek.docker_setup import SlskdHealthStatus
    from seeker.ui.wizard import HEALTH_POLL_TIMEOUT_SECONDS

    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
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
    assert wizard.slskd_chip.lamp == status_lamp.FAULT


def test_render_docker_state_not_installed_offers_download_link(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    monkeypatch.setattr(
        "seeker.ui.wizard.detect_docker_state",
        lambda: DockerState.NOT_INSTALLED,
    )

    application = make_application(tmp_path, monkeypatch)
    application.library_service.add_location("Library", str(tmp_path))

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)

    qtbot.waitUntil(
        lambda: wizard.docker_chip.text() == "Docker isn't installed",
        timeout=2000,
    )
    assert wizard.docker_chip.lamp == status_lamp.FAULT
    assert wizard.docker_action_button.text() == "Download Docker Desktop"
    # isHidden() reflects the widget's own explicit hide/show state,
    # unlike isVisible() which also requires the whole ancestor chain
    # to be shown — this wizard is never .show()n in this test.
    assert not wizard.docker_action_button.isHidden()


def test_render_docker_state_installed_not_running_offers_launch(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
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
        lambda: wizard.docker_chip.text() == "Docker isn't running",
        timeout=2000,
    )
    # A ring: Docker waits on the user to launch it.
    assert wizard.docker_chip.lamp == status_lamp.CUE_WAITING
    assert wizard.docker_action_button.text() == "Launch Docker Desktop"


def test_launch_docker_clicked_success_updates_status_and_button(
        qtbot, tmp_path, monkeypatch,
):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
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
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "already-set")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
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


def _blocking_connect_spotify(started: threading.Event, calls: list[str]):
    """A connect_spotify stand-in that waits in the browser the way the
    real one does, until its cancel event is set."""
    def fake(client_id, force_reauthorize=False, cancel=None):
        calls.append(client_id)
        started.set()
        cancel.wait(timeout=5.0)
        raise AuthorizationCancelledError

    return fake


def test_waiting_for_spotify_offers_cancel_and_keeps_connect_disabled(
        qtbot, tmp_path, monkeypatch,
):
    # Typing in the Client ID field used to re-enable Connect while the
    # first attempt still held 127.0.0.1:8888; a second click then
    # failed with a raw "Address already in use".
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)
    application = make_application(tmp_path, monkeypatch)
    started = threading.Event()
    calls: list[str] = []
    monkeypatch.setattr(
        application,
        "connect_spotify",
        _blocking_connect_spotify(started, calls),
    )

    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)
    wait = wizard.spotify_authorization_wait
    assert wait.isHidden()

    wizard.client_id_field.setText("mistyped-client-id")
    wizard.connect_button.click()
    qtbot.waitUntil(started.is_set, timeout=2000)

    assert not wait.isHidden()
    assert wait.cancel_button.isEnabled()
    assert "Client ID" in wait.hint_label.text()
    assert wizard.spotify_status_label.text() == (
        "Waiting for approval in your browser…"
    )
    assert not wizard.connect_button.isEnabled()

    wizard.client_id_field.setText("corrected-client-id")
    assert not wizard.connect_button.isEnabled()
    wizard.client_id_field.returnPressed.emit()

    wait.cancel_button.click()

    qtbot.waitUntil(wizard.connect_button.isEnabled, timeout=2000)
    assert wait.isHidden()
    assert wizard.spotify_status_label.text() == "Authorization cancelled."
    assert wizard.stack.currentIndex() == 0
    assert calls == ["mistyped-client-id"]


def _built_wizard(qtbot, tmp_path, monkeypatch) -> OnboardingWizard:
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_REDIRECT_URI", raising=False)
    application = make_application(tmp_path, monkeypatch)
    wizard = OnboardingWizard(application, on_complete=lambda: None)
    qtbot.addWidget(wizard)
    return wizard


def test_wizard_content_is_one_centred_column(qtbot, tmp_path, monkeypatch):
    wizard = _built_wizard(qtbot, tmp_path, monkeypatch)
    wizard.resize(1280, 820)
    wizard.show()
    qtbot.waitExposed(wizard)

    column = wizard.column
    left = column.mapTo(wizard, column.rect().topLeft()).x()
    right_gap = wizard.width() - (left + column.width())

    assert column.width() <= 560
    # A vertical scroll bar, if one shows, takes its width off the
    # right-hand gap only.
    assert abs(left - right_gap) <= 20


def test_every_wizard_step_has_a_page_title(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel

    wizard = _built_wizard(qtbot, tmp_path, monkeypatch)

    titles = [
        [
            label.text()
            for label in wizard.stack.widget(index).findChildren(QLabel)
            if label.objectName() == "pageTitleLabel"
        ]
        for index in range(wizard.stack.count())
    ]

    assert titles == [
        ["Connect Spotify"],
        ["Choose your music library"],
        ["Set up SoulSeek"],
        ["You're all set"],
    ]


def test_step_indicator_follows_the_current_step(
        qtbot, tmp_path, monkeypatch,
):
    from seeker.ui import status_lamp

    wizard = _built_wizard(qtbot, tmp_path, monkeypatch)
    indicator = wizard.step_indicator

    assert indicator.lamps() == [
        status_lamp.CUE_WAITING, status_lamp.STANDBY, status_lamp.STANDBY,
    ]
    assert indicator.accessibleName() == "Step 1 of 3: Spotify"

    wizard.stack.setCurrentIndex(2)

    assert indicator.lamps() == [
        status_lamp.PLAY, status_lamp.PLAY, status_lamp.CUE_WAITING,
    ]
    assert indicator.accessibleName() == "Step 3 of 3: SoulSeek (optional)"


def test_skipping_soulseek_leaves_its_step_unlit(qtbot, tmp_path, monkeypatch):
    from seeker.ui import status_lamp

    wizard = _built_wizard(qtbot, tmp_path, monkeypatch)
    wizard.stack.setCurrentIndex(2)

    wizard._on_skip_soulseek_clicked()

    assert wizard.stack.currentIndex() == 3
    assert wizard.step_indicator.lamps() == [
        status_lamp.PLAY, status_lamp.PLAY, status_lamp.STANDBY,
    ]
    assert wizard.step_indicator.accessibleName() == (
        "Setup complete; SoulSeek (optional) skipped"
    )


def test_spotify_step_numbers_its_registration_steps(
        qtbot, tmp_path, monkeypatch,
):
    from PySide6.QtWidgets import QLabel

    wizard = _built_wizard(qtbot, tmp_path, monkeypatch)
    spotify_page = wizard.stack.widget(0)

    numbers = [
        label.text()
        for label in spotify_page.findChildren(QLabel)
        if label.objectName() == "stepNumber"
    ]

    assert numbers == ["1", "2", "3"]


def test_spotify_step_shows_the_redirect_uri_read_only(
        qtbot, tmp_path, monkeypatch,
):
    from seeker.spotify.callback_server import DEFAULT_REDIRECT_URI

    wizard = _built_wizard(qtbot, tmp_path, monkeypatch)

    assert wizard.redirect_uri_field.text() == DEFAULT_REDIRECT_URI
    assert wizard.redirect_uri_field.isReadOnly()


def test_soulseek_chip_stands_by_until_set_up_starts(
        qtbot, tmp_path, monkeypatch,
):
    wizard = _built_wizard(qtbot, tmp_path, monkeypatch)

    assert wizard.slskd_chip.lamp == status_lamp.STANDBY
    assert wizard.slskd_chip.text() == "SoulSeek isn't set up"


def test_soulseek_chip_shows_the_wait_for_a_connection(
        qtbot, tmp_path, monkeypatch,
):
    wizard = _built_wizard(qtbot, tmp_path, monkeypatch)

    wizard._start_health_poll(SlskdStartResult(
        api_key="real-api-key", download_dir=str(tmp_path),
    ))
    wizard._stop_health_poll()

    assert wizard.slskd_chip.lamp == status_lamp.CUE
    assert wizard.slskd_chip.text() == "Connecting to SoulSeek…"


def test_a_status_chip_follows_its_state(qtbot):
    chip = status_lamp.StatusChip(status_lamp.CUE, "Checking Docker…")
    qtbot.addWidget(chip)

    chip.set_state(status_lamp.PLAY, "Docker is running")

    assert chip.lamp == status_lamp.PLAY
    assert chip.text() == "Docker is running"
    assert chip.accessibleName() == "Docker is running"


def test_each_wizard_step_has_one_primary_action(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QPushButton

    wizard = _built_wizard(qtbot, tmp_path, monkeypatch)

    primaries = [
        [
            button.text()
            for button in wizard.stack.widget(index).findChildren(QPushButton)
            if button.property("variant") == "primary"
            and not button.isHidden()
        ]
        for index in range(wizard.stack.count())
    ]

    assert primaries == [
        ["Connect"],
        ["Choose Folder..."],
        ["Set up SoulSeek"],
        ["Go to Dashboard"],
    ]
