from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from signalforge.config import Settings
from signalforge.models import ImageResult, ProjectResult
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


ProgressCallback = Callable[[str, int], None]


async def process_project(
    project_id: str,
    goal: str,
    context_notes: str,
    originals: list[tuple[str, str, Path]],
    settings: Settings,
    progress: ProgressCallback,
) -> ProjectResult:
    progress("Finding duplicate shots", 8)
    inspected: list[StoredImage] = await asyncio.gather(
        *(asyncio.to_thread(inspect_image, image_id, filename, path) for image_id, filename, path in originals)
    )
    duplicate_map = deduplicate(inspected)
    retained = [image for image in inspected if image.image_id not in duplicate_map]

    muse = None if settings.demo_mode else MuseService(settings.model_api_key or "", settings.muse_model)
    sam = None if settings.demo_mode else SamService(settings.model_api_key or "", settings.sam_model)
    corrected_dir = settings.data_dir / project_id / "corrected"
    corrected_dir.mkdir(parents=True, exist_ok=True)

    analyses = []
    results: list[ImageResult] = []
    retained_lookup = {image.image_id: image for image in retained}

    for index, image in enumerate(retained, start=1):
        progress(f"Reading {index} of {len(retained)} retained images", 12 + int(index / len(retained) * 55))
        if muse is None:
            analysis = demo_analysis(image.image_id, image.filename, goal)
        else:
            analysis = await asyncio.to_thread(muse.analyze_image, image.image_id, image.path, goal)

        corrected_path = corrected_dir / f"{image.image_id}.jpg"
        corrected_url = None
        correction_status = "not_needed"
        should_correct = analysis.surface_prompt != "none"

        if should_correct:
            mask = None
            used_sam = False
            if sam is not None:
                try:
                    segmented = await sam.segment(image.path, analysis.surface_prompt)
                    if segmented is not None:
                        mask, confidence = segmented
                        used_sam = confidence is None or confidence >= 0.35
                        if not used_sam:
                            mask = None
                except Exception:
                    mask = None
            if mask is None:
                mask = await asyncio.to_thread(detect_surface_mask_locally, image.path)

            if mask is not None and await asyncio.to_thread(
                perspective_correct, image.path, corrected_path, mask
            ):
                corrected_url = f"/runs/{project_id}/corrected/{corrected_path.name}"
                correction_status = "corrected" if used_sam else "fallback"
                if muse is not None:
                    analysis = await asyncio.to_thread(
                        muse.analyze_image, image.image_id, corrected_path, goal
                    )
            else:
                correction_status = "failed"

        analyses.append(analysis)
        results.append(
            ImageResult(
                image_id=image.image_id,
                filename=image.filename,
                original_url=f"/runs/{project_id}/originals/{image.path.name}",
                corrected_url=corrected_url,
                correction_status=correction_status,
                analysis=analysis,
            )
        )

    for duplicate_id, retained_id in duplicate_map.items():
        image = next(item for item in inspected if item.image_id == duplicate_id)
        results.append(
            ImageResult(
                image_id=image.image_id,
                filename=image.filename,
                original_url=f"/runs/{project_id}/originals/{image.path.name}",
                duplicate_of=retained_id,
                correction_status="not_needed",
            )
        )

    progress("Compiling the evidence-backed plan", 78)
    if muse is None:
        plan = demo_plan(goal, analyses, context_notes)
    else:
        plan = await asyncio.to_thread(
            muse.build_plan,
            goal,
            analyses,
            set(retained_lookup),
            context_notes,
        )

    progress("Plan ready", 100)
    return ProjectResult(
        project_id=project_id,
        goal=goal,
        context_notes=context_notes,
        plan=plan,
        images=sorted(results, key=lambda item: item.image_id),
        duplicate_count=len(duplicate_map),
        demo_mode=settings.demo_mode,
    )

