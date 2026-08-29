from seeker.file_deletion import delete_file


def test_delete_file_removes_a_real_file_and_returns_none(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("data")

    assert delete_file(path) is None
    assert not path.exists()


def test_delete_file_returns_a_message_for_a_missing_file(tmp_path):
    path = tmp_path / "does_not_exist.txt"

    error = delete_file(path)

    assert error is not None
    assert "does_not_exist.txt" in error
