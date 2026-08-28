from seeker.application import (
    Application,
    _migrate_legacy_database,
    _resolve_database_path,
)
from seeker.database.connection import Database


def _fake_user_data_dir(data_dir):
    # platformdirs.user_data_dir's real signature varies by OS
    # (appauthor is ignored on macOS/Linux, used on Windows) — accepting
    # **kwargs keeps this fake correct regardless of which platform the
    # test suite runs on.
    def fake(appname, **kwargs):
        return str(data_dir)

    return fake


def test_resolve_database_path_creates_directory_and_uses_platformdirs(
        tmp_path, monkeypatch,
):
    fake_data_dir = tmp_path / "AppData" / "Seeker"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(fake_data_dir),
    )

    assert not fake_data_dir.exists()

    db_path = _resolve_database_path()

    assert db_path == fake_data_dir / "seeker.db"
    assert fake_data_dir.is_dir()


def test_migrate_legacy_database_moves_existing_file_and_preserves_data(
        tmp_path, capsys,
):
    legacy_path = tmp_path / "old" / ".seeker" / "seeker.db"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(b"real sqlite bytes, not a fresh empty db")

    new_path = tmp_path / "new" / "seeker.db"
    new_path.parent.mkdir(parents=True)

    migrated = _migrate_legacy_database(new_path, legacy_path=legacy_path)

    assert migrated is True
    assert not legacy_path.exists()
    assert (
        new_path.read_bytes() == b"real sqlite bytes, not a fresh empty db"
    )

    output = capsys.readouterr().out
    assert "Migrated existing database" in output
    assert str(legacy_path) in output
    assert str(new_path) in output


def test_migrate_legacy_database_does_nothing_when_neither_exists(
        tmp_path,
):
    legacy_path = tmp_path / "old" / ".seeker" / "seeker.db"
    new_path = tmp_path / "new" / "seeker.db"

    migrated = _migrate_legacy_database(new_path, legacy_path=legacy_path)

    assert migrated is False
    assert not legacy_path.exists()
    assert not new_path.exists()


def test_migrate_legacy_database_does_not_overwrite_existing_new_db(
        tmp_path,
):
    # A DB already exists at the new location (e.g. the migration
    # already ran once before, on a prior startup) — a stale leftover
    # legacy file must never clobber it.
    legacy_path = tmp_path / "old" / ".seeker" / "seeker.db"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(b"stale legacy bytes")

    new_path = tmp_path / "new" / "seeker.db"
    new_path.parent.mkdir(parents=True)
    new_path.write_bytes(b"current real data")

    migrated = _migrate_legacy_database(new_path, legacy_path=legacy_path)

    assert migrated is False
    assert legacy_path.exists()
    assert new_path.read_bytes() == b"current real data"


def test_application_fresh_install_creates_database_at_new_location(
        tmp_path, monkeypatch,
):
    # Neither the new platformdirs location nor the old CWD-relative
    # .seeker/ path exist yet — a genuinely fresh install.
    monkeypatch.chdir(tmp_path)

    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )

    app = Application("client-id", "http://localhost/callback")

    expected_path = data_dir / "seeker.db"
    assert app.database.path == expected_path
    assert expected_path.exists()
    assert not (tmp_path / ".seeker").exists()


def test_application_migrates_real_legacy_database_on_startup(
        tmp_path, monkeypatch, capsys,
):
    # A real, non-empty database already exists at the old CWD-relative
    # .seeker/seeker.db location (e.g. a pre-migration install) — this
    # must be moved into the new location automatically, with real data
    # intact, not silently left behind while a fresh empty DB is
    # created at the new path.
    monkeypatch.chdir(tmp_path)

    legacy_db_path = tmp_path / ".seeker" / "seeker.db"
    legacy_db_path.parent.mkdir(parents=True)

    real_db = Database(legacy_db_path)
    real_db.initialize()

    with real_db.transaction() as connection:
        connection.execute(
            "INSERT INTO playlists (id, name, track_count) "
            "VALUES (?, ?, ?)",
            ("p1", "Real Playlist", 3),
        )

    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )

    app = Application("client-id", "http://localhost/callback")

    new_db_path = data_dir / "seeker.db"
    assert app.database.path == new_db_path
    assert new_db_path.exists()
    assert not legacy_db_path.exists()

    with app.database.transaction() as connection:
        row = connection.execute(
            "SELECT name, track_count FROM playlists WHERE id = 'p1'"
        ).fetchone()

    assert row["name"] == "Real Playlist"
    assert row["track_count"] == 3

    output = capsys.readouterr().out
    assert "Migrated existing database" in output


def test_application_does_not_migrate_when_new_database_already_exists(
        tmp_path, monkeypatch,
):
    # Both a legacy file and a real database at the new location exist
    # (e.g. this is the second startup after an earlier successful
    # migration) — the legacy leftover must not overwrite real, current
    # data.
    monkeypatch.chdir(tmp_path)

    legacy_db_path = tmp_path / ".seeker" / "seeker.db"
    legacy_db_path.parent.mkdir(parents=True)
    legacy_db_path.write_bytes(b"stale pre-migration bytes")

    data_dir = tmp_path / "platformdirs-data"
    data_dir.mkdir(parents=True)

    new_db_path = data_dir / "seeker.db"
    real_db = Database(new_db_path)
    real_db.initialize()

    with real_db.transaction() as connection:
        connection.execute(
            "INSERT INTO playlists (id, name, track_count) "
            "VALUES (?, ?, ?)",
            ("p1", "Current Real Playlist", 5),
        )

    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )

    app = Application("client-id", "http://localhost/callback")

    assert legacy_db_path.exists()

    with app.database.transaction() as connection:
        row = connection.execute(
            "SELECT name FROM playlists WHERE id = 'p1'"
        ).fetchone()

    assert row["name"] == "Current Real Playlist"
