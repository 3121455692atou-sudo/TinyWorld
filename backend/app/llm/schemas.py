from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


TRAIT_NAMES = [
    "openness",
    "caution",
    "sociability",
    "empathy",
    "curiosity",
    "discipline",
    "aggression",
    "honesty",
    "creativity",
    "neuroticism",
]


class IdentityDraft(BaseModel):
    chosen_name: str = Field(min_length=1, max_length=12)
    gender_identity: Literal["女", "男", "非二元", "无性别", "不愿公开", "自定义"]
    gender_custom_text: str = ""
    gender_publicity: bool = True
    gender_expression: str = Field(default="难以判断", max_length=80)
    appearance_full: str = Field(min_length=20, max_length=4000)
    appearance_short: str = Field(min_length=8, max_length=120)
    avatar_hint: dict[str, Any] = Field(default_factory=dict)
    speaking_style: str = Field(min_length=4, max_length=120)
    personality_seed: str = Field(min_length=10, max_length=160)
    initial_goal: str = Field(min_length=6, max_length=160)
    intro_policy: Literal["open", "selective", "secretive"] = "selective"
    trait_sliders: dict[str, int] = Field(default_factory=dict)

    @field_validator("gender_publicity", mode="before")
    @classmethod
    def normalize_gender_publicity(cls, value: bool | str) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"公开", "愿意公开", "true", "yes", "1", "open"}:
            return True
        if text in {"不公开", "不愿公开", "false", "no", "0", "secret"}:
            return False
        return True

    @field_validator("avatar_hint", mode="before")
    @classmethod
    def normalize_avatar_hint(cls, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            return {"color": "#607d8b", "tags": [part.strip() for part in value.replace("，", "、").split("、") if part.strip()][:3]}
        return {}

    @field_validator("intro_policy", mode="before")
    @classmethod
    def normalize_intro_policy(cls, value: str) -> str:
        text = str(value).strip().lower()
        if text in {"open", "selective", "secretive"}:
            return text
        if "坦" in text or "公开" in text or "开放" in text:
            return "open"
        if "拒" in text or "秘密" in text or "谨慎" in text or "保留" in text:
            return "secretive"
        return "selective"

    @field_validator("trait_sliders")
    @classmethod
    def clamp_traits(cls, value: dict[str, int]) -> dict[str, int]:
        return {name: max(0, min(100, int(value.get(name, 50)))) for name in TRAIT_NAMES}


class ActionChoice(BaseModel):
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    plan_summary: str = "我先按眼前情况行动。"


class BabyNameDraft(BaseModel):
    chosen_name: str = Field(min_length=1, max_length=12)


class NarrationDraft(BaseModel):
    summary_title: str = Field(default="片刻之后", max_length=80)
    narration: str = Field(default="事件继续推进，居民们的行动留下了新的记录。", min_length=8)
    highlight_agent_ids: list[str] = Field(default_factory=list)
    tone: Literal["calm", "warm", "tense", "sad", "funny"] = "calm"
    importance: int = 40

    @model_validator(mode="before")
    @classmethod
    def normalize_keys(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        if "summary_title" not in data:
            for key in ("title", "标题", "summaryTitle"):
                if key in data:
                    data["summary_title"] = data[key]
                    break
        if "narration" not in data:
            for key in ("summary", "content", "text", "解说", "正文"):
                if key in data:
                    data["narration"] = data[key]
                    break
        if "highlight_agent_ids" not in data:
            for key in ("highlights", "agents", "highlightAgents"):
                if key in data:
                    data["highlight_agent_ids"] = data[key]
                    break
        return data

    @field_validator("narration", mode="before")
    @classmethod
    def normalize_narration(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            text = "事件继续推进，居民们的行动留下了新的记录。"
        if len(text) < 8:
            text = f"{text}。事件仍在继续。"
        return text

    @field_validator("highlight_agent_ids", mode="before")
    @classmethod
    def normalize_highlights(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if item]
        if isinstance(value, str):
            return [part.strip() for part in value.replace("，", ",").split(",") if part.strip()]
        return []

    @field_validator("tone", mode="before")
    @classmethod
    def normalize_tone(cls, value: str) -> str:
        mapping = {
            "平静": "calm",
            "冷静": "calm",
            "温暖": "warm",
            "温和": "warm",
            "紧张": "tense",
            "悲伤": "sad",
            "难过": "sad",
            "有趣": "funny",
            "轻松": "funny",
            "neutral": "calm",
        }
        text = str(value or "").strip()
        normalized = mapping.get(text, text)
        return normalized if normalized in {"calm", "warm", "tense", "sad", "funny"} else "calm"

    @field_validator("importance", mode="before")
    @classmethod
    def normalize_importance(cls, value: int | float | str) -> int:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 40
        if 0 <= numeric <= 1:
            numeric *= 100
        return int(max(0, min(100, round(numeric))))


class DiaryDraft(BaseModel):
    title: str = Field(default="今天的记录", max_length=80)
    content: str = Field(min_length=40, max_length=600)
    mood_words: list[str] = Field(default_factory=list)
    mentioned_known_names: list[str] = Field(default_factory=list)
    mentioned_visual_refs: list[str] = Field(default_factory=list)
