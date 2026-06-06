from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Agent, Event, Memory


_MECHANICAL_MEMORY_MARKERS = (
    "工具调用格式错误",
    "当前尝试的工具",
    "请重新选择",
    "参数完整且符合",
    "validation.message",
    "llm_feedback",
    "failure_reason_code",
    "state_delta",
    "EffectEngine",
    "RuleEngine",
    "ToolValidation",
    "missing_visible_ref",
    "missing_location",
    "missing_speech",
    "private_room_blocked",
    "后端",
    "硬规则",
)


def add_memory(
    session: Session,
    *,
    agent_id: str,
    content: str,
    world_time: int,
    source_event_id: int | None = None,
    memory_type: str = "short",
    importance: int = 30,
    visibility: str = "private",
) -> Memory:
    memory = Memory(
        agent_id=agent_id,
        source_event_id=source_event_id,
        memory_type=memory_type,
        content=content,
        importance=importance,
        visibility=visibility,
        created_world_time=world_time,
    )
    session.add(memory)
    session.flush()
    return memory


def auto_memory_for_event(session: Session, event: Event, related_agent_ids: list[str]) -> None:
    # Tool-repair failures are useful as immediate LLM feedback, but they should not become a
    # character's autobiographical memory. Otherwise agents start remembering parser hints instead
    # of what actually happened in the world.
    if event.event_type == "tool_failed":
        return
    persistent_event_types = {
        "introduce_self",
        "refuse_introduction",
        "death",
        "critical",
        "governance_meeting",
        "governance_proposal",
        "governance_support",
        "governance_oppose",
        "rough_sleep_risk",
        "unconscious",
        "unconscious_sleep",
        "dialogue",
        "speech",
        "aid_request",
        "seek_help",
        "werewolf_speech",
        "werewolf_vote",
        "werewolf_death",
    }
    memory_content = _memory_content_for_event(session, event)
    if not memory_content or _contains_mechanical_memory_text(memory_content):
        return
    if event.importance < 40 and event.event_type not in persistent_event_types and not _payload_dialogue_texts(event):
        return
    public_rule_event = event.event_type in {"governance_meeting", "governance_proposal", "governance_support", "governance_oppose"}
    for agent_id in set(related_agent_ids):
        if not agent_id:
            continue
        add_memory(
            session,
            agent_id=agent_id,
            source_event_id=event.event_id,
            content=memory_content,
            world_time=event.world_time,
            memory_type="long" if public_rule_event or event.importance >= 70 else "short",
            importance=max(event.importance, 75) if public_rule_event else max(event.importance, 45 if _payload_dialogue_texts(event) else event.importance),
        )


def _memory_content_for_event(session: Session, event: Event) -> str:
    base = _clean_memory_text(event.agent_visible_text or event.viewer_text or "")
    dialogue_parts: list[str] = []
    for raw in _payload_dialogue_texts(event):
        speaker_id = str(raw.get("speaker_agent_id") or event.actor_agent_id or "").strip()
        target_id = str(raw.get("target_agent_id") or event.target_agent_id or "").strip()
        speaker = public_agent_label(session, speaker_id) if speaker_id else "某个居民"
        text = _clip(_clean_memory_text(str(raw.get("text") or raw.get("speech") or "")), 180)
        if not text:
            continue
        if target_id and target_id != speaker_id:
            target = public_agent_label(session, target_id)
            dialogue_parts.append(f"{speaker}对{target}说过：『{text}』")
        else:
            dialogue_parts.append(f"{speaker}说过：『{text}』")
    pieces = [piece for piece in [base, *dialogue_parts] if piece]
    if not pieces:
        return "发生了一件重要但已经被公开叙述压缩的事件。"
    # 角色话语必须从结构化 payload 进入记忆，避免旁白去猜台词；同一句话只保留一次。
    deduped: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        key = _memory_key(piece)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(piece)
    return "；".join(deduped)[:1200]


def _payload_dialogue_texts(event: Event) -> list[dict]:
    payload = event.payload if isinstance(event.payload, dict) else {}
    result: list[dict] = []
    raw_lines = payload.get("dialogue_lines")
    if isinstance(raw_lines, list):
        for raw in raw_lines:
            if not isinstance(raw, dict):
                continue
            text = raw.get("text") if isinstance(raw.get("text"), str) else raw.get("speech")
            if isinstance(text, str) and text.strip():
                normalized = dict(raw)
                normalized["text"] = text.strip()
                result.append(normalized)
    speech = payload.get("speech")
    if isinstance(speech, str) and speech.strip() and not result:
        result.append({"speaker_agent_id": event.actor_agent_id, "target_agent_id": event.target_agent_id, "text": speech.strip()})
    return result


def _contains_mechanical_memory_text(text: str) -> bool:
    value = str(text or "").lower()
    return any(marker.lower() in value for marker in _MECHANICAL_MEMORY_MARKERS)


def recent_memories(session: Session, agent_id: str, limit: int = 10, memory_type: str | None = None) -> list[Memory]:
    stmt = select(Memory).where(Memory.agent_id == agent_id, Memory.archived.is_(False))
    if memory_type:
        stmt = stmt.where(Memory.memory_type == memory_type)
    return list(session.execute(stmt.order_by(Memory.memory_id.desc()).limit(limit)).scalars())


def public_agent_label(session: Session, agent_id: str) -> str:
    agent = session.get(Agent, agent_id)
    return agent.chosen_name if agent and agent.chosen_name else "某个居民"


def create_sleep_dream_summary(session: Session, *, agent: Agent, world_time: int, source_event_id: int | None = None) -> Memory:
    settings = _prompt_settings(agent)
    recent = recent_memories(session, agent.agent_id, limit=_prompt_int(settings, "dream_memory_limit", 48, 4, 200))
    if not recent:
        content = "梦醒前的余波: 梦里只剩一点模糊的光。醒来后，先照顾身体，再决定要走向谁。"
        return add_memory(
            session,
            agent_id=agent.agent_id,
            source_event_id=source_event_id,
            memory_type="summary",
            content=content,
            importance=60,
            visibility="private",
            world_time=world_time,
        )

    persistent_keywords = [
        "死", "死亡", "危急", "昏", "犯罪", "偷", "抢", "攻击", "入狱", "监狱", "举报", "创伤", "被伤害", "被偷",
        "怀孕", "孩子", "宝宝", "父母", "表白", "恋爱", "分手", "承诺", "约定", "房租", "驱逐", "无家可归",
        "规则", "宪法", "会议", "公共", "互助", "提议",
    ]
    ordered_raw = list(reversed(recent))
    ordered = _dedupe_memories(ordered_raw)
    important: list[Memory] = []
    ordinary: list[Memory] = []
    for memory in ordered:
        text = _clean_memory_text(memory.content or "")
        if memory.importance >= 70 or any(keyword in text for keyword in persistent_keywords):
            important.append(memory)
        else:
            ordinary.append(memory)

    important_limit = _prompt_int(settings, "dream_important_limit", 10, 0, 40)
    background_limit = _prompt_int(settings, "dream_background_limit", 5, 0, 40)
    lines: list[str] = ["梦醒前的余波:"]
    if important and important_limit:
        lines.append("- 醒来后仍清楚的事: " + "；".join(_clip(_clean_memory_text(memory.content), 90) for memory in important[-important_limit:]))
    if ordinary:
        clusters = _background_impressions(ordinary, limit=background_limit)
        if clusters:
            lines.append("- 已经淡成背景的日常: " + "；".join(clusters))

    unresolved: list[str] = []
    if agent.dynamic_state:
        st = agent.dynamic_state
        if st.hydration < 45:
            unresolved.append("醒来后应该补水")
        if st.satiety < 45:
            unresolved.append("醒来后应该找食物")
        if st.energy < 35:
            unresolved.append("身体还没有完全恢复")
        if st.stress > 60:
            unresolved.append("压力仍然很高，需要找原因")
    wallet = agent.wallet_json or {}
    housing = wallet.get("housing") or {}
    if housing.get("homeless"):
        unresolved.append("住房问题还没解决")
    if wallet.get("liabilities"):
        unresolved.append("债务/还款压力还在")
    if unresolved:
        lines.append("- 醒来后仍牵挂的事: " + "；".join(unresolved[:8]))

    content = "\n".join(lines)[:1200]
    memory = add_memory(
        session,
        agent_id=agent.agent_id,
        source_event_id=source_event_id,
        memory_type="summary",
        content=content,
        importance=65 if important else 55,
        visibility="private",
        world_time=world_time,
    )

    # 做梦整理不是删除人生，而是把普通短时记忆压缩归档；高重要度/创伤/公共规则等记忆保留。
    raw_ordinary = []
    for old in ordered_raw:
        text = _clean_memory_text(old.content or "")
        if old.importance < 70 and not any(keyword in text for keyword in persistent_keywords):
            raw_ordinary.append(old)
    for old in raw_ordinary[:-6]:
        if old.memory_type == "short" and old.importance < 55:
            old.archived = True
    return memory


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _prompt_settings(agent: Agent) -> dict:
    raw = ((agent.world.settings_json or {}) if agent.world else {}).get("prompt_settings")
    return dict(raw) if isinstance(raw, dict) else {}


def _prompt_int(settings_json: dict, key: str, fallback: int, minimum: int, maximum: int) -> int:
    try:
        value = int(settings_json.get(key, fallback))
    except (TypeError, ValueError):
        value = fallback
    return max(minimum, min(maximum, value))


def _dedupe_memories(memories: list[Memory]) -> list[Memory]:
    seen: set[str] = set()
    result: list[Memory] = []
    for memory in memories:
        key = _memory_key(memory.content or "")
        if key in seen:
            continue
        seen.add(key)
        result.append(memory)
    return result


def _memory_key(text: str) -> str:
    cleaned = _clean_memory_text(text)
    cleaned = re.sub(r"『[^』]{0,120}』|“[^”]{0,120}”", "", cleaned)
    cleaned = re.sub(r"\d+", "#", cleaned)
    return cleaned[:80]


def _clean_memory_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    replacements = [
        (r"注意到了这个动作，有机会躲开、抗议或选择不躲。?", "看见了这个动作。"),
        (r"注意到了但没有成功阻止", "察觉到了，却没能避开"),
        (r"注意到了并选择不躲开", "看见了，没有躲开"),
        (r"；目标的主观理解:\s*", "，留下的感受是："),
        (r"对方明确接受了请求，因此请求被完成。?", ""),
        (r"这只是请求，正在等待对方接受或拒绝。?", ""),
        (r"对方能听见这句话：『([^』]+)』", r"说过：『\1』"),
        (r"尝试修复两人之间的关系", "试着把关系往回拉一点"),
    ]
    for pattern, repl in replacements:
        cleaned = re.sub(pattern, repl, cleaned)
    if _contains_mechanical_memory_text(cleaned):
        return ""
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _background_impressions(memories: list[Memory], *, limit: int) -> list[str]:
    if limit <= 0:
        return []
    buckets = {
        "吃饭与补给": ["吃", "饭", "食物", "喝水", "水"],
        "睡眠与身体": ["睡", "休息", "体力", "疲惫", "清洁"],
        "日常交谈": ["说:", "发言", "聊天", "问", "回答"],
        "移动与场所": ["走向", "回到", "到了", "广场", "食堂", "住所"],
        "关系试探": ["拥抱", "牵手", "约会", "好感", "道歉", "修复"],
    }
    counts: dict[str, int] = {}
    examples: dict[str, str] = {}
    for memory in memories:
        text = _clean_memory_text(memory.content or "")
        label = next((name for name, tokens in buckets.items() if any(token in text for token in tokens)), "零碎日常")
        counts[label] = counts.get(label, 0) + 1
        examples.setdefault(label, _clip(text, 44))
    ordered = sorted(counts, key=lambda label: counts[label], reverse=True)
    result = []
    for label in ordered[:limit]:
        count = counts[label]
        if count >= 3:
            result.append(f"{label}反复出现了 {count} 次，只留下大致印象")
        else:
            result.append(examples[label])
    return result
