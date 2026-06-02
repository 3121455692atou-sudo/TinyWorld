from __future__ import annotations

import re
from typing import Any

from app.llm.language import normalize_language
from app.llm.schemas import BabyNameDraft, IdentityDraft, NarrationDraft, TRAIT_NAMES


KEY_ALIASES = {
    "NAME": "NAME",
    "名字": "NAME",
    "姓名": "NAME",
    "GENDER": "GENDER",
    "性别": "GENDER",
    "GENDER_CUSTOM": "GENDER_CUSTOM",
    "GENDER_PUBLIC": "GENDER_PUBLIC",
    "公开性别": "GENDER_PUBLIC",
    "GENDER_EXPR": "GENDER_EXPR",
    "性别表达": "GENDER_EXPR",
    "LOOK_FULL": "LOOK_FULL",
    "完整外貌": "LOOK_FULL",
    "LOOK_SHORT": "LOOK_SHORT",
    "短外貌": "LOOK_SHORT",
    "AVATAR_COLOR": "AVATAR_COLOR",
    "AVATAR_TAGS": "AVATAR_TAGS",
    "SPEAK": "SPEAK",
    "说话风格": "SPEAK",
    "SEED": "SEED",
    "人格种子": "SEED",
    "GOAL": "GOAL",
    "目标": "GOAL",
    "INTRO": "INTRO",
    "介绍策略": "INTRO",
    "TRAITS": "TRAITS",
    "特质": "TRAITS",
    "TITLE": "TITLE",
    "标题": "TITLE",
    "TEXT": "TEXT",
    "正文": "TEXT",
    "TONE": "TONE",
    "语气": "TONE",
    "IMPORTANCE": "IMPORTANCE",
    "重要性": "IMPORTANCE",
    "HIGHLIGHTS": "HIGHLIGHTS",
    "高亮": "HIGHLIGHTS",
}


def parse_field_lines(raw: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in str(raw or "").replace("\r", "\n").split("\n"):
        line = raw_line.strip().strip("` ")
        if not line:
            continue
        match = re.match(r"^([A-Za-z_]+|[\u4e00-\u9fa5]{1,12})\s*[:=：]\s*(.*)$", line)
        if match:
            key = KEY_ALIASES.get(match.group(1).strip(), match.group(1).strip().upper())
            value = match.group(2).strip()
            fields[key] = value
            current_key = key
        elif current_key and current_key in {"LOOK_FULL", "TEXT", "SEED"}:
            fields[current_key] = (fields.get(current_key, "") + "\n" + line).strip()
    return fields


def parse_identity_draft(raw: str, *, forced_name: str | None = None, default_name: str = "旅人", child: bool = False) -> IdentityDraft | None:
    data = parse_field_lines(raw)
    name = (forced_name or data.get("NAME") or default_name).strip()[:12] or default_name
    gender = _normalize_gender(data.get("GENDER") or "不愿公开")
    public = _parse_bool(data.get("GENDER_PUBLIC"), default=True)
    look_full = (data.get("LOOK_FULL") or data.get("LOOK_SHORT") or f"{name}的外貌暂时只留下模糊印象，需要在世界中慢慢变得清晰。").strip()
    if len(look_full) < 20:
        look_full = f"{name}看起来{look_full}，身上有一种刚进入世界时尚未完全安定的气质。"
    look_short = (data.get("LOOK_SHORT") or _first_sentence(look_full))[:120]
    if len(look_short) < 8:
        look_short = f"{name}的轮廓安静而清楚"[:120]
    traits = _parse_traits(data.get("TRAITS") or "")
    avatar_hint = {
        "color": _normalize_color(data.get("AVATAR_COLOR")),
        "tags": _split_list(data.get("AVATAR_TAGS"))[:3],
    }
    try:
        return IdentityDraft(
            chosen_name=name,
            gender_identity=gender,
            gender_custom_text=(data.get("GENDER_CUSTOM") or "")[:120],
            gender_publicity=public,
            gender_expression=(data.get("GENDER_EXPR") or "难以判断")[:80],
            appearance_full=look_full[:4000],
            appearance_short=look_short,
            avatar_hint=avatar_hint,
            speaking_style=(data.get("SPEAK") or "说话自然，按当前情绪和处境表达。")[:120],
            personality_seed=(data.get("SEED") or f"{name}刚来到这个世界，想先理解自己的处境和身边的人。")[:160],
            initial_goal=(data.get("GOAL") or "先照顾自己，并尝试理解这个世界。")[:160],
            intro_policy=_normalize_intro(data.get("INTRO") or "selective"),
            trait_sliders=traits,
        )
    except Exception:
        return None


def parse_baby_name(raw: str, *, fallback: str = "小星") -> BabyNameDraft:
    fields = parse_field_lines(raw)
    name = fields.get("NAME") or _first_nonempty_line(raw) or fallback
    name = _sanitize_name(name) or fallback
    return BabyNameDraft(chosen_name=name[:12])


def parse_narration_draft(raw: str, *, fallback_text: str = "事件继续推进，居民们留下了新的记录。") -> NarrationDraft | None:
    fields = parse_field_lines(raw)
    text = (fields.get("TEXT") or _strip_protocol_noise(raw) or fallback_text).strip()
    title = (fields.get("TITLE") or "片刻之后").strip()[:80]
    tone = _normalize_tone(fields.get("TONE") or "calm")
    importance = _parse_int(fields.get("IMPORTANCE"), default=40, low=0, high=100)
    highlights = _split_list(fields.get("HIGHLIGHTS"))[:12]
    try:
        return NarrationDraft(summary_title=title, narration=text, highlight_agent_ids=highlights, tone=tone, importance=importance)
    except Exception:
        return None


def identity_output_contract(language: str = "zh") -> str:
    if normalize_language(language) == "en":
        return (
            "Output only this field-line protocol, one field per line. Do not use braces, JSON-like objects, Markdown, or explanations.\n"
            "NAME=English name\n"
            "GENDER=female/male/nonbinary/agender/private/custom\n"
            "GENDER_CUSTOM=custom gender note or -\n"
            "GENDER_PUBLIC=1 or 0\n"
            "GENDER_EXPR=external gender expression\n"
            "LOOK_SHORT=8 to 120 characters of short appearance\n"
            "LOOK_FULL=80 to 800 English words or characters about appearance and presence\n"
            "AVATAR_COLOR=#607d8b\n"
            "AVATAR_TAGS=tag1,tag2,tag3\n"
            "SPEAK=speaking style\n"
            "SEED=personality seed\n"
            "GOAL=initial goal after entering the world\n"
            "INTRO=open/selective/secretive\n"
            "TRAITS=openness:50,caution:50,sociability:50,empathy:50,curiosity:50,discipline:50,aggression:20,honesty:50,creativity:50,neuroticism:50"
        )
    return (
        "只输出字段协议，每行一个字段，不要使用大括号结构，不要 Markdown，不要解释。\n"
        "NAME=中文名\n"
        "GENDER=女/男/非二元/无性别/不愿公开/自定义\n"
        "GENDER_CUSTOM=自定义性别说明或-\n"
        "GENDER_PUBLIC=1或0\n"
        "GENDER_EXPR=外在性别表达\n"
        "LOOK_SHORT=8到120字外貌短描述\n"
        "LOOK_FULL=80到800字完整外貌和气质\n"
        "AVATAR_COLOR=#607d8b\n"
        "AVATAR_TAGS=标签1,标签2,标签3\n"
        "SPEAK=说话风格\n"
        "SEED=人格种子\n"
        "GOAL=进入世界后的初始目标\n"
        "INTRO=open/selective/secretive\n"
        "TRAITS=openness:50,caution:50,sociability:50,empathy:50,curiosity:50,discipline:50,aggression:20,honesty:50,creativity:50,neuroticism:50"
    )


def narration_output_contract(language: str = "zh") -> str:
    if normalize_language(language) == "en":
        return (
            "Output only this field-line protocol, one field per line. Do not use braces, JSON-like objects, Markdown, or explanations.\n"
            "TITLE=short English title\n"
            "TEXT=60 to 180 words of English narration\n"
            "TONE=calm/warm/tense/sad/funny\n"
            "IMPORTANCE=0 to 100\n"
            "HIGHLIGHTS=related agent_id separated by English commas, or -"
        )
    return (
        "只输出字段协议，每行一个字段，不要使用大括号结构，不要 Markdown，不要解释。\n"
        "TITLE=不超过20字标题\n"
        "TEXT=60到180字中文旁白\n"
        "TONE=calm/warm/tense/sad/funny\n"
        "IMPORTANCE=0到100\n"
        "HIGHLIGHTS=相关agent_id，用英文逗号分隔；没有则-"
    )


def _parse_traits(text: str) -> dict[str, int]:
    values = {name: 50 for name in TRAIT_NAMES}
    values["aggression"] = 20
    for name in TRAIT_NAMES:
        match = re.search(rf"{re.escape(name)}\s*[:=：]\s*(-?\d+)", text, re.I)
        if match:
            values[name] = max(0, min(100, int(match.group(1))))
    # Also accept bare comma-separated numbers in TRAIT_NAMES order.
    numbers = [int(x) for x in re.findall(r"-?\d+", text)]
    if len(numbers) >= len(TRAIT_NAMES) and not any(re.search(rf"{name}\s*[:=：]", text, re.I) for name in TRAIT_NAMES):
        for name, number in zip(TRAIT_NAMES, numbers):
            values[name] = max(0, min(100, number))
    return values


def _normalize_gender(text: str) -> str:
    value = str(text or "").strip()
    mapping = {
        "女性": "女",
        "女人": "女",
        "女孩": "女",
        "female": "女",
        "woman": "女",
        "girl": "女",
        "feminine": "女",
        "男性": "男",
        "男人": "男",
        "男孩": "男",
        "male": "男",
        "man": "男",
        "boy": "男",
        "masculine": "男",
        "nonbinary": "非二元",
        "non-binary": "非二元",
        "nb": "非二元",
        "agender": "无性别",
        "genderless": "无性别",
        "private": "不愿公开",
        "unknown": "不愿公开",
        "none": "不愿公开",
        "custom": "自定义",
        "-": "不愿公开",
    }
    value = mapping.get(value, value)
    return value if value in {"女", "男", "非二元", "无性别", "不愿公开", "自定义"} else "不愿公开"


def _normalize_intro(text: str) -> str:
    lowered = str(text or "").strip().lower()
    if lowered in {"open", "selective", "secretive"}:
        return lowered
    if any(token in lowered for token in ["开放", "公开", "坦率"]):
        return "open"
    if any(token in lowered for token in ["秘密", "拒", "谨慎"]):
        return "secretive"
    return "selective"


def _normalize_tone(text: str) -> str:
    value = str(text or "").strip().lower()
    mapping = {"平静": "calm", "温暖": "warm", "紧张": "tense", "悲伤": "sad", "有趣": "funny"}
    value = mapping.get(value, value)
    return value if value in {"calm", "warm", "tense", "sad", "funny"} else "calm"


def _parse_bool(text: str | None, *, default: bool) -> bool:
    if text is None:
        return default
    lowered = str(text).strip().lower()
    if lowered in {"1", "true", "yes", "y", "公开", "愿意", "是"}:
        return True
    if lowered in {"0", "false", "no", "n", "不公开", "否", "-"}:
        return False
    return default


def _parse_int(text: str | None, *, default: int, low: int, high: int) -> int:
    if text is None:
        return default
    match = re.search(r"-?\d+", str(text))
    if not match:
        return default
    return max(low, min(high, int(match.group(0))))


def _normalize_color(text: str | None) -> str:
    value = str(text or "").strip()
    if re.match(r"^#[0-9a-fA-F]{6}$", value):
        return value
    return "#607d8b"


def _split_list(text: str | None) -> list[str]:
    if not text or str(text).strip() in {"-", "无", "none"}:
        return []
    return [part.strip() for part in re.split(r"[,，、;；]\s*", str(text)) if part.strip()]


def _first_sentence(text: str) -> str:
    value = re.split(r"[。！？!?\n]", str(text or ""), maxsplit=1)[0].strip()
    return value or str(text or "").strip()[:120]


def _first_nonempty_line(text: str) -> str:
    for line in str(text or "").splitlines():
        line = re.sub(r"^(?:NAME|名字|姓名)\s*[:=：]\s*", "", line.strip(), flags=re.I)
        if line:
            return line
    return ""


def _sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[`@#{}\[\]<>|]", "", str(name or "")).strip()
    cleaned = re.sub(r"^(?:NAME|名字|姓名)\s*[:=：]\s*", "", cleaned, flags=re.I)
    cleaned = re.split(r"[\s,，。；;]", cleaned, maxsplit=1)[0]
    return cleaned[:12]


def _strip_protocol_noise(raw: str) -> str:
    lines = []
    for line in str(raw or "").splitlines():
        if re.match(r"^([A-Za-z_]+|[\u4e00-\u9fa5]{1,12})\s*[:=：]", line.strip()):
            key = line.split("=", 1)[0].split("：", 1)[0].split(":", 1)[0].strip()
            if KEY_ALIASES.get(key, key.upper()) != "TEXT":
                continue
            line = re.split(r"[:=：]", line, maxsplit=1)[-1]
        lines.append(line.strip())
    return " ".join(line for line in lines if line).strip()


def identity_protocol_system(*, child: bool = False, language: str = "zh") -> str:
    if normalize_language(language) == "en":
        subject = "newborn identity" if child else "resident identity"
        return f"You generate a virtual-world {subject}. " + identity_output_contract(language)
    subject = "新生儿身份" if child else "居民身份"
    return f"你负责生成虚拟世界的{subject}。" + identity_output_contract(language)


def identity_protocol_user_suffix(language: str = "zh") -> str:
    return identity_output_contract(language)


def baby_name_system(language: str = "zh") -> str:
    if normalize_language(language) == "en":
        return "You name a newborn in a virtual world. Output only one line: NAME=name. Do not explain."
    return "你负责为虚拟世界中的新生儿取一个中文或中文风格名字。只输出一行 NAME=名字，不要解释。"


def narrator_protocol_system(language: str = "zh") -> str:
    return narration_output_contract(language)


def parse_narration(raw: str) -> NarrationDraft | None:
    return parse_narration_draft(raw)
