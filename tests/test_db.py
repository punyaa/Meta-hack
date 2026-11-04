import pytest

from signalforge.services.db import (
    DatabaseNotConfiguredError,
    EmailTakenError,
    FakeDatabase,
    NullDatabase,
    PostgresDatabase,
    SCHEMA_STATEMENTS,
    get_database,
)


class FakeSettings:
    def __init__(self, postgres_url=None) -> None:
        self.postgres_url = postgres_url
        self.db_configured = bool(postgres_url)


def test_fake_user_cycle() -> None:
    db = FakeDatabase()
    user = db.create_user("Ada@Example.com", "hash-1")
    assert user["email"] == "ada@example.com"
    assert db.get_user_by_email("ADA@example.COM")["id"] == user["id"]
    assert db.get_user_by_id(user["id"])["email"] == "ada@example.com"
    assert db.get_user_by_email("missing@example.com") is None
    with pytest.raises(EmailTakenError):
        db.create_user("ada@example.com", "hash-2")


def test_fake_projects_isolated_per_user() -> None:
    db = FakeDatabase()
    ada = db.create_user("ada@example.com", "h")["id"]
    bob = db.create_user("bob@example.com", "h")["id"]
    db.create_project("p1", ada, "Goal one", "", True)
    db.create_project("p2", ada, "Goal two", "notes", False)
    db.create_project("p3", bob, "Goal three", "", True)

    db.update_project("p1", status="complete", progress=100)
    row = db.get_project("p1")
    assert row["status"] == "complete"
    assert row["progress"] == 100

    ada_projects = db.list_projects(ada)
    assert [row["id"] for row in ada_projects] == ["p1", "p2"]
    assert [row["id"] for row in db.list_projects(bob)] == ["p3"]
    assert db.list_projects("nobody") == []

    with pytest.raises(ValueError, match="Cannot update"):
        db.update_project("p1", user_id="mallory")


def test_null_database_misses_reads_and_blocks_writes() -> None:
    db = NullDatabase()
    assert db.get_user_by_email("a@b.c") is None
    assert db.get_project("p1") is None
    assert db.list_projects("u1") == []
    with pytest.raises(DatabaseNotConfiguredError):
        db.create_user("a@b.c", "h")
    with pytest.raises(DatabaseNotConfiguredError):
        db.create_project("p1", "u1", "g", "", True)


def test_get_database_selection() -> None:
    assert isinstance(get_database(FakeSettings()), NullDatabase)
    assert isinstance(
        get_database(FakeSettings("postgresql://x")), PostgresDatabase
    )
    with pytest.raises(DatabaseNotConfiguredError):
        PostgresDatabase(None)


def test_schema_covers_users_and_projects() -> None:
    joined = "\n".join(SCHEMA_STATEMENTS)
    assert "CREATE TABLE IF NOT EXISTS users" in joined
    assert "CREATE TABLE IF NOT EXISTS projects" in joined
    assert "email TEXT UNIQUE NOT NULL" in joined
    assert "result JSONB" in joined
    assert "projects_user_idx" in joined
