from __future__ import annotations

from typing import Any
import re

from sqlalchemy import select
from sqlalchemy.sql import ColumnElement
from sqlalchemy.orm import Session

from app.core.models import Agent, Event, World
from app.events.importance import color_for_importance


TRIVIAL_CONFIG_EVENT_TYPES = {"llm_config_changed", "agent_profile_changed"}


_PUBLIC_MECHANICAL_MARKERS = (
    "工具调用格式错误",
    "当前尝试的工具",
    "请重新选择",
    "参数完整且符合",
    "参数完整",
    "validation.message",
    "failure_reason_code",
    "failure_reason",
    "llm_feedback",
    "state_delta",
    "payload",
    "EffectEngine",
    "RuleEngine",
    "ToolValidation",
    "tool_name",
    "reason_code",
    "missing_visible_ref",
    "missing_location",
    "missing_known_name",
    "missing_speech",
    "missing_text",
    "target_not_visible",
    "private_room_blocked",
    "工具失败",
    "当前生命状态不能执行",
    "这个行动需要第二行",
    "这个行动需要台词",
    "请用行动菜单",
    "后端",
    "硬规则",
    "基础饱腹规则",
    "数值变化",
    "机制词",
    "抽象结果",
)

_MODEL_REASONING_BLOCK_RE = re.compile(
    r"(?is)<\s*(?:think|thought|analysis|reasoning|chain_of_thought)\b[^>]*>.*?<\s*/\s*(?:think|thought|analysis|reasoning|chain_of_thought)\s*>"
)
_MODEL_REASONING_OPEN_RE = re.compile(r"(?is)<\s*(?:think|thought|analysis|reasoning|chain_of_thought)\b[^>]*>")
_MODEL_ACTION_HEADER_RE = re.compile(r"(?m)^[^\S\r\n]*(?:\[\d{1,3}(?:(?:\s*[:：]\s*|\s+)[^\]\r\n]{1,48})?\]|\d{1,3}\s+\d{1,3})[^\S\r\n]*(?:#.*)?$")
_MODEL_FORMAT_CHECK_RE = re.compile(r"(?is)(?:^|\n)\s*(?:format check|格式检查|格式校验)\s*[:：]?.*?$")

_DIALOGUE_EVENT_HINTS = {
    "dialogue",
    "introduce_self",
    "refuse_introduction",
    "aid_request",
    "seek_help",
    "wake_request",
    "story",
    "sing",
    "social_request",
    "romance",
    "relationship",
    "work_service_speech",
    "werewolf_speech",
    "werewolf_wolf_discussion",
}

_FAILURE_REASON_TEXT = {
    "missing_text": "一时没有把要表达的内容说清楚，行动没有完成。",
    "missing_speech": "一时没有把话说出口，行动没有完成。",
    "missing_visible_ref": "想和某个人互动，但没有选定眼前的对象。",
    "target_not_visible": "想和某个人互动，但眼前没有找到合适的对象。",
    "visible_ref_not_found": "想和某个人互动，但眼前没有找到合适的对象。",
    "missing_location": "想换个地方，但没有选定能去的方向。",
    "location_not_adjacent": "想换个地方，但那不是现在能直接走到的方向。",
    "bad_location": "想换个地方，但这次没有走成。",
    "private_room_blocked": "想进一间别人房间，但门没有对自己开放。",
    "not_private_room": "想处理私人房间相关的事情，但地点不合适。",
    "own_private_room": "想处理私人房间相关的事情，但对象选错了。",
    "name_unknown": "还不知道对方的名字，想继续互动但没能确认对象。",
    "missing_item": "想处理物品，但没有找到合适的东西。",
    "item_not_found": "想处理物品，但没有找到合适的东西。",
    "broker_missing": "想处理金融行动，但相关条件还没有准备好。",
    "no_broker_account": "想处理证券账户相关行动，但账户还没有准备好。",
}


def _payload_copy(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(payload or {})


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def strip_model_reasoning_text(text: str | None) -> str:
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value:
        return ""
    value = _MODEL_REASONING_BLOCK_RE.sub("", value)
    open_match = _MODEL_REASONING_OPEN_RE.search(value)
    if open_match:
        later_header = _MODEL_ACTION_HEADER_RE.search(value, open_match.end())
        if later_header:
            value = value[: open_match.start()] + value[later_header.start() :]
        else:
            value = value[: open_match.start()]
    matches = list(_MODEL_ACTION_HEADER_RE.finditer(value))
    if matches:
        value = value[matches[-1].end() :]
    value = _MODEL_FORMAT_CHECK_RE.sub("", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _normalize_dialogue_payload(
    session: Session,
    *,
    event_type: str,
    payload: dict[str, Any] | None,
    actor_agent_id: str | None,
    target_agent_id: str | None,
) -> dict[str, Any]:
    data = _payload_copy(payload)
    raw_lines = data.get("dialogue_lines")
    lines: list[dict[str, Any]] = []
    if isinstance(raw_lines, list):
        for raw in raw_lines:
            if not isinstance(raw, dict):
                continue
            text = strip_model_reasoning_text(_first_text(raw.get("text"), raw.get("speech")))
            if not text or _contains_public_mechanical_text(text):
                continue
            speaker_id = raw.get("speaker_agent_id") or actor_agent_id
            target_id = raw.get("target_agent_id") or target_agent_id
            lines.append(
                {
                    "speaker_agent_id": str(speaker_id) if speaker_id else None,
                    "target_agent_id": str(target_id) if target_id else None,
                    "text": text,
                    "tone": str(raw.get("tone") or data.get("tone") or "neutral"),
                }
            )
    if not lines and actor_agent_id and _should_treat_payload_as_dialogue(event_type, data):
        text = strip_model_reasoning_text(_first_text(data.get("speech")))
        if text and not _contains_public_mechanical_text(text):
            lines.append(
                {
                    "speaker_agent_id": actor_agent_id,
                    "target_agent_id": target_agent_id,
                    "text": text,
                    "tone": str(data.get("tone") or "neutral"),
                }
            )
    if lines:
        data["dialogue_lines"] = lines
        if isinstance(data.get("speech"), str):
            data["speech"] = str(lines[0].get("text") or "")
        # 公开事件里，角色台词只能放在 speech/dialogue_lines。message/content 容易被前端误判成旁白或后端提示。
        speech_texts = {str(line.get("text") or "").strip() for line in lines if line.get("text")}
        for speech_key in ("message", "content"):
            value = data.get(speech_key)
            if isinstance(value, str) and (not value.strip() or value.strip() in speech_texts):
                data.pop(speech_key, None)
    return data


def _should_treat_payload_as_dialogue(event_type: str, payload: dict[str, Any]) -> bool:
    if "speech" in payload:
        return True
    return False


def _contains_public_mechanical_text(text: str | None) -> bool:
    if not text:
        return False
    lowered = strip_model_reasoning_text(str(text)).lower()
    return any(marker.lower() in lowered for marker in _PUBLIC_MECHANICAL_MARKERS)


def _agent_display_name(session: Session, agent_id: str | None) -> str:
    if not agent_id:
        return "某位居民"
    agent = session.get(Agent, agent_id)
    return agent.chosen_name if agent and agent.chosen_name else "某位居民"


def _sanitize_public_viewer_text(
    session: Session,
    *,
    event_type: str,
    viewer_text: str,
    actor_agent_id: str | None,
    payload: dict[str, Any],
) -> str:
    text = strip_model_reasoning_text(viewer_text)
    actor_name = _agent_display_name(session, actor_agent_id)
    if not text:
        text = f"{actor_name}做了一件事。" if actor_agent_id else "有一次行动被记录。"
    if _contains_public_mechanical_text(text):
        if event_type == "tool_failed":
            return f"{actor_name}{_failure_reason_suffix(payload)}"
        return "有一次行动被记录。"
    dialogue_lines = payload.get("dialogue_lines")
    if isinstance(dialogue_lines, list) and dialogue_lines:
        text = _strip_dialogue_from_narration(text, dialogue_lines)
        if not text:
            return f"{actor_name}开口说话。"
    if _contains_public_mechanical_text(text):
        return f"{actor_name}试着行动，但这次没有完成。" if event_type == "tool_failed" else "有一次行动被记录。"
    return text


def _failure_reason_suffix(payload: dict[str, Any]) -> str:
    code = str(payload.get("failure_reason_code") or "")
    if code in _FAILURE_REASON_TEXT:
        return _FAILURE_REASON_TEXT[code]
    tool = str(payload.get("tool_name") or "")
    if "private_room" in tool:
        return "想进一间别人房间，但门没有对自己开放。"
    if "move" in tool or "location" in tool:
        return "想换个地方，但这次没有走成。"
    if tool.startswith("v6_"):
        return "想处理一项经济行动，但这次没有办成。"
    return "试着行动，但这次没有完成。"


def _strip_dialogue_from_narration(text: str, dialogue_lines: list[Any]) -> str:
    cleaned = text
    for line in dialogue_lines:
        if not isinstance(line, dict):
            continue
        speech = _first_text(line.get("text"), line.get("speech"))
        if not speech:
            continue
        escaped = re.escape(speech)
        cleaned = re.sub(rf"[：:，,、\s]*[“『\"']{escaped}[”』\"']", "", cleaned)
        cleaned = cleaned.replace(speech, "")
    # Any remaining quoted segment in a dialogue event is treated as speech and hidden from narration.
    cleaned = re.sub(r"[：:，,、\s]*[“『\"'][^”』\"']{1,240}[”』\"']", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"(询问|提问|问)\s*[:：]?\s*$", "询问。", cleaned)
    cleaned = re.sub(r"(说|说道|开口说|回答|请求|喊道)\s*[:：]?\s*$", "开口说话。", cleaned)
    cleaned = cleaned.replace("  ", " ").strip()
    return cleaned


def create_event(
    session: Session,
    *,
    world: World,
    event_type: str,
    viewer_text: str,
    agent_visible_text: str | None = None,
    actor_agent_id: str | None = None,
    target_agent_id: str | None = None,
    location_id: str | None = None,
    visibility_scope: str = "public",
    importance: int = 10,
    color_class: str | None = None,
    payload: dict[str, Any] | None = None,
    state_delta: dict[str, Any] | None = None,
    no_state_changed: bool = False,
) -> Event:
    if event_type in TRIVIAL_CONFIG_EVENT_TYPES:
        importance = 1
        color_class = "muted"
        no_state_changed = True
    public_payload = _normalize_dialogue_payload(
        session,
        event_type=event_type,
        payload=payload,
        actor_agent_id=actor_agent_id,
        target_agent_id=target_agent_id,
    )
    public_viewer_text = _sanitize_public_viewer_text(
        session,
        event_type=event_type,
        viewer_text=viewer_text,
        actor_agent_id=actor_agent_id,
        payload=public_payload,
    )
    event = Event(
        world_id=world.world_id,
        world_time=world.current_world_time_minutes,
        event_type=event_type,
        actor_agent_id=actor_agent_id,
        target_agent_id=target_agent_id,
        location_id=location_id,
        visibility_scope=visibility_scope,
        importance=importance,
        color_class=color_class or color_for_importance(importance, event_type),
        viewer_text=public_viewer_text,
        agent_visible_text=agent_visible_text or public_viewer_text,
        payload=public_payload,
        state_delta=state_delta or {},
        no_state_changed=no_state_changed,
    )
    session.add(event)
    session.flush()
    return event


def chronological_order_asc() -> tuple[ColumnElement, ColumnElement]:
    return (Event.world_time.asc(), Event.event_id.asc())


def chronological_order_desc() -> tuple[ColumnElement, ColumnElement]:
    return (Event.world_time.desc(), Event.event_id.desc())


def sort_chronologically(events: list[Event]) -> list[Event]:
    return sorted(events, key=lambda event: (int(event.world_time or 0), int(event.event_id or 0)))


def latest_events(session: Session, world_id: str, limit: int = 50, min_importance: int = 0) -> list[Event]:
    newest = list(
        session.execute(
            select(Event)
            .where(Event.world_id == world_id, Event.importance >= min_importance)
            .order_by(*chronological_order_desc())
            .limit(limit)
        ).scalars()
    )
    return sort_chronologically(newest)


def events_after(session: Session, world_id: str, after_event_id: int | None, limit: int = 100) -> list[Event]:
    stmt = select(Event).where(Event.world_id == world_id)
    if after_event_id:
        stmt = stmt.where(Event.event_id > after_event_id)
    return list(session.execute(stmt.order_by(*chronological_order_asc()).limit(limit)).scalars())
