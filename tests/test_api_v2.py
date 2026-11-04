import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile
from PIL import Image, ImageDraw
from starlette.datastructures import Headers
from starlette.requests import Request

import signalforge.main as main
from signalforge.config import Settings
from signalforge.main import (
    ProjectCreate,
    add_v2_image,
    advance_v2_project,
    create_v2_project,
    finalize_v2_project,
)
from signalforge.services.auth import create_session_token, hash_password
from signalforge.services.db import FakeDatabase


def make_settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, **overrides)


def use_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(main, "settings", settings)


def req(cookie: str | None = None) -> Request:
    headers = [(b"cookie", f"sf_session={cookie}".encode())] if cookie else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def authed_req(monkeypatch: pytest.MonkeyPatch, settings: Settings, db: FakeDatabase, email: str) -> Request:
    monkeypatch.setattr(main, "db", db)
    user = db.create_user(email, hash_password("password123"))
    token = create_session_token(user["id"], settings.session_secret or "")
    return req(token)


def make_upload(filename: str, data: bytes, content_type: str = "image/jpeg") -> UploadFile:
    return UploadFile(
        filename=filename,
        file=BytesIO(data),
        headers=Headers({"content-type": content_type}),
    )


def make_slide(offset: int) -> bytes:
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([80 + offset, 80, 480 + offset, 380], fill="black")
    buffer = BytesIO()
    image.save(buffer, "JPEG")
    return buffer.getvalue()


def test_v2_full_flow_completes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        created = await create_v2_project(req(), ProjectCreate(goal="Ship a slide assistant", context_notes=""))
        project_id = created["project_id"]
        first = await add_v2_image(project_id, req(), make_upload("a.jpg", make_slide(0)))
        second = await add_v2_image(project_id, req(), make_upload("b.jpg", make_slide(120)))
        assert (first["image_id"], first["count"]) == ("img-01", 1)
        assert (second["image_id"], second["count"]) == ("img-02", 2)
        finalized = await finalize_v2_project(project_id, req())
        assert finalized["status"] == "queued"

        state: dict = {}
        for _ in range(40):
            state = await advance_v2_project(project_id, req())
            if state["status"] in ("complete", "failed"):
                break
        assert state["status"] == "complete"
        assert state["progress"] == 100
        assert len(state["result"]["images"]) == 2
        assert state["result"]["plan"]["headline"]

    use_settings(monkeypatch, make_settings(tmp_path))
    asyncio.run(run())


def test_v2_enforces_ownership_and_records_to_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        db = FakeDatabase()
        ada = authed_req(monkeypatch, settings, db, "ada@example.com")
        bob = authed_req(monkeypatch, settings, db, "bob@example.com")
        created = await create_v2_project(ada, ProjectCreate(goal="Ship a slide assistant"))
        project_id = created["project_id"]
        row = db.get_project(project_id)
        assert row["status"] == "collecting"

        with pytest.raises(Exception) as forbidden:
            await add_v2_image(project_id, bob, make_upload("a.jpg", make_slide(0)))
        assert forbidden.value.status_code == 404

        await add_v2_image(project_id, ada, make_upload("a.jpg", make_slide(0)))
        with pytest.raises(Exception) as forbidden_finalize:
            await finalize_v2_project(project_id, bob)
        assert forbidden_finalize.value.status_code == 404
        await finalize_v2_project(project_id, ada)
        assert db.get_project(project_id)["status"] == "queued"

        state: dict = {}
        for _ in range(40):
            state = await advance_v2_project(project_id, ada)
            if state["status"] in ("complete", "failed"):
                break
        assert state["status"] == "complete"
        recorded = db.get_project(project_id)
        assert recorded["status"] == "complete"
        assert recorded["result"]["plan"]["headline"]

    settings = make_settings(
        tmp_path, postgres_url="postgresql://test", session_secret="test-secret"
    )
    use_settings(monkeypatch, settings)
    asyncio.run(run())


def test_v2_finalize_requires_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        created = await create_v2_project(req(), ProjectCreate(goal="Ship a slide assistant"))
        with pytest.raises(Exception) as raised:
            await finalize_v2_project(created["project_id"], req())
        assert raised.value.status_code == 400

    use_settings(monkeypatch, make_settings(tmp_path))
    asyncio.run(run())


def test_v2_rejects_bad_uploads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        created = await create_v2_project(req(), ProjectCreate(goal="Ship a slide assistant"))
        project_id = created["project_id"]
        with pytest.raises(Exception) as wrong_type:
            await add_v2_image(
                project_id, req(), make_upload("a.txt", b"nope", "text/plain")
            )
        assert wrong_type.value.status_code == 400
        with pytest.raises(Exception) as too_big:
            await add_v2_image(project_id, req(), make_upload("a.jpg", b"x" * (4 * 1024 * 1024 + 1)))
        assert too_big.value.status_code == 400
        with pytest.raises(Exception) as missing:
            await add_v2_image("nope01", req(), make_upload("a.jpg", make_slide(0)))
        assert missing.value.status_code == 404
        with pytest.raises(Exception) as poll_missing:
            await advance_v2_project("nope01", req())
        assert poll_missing.value.status_code == 404

    use_settings(monkeypatch, make_settings(tmp_path))
    asyncio.run(run())
