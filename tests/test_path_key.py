import sys

import pytest

from seeker.files.path_key import path_key


@pytest.mark.parametrize(
    "spelling",
    [
        "C:\\Users\\Alex\\Music",
        "c:/users/alex/music",
        "C:/Users/Alex/Music/",
        "C:\\Users\\\\Alex\\Music\\",
    ],
)
def test_on_windows_every_spelling_of_a_folder_has_one_key(
        monkeypatch, spelling,
):
    monkeypatch.setattr(sys, "platform", "win32")

    assert path_key(spelling) == "c:\\users\\alex\\music"


def test_on_windows_a_drive_root_keeps_its_separator(monkeypatch):
    # "C:" alone names the current folder on drive C, not its root.
    monkeypatch.setattr(sys, "platform", "win32")

    assert path_key("C:/") == path_key("c:\\") == "c:\\"
    assert path_key("C:") != path_key("C:/")


def test_on_windows_different_folders_keep_different_keys(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    assert path_key("C:/Music") != path_key("C:/Music Other")
    assert path_key("C:/Music") != path_key("D:/Music")


def test_on_macos_a_path_is_its_own_key(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")

    assert path_key("/Volumes/Drive/Music/") == "/Volumes/Drive/Music/"
    assert path_key("/Volumes/Drive/Music") != path_key("/volumes/drive/music")
