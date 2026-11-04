import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from signalforge.main import create_project, health


def test_health_exposes_model_configuration() -> None:
    payload = asyncio.run(health())

    assert payload["status"] == "ok"
    assert payload["muse_model"] == "muse-spark-1.3"
    assert payload["sam_model"] == "sam-3.1"


def test_upload_rejects_unsupported_content_type() -> None:
    upload = UploadFile(
        filename="notes.txt",
        file=BytesIO(b"not an image"),
        headers=Headers({"content-type": "text/plain"}),
    )

    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            create_project(
                goal="Build something useful",
                context_notes="",
                files=[upload],
            )
        )

    assert raised.value.status_code == 400
    assert "not a supported image" in str(raised.value.detail)
