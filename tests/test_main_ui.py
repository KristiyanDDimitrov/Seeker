from importlib.metadata import version

from seeker import main_ui


def test_application_identity_is_seekers_own(qapp):
    previous = (
        qapp.applicationName(),
        qapp.applicationDisplayName(),
        qapp.applicationVersion(),
    )

    try:
        main_ui._configure_application_identity(qapp)

        assert qapp.applicationName() == "Seeker"
        assert qapp.applicationDisplayName() == "Seeker"
        assert qapp.applicationVersion() == version("seeker")
    finally:
        qapp.setApplicationName(previous[0])
        qapp.setApplicationDisplayName(previous[1])
        qapp.setApplicationVersion(previous[2])
