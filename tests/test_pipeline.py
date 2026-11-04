import asyncio
from pathlib import Path

from PIL import Image, ImageDraw

from signalforge.config import Settings
from signalforge.services.pipeline import process_project


def make_slide(path: Path) -> None:
    image = Image.new("RGB", (900, 620), "#1d2228")
    draw = ImageDraw.Draw(image)
    draw.polygon([(110, 90), (790, 115), (760, 540), (85, 505)], fill="#f4f0df")
    draw.text((180, 180), "SignalForge test slide", fill="#262626")
    image.save(path, "JPEG")


def test_demo_pipeline_builds_magazine_report_and_tracks_progress(tmp_path: Path) -> None:
    source_a = tmp_path / "a.jpg"
    source_b = tmp_path / "b.jpg"
    make_slide(source_a)
    source_b.write_bytes(source_a.read_bytes())
    settings = Settings(
        _env_file=None,
        signalforge_demo_mode=True,
        data_dir=tmp_path / "runs",
    )
    progress_events: list[tuple[str, int]] = []

    result = asyncio.run(
        process_project(
            "project-test",
            "Build a useful visual assistant",
            "The speaker emphasized checking every source.",
            [
                ("img-01", "capture-one.jpg", source_a),
                ("img-02", "capture-two.jpg", source_b),
            ],
            settings,
            lambda message, value: progress_events.append((message, value)),
        )
    )

    assert result.demo_mode is True
    assert result.context_notes.startswith("The speaker")
    assert result.duplicate_count == 1
    assert result.plan.themes
    assert result.plan.notes_takeaways
    assert result.plan.blueprint.first_task is not None
    assert progress_events[0][1] == 8
    assert progress_events[-1] == ("Plan ready", 100)
