import asyncio
from pathlib import Path

import pytest
from starlette.requests import Request

import signalforge.main as main
from signalforge.config import Settings
from signalforge.main import library, project_report
from signalforge.services.auth import SESSION_COOKIE, create_session_token, hash_password
from signalforge.services.db import FakeDatabase


def make_settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, **overrides)


def db_settings(tmp_path: Path) -> Settings:
    return make_settings(
        tmp_path, postgres_url="postgresql://test", session_secret="test-secret"
    )


def req(cookie: str | None = None) -> Request:
    headers = [(b"cookie", f"{SESSION_COOKIE}={cookie}".encode())] if cookie else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def authed(db: FakeDatabase, secret: str, email: str) -> Request:
    user = db.create_user(email, hash_password("password123"))
    return req(create_session_token(user["id"], secret))


def test_report_from_live_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        await main.memory_jobstore.write(
            "live01",
            {"status": "complete", "result": {"plan": {"headline": "Hi"}}, "user_id": "local"},
        )
        payload = await project_report("live01", req())
        assert payload["result"]["plan"]["headline"] == "Hi"

        await main.memory_jobstore.write(
            "busy01", {"status": "analyzing", "message": "Reading", "user_id": "local"}
        )
        with pytest.raises(Exception) as busy:
            await project_report("busy01", req())
        assert busy.value.status_code == 409

        with pytest.raises(Exception) as missing:
            await project_report("nope01", req())
        assert missing.value.status_code == 404

    monkeypatch.setattr(main, "settings", make_settings(tmp_path))
    asyncio.run(run())


def test_report_from_database_with_ownership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        settings = db_settings(tmp_path)
        monkeypatch.setattr(main, "settings", settings)
        db = FakeDatabase()
        monkeypatch.setattr(main, "db", db)
        ada = authed(db, settings.session_secret or "", "ada@example.com")
        bob = authed(db, settings.session_secret or "", "bob@example.com")
        ada_id = db.get_user_by_email("ada@example.com")["id"]
        db.create_project("db01", ada_id, "Goal", "", True)
        db.update_project("db01", status="complete", result={"plan": {"headline": "Saved"}})

        payload = await project_report("db01", ada)
        assert payload["result"]["plan"]["headline"] == "Saved"
        with pytest.raises(Exception) as forbidden:
            await project_report("db01", bob)
        assert forbidden.value.status_code == 404

    asyncio.run(run())


def test_library_route_lists_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        settings = db_settings(tmp_path)
        monkeypatch.setattr(main, "settings", settings)
        db = FakeDatabase()
        monkeypatch.setattr(main, "db", db)
        request = authed(db, settings.session_secret or "", "ada@example.com")
        user_id = db.get_user_by_email("ada@example.com")["id"]
        db.create_project("db01", user_id, "Goal", "", True)
        response = await library(request)
        assert response.status_code == 200

    asyncio.run(run())


def sample_cards() -> list[dict]:
    return [
        {
            "id": "p1",
            "goal": "Ship <b>bold</b>",
            "status": "complete",
            "progress": 100,
            "updated": "2026-01-01",
            "image_count": 1,
            "cover": "https://cdn.test/cover.jpg",
            "photos": [{"thumb": "https://cdn.test/t.jpg", "full": "https://cdn.test/f.jpg", "title": "Slide"}],
            "notes": "speaker said <hi>",
            "takeaways": ["take <one>"],
            "ready": True,
        }
    ]


def test_library_template_renders_and_escapes() -> None:
    template = main.templates.env.get_template("library.html")
    body = template.render(projects=sample_cards(), user_email="ada@example.com")
    assert "Ship &lt;b&gt;bold" in body
    assert "speaker said &lt;hi&gt;" in body
    assert "take &lt;one&gt;" in body
    assert "/?project=p1" in body
    assert 'data-tab="photos-p1"' in body
    assert 'data-tab="notes-p1"' in body
    empty = template.render(projects=[], user_email="ada@example.com")
    assert "No projects yet" in empty


def test_auth_templates_render() -> None:
    login_body = main.templates.env.get_template("login.html").render(error=None)
    assert 'action="/login"' in login_body
    error_body = main.templates.env.get_template("login.html").render(error="Bad <creds>")
    assert "Bad &lt;creds&gt;" in error_body
    signup_body = main.templates.env.get_template("signup.html").render(error=None)
    assert 'action="/signup"' in signup_body
