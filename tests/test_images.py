from pathlib import Path

import cv2
import numpy as np

from signalforge.services.images import perspective_correct, quadrilateral_from_mask


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

