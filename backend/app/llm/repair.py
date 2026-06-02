from __future__ import annotations

import json
import re
from typing import Any


CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")


def chinese_ratio(text: str) -> float:
    if not text:
        return 0.0
    meaningful = [c for c in text if not c.isspace()]
    if not meaningful:
        return 0.0
    return len(CHINESE_RE.findall(text)) / len(meaningful)


def ensure_chinese(text: str, fallback: str = "我一时不知道该怎么说，只好沉默了一会儿。") -> str:
    if len(text) <= 10 or chinese_ratio(text) >= 0.6:
        return text
    return fallback


def extract_json_object(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def redact_unknown_names(text: str, unauthorized_names: list[str]) -> tuple[str, bool]:
    changed = False
    for name in unauthorized_names:
        if name and name in text:
            text = text.replace(name, "你")
            changed = True
    return text, changed

