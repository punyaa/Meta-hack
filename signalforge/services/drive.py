from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

API_BASE = "https://www.googleapis.com/drive/v3"
REQUEST_TIMEOUT = 25
_CHUNK = 64 * 1024


class DriveError(Exception):
    pass


_FOLDER_PATH_RE = re.compile(r"/drive/(?:u/\d+/)?folders/([A-Za-z0-9_-]+)")
_ID_PARAM_RE = re.compile(r"[?&]id=([A-Za-z0-9_-]{10,})")
_BARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")

DOC_EXPORTS = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
}


def parse_folder_id(link: str) -> str:
    link = (link or "").strip()
    match = _FOLDER_PATH_RE.search(link) or _ID_PARAM_RE.search(link)
    if match:
        return match.group(1)
    if _BARE_ID_RE.match(link):
        return link
    raise DriveError("That doesn't look like a Google Drive folder link.")


def is_image(mime_type: str) -> bool:
    return (mime_type or "").startswith("image/")


def is_exportable(mime_type: str) -> bool:
    return mime_type in DOC_EXPORTS


def _describe_http_error(error: HTTPError) -> str:
    if error.code == 404:
        return "Drive folder or file not found. Make sure link sharing is on (Anyone with the link)."
    if error.code == 403:
        return "Drive request was denied. Check the API key and that the Drive API is enabled."
    if error.code == 400:
        return "Drive rejected the request. Check the API key."
    return f"Drive request failed (HTTP {error.code})."


def _request_json(url: str) -> dict:
    try:
        with urlopen(url, timeout=REQUEST_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise DriveError(_describe_http_error(error)) from error
    except (URLError, TimeoutError, ValueError) as error:
        raise DriveError(f"Could not reach Google Drive: {error}") from error


def _request_bytes(url: str, max_bytes: int) -> bytes:
    try:
        with urlopen(url, timeout=REQUEST_TIMEOUT) as response:
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise DriveError("File is larger than the 20 MB import limit.")
                chunks.append(chunk)
            return b"".join(chunks)
    except HTTPError as error:
        raise DriveError(_describe_http_error(error)) from error
    except (URLError, TimeoutError) as error:
        raise DriveError(f"Could not reach Google Drive: {error}") from error


def list_folder_files(
    api_key: str, folder_id: str, page_size: int = 100, max_pages: int = 5
) -> list[dict]:
    if not _BARE_ID_RE.match(folder_id):
        raise DriveError("Invalid Drive folder id.")
    files: list[dict] = []
    page_token: str | None = None
    for _ in range(max_pages):
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,size)",
            "pageSize": page_size,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        payload = _request_json(f"{API_BASE}/files?{urlencode(params)}")
        files.extend(payload.get("files", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return files


def download_file(api_key: str, file_id: str, max_bytes: int) -> bytes:
    params = {"alt": "media", "key": api_key}
    return _request_bytes(f"{API_BASE}/files/{file_id}?{urlencode(params)}", max_bytes)


def export_text(api_key: str, file_id: str, mime_type: str) -> str:
    export_mime = DOC_EXPORTS.get(mime_type)
    if export_mime is None:
        raise DriveError(f"Cannot export {mime_type} as text.")
    params = {"mimeType": export_mime, "key": api_key}
    raw = _request_bytes(f"{API_BASE}/files/{file_id}/export?{urlencode(params)}", 2 * 1024 * 1024)
    return raw.decode("utf-8", errors="replace")
