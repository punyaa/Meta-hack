import asyncio
from pathlib import Path

import pytest

from signalforge.config import Settings
from signalforge.services.jobstore import (
    BlobJobStore,
    FileJobStore,
    MemoryJobStore,
    get_jobstore,
)


def make_settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, **overrides)


def test_memory_jobstore_roundtrip() -> None:
    async def run() -> None:
        store = MemoryJobStore()
        assert await store.read("missing") is None
        await store.write("abc", {"status": "queued"})
        assert await store.read("abc") == {"status": "queued"}

    asyncio.run(run())


def test_file_jobstore_roundtrip(tmp_path: Path) -> None:
    async def run() -> None:
        store = FileJobStore(tmp_path)
        assert await store.read("missing") is None
        await store.write("abc", {"status": "queued", "progress": 3})
        assert await store.read("abc") == {"status": "queued", "progress": 3}
        assert (tmp_path / "abc" / "job.json").exists()

    asyncio.run(run())


class DictStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        self.files[key] = data
        return f"https://blob.test/{key}"

    async def get(self, key: str) -> bytes:
        return self.files[key]

    def url(self, key: str) -> str:
        return f"https://blob.test/{key}"


def test_blob_jobstore_roundtrip() -> None:
    async def run() -> None:
        store = BlobJobStore(DictStorage())
        assert await store.read("missing") is None
        await store.write("abc", {"status": "queued"})
        assert await store.read("abc") == {"status": "queued"}

    asyncio.run(run())


def test_get_jobstore_selects_backend(tmp_path: Path) -> None:
    assert isinstance(get_jobstore(make_settings(tmp_path)), MemoryJobStore)
    assert isinstance(
        get_jobstore(make_settings(tmp_path, job_backend="file")), FileJobStore
    )
    assert isinstance(
        get_jobstore(make_settings(tmp_path, job_backend="blob"), DictStorage()),
        BlobJobStore,
    )
    with pytest.raises(ValueError, match="Unknown job backend"):
        get_jobstore(make_settings(tmp_path, job_backend="redis"))
