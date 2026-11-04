from __future__ import annotations

import time
import uuid
from typing import Any, Protocol

from signalforge.config import Settings


class EmailTakenError(ValueError):
    pass


class DatabaseNotConfiguredError(RuntimeError):
    pass


class Database(Protocol):
    def create_user(self, email: str, password_hash: str) -> dict[str, Any]:
        ...

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        ...

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        ...

    def create_project(
        self,
        project_id: str,
        user_id: str,
        goal: str,
        context_notes: str,
        demo_mode: bool,
    ) -> None:
        ...

    def update_project(self, project_id: str, **fields: Any) -> None:
        ...

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        ...

    def list_projects(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        ...


SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        goal TEXT NOT NULL,
        context_notes TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'collecting',
        message TEXT NOT NULL DEFAULT '',
        progress INTEGER NOT NULL DEFAULT 0,
        demo_mode BOOLEAN NOT NULL DEFAULT TRUE,
        result JSONB NULL,
        error TEXT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS projects_user_idx ON projects(user_id, updated_at DESC)",
)

PROJECT_COLUMNS = (
    "id",
    "user_id",
    "goal",
    "context_notes",
    "status",
    "message",
    "progress",
    "demo_mode",
    "result",
    "error",
    "created_at",
    "updated_at",
)

UPDATABLE_PROJECT_FIELDS = {
    "goal",
    "context_notes",
    "status",
    "message",
    "progress",
    "demo_mode",
    "result",
    "error",
}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class PostgresDatabase:
    """Vercel Postgres (Neon) via short-lived connections (serverless-safe)."""

    def __init__(self, dsn: str | None) -> None:
        if not dsn:
            raise DatabaseNotConfiguredError("Set POSTGRES_URL to use the database.")
        self.dsn = dsn
        self._ready = False

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(self.dsn, row_factory=dict_row)
        if not self._ready:
            with conn.cursor() as cursor:
                for statement in SCHEMA_STATEMENTS:
                    cursor.execute(statement)
            conn.commit()
            self._ready = True
        return conn

    def create_user(self, email: str, password_hash: str) -> dict[str, Any]:
        import psycopg.errors

        user_id = uuid.uuid4().hex
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO users (id, email, password_hash) "
                        "VALUES (%s, %s, %s) RETURNING id, email, created_at",
                        (user_id, email, password_hash),
                    )
                    row = cursor.fetchone()
                conn.commit()
        except psycopg.errors.UniqueViolation as error:
            raise EmailTakenError(email) from error
        return _serialize_user(row)

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, email, password_hash, created_at FROM users WHERE email = %s",
                    (email,),
                )
                row = cursor.fetchone()
        return _serialize_user(row) if row else None

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, email, password_hash, created_at FROM users WHERE id = %s",
                    (user_id,),
                )
                row = cursor.fetchone()
        return _serialize_user(row) if row else None

    def create_project(
        self,
        project_id: str,
        user_id: str,
        goal: str,
        context_notes: str,
        demo_mode: bool,
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO projects (id, user_id, goal, context_notes, demo_mode) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (project_id, user_id, goal, context_notes, demo_mode),
                )
            conn.commit()

    def update_project(self, project_id: str, **fields: Any) -> None:
        assignments = []
        values: list[Any] = []
        for key, value in fields.items():
            if key not in UPDATABLE_PROJECT_FIELDS:
                raise ValueError(f"Cannot update project field: {key}")
            assignments.append(f"{key} = %s")
            values.append(value)
        if not assignments:
            return
        assignments.append("updated_at = now()")
        values.append(project_id)
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"UPDATE projects SET {', '.join(assignments)} WHERE id = %s",
                    values,
                )
            conn.commit()

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT {', '.join(PROJECT_COLUMNS)} FROM projects WHERE id = %s",
                    (project_id,),
                )
                row = cursor.fetchone()
        return _serialize_project(row) if row else None

    def list_projects(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT {', '.join(PROJECT_COLUMNS)} FROM projects "
                    "WHERE user_id = %s ORDER BY updated_at DESC LIMIT %s",
                    (user_id, limit),
                )
                rows = cursor.fetchall()
        return [_serialize_project(row) for row in rows]


def _serialize_user(row: dict[str, Any]) -> dict[str, Any]:
    created = row.get("created_at")
    return {
        "id": row["id"],
        "email": row["email"],
        "password_hash": row.get("password_hash", ""),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
    }


def _serialize_project(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for key in ("created_at", "updated_at"):
        value = out.get(key)
        out[key] = value.isoformat() if hasattr(value, "isoformat") else value
    return out


class FakeDatabase:
    """In-memory database for tests and local previews without Postgres."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.emails: dict[str, str] = {}
        self.projects: dict[str, dict[str, Any]] = {}
        self._tick = 0

    def _stamp(self) -> str:
        self._tick += 1
        return f"{_now_iso()}#{self._tick:06d}"

    def create_user(self, email: str, password_hash: str) -> dict[str, Any]:
        normalized = email.strip().lower()
        if normalized in self.emails:
            raise EmailTakenError(email)
        user = {
            "id": uuid.uuid4().hex,
            "email": normalized,
            "password_hash": password_hash,
            "created_at": self._stamp(),
        }
        self.users[user["id"]] = user
        self.emails[normalized] = user["id"]
        return dict(user)

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        user_id = self.emails.get(email.strip().lower())
        return dict(self.users[user_id]) if user_id else None

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        return dict(self.users[user_id]) if user_id in self.users else None

    def create_project(
        self,
        project_id: str,
        user_id: str,
        goal: str,
        context_notes: str,
        demo_mode: bool,
    ) -> None:
        stamp = self._stamp()
        self.projects[project_id] = {
            "id": project_id,
            "user_id": user_id,
            "goal": goal,
            "context_notes": context_notes,
            "status": "collecting",
            "message": "",
            "progress": 0,
            "demo_mode": demo_mode,
            "result": None,
            "error": None,
            "created_at": stamp,
            "updated_at": stamp,
        }

    def update_project(self, project_id: str, **fields: Any) -> None:
        row = self.projects.get(project_id)
        if row is None:
            return
        for key, value in fields.items():
            if key not in UPDATABLE_PROJECT_FIELDS:
                raise ValueError(f"Cannot update project field: {key}")
            row[key] = value
        row["updated_at"] = self._stamp()

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        row = self.projects.get(project_id)
        return dict(row) if row else None

    def list_projects(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        owned = [row for row in self.projects.values() if row["user_id"] == user_id]
        owned.sort(key=lambda row: row["updated_at"], reverse=True)
        return [dict(row) for row in owned[:limit]]


class NullDatabase:
    """No-op database when POSTGRES_URL is unset; reads miss, writes fail loud."""

    def create_user(self, email: str, password_hash: str) -> dict[str, Any]:
        raise DatabaseNotConfiguredError("Set POSTGRES_URL to use accounts.")

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return None

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        return None

    def create_project(self, *args: Any, **kwargs: Any) -> None:
        raise DatabaseNotConfiguredError("Set POSTGRES_URL to record projects.")

    def update_project(self, project_id: str, **fields: Any) -> None:
        raise DatabaseNotConfiguredError("Set POSTGRES_URL to record projects.")

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return None

    def list_projects(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return []


def get_database(settings: Settings) -> Database:
    if settings.db_configured:
        return PostgresDatabase(settings.postgres_url)
    return NullDatabase()
