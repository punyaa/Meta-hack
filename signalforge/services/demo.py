from __future__ import annotations

from signalforge.models import CollectionPlan, ImageAnalysis, PlanAction


def demo_analysis(image_id: str, filename: str, goal: str) -> ImageAnalysis:
    readable_name = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
    return ImageAnalysis(
        image_id=image_id,
        content_type="projected_slide",
        title=readable_name.title() or f"Slide {image_id}",
        topic="Technical presentation",
        key_points=[
            "This image has been retained as visual evidence.",
            f"It may contribute to the goal: {goal}",
        ],
        claims=[],
        missing_context=["Demo mode does not read the slide content."],
        relevance_score=0.72,
        surface_prompt="projection screen",
        evidence_note="Demo evidence generated locally; connect MODEL_API_KEY for grounded analysis.",
    )


def demo_plan(goal: str, analyses: list[ImageAnalysis]) -> CollectionPlan:
    ids = [analysis.image_id for analysis in analyses]
    first = ids[:2]
    return CollectionPlan(
        headline="Your visual research has been compiled",
        summary=(
            f"SignalForge organized {len(analyses)} retained images around: {goal}. "
            "Connect the Meta Model API key to replace this demonstration plan with grounded Muse analysis."
        ),
        now=[
            PlanAction(
                title="Review the corrected visual evidence",
                description="Confirm that the retained slide photographs are readable and relevant.",
                evidence_ids=first,
                support="partial",
            )
        ],
        next=[
            PlanAction(
                title="Connect Muse Spark",
                description="Add MODEL_API_KEY so claims, missing context, and actions come from the images.",
                evidence_ids=[],
                support="inference",
            )
        ],
        later=[
            PlanAction(
                title="Validate the plan against its sources",
                description="Open each evidence thumbnail and confirm the associated action.",
                evidence_ids=ids[:3],
                support="partial",
            )
        ],
        missing=["Grounded content analysis is unavailable while demo mode is active."],
        conflicts=[],
    )

