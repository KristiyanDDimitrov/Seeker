from collections.abc import Callable

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QAbstractButton, QFileDialog, QLabel, QWidget

from seeker.application import Application
from seeker.models.library_location import LibraryLocation
from seeker.ui.workers import run_worker


def pick_and_add_library_location(
        parent: QWidget,
        thread_pool: QThreadPool,
        application: Application,
        name: str,
        dialog_title: str = "Choose Music Folder",
        button: QAbstractButton | None = None,
        status_label: QLabel | None = None,
        on_path_picked: Callable[[str], None] | None = None,
        on_finished: Callable[[LibraryLocation], None] | None = None,
) -> None:
    """Open a native folder picker and, if the user picked something,
    register it as a library location — the onboarding wizard's own
    "Choose your music library" step, extracted so Settings' "Add
    location" action can call the identical flow instead of a second
    copy. The wizard hardcodes name="Library" (a single-location
    onboarding assumption); Settings passes a real user-chosen name,
    since it supports multiple named locations.

    on_path_picked (optional) fires synchronously the moment a real
    path is chosen, before add_location() runs on the worker thread —
    the wizard uses this for immediate label feedback while the
    (usually near-instant, but still worker-routed) registration is
    still in flight.
    """
    path = QFileDialog.getExistingDirectory(parent, dialog_title)

    if not path:
        return

    if on_path_picked is not None:
        on_path_picked(path)

    def do_add_location() -> LibraryLocation:
        return application.library_service.add_location(name, path)

    run_worker(
        thread_pool,
        do_add_location,
        button=button,
        status_label=status_label,
        on_finished=on_finished,
    )
