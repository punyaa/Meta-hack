from signalforge.models import (
    BuildBlueprint,
    CollectionPlan,
    PlanAction,
    ThemeInsight,
)
from signalforge.services.muse import _remove_invalid_evidence


def action(*ids: str, support: str = "supported") -> PlanAction:
    return PlanAction(
        title="Test action",
        description="Test description",
        evidence_ids=list(ids),
        support=support,
    )


def test_invalid_evidence_is_removed_from_entire_report() -> None:
    plan = CollectionPlan(
        headline="Report",
        summary="Summary",
        themes=[
            ThemeInsight(
                title="Theme",
                insight="Insight",
                evidence_ids=["img-01", "missing"],
                support="supported",
            )
        ],
        blueprint=BuildBlueprint(
            backlog=[action("missing")],
            first_task=action("img-01", "missing"),
        ),
        now=[action("missing")],
    )

    cleaned = _remove_invalid_evidence(plan, {"img-01"})

    assert cleaned.themes[0].evidence_ids == ["img-01"]
    assert cleaned.blueprint.backlog[0].evidence_ids == []
    assert cleaned.blueprint.backlog[0].support == "inference"
    assert cleaned.blueprint.first_task is not None
    assert cleaned.blueprint.first_task.evidence_ids == ["img-01"]
    assert cleaned.now[0].support == "inference"


def test_partial_action_can_exist_without_visual_evidence() -> None:
    plan = CollectionPlan(
        headline="Report",
        summary="Summary",
        now=[action("missing", support="partial")],
    )

    cleaned = _remove_invalid_evidence(plan, set())

    assert cleaned.now[0].evidence_ids == []
    assert cleaned.now[0].support == "partial"
