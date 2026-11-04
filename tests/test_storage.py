import asyncio
import sys
import types
from pathlib import Path

import pytest

from signalforge.config import Settings
from signalforge.services.storage import (
    BlobFileStorage,
    LocalFileStorage,
    get_storage,
)


def make_settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, **overrides)


def test_local_storage_roundtrip(tmp_path: Path) -> None:
    async def run() -> None:
        storage = LocalFileStorage(tmp_path)
        url = await storage.put("abc/originals/img-01.jpg", b"bytes", "image/jpeg")
        assert url == "/runs/abc/originals/img-01.jpg"
        assert await storage.get("abc/originals/img-01.jpg") == b"bytes"
        assert (tmp_path / "abc" / "originals" / "img-01.jpg").exists()

    asyncio.run(run())


def test_get_storage_selects_local_by_default(tmp_path: Path) -> None:
    storage = get_storage(make_settings(tmp_path))
    assert isinstance(storage, LocalFileStorage)


def test_get_storage_rejects_unknown_backend(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown storage backend"):
        get_storage(make_settings(tmp_path, storage_backend="s3"))


def test_blob_storage_requires_token() -> None:
    with pytest.raises(ValueError, match="BLOB_READ_WRITE_TOKEN"):
        BlobFileStorage(None)


def install_fake_blob_sdk(monkeypatch: pytest.MonkeyPatch) -> dict:
    calls: dict = {}
    vercel_module = types.ModuleType("vercel")
    blob_module = types.ModuleType("vercel.blob")

    async def put_blob(pathname, body, **kwargs):
        calls["put"] = (pathname, bytes(body), kwargs)

        class PutResult:
            url = f"https://store.public.blob.vercel-storage.com/{pathname}"

        return PutResult()

    async def get_blob(pathname_or_url, **kwargs):
        calls["get"] = (pathname_or_url, kwargs)

        class GetResult:
            body = b"stored-bytes"

        return GetResult()

    blob_module.put_blob = put_blob
    blob_module.get_blob = get_blob
    vercel_module.blob = blob_module
    monkeypatch.setitem(sys.modules, "vercel", vercel_module)
    monkeypatch.setitem(sys.modules, "vercel.blob", blob_module)
    return calls


def test_blob_storage_put_and_get(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        storage = BlobFileStorage("token")
        url = await storage.put("abc/img-01.jpg", b"bytes", "image/jpeg")
        assert url == "https://store.public.blob.vercel-storage.com/abc/img-01.jpg"
        assert await storage.get("abc/img-01.jpg") == b"stored-bytes"

    calls = install_fake_blob_sdk(monkeypatch)
    asyncio.run(run())
    assert calls["put"][0] == "abc/img-01.jpg"
    assert calls["put"][2]["access"] == "public"
    assert calls["put"][2]["content_type"] == "image/jpeg"
    assert calls["put"][2]["allow_overwrite"] is True
    assert calls["get"][0] == "abc/img-01.jpg"
