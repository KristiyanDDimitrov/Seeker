from PySide6.QtWidgets import QFileDialog, QLabel, QWidget

from seeker.models.library_location import LibraryLocation
from seeker.ui.library_location_picker import pick_and_add_library_location


class FakeLibraryService:
    def __init__(self) -> None:
        self.add_location_calls: list[tuple[str, str]] = []

    def add_location(self, name: str, path: str) -> LibraryLocation:
        self.add_location_calls.append((name, path))
        return LibraryLocation(
            id=1, name=name, path=path, added_at="2026-01-01T00:00:00+00:00",
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

    pick_and_add_library_location(
        parent, SynchronousPool(), application, "Main",
    )

    assert application.library_service.add_location_calls == []


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
        "Main",
        on_path_picked=picked_paths.append,
        on_finished=finished_locations.append,
    )

    assert application.library_service.add_location_calls == [
        ("Main", "/music/main"),
    ]
    # on_path_picked fires with the raw picked path, synchronously,
    # before add_location() even runs — the wizard relies on this for
    # immediate label feedback while registration is still in flight.
    assert picked_paths == ["/music/main"]
    assert len(finished_locations) == 1
    assert finished_locations[0].name == "Main"
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
        "Main",
        button=button,
        status_label=label,
    )

    assert button_state_during_run == [False]
    assert button.isEnabled() is True
