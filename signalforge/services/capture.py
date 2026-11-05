from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

from signalforge.services.images import quadrilateral_from_mask, resize_mask


@dataclass(frozen=True)
class CaptureMetrics:
    coverage: float
    centered: float
    perspective: float
    sharpness: float
    glare: float
    brightness: float


def _edge_length(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.linalg.norm(first - second))


def _balance(first: float, second: float) -> float:
    largest = max(first, second, 1.0)
    return min(first, second) / largest


def assess_capture(image: np.ndarray, mask: np.ndarray | None) -> dict[str, object]:
    """Turn a surface mask into simple, stable camera guidance.

    SAM supplies the mask. These deterministic measurements decide whether the
    user should reframe, reduce glare, or hold still before taking the photo.
    """
    height, width = image.shape[:2]
    if mask is None:
        return {
            "ready": False,
            "score": 0,
            "guidance": "Point the camera at the presentation screen",
            "detail": "Keep the entire screen visible inside the frame.",
            "polygon": [],
            "metrics": None,
        }

    binary = resize_mask(mask, width, height)
    corners = quadrilateral_from_mask(binary)
    if corners is None:
        return {
            "ready": False,
            "score": 12,
            "guidance": "Move closer to the screen",
            "detail": "SignalForge can see a surface, but it is too small to guide reliably.",
            "polygon": [],
            "metrics": None,
        }

    top_left, top_right, bottom_right, bottom_left = corners
    coverage = float(np.count_nonzero(binary)) / float(width * height)
    center = corners.mean(axis=0)
    center_x = float(center[0] / width)
    center_y = float(center[1] / height)
    centered = max(0.0, 1.0 - (abs(center_x - 0.5) + abs(center_y - 0.5)) * 1.8)

    horizontal_balance = _balance(
        _edge_length(top_left, top_right),
        _edge_length(bottom_left, bottom_right),
    )
    vertical_balance = _balance(
        _edge_length(top_left, bottom_left),
        _edge_length(top_right, bottom_right),
    )
    perspective = min(horizontal_balance, vertical_balance)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    selected = binary > 0
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    glare = float(np.mean(gray[selected] >= 245)) if np.any(selected) else 0.0
    brightness = float(np.mean(gray[selected]) / 255.0) if np.any(selected) else 0.0

    margin_x = width * 0.025
    margin_y = height * 0.025
    clipped = bool(
        np.any(corners[:, 0] <= margin_x)
        or np.any(corners[:, 0] >= width - margin_x)
        or np.any(corners[:, 1] <= margin_y)
        or np.any(corners[:, 1] >= height - margin_y)
    )

    if clipped or coverage > 0.88:
        guidance = "Step back slightly"
        detail = "Keep every edge of the screen inside the guide."
    elif coverage < 0.20:
        guidance = "Move closer"
        detail = "Let the screen fill more of the frame."
    elif center_x < 0.42:
        guidance = "Aim slightly left"
        detail = "Center the screen inside the frame."
    elif center_x > 0.58:
        guidance = "Aim slightly right"
        detail = "Center the screen inside the frame."
    elif center_y < 0.40:
        guidance = "Aim slightly up"
        detail = "Center the screen inside the frame."
    elif center_y > 0.62:
        guidance = "Aim slightly down"
        detail = "Center the screen inside the frame."
    elif perspective < 0.70:
        guidance = "Move more squarely in front"
        detail = "Reduce the side angle so both edges look similar."
    elif glare > 0.14:
        guidance = "Change the angle to reduce glare"
        detail = "A small sideways movement should recover hidden details."
    elif brightness < 0.20:
        guidance = "Find a brighter position"
        detail = "The screen is too dark for a reliable capture."
    elif sharpness < 65:
        guidance = "Hold steady"
        detail = "Pause briefly so the text stays sharp."
    else:
        guidance = "Ready — capture now"
        detail = "The screen is centered, clear, and fully visible."

    ready = guidance.startswith("Ready")
    coverage_score = max(0.0, 1.0 - abs(coverage - 0.55) / 0.55)
    sharpness_score = min(1.0, sharpness / 140.0)
    glare_score = max(0.0, 1.0 - glare / 0.25)
    score = round(
        100
        * (
            coverage_score * 0.23
            + centered * 0.22
            + perspective * 0.25
            + sharpness_score * 0.18
            + glare_score * 0.12
        )
    )
    metrics = CaptureMetrics(
        coverage=round(coverage, 3),
        centered=round(centered, 3),
        perspective=round(perspective, 3),
        sharpness=round(sharpness, 1),
        glare=round(glare, 3),
        brightness=round(brightness, 3),
    )
    polygon = [
        {"x": round(float(point[0] / width), 4), "y": round(float(point[1] / height), 4)}
        for point in corners
    ]
    return {
        "ready": ready,
        "score": min(100, max(0, score)),
        "guidance": guidance,
        "detail": detail,
        "polygon": polygon,
        "metrics": asdict(metrics),
    }
