import asyncio
import json
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest
from PIL import Image
from starlette.requests import Request

import signalforge.main as main
from signalforge.config import Settings
from signalforge.main import DriveImport, create_v2_project, import_drive
from signalforge.services import drive
from signalforge.services.drive import (
    DriveError,
    download_file,
    export_text,
    is_exportable,
    is_image,
    list_folder_files,
    parse_folder_id,
)


def test_parse_folder_id() -> None:
    assert parse_folder_id("https://drive.google.com/drive/folders/abcDEF123-_") == "abcDEF123-_"
    assert parse_folder_id("https://drive.google.com/drive/u/0/folders/abcDEF123-_?x=1") == "abcDEF123-_"
    assert parse_folder_id("https://drive.google.com/open?id=abcDEF123-_") == "abcDEF123-_"
    assert parse_folder_id("abcDEF123-_") == "abcDEF123-_"
    with pytest.raises(DriveError):
        parse_folder_id("https://example.com/nope")
    with pytest.raises(DriveError):
        parse_folder_id("short")


def test_mime_classifiers() -> None:
    assert is_image("image/png") is True
    assert is_image("application/pdf") is False
    assert is_exportable("application/vnd.google-apps.document") is True
    assert is_exportable("application/vnd.google-apps.spreadsheet") is True
    assert is_exportable("image/png") is False


class StubResponse:
    def __init__(self, data: bytes) -> None:
        self._stream = BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


def test_list_folder_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []
    pages = [
        {"files": [{"id": "a", "name": "a"}], "nextPageToken": "tok"},
        {"files": [{"id": "b", "name": "b"}]},
    ]

    def fake_urlopen(url, timeout=None):
        urls.append(url)
        return StubResponse(json.dumps(pages.pop(0)).encode())

    monkeypatch.setattr(drive, "urlopen", fake_urlopen)
    files = list_folder_files("key", "folderABCDEF1234")
    assert [item["id"] for item in files] == ["a", "b"]
    assert "folders" not in urls[0]
    assert "in+parents" in urls[0] or "in parents" in urls[0]
    assert "pageToken=tok" in urls[1]


def test_list_folder_http_error_maps_to_drive_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(url, timeout=None):
        raise HTTPError(url, 404, "Not Found", {}, BytesIO(b"{}"))

    monkeypatch.setattr(drive, "urlopen", fake_urlopen)
    with pytest.raises(DriveError, match="link sharing is on"):
        list_folder_files("key", "folderABCDEF1234")


def test_download_enforces_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(url, timeout=None):
        return StubResponse(b"x" * 100)

    monkeypatch.setattr(drive, "urlopen", fake_urlopen)
    assert download_file("key", "f1", 200) == b"x" * 100
    with pytest.raises(DriveError, match="20 MB"):
        download_file("key", "f1", 10)


def test_export_uses_mime_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []

    def fake_urlopen(url, timeout=None):
        urls.append(url)
        return StubResponse("hello".encode())

    monkeypatch.setattr(drive, "urlopen", fake_urlopen)
    assert export_text("key", "d1", "application/vnd.google-apps.document") == "hello"
    assert "mimeType=text%2Fplain" in urls[0]
    export_text("key", "s1", "application/vnd.google-apps.spreadsheet")
    assert "mimeType=text%2Fcsv" in urls[1]
    with pytest.raises(DriveError):
        export_text("key", "x", "application/pdf")


def make_slide_bytes() -> bytes:
    image = Image.new("RGB", (400, 300), "white")
    buffer = BytesIO()
    image.save(buffer, "JPEG")
    return buffer.getvalue()


def req() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


def test_import_endpoint_adds_images_and_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        created = await create_v2_project(req(), main.ProjectCreate(goal="Ship a slide assistant"))
        project_id = created["project_id"]
        payload = await import_drive(
            project_id, req(), DriveImport(drive_url="https://drive.google.com/drive/folders/folderABCDEF1234")
        )
        assert payload["added_images"] == 1
        assert payload["added_notes"] == 1
        assert payload["skipped_large"] == 1
        assert payload["count"] == 1
        job = await main._v2_store().read(project_id)
        assert "## Talk notes" in job["context_notes"]

    settings = Settings(
        _env_file=None, data_dir=tmp_path, google_api_key="test-key"
    )
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(
        drive,
        "list_folder_files",
        lambda *args, **kwargs: [
            {"id": "img1", "name": "slide.png", "mimeType": "image/png", "size": "999"},
            {"id": "big1", "name": "huge.tiff", "mimeType": "image/tiff", "size": str(30 * 1024 * 1024)},
            {"id": "doc1", "name": "Talk notes", "mimeType": "application/vnd.google-apps.document"},
        ],
    )
    monkeypatch.setattr(drive, "download_file", lambda *args, **kwargs: make_slide_bytes())
    monkeypatch.setattr(drive, "export_text", lambda *args, **kwargs: "remember the demo")
    asyncio.run(run())


def test_import_endpoint_validates_link_and_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        created = await create_v2_project(req(), main.ProjectCreate(goal="Ship a slide assistant"))
        project_id = created["project_id"]
        with pytest.raises(Exception) as bad_link:
            await import_drive(project_id, req(), DriveImport(drive_url="https://example.com/nope____"))
        assert bad_link.value.status_code == 400

    monkeypatch.setattr(
        main, "settings", Settings(_env_file=None, data_dir=tmp_path, google_api_key="k")
    )
    asyncio.run(run())

    async def run_unconfigured() -> None:
        created = await create_v2_project(req(), main.ProjectCreate(goal="Ship a slide assistant"))
        with pytest.raises(Exception) as missing_key:
            await import_drive(
                created["project_id"], req(), DriveImport(drive_url="folderABCDEF1234")
            )
        assert missing_key.value.status_code == 400

    monkeypatch.setattr(main, "settings", Settings(_env_file=None, data_dir=tmp_path))
    asyncio.run(run_unconfigured())
