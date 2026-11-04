from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from signalforge.models import CollectionPlan, ImageAnalysis, PlanAction
from signalforge.services.muse import MuseService


class FakeCompletions:
    def __init__(self, parsed: object) -> None:
        self.parsed = parsed
        self.kwargs: dict[str, object] = {}

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=self.parsed))]
        )


def fake_client(parsed: object) -> tuple[SimpleNamespace, FakeCompletions]:
    completions = FakeCompletions(parsed)
    client = SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=completions))
    )
    return client, completions


def test_analyze_image_sends_data_url_and_returns_typed_result(tmp_path: Path) -> None:
    image_path = tmp_path / "slide.jpg"
    Image.new("RGB", (32, 24), "white").save(image_path)
    parsed = ImageAnalysis(
        image_id="model-value",
        content_type="clean_screenshot",
        title="Architecture",
        topic="System design",
        key_points=["A service calls a model."],
        claims=["The diagram contains an API."],
        missing_context=[],
        relevance_score=0.9,
        surface_prompt="none",
        evidence_note="Visible in the screenshot.",
    )
    service = MuseService("test-key", "muse-spark-1.3")
    service.client, completions = fake_client(parsed)

    result = service.analyze_image("img-01", image_path, "Build the system")

    assert result.image_id == "img-01"
    assert completions.kwargs["model"] == "muse-spark-1.3"
    message = completions.kwargs["messages"][0]  # type: ignore[index]
    image_url = message["content"][1]["image_url"]["url"]  # type: ignore[index]
    assert image_url.startswith("data:image/jpeg;base64,")


def test_build_plan_includes_transcript_and_sanitizes_sources() -> None:
    parsed = CollectionPlan(
        headline="Build brief",
        summary="Summary",
        notes_takeaways=["Validate the output with a human."],
        now=[
            PlanAction(
                title="Start",
                description="Begin implementation.",
                evidence_ids=["invalid"],
                support="supported",
            )
        ],
    )
    service = MuseService("test-key", "muse-spark-1.3")
    service.client, completions = fake_client(parsed)

    result = service.build_plan(
        "Build the system",
        [],
        {"img-01"},
        "The speaker asked for human verification.",
    )

    assert result.now[0].evidence_ids == []
    assert result.now[0].support == "inference"
    prompt = completions.kwargs["messages"][0]["content"]  # type: ignore[index]
    assert "human verification" in prompt
    assert completions.kwargs["response_format"] is CollectionPlan
