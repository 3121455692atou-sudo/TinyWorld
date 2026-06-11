from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Any

from app.core.config import DATA_DIR


AUDIO_DIR = DATA_DIR / "media" / "audio"
_DATA_URL_RE = re.compile(r"^data:(audio/[a-zA-Z0-9.+-]+);base64,(.*)$", re.DOTALL)
_SAFE_KEY_RE = re.compile(r"^[a-f0-9]{64}\.[a-z0-9]+$")


def store_audio_data_url(data_url: str) -> dict[str, Any]:
    parsed = parse_audio_data_url(data_url)
    if not parsed:
        raise ValueError("invalid audio data url")
    mime_type, content = parsed
    digest = hashlib.sha256(content).hexdigest()
    extension = _extension_for_mime(mime_type)
    key = f"{digest}.{extension}"
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIO_DIR / key
    if not path.exists():
        path.write_bytes(content)
    return {
        "tts_audio_key": key,
        "tts_audio_url": audio_url_for_key(key),
        "tts_audio_mime_type": mime_type,
        "tts_audio_size_bytes": len(content),
        "tts_audio_sha256": digest,
    }


def audio_url_for_key(key: str) -> str:
    return f"/api/storage/audio/file/{key}"


def audio_path_for_key(key: str) -> Path | None:
    if not _SAFE_KEY_RE.match(key):
        return None
    path = (AUDIO_DIR / key).resolve()
    try:
        path.relative_to(AUDIO_DIR.resolve())
    except ValueError:
        return None
    return path


def audio_data_url_for_key(key: str) -> str:
    path = audio_path_for_key(key)
    if not path or not path.exists():
        return ""
    mime_type = mimetypes.guess_type(path.name)[0] or "audio/wav"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def parse_audio_data_url(data_url: str) -> tuple[str, bytes] | None:
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
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/ogg": "ogg",
        "audio/webm": "webm",
        "audio/flac": "flac",
    }
    return mapping.get(mime_type.lower(), "wav")
