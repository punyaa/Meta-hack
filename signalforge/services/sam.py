from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

import numpy as np
from meta_sam_parser import (
    SegmentationMaskRecord,
    decode_mask_to_raster,
    image_segmentation_format,
    parse_responses_stream,
)
from openai import AsyncOpenAI


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


class SamService:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = AsyncOpenAI(base_url="https://api.meta.ai/v1", api_key=api_key)
        self.model = model

    async def segment(self, path: Path, prompt: str) -> tuple[np.ndarray, float | None] | None:
        events = await self.client.responses.create(
            model=self.model,
            input=[
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": _data_url(path)},
                    ],
                }
            ],
            stream=True,
            metadata={"mask_encoding": "one_bit", "include_confidence": "true"},
        )
        parsed = parse_responses_stream(events, image_segmentation_format())
        result = await parsed.final_result()
        records = [record for record in result.records if isinstance(record, SegmentationMaskRecord)]
        if not records:
            return None

        candidates: list[tuple[np.ndarray, float | None]] = []
        for record in records:
            raster = np.frombuffer(decode_mask_to_raster(record.mask), dtype=np.uint8)
            raster = raster.reshape((record.mask.height, record.mask.width))
            candidates.append((raster, record.confidence))
        return max(
            candidates,
            key=lambda item: ((item[1] if item[1] is not None else 0.0), int(item[0].sum())),
        )

