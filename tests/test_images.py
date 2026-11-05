from pathlib import Path

import cv2
import imagehash
import numpy as np

from signalforge.services.images import (
    StoredImage,
    deduplicate,
    perspective_correct,
    quadrilateral_from_mask,
    resize_mask,
)
from signalforge.services.capture import assess_capture


def test_quadrilateral_from_mask_finds_screen() -> None:
    mask = np.zeros((600, 800), dtype=np.uint8)
    polygon = np.array([[120, 90], [690, 120], [650, 510], [90, 470]], dtype=np.int32)
    cv2.fillConvexPoly(mask, polygon, 255)

    points = quadrilateral_from_mask(mask)

    assert points is not None
    assert points.shape == (4, 2)


def test_perspective_correct_writes_output(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    destination = tmp_path / "corrected.jpg"
    image = np.full((600, 800, 3), 25, dtype=np.uint8)
    polygon = np.array([[120, 90], [690, 120], [650, 510], [90, 470]], dtype=np.int32)
    cv2.fillConvexPoly(image, polygon, (235, 235, 235))
    cv2.imwrite(str(source), image)

    mask = np.zeros((600, 800), dtype=np.uint8)
    cv2.fillConvexPoly(mask, polygon, 255)

    assert perspective_correct(source, destination, mask)
    assert destination.exists()


def test_quadrilateral_rejects_tiny_surface() -> None:
    mask = np.zeros((600, 800), dtype=np.uint8)
    cv2.rectangle(mask, (10, 10), (40, 40), 255, -1)

    assert quadrilateral_from_mask(mask) is None


def test_resize_mask_returns_binary_target_size() -> None:
    mask = np.array([[0, 1], [1, 0]], dtype=np.uint8)

    resized = resize_mask(mask, 8, 6)

    assert resized.shape == (6, 8)
    assert set(np.unique(resized)) == {0, 255}


def test_deduplicate_prefers_sharper_capture(tmp_path: Path) -> None:
    same_hash = imagehash.ImageHash(np.zeros((8, 8), dtype=bool))
    soft = StoredImage("img-01", "soft.jpg", tmp_path / "soft.jpg", same_hash, 12.0)
    sharp = StoredImage("img-02", "sharp.jpg", tmp_path / "sharp.jpg", same_hash, 88.0)

    assert deduplicate([soft, sharp]) == {"img-01": "img-02"}


def test_capture_coach_marks_clean_centered_screen_ready() -> None:
    image = np.zeros((600, 800, 3), dtype=np.uint8)
    cv2.rectangle(image, (120, 100), (680, 500), (180, 180, 180), -1)
    cv2.putText(image, "SIGNAL", (250, 320), cv2.FONT_HERSHEY_SIMPLEX, 2, (20, 20, 20), 5)
    mask = np.zeros((600, 800), dtype=np.uint8)
    cv2.rectangle(mask, (120, 100), (680, 500), 255, -1)

    result = assess_capture(image, mask)

    assert result["ready"] is True
    assert result["guidance"] == "Ready — capture now"
    assert len(result["polygon"]) == 4


def test_capture_coach_asks_user_to_move_closer() -> None:
    image = np.full((600, 800, 3), 90, dtype=np.uint8)
    mask = np.zeros((600, 800), dtype=np.uint8)
    cv2.rectangle(mask, (300, 240), (500, 360), 255, -1)

    result = assess_capture(image, mask)

    assert result["ready"] is False
    assert result["guidance"] in {"Move closer", "Move closer to the screen"}

