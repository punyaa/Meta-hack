from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from signalforge.config import Settings
from signalforge.services.storage import FileStorage, get_storage


class JobStore(Protocol):
    async def read(self, project_id: str) -> dict[str, Any] | None:
        ...

    async def write(self, project_id: str, job: dict[str, Any]) -> None:
        ...


class MemoryJobStore:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}

    async def read(self, project_id: str) -> dict[str, Any] | None:
        return self.jobs.get(project_id)

    async def write(self, project_id: str, job: dict[str, Any]) -> None:
        self.jobs[project_id] = job


class FileJobStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, project_id: str) -> Path:
        return self.root / project_id / "job.json"

    async def read(self, project_id: str) -> dict[str, Any] | None:
        path = self._path(project_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    async def write(self, project_id: str, job: dict[str, Any]) -> None:
        path = self._path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(job), encoding="utf-8")


class BlobJobStore:
    def __init__(self, storage: FileStorage) -> None:
        self.storage = storage

    @staticmethod
    def _key(project_id: str) -> str:
        return f"{project_id}/job.json"

    async def read(self, project_id: str) -> dict[str, Any] | None:
        try:
            raw = await self.storage.get(self._key(project_id))
        except Exception:
            return None
        return json.loads(raw.decode("utf-8"))

    async def write(self, project_id: str, job: dict[str, Any]) -> None:
        await self.storage.put(
            self._key(project_id),
            json.dumps(job).encode("utf-8"),
            "application/json",
        )


def get_jobstore(settings: Settings, storage: FileStorage | None = None) -> JobStore:
    if settings.job_backend == "memory":
        return MemoryJobStore()
    if settings.job_backend == "file":
        return FileJobStore(settings.data_dir)
    if settings.job_backend == "blob":
        return BlobJobStore(storage or get_storage(settings))
    raise ValueError(f"Unknown job backend: {settings.job_backend}")
