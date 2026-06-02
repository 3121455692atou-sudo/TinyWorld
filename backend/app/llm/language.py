from __future__ import annotations

import re
from typing import Any

from app.core.models import Location, World

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")

DEFAULT_LOCATION_EN: dict[str, str] = {
    "central_square": "Central Square",
    "cafeteria": "Cafeteria",
    "cabin": "Forest Cabin",
    "library": "Library",
    "lake": "Lakeside",
    "workshop": "Workshop",
    "medical_room": "Medical Room",
    "garden": "Garden",
    "market": "Market",
    "hot_spring_lobby": "Hot Spring Lobby",
    "hot_spring_men": "Men's Bath",
    "hot_spring_women": "Women's Bath",
    "hot_spring_mixed": "Mixed Hot Spring",
    "campfire": "Campfire Camp",
    "notice_board": "Notice Board",
    "jail": "Temporary Jail",
}

DEFAULT_ITEM_EN: dict[str, str] = {
    "水": "water",
    "简餐": "simple meal",
    "野果": "wild fruit",
    "草药": "herbs",
    "木料": "wood",
    "布料": "cloth",
    "工具箱": "toolbox",
    "空白笔记本": "blank notebook",
    "旧书": "old book",
    "木柴": "firewood",
    "手作小物": "handmade trinket",
}

GENDER_EN: dict[str, str] = {
    "女": "female",
    "男": "male",
    "非二元": "nonbinary",
    "无性别": "agender",
    "不愿公开": "private",
    "自定义": "custom",
    "未知": "unknown",
    "中性": "androgynous",
    "女性化": "feminine",
    "男性化": "masculine",
    "难以判断": "hard to read",
}

MOOD_EN: dict[str, str] = {
    "崩溃": "broken",
    "痛苦": "in pain",
    "低落": "low",
    "平静": "calm",
    "不错": "okay",
    "开心": "happy",
    "振奋": "uplifted",
}


def normalize_language(value: Any) -> str:
    return "en" if str(value or "").lower().startswith("en") else "zh"


def world_language(world: World | None) -> str:
    settings = world.settings_json if world and isinstance(world.settings_json, dict) else {}
    return normalize_language(settings.get("language"))


def output_language_name(language: str) -> str:
    return "English" if normalize_language(language) == "en" else "Simplified Chinese"


def contains_cjk(value: Any) -> bool:
    return bool(_CJK_RE.search(str(value or "")))


def cjk_count(value: Any) -> int:
    return len(_CJK_RE.findall(str(value or "")))


def action_language_instruction(language: str) -> str:
    if normalize_language(language) == "en":
        return (
            "All free text after the action header must be natural English. "
            "If the action requires speech, write only first-person spoken English words from this character's mouth; "
            "do not include narration, stage directions, thoughts, Chinese quotation marks, or third-person description."
        )
    return (
        "第二行之后必须写自然中文正文。若行动需要台词，只能写这个角色第一人称亲口说出的话；"
        "不要夹旁白、动作描写、心理描写、舞台指示或第三人称叙述。"
    )


def identity_language_instruction(language: str) -> str:
    if normalize_language(language) == "en":
        return (
            "Use English for NAME, LOOK_FULL, LOOK_SHORT, speaking style, personality seed, and initial goal. "
            "The name should be an English name or nickname, not a Chinese-style name."
        )
    return "姓名使用中文或中文风格昵称，LOOK_FULL、LOOK_SHORT、说话风格、人格种子和初始目标都使用中文。"


def narrator_language_instruction(language: str) -> str:
    if normalize_language(language) == "en":
        return "Write all narrator titles, narration text, and daily summaries in natural English."
    return "所有解说标题、旁白和每日总结都使用自然中文。"


def person_ref_label(ref: str, language: str = "zh") -> str:
    ref = str(ref or "")
    if normalize_language(language) != "en":
        return ref
    # Default Chinese refs are 附近人物A / 附近人物1. Convert them to stable English refs.
    m = re.search(r"([A-Z])$", ref)
    if m:
        return f"Person {m.group(1)}"
    m = re.search(r"(\d+)$", ref)
    if m:
        return f"Person {m.group(1)}"
    if ref.lower().startswith("person"):
        return ref
    return "Person"


def corpse_ref_label(ref: str, language: str = "zh") -> str:
    ref = str(ref or "")
    if normalize_language(language) != "en":
        return ref
    m = re.search(r"([A-Z])$", ref)
    if m:
        return f"Corpse {m.group(1)}"
    m = re.search(r"(\d+)$", ref)
    if m:
        return f"Corpse {m.group(1)}"
    return "Corpse"


def location_label(location: Location | None, language: str = "zh") -> str:
    if not location:
        return "Unknown location" if normalize_language(language) == "en" else "未知地点"
    if normalize_language(language) != "en":
        return location.public_name
    key = str(location.location_id or "").split(":", 1)[-1]
    if key.startswith("private_cabin_"):
        suffix = key.rsplit("_", 1)[-1]
        return f"Private Cabin {suffix}"
    if key.startswith("home_"):
        return f"Private Home {key.rsplit('_', 1)[-1]}"
    if key in DEFAULT_LOCATION_EN:
        return DEFAULT_LOCATION_EN[key]
    return english_safe_label(location.public_name or key, fallback=_title_from_id(key))


def item_label(name: str, language: str = "zh") -> str:
    name = str(name or "")
    if normalize_language(language) != "en":
        return name
    return DEFAULT_ITEM_EN.get(name, english_safe_label(name, fallback="item"))


def gender_label(value: str | None, language: str = "zh") -> str:
    value = str(value or "未知")
    if normalize_language(language) != "en":
        return value
    return GENDER_EN.get(value, english_safe_label(value, fallback="unknown"))


def mood_label_text(value: str | None, language: str = "zh") -> str:
    value = str(value or "")
    if normalize_language(language) != "en":
        return value
    return MOOD_EN.get(value, english_safe_label(value, fallback="neutral"))


def english_safe_label(value: Any, *, fallback: str = "unknown") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if not contains_cjk(text):
        return text
    # Replace CJK runs with a readable placeholder instead of leaking mixed Chinese into English prompts.
    cleaned = _CJK_RUN_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:，。；：、")
    return cleaned or fallback


def english_safe_sentence(value: Any, *, fallback: str = "No additional detail.") -> str:
    text = str(value or "").replace("\r", "\n").strip()
    if not text:
        return fallback
    if not contains_cjk(text):
        return text
    # Do not pass opaque Chinese world/event text into an English LLM prompt. Keep a factual placeholder.
    return fallback


def remove_cjk(value: Any, *, placeholder: str = "") -> str:
    text = _CJK_RUN_RE.sub(placeholder, str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _title_from_id(raw: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", " ", str(raw or "")).strip()
    return text.title() if text else "Location"
