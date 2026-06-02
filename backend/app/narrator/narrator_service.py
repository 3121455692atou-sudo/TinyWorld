from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.clock import format_world_time
from app.core.database import SessionLocal
from app.core.models import Event, NarratorRun, World
from app.events.event_store import create_event
from app.llm.openai_compatible import provider
from app.llm.language import normalize_language, world_language
from app.llm.runtime import llm_runtime_kwargs, normalize_llm_runtime
from app.llm.schemas import NarrationDraft
from app.llm.text_protocols import narrator_protocol_system, parse_narration
from app.narrator.narrator_prompts import narrator_system_prompt, narrator_user_prompt


async def maybe_create_narration(session: Session, world: World, input_event_ids: list[int], *, force: bool = False) -> list[int]:
    if not _narrator_enabled(world) or not input_event_ids:
        return []
    display_count = session.execute(
        select(func.count(Event.event_id)).where(Event.world_id == world.world_id, Event.importance >= 15, Event.event_type != "narration")
    ).scalar_one()
    if not force and display_count % settings.narrator_events_per_summary != 0:
        return []
    return await create_narration(session, world, input_event_ids, trigger_type="major" if force else "batch")


async def create_narration(session: Session, world: World, input_event_ids: list[int], trigger_type: str = "manual") -> list[int]:
    if not _narrator_enabled(world):
        return []
    events = [session.get(Event, event_id) for event_id in input_event_ids]
    events = [event for event in events if event]
    if not events:
        events = list(
            session.execute(
                select(Event).where(Event.world_id == world.world_id, Event.event_type != "narration").order_by(Event.world_time.desc(), Event.event_id.desc()).limit(8)
            ).scalars()
        )[::-1]
    text = "\n".join(f"- {event.viewer_text}" for event in events)
    narrator_config = _narrator_config(world)
    language = world_language(world)
    system_prompt = narrator_protocol_system(language) + "\n" + narrator_system_prompt(language)
    if narrator_config.get("system_prompt"):
        system_prompt += f"\n用户给解说 agent 的额外提示: {narrator_config['system_prompt']}"
    try:
        result = await provider.complete_text(
            model_alias="narrator",
            system_prompt=system_prompt,
            user_prompt=narrator_user_prompt(text, language),
            temperature=0.55,
            model_name=narrator_config.get("model_name"),
            base_url=narrator_config.get("base_url"),
            api_key=narrator_config.get("api_key"),
            **llm_runtime_kwargs(normalize_llm_runtime(narrator_config)),
        )
        if result.error:
            return []
        parsed_narration = result.parsed_object if isinstance(result.parsed_object, NarrationDraft) else parse_narration(result.raw_text)
        result = type(result)(result.raw_text, parsed_narration, result.token_usage, result.latency_ms, result.provider_name, result.error)
    except Exception:
        return []
    if not isinstance(result.parsed_object, NarrationDraft):
        return []
    draft = result.parsed_object
    run = NarratorRun(
        world_id=world.world_id,
        trigger_type=trigger_type,
        input_event_ids_json=[event.event_id for event in events],
        summary_title=draft.summary_title,
        narration=draft.narration,
        tone=draft.tone,
        importance=max(0, min(100, draft.importance)),
        created_world_time=world.current_world_time_minutes,
        error=None,
    )
    session.add(run)
    session.flush()
    event = create_event(
        session,
        world=world,
        event_type="narration",
        visibility_scope="viewer_only",
        importance=run.importance,
        color_class="narrator",
        viewer_text=f"【解说】{draft.summary_title}: {draft.narration}",
        payload={"summary_title": draft.summary_title, "narration": draft.narration, "tone": draft.tone, "narrator_run_id": run.narrator_run_id},
    )
    return [event.event_id]


def schedule_daily_summary_tasks(session: Session, world: World) -> None:
    if not _narrator_enabled(world):
        return
    completed_day = int(world.current_world_time_minutes // 1440)
    if completed_day <= 0:
        return
    settings_json = dict(world.settings_json or {})
    scheduled = {int(day) for day in settings_json.get("daily_summary_scheduled_days", []) if str(day).isdigit()}
    missing = [day for day in range(1, completed_day + 1) if day not in scheduled]
    if not missing:
        return
    settings_json["daily_summary_scheduled_days"] = sorted(scheduled | set(missing))[-365:]
    world.settings_json = settings_json
    session.flush()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for day in missing:
        loop.create_task(_create_daily_summary_background(world.world_id, day))


async def _create_daily_summary_background(world_id: str, day: int) -> None:
    try:
        with SessionLocal() as session:
            world = session.get(World, world_id)
            if not world or not _narrator_enabled(world):
                return
            exists = session.execute(
                select(NarratorRun).where(
                    NarratorRun.world_id == world_id,
                    NarratorRun.trigger_type == "daily_summary",
                    NarratorRun.created_world_time == day * 1440,
                )
            ).scalar_one_or_none()
            if exists:
                return
            start = (day - 1) * 1440
            end = day * 1440
            events = list(
                session.execute(
                    select(Event)
                    .where(
                        Event.world_id == world_id,
                        Event.world_time >= start,
                        Event.world_time < end,
                        Event.event_type.not_in(["narration", "narrator_failed", "tool_failed"]),
                    )
                    .order_by(Event.importance.desc(), Event.event_id.asc())
                    .limit(28)
                ).scalars()
            )
            if not events:
                language = world_language(world)
                run = NarratorRun(
                    world_id=world_id,
                    trigger_type="daily_summary",
                    input_event_ids_json=[],
                    summary_title=f"Day {day}" if normalize_language(language) == "en" else f"第{day}天",
                    narration="The day left no clear events behind. The world crossed midnight quietly." if normalize_language(language) == "en" else "这一天没有留下足够清晰的事件。世界安静地越过了日界线。",
                    tone="calm",
                    importance=20,
                    created_world_time=end,
                    error=None,
                )
                session.add(run)
                session.commit()
                return
            await create_daily_summary(session, world, day, events)
            session.commit()
    except Exception:
        return


async def create_daily_summary(session: Session, world: World, day: int, events: list[Event]) -> None:
    narrator_config = _narrator_config(world)
    language = world_language(world)
    lines = "\n".join(f"- {format_world_time(event.world_time)} {event.viewer_text}" for event in sorted(events, key=lambda item: (item.world_time, item.event_id)))
    system_prompt = narrator_protocol_system(language) + "\n" + narrator_system_prompt(language)
    if narrator_config.get("system_prompt"):
        system_prompt += f"\n用户给解说 agent 的额外提示: {narrator_config['system_prompt']}"
    if normalize_language(language) == "en":
        user_prompt = f"""
Write an English daily summary for Day {day}.
This is a day-end review for the player, not event-feed narration. You may summarize what happened, relationship changes, danger, and who cared for themselves or others.
Do not add events that did not happen. Do not write tool names, rules, payloads, numeric deltas, or backend judgments.
If someone died, was born, became pregnant, was jailed, became homeless, or entered a serious crisis, mention it naturally.

Day {day} event excerpts:
{lines}

Output using this field protocol: TITLE=Day {day}, TEXT=summary, TONE=calm/warm/tense/sad/funny, IMPORTANCE=0 to 100, HIGHLIGHTS=related agent_id or -. Do not explain.
"""
    else:
        user_prompt = f"""
请为第{day}天写一段中文每日总结。
这是给玩家看的日终回顾，不是事件流旁白；可以概括一天里发生了什么、谁的关系变化、谁陷入危险、谁照顾了自己或别人。
不要添加没有发生过的新事件，不要写工具名、规则、payload、数值变化或后端判定。
如果有人死亡、出生、怀孕、入狱、无家可归、陷入严重危机，要自然提到。

第{day}天事件摘录:
{lines}

按字段协议输出：TITLE=第{day}天、TEXT=总结、TONE=calm/warm/tense/sad/funny、IMPORTANCE=0到100、HIGHLIGHTS=相关agent_id或-。不要解释。
"""
    try:
        result = await provider.complete_text(
            model_alias="narrator",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.45,
            model_name=narrator_config.get("model_name"),
            base_url=narrator_config.get("base_url"),
            api_key=narrator_config.get("api_key"),
            **llm_runtime_kwargs(normalize_llm_runtime(narrator_config)),
        )
        draft = parse_narration(result.raw_text) if not result.error else None
    except Exception:
        draft = None
    if draft is None:
        fallback = _fallback_draft(events, language=language)
        draft = NarrationDraft(
            summary_title=f"Day {day}" if normalize_language(language) == "en" else f"第{day}天",
            narration=fallback.narration,
            highlight_agent_ids=fallback.highlight_agent_ids,
            tone=fallback.tone,
            importance=fallback.importance,
        )
    run = NarratorRun(
        world_id=world.world_id,
        trigger_type="daily_summary",
        input_event_ids_json=[event.event_id for event in events],
        summary_title=draft.summary_title or (f"Day {day}" if normalize_language(language) == "en" else f"第{day}天"),
        narration=draft.narration,
        tone=draft.tone,
        importance=max(0, min(100, draft.importance)),
        created_world_time=day * 1440,
        error=None,
    )
    session.add(run)
    session.flush()


def _narrator_config(world: World) -> dict:
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    config = settings_json.get("narrator_config")
    return config if isinstance(config, dict) else {}


def _narrator_enabled(world: World) -> bool:
    if not settings.narrator_enabled:
        return False
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    if settings_json.get("narrator_enabled") is False:
        return False
    return bool(_narrator_config(world))


def _fallback_draft(events: list[Event], language: str = "zh") -> NarrationDraft:
    visible_events = [event for event in events if event.event_type != "narration"]
    english = normalize_language(language) == "en"
    if not visible_events:
        return NarrationDraft(
            summary_title="A quiet moment" if english else "片刻之后",
            narration="There are only a few event records for now. The world is still waiting for new actions." if english else "事件记录暂时很少，世界仍在等待新的行动发生。",
            highlight_agent_ids=[],
            tone="calm",
            importance=25,
        )
    last = visible_events[-1]
    title = ("A death occurs" if last.event_type == "death" else "Events move forward") if english else ("死亡发生" if last.event_type == "death" else "事件推进")
    if english:
        fragments = []
        for event in visible_events[-4:]:
            text = (event.viewer_text or event.event_type).strip()
            if any("\u4e00" <= ch <= "\u9fff" for ch in text):
                actor = event.actor_agent_id or "system"
                target = f" and {event.target_agent_id}" if event.target_agent_id else ""
                text = f"A {event.event_type} event involving {actor}{target} was recorded."
            fragments.append(text)
    else:
        fragments = [event.viewer_text.strip() for event in visible_events[-4:] if event.viewer_text.strip()]
    narration = " ".join(fragments)
    if len(narration) > 360:
        narration = narration[:357] + "..."
    return NarrationDraft(
        summary_title=title,
        narration=narration,
        highlight_agent_ids=[agent_id for event in visible_events for agent_id in [event.actor_agent_id, event.target_agent_id] if agent_id],
        tone="sad" if last.event_type == "death" else "calm",
        importance=max(35, min(100, max(event.importance for event in visible_events))),
    )
