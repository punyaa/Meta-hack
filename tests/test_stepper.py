import asyncio
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from signalforge.config import Settings
from signalforge.services.stepper import advance_job, new_job
from signalforge.services.storage import LocalFileStorage


def make_settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path)


def make_slide(path: Path, offset: int) -> None:
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([80 + offset, 80, 480 + offset, 380], fill="black")
    draw.ellipse([520, 400, 700, 520], fill="gray")
    image.save(path, "JPEG")


async def run_to_terminal(job: dict, storage, settings: Settings, limit: int = 40) -> dict:
    for _ in range(limit):
        job = await advance_job(job, storage, settings)
        if job["status"] in ("complete", "failed"):
            return job
    raise AssertionError(f"job did not finish: {job['status']} {job['message']}")


async def add_file(storage, job: dict, image_id: str, filename: str, data: bytes) -> None:
    key = f"{job['project_id']}/originals/{image_id}.jpg"
    url = await storage.put(key, data, "image/jpeg")
    job["files"].append(
        {"image_id": image_id, "filename": filename, "key": key, "url": url}
    )


def test_stepper_completes_demo_project(tmp_path: Path) -> None:
    async def run() -> None:
        settings = make_settings(tmp_path)
        storage = LocalFileStorage(tmp_path)
        job = new_job("abc123", "Ship a slide assistant", demo_mode=True)
        first = tmp_path / "a.jpg"
        second = tmp_path / "b.jpg"
        make_slide(first, 0)
        make_slide(second, 120)
        await add_file(storage, job, "img-01", "a.jpg", first.read_bytes())
        await add_file(storage, job, "img-02", "b.jpg", second.read_bytes())
        job["status"] = "queued"

        job = await run_to_terminal(job, storage, settings)

        assert job["status"] == "complete"
        assert job["progress"] == 100
        assert job["duplicate_count"] == 0
        assert len(job["result"]["images"]) == 2
        assert job["result"]["images"][0]["analysis"] is not None
        assert job["result"]["plan"]["headline"]

    asyncio.run(run())


def test_stepper_detects_duplicates(tmp_path: Path) -> None:
    async def run() -> None:
        settings = make_settings(tmp_path)
        storage = LocalFileStorage(tmp_path)
        job = new_job("dup01", "Ship a slide assistant", demo_mode=True)
        slide = tmp_path / "a.jpg"
        make_slide(slide, 0)
        raw = slide.read_bytes()
        await add_file(storage, job, "img-01", "a.jpg", raw)
        await add_file(storage, job, "img-02", "a-copy.jpg", raw)
        job["status"] = "queued"

        job = await run_to_terminal(job, storage, settings)

        assert job["status"] == "complete"
        assert job["duplicate_count"] == 1
        by_id = {image["image_id"]: image for image in job["result"]["images"]}
        assert by_id["img-02"]["duplicate_of"] == "img-01"
        assert by_id["img-02"]["analysis"] is None

    asyncio.run(run())


def test_stepper_fails_corrupt_images_after_retries(tmp_path: Path) -> None:
    async def run() -> None:
        settings = make_settings(tmp_path)
        storage = LocalFileStorage(tmp_path)
        job = new_job("bad01", "Ship a slide assistant", demo_mode=True)
        await add_file(storage, job, "img-01", "a.jpg", b"not-an-image")
        job["status"] = "queued"

        for _ in range(6):
            job = await advance_job(job, storage, settings)

        assert job["status"] == "failed"
        assert job["error"]

    asyncio.run(run())


def test_advance_rejects_collecting_and_ignores_terminal(tmp_path: Path) -> None:
    async def run() -> None:
        settings = make_settings(tmp_path)
        storage = LocalFileStorage(tmp_path)
        job = new_job("abc123", "Ship a slide assistant", demo_mode=True)
        with pytest.raises(ValueError, match="Finalize"):
            await advance_job(job, storage, settings)
        job["status"] = "complete"
        assert await advance_job(job, storage, settings) is job

    asyncio.run(run())
