from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError

from signalforge.config import get_settings
from signalforge.services.images import normalize_image
from signalforge.services.pipeline import process_project


ROOT = Path(__file__).resolve().parent.parent
settings = get_settings()
app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount("/runs", StaticFiles(directory=settings.data_dir), name="runs")
templates = Jinja2Templates(directory=ROOT / "templates")

jobs: dict[str, dict[str, Any]] = {}


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"demo_mode": settings.demo_mode, "max_images": settings.max_images},
    )


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "muse_model": settings.muse_model,
        "sam_model": settings.sam_model,
    }


@app.post("/api/projects", status_code=202)
async def create_project(
    goal: str = Form(min_length=8, max_length=500),
    context_notes: str = Form(default="", max_length=12000),
    files: list[UploadFile] = File(...),
) -> dict[str, str]:
    if not files or len(files) > settings.max_images:
        raise HTTPException(400, f"Upload between 1 and {settings.max_images} images.")

    supported_types = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
    unsupported = next((upload for upload in files if upload.content_type not in supported_types), None)
    if unsupported is not None:
        raise HTTPException(400, f"{unsupported.filename or 'A file'} is not a supported image.")

    project_id = uuid.uuid4().hex[:12]
    original_dir = settings.data_dir / project_id / "originals"
    original_dir.mkdir(parents=True, exist_ok=False)
    originals: list[tuple[str, str, Path]] = []

    for index, upload in enumerate(files, start=1):
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", upload.filename or f"image-{index}")
        raw = await upload.read()
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(400, f"{safe_name} is larger than 20 MB.")

        temporary = original_dir / f"upload-{index}"
        temporary.write_bytes(raw)
        image_id = f"img-{index:02d}"
        destination = original_dir / f"{image_id}.jpg"
        try:
            with Image.open(temporary) as image:
                image.verify()
            await asyncio.to_thread(normalize_image, temporary, destination)
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise HTTPException(400, f"{safe_name} could not be read as an image.") from error
        finally:
            temporary.unlink(missing_ok=True)
        originals.append((image_id, safe_name, destination))

    jobs[project_id] = {"status": "queued", "message": "Preparing images", "progress": 2}

    def report(message: str, progress: int) -> None:
        jobs[project_id].update(message=message, progress=progress)

    async def run() -> None:
        jobs[project_id]["status"] = "processing"
        try:
            result = await process_project(
                project_id,
                goal,
                context_notes,
                originals,
                settings,
                report,
            )
            jobs[project_id].update(status="complete", result=result.model_dump(mode="json"))
        except Exception as error:
            jobs[project_id].update(
                status="failed",
                message="Processing failed. Check the server log and API configuration.",
                error=type(error).__name__,
            )

    asyncio.create_task(run())
    return {"project_id": project_id}


@app.get("/api/projects/{project_id}")
async def project_status(project_id: str) -> dict[str, Any]:
    job = jobs.get(project_id)
    if job is None:
        raise HTTPException(404, "Project not found.")
    return job

