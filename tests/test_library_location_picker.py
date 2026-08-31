from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QLabel, QWidget

from seeker.models.library_location import LibraryLocation
from seeker.ui.library_location_picker import pick_and_add_library_location


class FakeLibraryService:
    def __init__(self) -> None:
        self.add_location_from_path_calls: list[str] = []

    def add_location_from_path(self, path: str) -> LibraryLocation:
        self.add_location_from_path_calls.append(path)
        return LibraryLocation(
            id=1, name=Path(path).name, path=path,
            added_at="2026-01-01T00:00:00+00:00",
        )


class FakeApplication:
    def __init__(self) -> None:
        self.library_service = FakeLibraryService()


class SynchronousPool:
    def start(self, worker):
        worker.run()


def test_pick_and_add_library_location_no_op_when_dialog_cancelled(
        qtbot, monkeypatch,
):
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: "",
    )

    application = FakeApplication()
    parent = QWidget()
    qtbot.addWidget(parent)

    pick_and_add_library_location(parent, SynchronousPool(), application)

    assert application.library_service.add_location_from_path_calls == []


def test_pick_and_add_library_location_adds_chosen_path(qtbot, monkeypatch):
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: "/music/main",
    )

    application = FakeApplication()
    parent = QWidget()
    qtbot.addWidget(parent)

    picked_paths = []
    finished_locations = []

    pick_and_add_library_location(
        parent,
        SynchronousPool(),
        application,
        on_path_picked=picked_paths.append,
        on_finished=finished_locations.append,
    )

    assert application.library_service.add_location_from_path_calls == [
        "/music/main",
    ]
    # on_path_picked fires with the raw picked path, synchronously,
    # before add_location_from_path() even runs — the wizard relies on
    # this for immediate label feedback while registration is still in
    # flight.
    assert picked_paths == ["/music/main"]
    assert len(finished_locations) == 1
    # Name is derived from the folder's own basename — no name field
    # anywhere in this flow (roadmap item 5).
    assert finished_locations[0].name == "main"
    assert finished_locations[0].path == "/music/main"


def test_pick_and_add_library_location_status_label_and_button_wired(
        qtbot, monkeypatch,
):
    # Confirms the picker actually routes through run_worker's
    # standard button/status_label handling rather than bypassing it -
    # not re-testing run_worker's own behavior, just that it's used.
    from PySide6.QtWidgets import QPushButton

    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: "/music/main",
    )

    application = FakeApplication()
    parent = QWidget()
    button = QPushButton("Add")
    label = QLabel("")
    qtbot.addWidget(parent)
    qtbot.addWidget(button)
    qtbot.addWidget(label)

    button_state_during_run = []

    class RecordingPool:
        def start(self, worker):
            button_state_during_run.append(button.isEnabled())
            worker.run()

    pick_and_add_library_location(
        parent,
        RecordingPool(),
        application,
        button=button,
        status_label=label,
    )

    assert button_state_during_run == [False]
    assert button.isEnabled() is True


def test_pick_and_add_library_location_on_error_fires_for_a_real_failure(
        qtbot, monkeypatch,
):
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: "/music/main",
    )

    class FailingLibraryService:
        def add_location_from_path(self, path: str) -> LibraryLocation:
            raise RuntimeError("'/music/main' is already registered as 'main'.")

    class FailingApplication:
        def __init__(self) -> None:
            self.library_service = FailingLibraryService()

    application = FailingApplication()
    parent = QWidget()
    qtbot.addWidget(parent)
    errors = []

    pick_and_add_library_location(
        parent,
        SynchronousPool(),
        application,
        on_error=errors.append,
    )

    assert errors == ["'/music/main' is already registered as 'main'."]
