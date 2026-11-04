from __future__ import annotations

import asyncio
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from signalforge.config import get_settings
from signalforge.services import drive
from signalforge.services.auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    create_session_token,
    hash_password,
    read_session_token,
    valid_email,
    valid_password,
    verify_password,
)
from signalforge.services.db import EmailTakenError, get_database
from signalforge.services.drive import DriveError
from signalforge.services.capture import assess_capture
from signalforge.services.images import detect_surface_mask_locally, normalize_image
from signalforge.services.jobstore import MemoryJobStore, get_jobstore
from signalforge.services.pipeline import process_project
from signalforge.services.sam import SamService
from signalforge.services.stepper import advance_job, new_job
from signalforge.services.storage import get_storage


ROOT = Path(__file__).resolve().parent.parent
settings = get_settings()
app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount("/runs", StaticFiles(directory=settings.data_dir), name="runs")
templates = Jinja2Templates(directory=ROOT / "templates")

jobs: dict[str, dict[str, Any]] = {}
memory_jobstore = MemoryJobStore()


def _v2_store():
    if settings.job_backend == "memory":
        return memory_jobstore
    return get_jobstore(settings)


db = get_database(settings)


def _session_secret() -> str:
    if not settings.session_secret:
        raise HTTPException(500, "Set SESSION_SECRET to enable accounts.")
    return settings.session_secret


def current_user_id(request: Request) -> str | None:
    if not settings.db_configured:
        return None
    token = request.cookies.get(SESSION_COOKIE)
    if not token or not settings.session_secret:
        return None
    return read_session_token(token, settings.session_secret)


def _owned_job(request: Request, job: dict[str, Any] | None) -> dict[str, Any]:
    if job is None:
        raise HTTPException(404, "Project not found.")
    if settings.db_configured and job.get("user_id") != current_user_id(request):
        raise HTTPException(404, "Project not found.")
    return job


async def _record_project(project_id: str, job: dict[str, Any]) -> None:
    if not settings.db_configured:
        return
    fields: dict[str, Any] = {
        "status": job["status"],
        "message": job["message"],
        "progress": job["progress"],
        "context_notes": job.get("context_notes", ""),
    }
    if job["status"] == "complete":
        fields["result"] = job["result"]
    if job["status"] == "failed":
        fields["error"] = job.get("error")
    await asyncio.to_thread(db.update_project, project_id, **fields)


OPEN_PATHS = {"/login", "/signup", "/api/health"}
OPEN_PREFIXES = ("/static",)


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    gated = (
        settings.db_configured
        and path not in OPEN_PATHS
        and not path.startswith(OPEN_PREFIXES)
    )
    if gated and current_user_id(request) is None:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Login required."}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    user_email = None
    if settings.db_configured:
        user_id = current_user_id(request)
        if user_id is not None:
            user = await asyncio.to_thread(db.get_user_by_id, user_id)
            user_email = user["email"] if user else None
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "demo_mode": settings.demo_mode,
            "max_images": settings.max_images,
            "flow": settings.flow,
            "db_configured": settings.db_configured,
            "user_email": user_email,
        },
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    if not settings.db_configured or current_user_id(request) is not None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@app.post("/login")
async def login(request: Request, email: str = Form(), password: str = Form()):
    if not settings.db_configured:
        return RedirectResponse("/", status_code=303)
    user = await asyncio.to_thread(db.get_user_by_email, email.strip().lower())
    if user is None or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid email or password."},
            status_code=401,
        )
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user["id"], _session_secret()),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.serverless_mode,
    )
    return response


@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request) -> HTMLResponse:
    if not settings.db_configured or current_user_id(request) is not None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="signup.html", context={"error": None})


@app.post("/signup")
async def signup(request: Request, email: str = Form(), password: str = Form()):
    if not settings.db_configured:
        return RedirectResponse("/", status_code=303)
    email = email.strip().lower()
    error = None
    if not valid_email(email):
        error = "Enter a valid email address."
    elif not valid_password(password):
        error = "Password must be 8–128 characters."
    else:
        try:
            user = await asyncio.to_thread(
                db.create_user, email, hash_password(password)
            )
        except EmailTakenError:
            error = "An account with this email already exists."
        else:
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(
                SESSION_COOKIE,
                create_session_token(user["id"], _session_secret()),
                max_age=SESSION_MAX_AGE,
                httponly=True,
                samesite="lax",
                secure=settings.serverless_mode,
            )
            return response
    return templates.TemplateResponse(
        request=request, name="signup.html", context={"error": error}, status_code=400
    )


@app.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/library", response_class=HTMLResponse)
async def library(request: Request) -> HTMLResponse:
    if not settings.db_configured:
        return RedirectResponse("/", status_code=303)
    user_id = current_user_id(request)
    user_email = None
    if user_id is not None:
        user = await asyncio.to_thread(db.get_user_by_id, user_id)
        user_email = user["email"] if user else None
    rows = await asyncio.to_thread(db.list_projects, user_id or "", 50)
    cards = []
    for row in rows:
        result = row.get("result") or {}
        images = result.get("images", [])
        cards.append(
            {
                "id": row["id"],
                "goal": row["goal"],
                "status": row["status"],
                "progress": row.get("progress", 0),
                "updated": (row.get("updated_at") or "")[:10],
                "image_count": len(images),
                "cover": images[0].get("original_url") if images else None,
                "photos": [
                    {
                        "thumb": image.get("corrected_url") or image.get("original_url"),
                        "full": image.get("original_url"),
                        "title": (image.get("analysis") or {}).get("title") or image.get("filename", ""),
                    }
                    for image in images
                ],
                "notes": row.get("context_notes", ""),
                "takeaways": (result.get("plan") or {}).get("notes_takeaways", []),
                "ready": row["status"] == "complete",
            }
        )
    return templates.TemplateResponse(
        request=request,
        name="library.html",
        context={"projects": cards, "user_email": user_email},
    )


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "muse_model": settings.muse_model,
        "sam_model": settings.sam_model,
        "flow": settings.flow,
        "storage": settings.storage_backend,
        "jobs": settings.job_backend,
    }


CAPTURE_TYPES = {"image/jpeg", "image/png", "image/webp"}
CAPTURE_MAX_BYTES = 3 * 1024 * 1024


@app.post("/api/capture-coach/analyze")
async def analyze_capture(
    frame: UploadFile = File(...),
    target: str = Form(default="presentation screen", max_length=80),
) -> dict[str, Any]:
    """Analyze one sampled camera frame; the browser throttles these requests."""
    if frame.content_type not in CAPTURE_TYPES:
        raise HTTPException(400, "Capture Coach accepts JPG, PNG, or WebP frames.")
    raw = await frame.read()
    if not raw or len(raw) > CAPTURE_MAX_BYTES:
        raise HTTPException(400, "Camera frame is empty or larger than 3 MB.")

    matrix = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if matrix is None:
        raise HTTPException(400, "Camera frame could not be read.")

    with tempfile.TemporaryDirectory() as tmp:
        frame_path = Path(tmp) / "capture.jpg"
        if not cv2.imwrite(str(frame_path), matrix):
            raise HTTPException(500, "Camera frame could not be prepared.")

        mask = None
        source = "local geometry"
        confidence = None
        if not settings.demo_mode and settings.model_api_key:
            service = SamService(settings.model_api_key, settings.sam_model)
            segmented = await service.segment(frame_path, target.strip() or "presentation screen")
            if segmented is not None:
                mask, confidence = segmented
                source = "SAM 3.1"
        if mask is None:
            mask = await asyncio.to_thread(detect_surface_mask_locally, frame_path)

    assessment = await asyncio.to_thread(assess_capture, matrix, mask)
    assessment.update(source=source, confidence=confidence)
    return assessment


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


async def _normalize_upload(raw: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        temporary = Path(tmp) / "upload"
        temporary.write_bytes(raw)
        destination = Path(tmp) / "normalized.jpg"
        try:
            with Image.open(temporary) as image:
                image.verify()
            await asyncio.to_thread(normalize_image, temporary, destination)
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise ValueError("unreadable image") from error
        return destination.read_bytes()


class ProjectCreate(BaseModel):
    goal: str = Field(min_length=8, max_length=500)
    context_notes: str = Field(default="", max_length=12000)


class DriveImport(BaseModel):
    drive_url: str = Field(min_length=8, max_length=2000)


V2_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
V2_MAX_BYTES = 4 * 1024 * 1024


@app.post("/api/v2/projects", status_code=201)
async def create_v2_project(request: Request, payload: ProjectCreate) -> dict[str, str]:
    project_id = uuid.uuid4().hex[:12]
    user_id = current_user_id(request) or "local"
    job = new_job(project_id, payload.goal, payload.context_notes, settings.demo_mode)
    job["user_id"] = user_id
    await _v2_store().write(project_id, job)
    if settings.db_configured:
        await asyncio.to_thread(
            db.create_project,
            project_id,
            user_id,
            payload.goal,
            payload.context_notes,
            settings.demo_mode,
        )
    return {"project_id": project_id}


@app.post("/api/v2/projects/{project_id}/images", status_code=201)
async def add_v2_image(
    project_id: str, request: Request, file: UploadFile = File(...)
) -> dict[str, Any]:
    store = _v2_store()
    job = _owned_job(request, await store.read(project_id))
    if job["status"] != "collecting":
        raise HTTPException(400, "Project is already finalized.")
    if len(job["files"]) >= settings.max_images:
        raise HTTPException(400, f"Upload between 1 and {settings.max_images} images.")
    if file.content_type not in V2_IMAGE_TYPES:
        raise HTTPException(400, f"{file.filename or 'A file'} is not a supported image.")
    raw = await file.read()
    if len(raw) > V2_MAX_BYTES:
        raise HTTPException(400, f"{file.filename or 'A file'} is larger than 4 MB.")

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", file.filename or "image")
    try:
        normalized = await _normalize_upload(raw)
    except ValueError as error:
        raise HTTPException(400, f"{safe_name} could not be read as an image.") from error

    image_id = f"img-{len(job['files']) + 1:02d}"
    key = f"{project_id}/originals/{image_id}.jpg"
    url = await get_storage(settings).put(key, normalized, "image/jpeg")
    job["files"].append(
        {"image_id": image_id, "filename": safe_name, "key": key, "url": url}
    )
    await store.write(project_id, job)
    return {"image_id": image_id, "count": len(job["files"])}


DRIVE_MAX_BYTES = 20 * 1024 * 1024
DRIVE_MAX_DOCS = 10
DRIVE_DOC_CHARS = 4000


@app.post("/api/v2/projects/{project_id}/import")
async def import_drive(
    project_id: str, request: Request, payload: DriveImport
) -> dict[str, Any]:
    store = _v2_store()
    job = _owned_job(request, await store.read(project_id))
    if job["status"] != "collecting":
        raise HTTPException(400, "Project is already finalized.")
    if not settings.google_api_key:
        raise HTTPException(400, "Drive import is not configured on this server.")
    try:
        folder_id = drive.parse_folder_id(payload.drive_url)
    except DriveError as error:
        raise HTTPException(400, str(error)) from error
    try:
        files = await asyncio.to_thread(
            drive.list_folder_files, settings.google_api_key, folder_id
        )
    except DriveError as error:
        raise HTTPException(502, str(error)) from error

    storage = get_storage(settings)
    slots = settings.max_images - len(job["files"])
    added_images = 0
    skipped_large = 0
    skipped_unreadable = 0
    for entry in files:
        if added_images >= slots:
            break
        if not drive.is_image(entry.get("mimeType", "")):
            continue
        if int(entry.get("size") or 0) > DRIVE_MAX_BYTES:
            skipped_large += 1
            continue
        try:
            raw = await asyncio.to_thread(
                drive.download_file, settings.google_api_key, entry["id"], DRIVE_MAX_BYTES
            )
            normalized = await _normalize_upload(raw)
        except (DriveError, ValueError):
            skipped_unreadable += 1
            continue
        image_id = f"img-{len(job['files']) + 1:02d}"
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", entry.get("name") or f"drive-{image_id}")
        key = f"{project_id}/originals/{image_id}.jpg"
        url = await storage.put(key, normalized, "image/jpeg")
        job["files"].append(
            {"image_id": image_id, "filename": safe_name, "key": key, "url": url}
        )
        added_images += 1

    notes_parts = []
    for entry in files:
        if len(notes_parts) >= DRIVE_MAX_DOCS:
            break
        if not drive.is_exportable(entry.get("mimeType", "")):
            continue
        try:
            text = await asyncio.to_thread(
                drive.export_text, settings.google_api_key, entry["id"], entry["mimeType"]
            )
        except DriveError:
            continue
        text = text.strip()[:DRIVE_DOC_CHARS]
        if text:
            notes_parts.append(f"## {entry.get('name') or 'Drive document'}\n{text}")
    if notes_parts:
        combined = job.get("context_notes", "")
        joined = "\n\n".join([part for part in [combined.strip(), *notes_parts] if part])
        job["context_notes"] = joined[:12000]

    await store.write(project_id, job)
    await _record_project(project_id, job)
    return {
        "added_images": added_images,
        "added_notes": len(notes_parts),
        "skipped_large": skipped_large,
        "skipped_unreadable": skipped_unreadable,
        "found": len(files),
        "count": len(job["files"]),
    }


@app.post("/api/v2/projects/{project_id}/finalize")
async def finalize_v2_project(project_id: str, request: Request) -> dict[str, Any]:
    store = _v2_store()
    job = _owned_job(request, await store.read(project_id))
    if job["status"] != "collecting":
        raise HTTPException(400, "Project is already finalized.")
    if not job["files"]:
        raise HTTPException(400, "Add at least one image.")
    job.update(status="queued", message="Queued for processing", progress=2)
    await store.write(project_id, job)
    await _record_project(project_id, job)
    return {"project_id": project_id, "status": job["status"], "count": len(job["files"])}


@app.get("/api/v2/projects/{project_id}")
async def advance_v2_project(project_id: str, request: Request) -> dict[str, Any]:
    store = _v2_store()
    job = _owned_job(request, await store.read(project_id))
    if job["status"] not in ("complete", "failed"):
        job = await advance_job(job, get_storage(settings), settings)
        await store.write(project_id, job)
        await _record_project(project_id, job)
    payload: dict[str, Any] = {
        "status": job["status"],
        "message": job["message"],
        "progress": job["progress"],
    }
    if job["status"] == "complete":
        payload["result"] = job["result"]
    return payload


@app.get("/api/v2/projects/{project_id}/report")
async def project_report(project_id: str, request: Request) -> dict[str, Any]:
    store = _v2_store()
    job = await store.read(project_id)
    if settings.db_configured:
        if job is not None and job.get("user_id") != current_user_id(request):
            raise HTTPException(404, "Project not found.")
        row = await asyncio.to_thread(db.get_project, project_id)
        if row is not None and row["user_id"] != current_user_id(request):
            raise HTTPException(404, "Project not found.")
        if row and row.get("result"):
            return {"result": row["result"]}
    if job is None:
        raise HTTPException(404, "Project not found.")
    if job.get("status") == "complete" and job.get("result"):
        return {"result": job["result"]}
    raise HTTPException(409, job.get("message") or "Report is not ready yet.")

