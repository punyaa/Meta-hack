from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from openai import OpenAI

from signalforge.models import CollectionPlan, ImageAnalysis


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


class MuseService:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = OpenAI(base_url="https://api.meta.ai/v1", api_key=api_key)
        self.model = model

    def analyze_image(self, image_id: str, path: Path, goal: str) -> ImageAnalysis:
        prompt = f"""
You are analyzing one image in a collection of technical slide photos and screenshots.
The user's goal is: {goal}

Read only what is visible. Do not invent missing text. Determine whether this is a
projected slide, whiteboard, clean screenshot, document, or unrelated image. Extract
the ideas that matter to the goal. Claims must be short statements supported by this
specific image. If the image is a photographed screen or board, choose the concrete
SAM prompt "projection screen" or "whiteboard"; otherwise choose "none".

Use image_id exactly as supplied: {image_id}
""".strip()
        completion = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": _data_url(path)}},
                    ],
                }
            ],
            response_format=ImageAnalysis,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("Muse returned no structured image analysis")
        parsed.image_id = image_id
        return parsed

    def build_plan(
        self,
        goal: str,
        analyses: list[ImageAnalysis],
        valid_image_ids: set[str],
        context_notes: str = "",
    ) -> CollectionPlan:
        evidence = "\n".join(analysis.model_dump_json() for analysis in analyses)
        notes = context_notes.strip() or "No notes or transcript were supplied."
        prompt = f"""
Create a concise editorial report and build blueprint for this goal:
{goal}

The JSON lines below are grounded analyses of the user's images:
{evidence}

The user also supplied these notes or transcript. Treat them as context, not visual
evidence, and summarize their useful takeaways separately:
{notes}

Rules:
- Write a strong headline and a short magazine-style standfirst in summary.
- Identify the most important themes and link each visual theme to image evidence.
- Put lessons found only in the notes or transcript in notes_takeaways.
- Create a build blueprint with a problem statement, target user, MVP scope,
  architecture, backlog, and one concrete first task.
- Use now/next/later as a real sequence, not generic advice.
- Every evidence_id must come from this exact allowed set: {sorted(valid_image_ids)}.
- Mark an action "supported" only when the supplied analysis directly supports it.
- Mark synthesis across images as "partial" and new recommendations as "inference".
- Put absent information in missing instead of inventing it.
- Report genuine disagreements in conflicts; do not manufacture a conflict.
- Keep the output useful for a three-minute demo.
""".strip()
        completion = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format=CollectionPlan,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("Muse returned no structured collection plan")
        return _remove_invalid_evidence(parsed, valid_image_ids)


def _remove_invalid_evidence(plan: CollectionPlan, valid_ids: set[str]) -> CollectionPlan:
    actions = [*plan.now, *plan.next, *plan.later, *plan.blueprint.backlog]
    if plan.blueprint.first_task is not None:
        actions.append(plan.blueprint.first_task)
    for action in actions:
        action.evidence_ids = [value for value in action.evidence_ids if value in valid_ids]
        if not action.evidence_ids and action.support == "supported":
            action.support = "inference"
    for theme in plan.themes:
        theme.evidence_ids = [value for value in theme.evidence_ids if value in valid_ids]
        if not theme.evidence_ids and theme.support == "supported":
            theme.support = "inference"
    for conflict in plan.conflicts:
        conflict.evidence_ids = [value for value in conflict.evidence_ids if value in valid_ids]
    return plan

