from typing import Literal

from pydantic import BaseModel, Field


ContentType = Literal[
    "projected_slide",
    "whiteboard",
    "clean_screenshot",
    "document",
    "unrelated",
]


class ImageAnalysis(BaseModel):
    image_id: str
    content_type: ContentType
    title: str
    topic: str
    key_points: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    code_summary: str = ""
    missing_context: list[str] = Field(default_factory=list)
    relevance_score: float = Field(ge=0, le=1)
    surface_prompt: Literal["projection screen", "whiteboard", "none"]
    evidence_note: str


SupportStatus = Literal["supported", "partial", "inference"]


class PlanAction(BaseModel):
    title: str
    description: str
    evidence_ids: list[str] = Field(default_factory=list)
    support: SupportStatus


class Conflict(BaseModel):
    description: str
    evidence_ids: list[str] = Field(default_factory=list)


class CollectionPlan(BaseModel):
    headline: str
    summary: str
    now: list[PlanAction] = Field(default_factory=list)
    next: list[PlanAction] = Field(default_factory=list)
    later: list[PlanAction] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)


class ImageResult(BaseModel):
    image_id: str
    filename: str
    original_url: str
    corrected_url: str | None = None
    duplicate_of: str | None = None
    correction_status: Literal["corrected", "not_needed", "fallback", "failed"]
    analysis: ImageAnalysis | None = None


class ProjectResult(BaseModel):
    project_id: str
    goal: str
    plan: CollectionPlan
    images: list[ImageResult]
    duplicate_count: int
    demo_mode: bool

