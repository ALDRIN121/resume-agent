import sqlite3

import pytest

from resume_agent.migrations import UnsupportedSchema, migrate


def test_backup_preserves_legacy_rows_and_checkpoint_schema(tmp_path):
    path = tmp_path / "library.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE companies(id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO companies VALUES(1,'Existing')")
    migrate(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("SELECT name FROM companies").fetchone() == ("Existing",)
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='checkpoints'").fetchone()
    backup = path.with_suffix(".sqlite.pre-v1.bak")
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT name FROM companies").fetchone() == ("Existing",)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    migrate(path)
    assert backup.exists()


def test_failed_migration_rolls_back_all_ddl_and_version(tmp_path):
    path = tmp_path / "library.sqlite"
    def fail(conn):
        conn.execute("CREATE TABLE should_rollback(id INTEGER)")
        raise RuntimeError("failure")
    with pytest.raises(RuntimeError):
        migrate(path, migrations=(fail,))
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert not conn.execute("SELECT name FROM sqlite_master").fetchall()


def test_future_version_rejected_unchanged(tmp_path):
    path = tmp_path / "library.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=99")
    before = path.read_bytes()
    with pytest.raises(UnsupportedSchema):
        migrate(path)
    assert path.read_bytes() == before
    assert not path.with_suffix(".sqlite.pre-v1.bak").exists()


def test_failed_later_migration_preserves_previous_version(tmp_path):
    path = tmp_path / "library.sqlite"
    def first(conn):
        conn.execute("CREATE TABLE original(id INTEGER)")
        conn.execute("INSERT INTO original VALUES(1)")
    def second(conn):
        conn.execute("ALTER TABLE original ADD COLUMN invalid TEXT")
        conn.execute("DELETE FROM original")
        raise RuntimeError("rollback")
    with pytest.raises(RuntimeError):
        migrate(path, migrations=(first, second))
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("SELECT * FROM original").fetchall() == [(1,)]
