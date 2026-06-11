from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Any

from app.core.config import DATA_DIR


IMAGE_DIR = DATA_DIR / "media" / "images"
_DATA_URL_RE = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.*)$", re.DOTALL)
_SAFE_KEY_RE = re.compile(r"^[a-f0-9]{64}\.[a-z0-9]+$")


def store_image_data_url(data_url: str) -> dict[str, Any]:
    parsed = parse_image_data_url(data_url)
    if not parsed:
        raise ValueError("invalid image data url")
    mime_type, content = parsed
    digest = hashlib.sha256(content).hexdigest()
    extension = _extension_for_mime(mime_type)
    key = f"{digest}.{extension}"
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGE_DIR / key
    if not path.exists():
        path.write_bytes(content)
    return {
        "image_key": key,
        "image_url": image_url_for_key(key),
        "image_mime_type": mime_type,
        "image_size_bytes": len(content),
        "image_sha256": digest,
    }


def image_url_for_key(key: str) -> str:
    return f"/api/storage/images/file/{key}"


def image_path_for_key(key: str) -> Path | None:
    if not _SAFE_KEY_RE.match(key):
        return None
    path = (IMAGE_DIR / key).resolve()
    try:
        path.relative_to(IMAGE_DIR.resolve())
    except ValueError:
        return None
    return path


def image_data_url_for_key(key: str) -> str:
    path = image_path_for_key(key)
    if not path or not path.exists():
        return ""
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def delete_image_file_if_unreferenced(key: str, referenced_keys: set[str]) -> bool:
    if key in referenced_keys:
        return False
    path = image_path_for_key(key)
    if not path or not path.exists():
        return False
    path.unlink()
    return True


def parse_image_data_url(data_url: str) -> tuple[str, bytes] | None:
    match = _DATA_URL_RE.match(data_url.strip())
    if not match:
        return None
    mime_type, encoded = match.groups()
    try:
        return mime_type.lower(), base64.b64decode(encoded, validate=False)
    except Exception:
        return None


def _extension_for_mime(mime_type: str) -> str:
    mapping = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    return mapping.get(mime_type.lower(), "png")
