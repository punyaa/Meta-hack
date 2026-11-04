from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image, ImageOps


@dataclass(frozen=True)
class StoredImage:
    image_id: str
    filename: str
    path: Path
    perceptual_hash: imagehash.ImageHash
    sharpness: float


def normalize_image(source: Path, destination: Path) -> None:
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((2400, 2400))
        image.save(destination, "JPEG", quality=92, optimize=True)


def inspect_image(image_id: str, filename: str, path: Path) -> StoredImage:
    with Image.open(path) as image:
        perceptual_hash = imagehash.phash(image)

    matrix = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if matrix is None:
        raise ValueError(f"Could not read {filename}")
    sharpness = float(cv2.Laplacian(matrix, cv2.CV_64F).var())
    return StoredImage(image_id, filename, path, perceptual_hash, sharpness)


def deduplicate(images: list[StoredImage], threshold: int = 4) -> dict[str, str]:
    """Return duplicate image id -> retained image id, preferring sharper shots."""
    duplicate_map: dict[str, str] = {}
    groups: list[list[StoredImage]] = []

    for candidate in images:
        group = next(
            (
                existing
                for existing in groups
                if candidate.perceptual_hash - existing[0].perceptual_hash <= threshold
            ),
            None,
        )
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)

    for group in groups:
        retained = max(group, key=lambda image: image.sharpness)
        for image in group:
            if image.image_id != retained.image_id:
                duplicate_map[image.image_id] = retained.image_id
    return duplicate_map


def resize_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    resized = cv2.resize(mask.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST)
    return (resized > 0).astype(np.uint8) * 255


def _order_points(points: np.ndarray) -> np.ndarray:
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(differences)]
    ordered[3] = points[np.argmax(differences)]
    return ordered


def quadrilateral_from_mask(mask: np.ndarray) -> np.ndarray | None:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    contour = max(contours, key=cv2.contourArea)
    image_area = mask.shape[0] * mask.shape[1]
    if cv2.contourArea(contour) < image_area * 0.08:
        return None

    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    for ratio in (0.02, 0.04, 0.06, 0.08):
        polygon = cv2.approxPolyDP(hull, ratio * perimeter, True)
        if len(polygon) == 4:
            return _order_points(polygon.reshape(4, 2).astype(np.float32))

    rectangle = cv2.minAreaRect(hull)
    return _order_points(cv2.boxPoints(rectangle).astype(np.float32))


def perspective_correct(source: Path, destination: Path, mask: np.ndarray) -> bool:
    image = cv2.imread(str(source))
    if image is None:
        return False

    mask = resize_mask(mask, image.shape[1], image.shape[0])
    corners = quadrilateral_from_mask(mask)
    if corners is None:
        return False

    top_left, top_right, bottom_right, bottom_left = corners
    width = int(
        max(
            np.linalg.norm(bottom_right - bottom_left),
            np.linalg.norm(top_right - top_left),
        )
    )
    height = int(
        max(
            np.linalg.norm(top_right - bottom_right),
            np.linalg.norm(top_left - bottom_left),
        )
    )
    if width < 320 or height < 180:
        return False

    target = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(corners, target)
    corrected = cv2.warpPerspective(image, transform, (width, height))

    lab = cv2.cvtColor(corrected, cv2.COLOR_BGR2LAB)
    lightness, channel_a, channel_b = cv2.split(lab)
    lightness = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(lightness)
    corrected = cv2.cvtColor(cv2.merge((lightness, channel_a, channel_b)), cv2.COLOR_LAB2BGR)
    return bool(cv2.imwrite(str(destination), corrected))


def detect_surface_mask_locally(source: Path) -> np.ndarray | None:
    """Best-effort fallback when SAM returns no mask or demo mode is active."""
    image = cv2.imread(str(source))
    if image is None:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 45, 140)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = image.shape[0] * image.shape[1]

    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(contour) < image_area * 0.08:
            break
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.fillConvexPoly(mask, polygon.reshape(4, 2), 255)
        return mask
    return None

