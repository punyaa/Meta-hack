import asyncio
from pathlib import Path

import pytest
from starlette.requests import Request

import signalforge.main as main
from signalforge.config import Settings
from signalforge.main import auth_gate, login, logout, signup
from signalforge.services.auth import SESSION_COOKIE, create_session_token, hash_password
from signalforge.services.db import FakeDatabase


def make_settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, **overrides)


def db_settings(tmp_path: Path) -> Settings:
    return make_settings(
        tmp_path, postgres_url="postgresql://test", session_secret="test-secret"
    )


def use_stack(monkeypatch: pytest.MonkeyPatch, settings: Settings, db) -> None:
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "db", db)


def http_request(path: str, cookie: str | None = None, method: str = "GET") -> Request:
    headers = [(b"cookie", f"{SESSION_COOKIE}={cookie}".encode())] if cookie else []
    return Request({"type": "http", "method": method, "path": path, "headers": headers})


async def passthrough(request: Request):
    return "PASSED"


def test_gate_open_without_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        use_stack(monkeypatch, make_settings(tmp_path), FakeDatabase())
        assert await auth_gate(http_request("/"), passthrough) == "PASSED"
        assert await auth_gate(http_request("/api/v2/projects"), passthrough) == "PASSED"

    asyncio.run(run())


def test_gate_redirects_pages_and_blocks_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        use_stack(monkeypatch, db_settings(tmp_path), FakeDatabase())
        redirect = await auth_gate(http_request("/"), passthrough)
        assert redirect.status_code == 303
        assert redirect.headers["location"] == "/login"
        denied = await auth_gate(http_request("/api/v2/projects"), passthrough)
        assert denied.status_code == 401
        assert await auth_gate(http_request("/login"), passthrough) == "PASSED"
        assert await auth_gate(http_request("/signup"), passthrough) == "PASSED"
        assert await auth_gate(http_request("/api/health"), passthrough) == "PASSED"
        assert await auth_gate(http_request("/static/app.js"), passthrough) == "PASSED"

    asyncio.run(run())


def test_gate_passes_logged_in_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        settings = db_settings(tmp_path)
        db = FakeDatabase()
        use_stack(monkeypatch, settings, db)
        user = db.create_user("ada@example.com", hash_password("password123"))
        token = create_session_token(user["id"], settings.session_secret or "")
        assert await auth_gate(http_request("/", token), passthrough) == "PASSED"

    asyncio.run(run())


def test_signup_and_login_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        db = FakeDatabase()
        use_stack(monkeypatch, db_settings(tmp_path), db)
        created = await signup(
            http_request("/signup", method="POST"), "ada@example.com", "password123"
        )
        assert created.status_code == 303
        assert SESSION_COOKIE in created.headers["set-cookie"]
        assert db.get_user_by_email("ada@example.com") is not None

        duplicate = await signup(
            http_request("/signup", method="POST"), "ada@example.com", "password123"
        )
        assert duplicate.status_code == 400

        bad_email = await signup(http_request("/signup", method="POST"), "nope", "password123")
        assert bad_email.status_code == 400

        short = await signup(
            http_request("/signup", method="POST"), "bob@example.com", "short"
        )
        assert short.status_code == 400

        logged_in = await login(
            http_request("/login", method="POST"), "ada@example.com", "password123"
        )
        assert logged_in.status_code == 303
        assert SESSION_COOKIE in logged_in.headers["set-cookie"]

        wrong = await login(
            http_request("/login", method="POST"), "ada@example.com", "wrong-password"
        )
        assert wrong.status_code == 401

    asyncio.run(run())


def test_auth_pages_redirect_without_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        use_stack(monkeypatch, make_settings(tmp_path), FakeDatabase())
        assert (await login(http_request("/login", method="POST"), "a@b.c", "x")).status_code == 303
        assert (await signup(http_request("/signup", method="POST"), "a@b.c", "x")).status_code == 303

    asyncio.run(run())


def test_logout_clears_cookie() -> None:
    response = asyncio.run(logout())
    assert response.status_code == 303
    assert SESSION_COOKIE in response.headers["set-cookie"]
