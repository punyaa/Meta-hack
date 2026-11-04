from __future__ import annotations

from pathlib import Path
from typing import Protocol

from signalforge.config import Settings


class FileStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> str:
        """Store bytes under key, returning the public URL."""
        ...

    async def get(self, key: str) -> bytes:
        ...

    def url(self, key: str) -> str:
        ...


class LocalFileStorage:
    """Filesystem storage for local development (served from /runs)."""

    def __init__(self, root: Path) -> None:
        self.root = root

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        del content_type
        destination = self.root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return self.url(key)

    async def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def url(self, key: str) -> str:
        return f"/runs/{key}"


class BlobFileStorage:
    """Vercel Blob storage for serverless deployments."""

    def __init__(self, token: str | None) -> None:
        if not token:
            raise ValueError("Blob storage needs BLOB_READ_WRITE_TOKEN.")
        self.token = token

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        from vercel import blob

        result = await blob.put_blob(
            key,
            data,
            access="public",
            content_type=content_type,
            allow_overwrite=True,
        )
        return result.url

    async def get(self, key: str) -> bytes:
        from vercel import blob

        result = await blob.get_blob(key, access="public")
        return result.body

    def url(self, key: str) -> str:
        raise NotImplementedError("Blob URLs come from put(); store the returned URL.")


def get_storage(settings: Settings) -> FileStorage:
    if settings.storage_backend == "blob":
        return BlobFileStorage(settings.blob_read_write_token)
    if settings.storage_backend != "local":
        raise ValueError(f"Unknown storage backend: {settings.storage_backend}")
    return LocalFileStorage(settings.data_dir)
