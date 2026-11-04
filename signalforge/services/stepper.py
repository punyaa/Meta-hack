from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import imagehash

from signalforge.config import Settings
from signalforge.models import ImageAnalysis, ImageResult, ProjectResult
from signalforge.services.demo import demo_analysis, demo_plan
from signalforge.services.images import (
    StoredImage,
    deduplicate,
    detect_surface_mask_locally,
    inspect_image,
    perspective_correct,
)
from signalforge.services.muse import MuseService
from signalforge.services.sam import SamService
from signalforge.services.storage import FileStorage

TERMINAL_STATUSES = ("complete", "failed")
MAX_STEP_ATTEMPTS = 4


def new_job(
    project_id: str,
    goal: str,
    context_notes: str = "",
    demo_mode: bool = True,
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "goal": goal,
        "context_notes": context_notes,
        "demo_mode": demo_mode,
        "status": "collecting",
        "message": "Waiting for images",
        "progress": 1,
        "files": [],
        "images": {},
        "order": [],
        "duplicate_count": 0,
        "retries": {},
        "plan": None,
        "result": None,
        "error": None,
    }


def _active_image(job: dict[str, Any]) -> str | None:
    for image_id in job["order"]:
        if job["images"][image_id]["state"] != "done":
            return image_id
    return None


def _retained_ids(job: dict[str, Any]) -> list[str]:
    return [
        image_id
        for image_id in job["order"]
        if not job["images"][image_id]["duplicate_of"]
    ]


def _refresh_progress(job: dict[str, Any]) -> None:
    retained = _retained_ids(job)
    if not retained:
        return
    done = sum(1 for image_id in retained if job["images"][image_id]["state"] == "done")
    job["progress"] = 12 + int(66 * done / len(retained))
    job["message"] = f"Reading {min(done + 1, len(retained))} of {len(retained)} retained images"


async def advance_job(
    job: dict[str, Any], storage: FileStorage, settings: Settings
) -> dict[str, Any]:
    """Run exactly one unit of work, mutating and returning the job."""
    status = job["status"]
    if status in TERMINAL_STATUSES:
        return job
    if status == "collecting":
        raise ValueError("Finalize the project before processing.")

    step_key = f"{status}:{_active_image(job) or '-'}"
    try:
        if status == "queued":
            await _ingest(job, storage)
        elif status == "analyzing":
            await _analyze_next(job, storage, settings)
        elif status == "segmenting":
            await _segment_next(job, storage, settings)
        elif status == "rereading":
            await _reread_next(job, storage, settings)
        elif status == "synthesizing":
            await _synthesize(job, settings)
        else:
            raise ValueError(f"Unknown job status: {status}")
    except Exception as error:
        attempts = job["retries"].get(step_key, 0) + 1
        job["retries"][step_key] = attempts
        if attempts >= MAX_STEP_ATTEMPTS:
            job.update(
                status="failed",
                message="Processing failed. Please try again with different images.",
                error=f"{type(error).__name__}: {error}",
            )
        else:
            job["message"] = f"Retrying ({attempts}/{MAX_STEP_ATTEMPTS})"
    return job


async def _ingest(job: dict[str, Any], storage: FileStorage) -> None:
    job["message"] = "Finding duplicate shots"
    with tempfile.TemporaryDirectory() as tmp:
        inspected: list[StoredImage] = []
        for file in job["files"]:
            raw = await storage.get(file["key"])
            path = Path(tmp) / f"{file['image_id']}.jpg"
            path.write_bytes(raw)
            inspected.append(
                await asyncio.to_thread(
                    inspect_image, file["image_id"], file["filename"], path
                )
            )
    duplicate_map = deduplicate(inspected)
    by_id = {file["image_id"]: file for file in job["files"]}
    images: dict[str, Any] = {}
    for stored in inspected:
        file = by_id[stored.image_id]
        duplicate_of = duplicate_map.get(stored.image_id)
        images[stored.image_id] = {
            "image_id": stored.image_id,
            "filename": stored.filename,
            "key": file["key"],
            "url": file["url"],
            "hash": str(stored.perceptual_hash),
            "sharpness": stored.sharpness,
            "duplicate_of": duplicate_of,
            "state": "done" if duplicate_of else "pending",
            "analysis": None,
            "corrected_key": None,
            "corrected_url": None,
            "correction_status": "not_needed",
        }
    job["images"] = images
    job["order"] = [file["image_id"] for file in job["files"]]
    job["duplicate_count"] = len(duplicate_map)
    job["status"] = "analyzing"
    job["progress"] = 8
    job["message"] = "Reading retained images"


def _muse(settings: Settings, demo_mode: bool) -> MuseService | None:
    if demo_mode:
        return None
    return MuseService(settings.model_api_key or "", settings.muse_model)


async def _analyze_next(
    job: dict[str, Any], storage: FileStorage, settings: Settings
) -> None:
    target = next(
        (
            image_id
            for image_id in _retained_ids(job)
            if job["images"][image_id]["state"] == "pending"
        ),
        None,
    )
    if target is None:
        job["status"] = "segmenting"
        return
    entry = job["images"][target]
    muse = _muse(settings, job["demo_mode"])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "original.jpg"
        path.write_bytes(await storage.get(entry["key"]))
        if muse is None:
            analysis = demo_analysis(target, entry["filename"], job["goal"])
        else:
            analysis = await asyncio.to_thread(
                muse.analyze_image, target, path, job["goal"]
            )
    entry["analysis"] = analysis.model_dump(mode="json")
    if analysis.surface_prompt == "none":
        entry["state"] = "done"
    else:
        entry["state"] = "pending_segment"
    _refresh_progress(job)


async def _segment_next(
    job: dict[str, Any], storage: FileStorage, settings: Settings
) -> None:
    target = next(
        (
            image_id
            for image_id in _retained_ids(job)
            if job["images"][image_id]["state"] == "pending_segment"
        ),
        None,
    )
    if target is None:
        job["status"] = "rereading"
        return
    entry = job["images"][target]
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "original.jpg"
        source.write_bytes(await storage.get(entry["key"]))
        destination = Path(tmp) / "corrected.jpg"
        mask = None
        used_sam = False
        if not job["demo_mode"]:
            sam = SamService(settings.model_api_key or "", settings.sam_model)
            try:
                segmented = await sam.segment(
                    source, entry["analysis"]["surface_prompt"]
                )
                if segmented is not None:
                    candidate, confidence = segmented
                    used_sam = confidence is None or confidence >= 0.35
                    if used_sam:
                        mask = candidate
            except Exception:
                mask = None
        if mask is None:
            mask = await asyncio.to_thread(detect_surface_mask_locally, source)
        corrected = mask is not None and await asyncio.to_thread(
            perspective_correct, source, destination, mask
        )
        if corrected:
            key = f"{job['project_id']}/corrected/{target}.jpg"
            url = await storage.put(key, destination.read_bytes(), "image/jpeg")
            entry["corrected_key"] = key
            entry["corrected_url"] = url
            entry["correction_status"] = "corrected" if used_sam else "fallback"
            entry["state"] = "pending_reread" if not job["demo_mode"] else "done"
        else:
            entry["correction_status"] = "failed"
            entry["state"] = "done"
    _refresh_progress(job)


async def _reread_next(
    job: dict[str, Any], storage: FileStorage, settings: Settings
) -> None:
    target = next(
        (
            image_id
            for image_id in _retained_ids(job)
            if job["images"][image_id]["state"] == "pending_reread"
        ),
        None,
    )
    if target is None:
        job["status"] = "synthesizing"
        job["progress"] = 78
        job["message"] = "Compiling the evidence-backed plan"
        return
    entry = job["images"][target]
    muse = _muse(settings, job["demo_mode"])
    assert muse is not None  # pending_reread only happens in live mode
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "corrected.jpg"
        path.write_bytes(await storage.get(entry["corrected_key"]))
        analysis = await asyncio.to_thread(
            muse.analyze_image, target, path, job["goal"]
        )
    entry["analysis"] = analysis.model_dump(mode="json")
    entry["state"] = "done"
    _refresh_progress(job)


async def _synthesize(job: dict[str, Any], settings: Settings) -> None:
    retained = _retained_ids(job)
    analyses = [
        ImageAnalysis(**job["images"][image_id]["analysis"]) for image_id in retained
    ]
    if job["demo_mode"]:
        plan = demo_plan(job["goal"], analyses, job["context_notes"])
    else:
        muse = _muse(settings, False)
        assert muse is not None
        plan = await asyncio.to_thread(
            muse.build_plan,
            job["goal"],
            analyses,
            set(retained),
            job["context_notes"],
        )
    results: list[ImageResult] = []
    for image_id in job["order"]:
        entry = job["images"][image_id]
        results.append(
            ImageResult(
                image_id=image_id,
                filename=entry["filename"],
                original_url=entry["url"],
                corrected_url=entry["corrected_url"],
                duplicate_of=entry["duplicate_of"],
                correction_status=entry["correction_status"],
                analysis=(
                    ImageAnalysis(**entry["analysis"])
                    if entry["analysis"] is not None
                    else None
                ),
            )
        )
    result = ProjectResult(
        project_id=job["project_id"],
        goal=job["goal"],
        context_notes=job["context_notes"],
        plan=plan,
        images=sorted(results, key=lambda item: item.image_id),
        duplicate_count=job["duplicate_count"],
        demo_mode=job["demo_mode"],
    )
    job["plan"] = plan.model_dump(mode="json")
    job["result"] = result.model_dump(mode="json")
    job["status"] = "complete"
    job["progress"] = 100
    job["message"] = "Plan ready"


def hash_to_stored(
    image_id: str, filename: str, path: Path, hash_hex: str, sharpness: float
) -> StoredImage:
    """Rebuild an inspected image from serialized job state (for dedupe reuse)."""
    return StoredImage(
        image_id=image_id,
        filename=filename,
        path=path,
        perceptual_hash=imagehash.hex_to_hash(hash_hex),
        sharpness=sharpness,
    )
