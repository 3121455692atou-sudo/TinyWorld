from __future__ import annotations

import asyncio
import random
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.websocket import manager
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.models import Agent, AgentLocation, Event, Inventory, Item, Location, World
from app.agents.v5_state import wallet_money
from app.economy.v6 import process_daily_economy_tick
from app.effects.decay import apply_time_decay
from app.effects.death import apply_danger_checks
from app.effects.drive_system import action_conflicts_with_pain, pain_repair_reason, write_drive_state
from app.effects.effect_engine import ExecutionResult, complete_scheduled_sleep, execute_tool, process_world_life_events
from app.events.event_store import create_event
from app.knowledge.perception import build_turn_context, build_turn_context_with_options
from app.llm.action_protocol import ActionOption, ids_hint, packet_to_action_choice, parse_action_packet
from app.llm.language import action_language_instruction, world_language
from app.llm.openai_compatible import provider
from app.llm.provider_base import LLMResult
from app.llm.runtime import agent_llm_runtime, llm_runtime_kwargs
from app.llm.schemas import ActionChoice
from app.narrator.narrator_service import maybe_create_narration, schedule_daily_summary_tasks
from app.simulation.difficulty import profile_for_agent
from app.simulation.reaction_queue import ReactionTask, reaction_queue
from app.social.forced_actions import choose_forced_action_for_fallback
from app.social.pending_requests import choose_social_request_for_fallback
from app.tools.registry import available_tools
from app.tools.validators import validate_tool
from app.world.corpses import apply_corpse_exposure
from app.world.housing import ensure_agent_home
from app.social.addressing import child_caregiver_reaction_ids, mentioned_visible_agent_ids, retarget_params_by_explicit_address, visible_ref_for_agent_id
from app.world.visibility import adjacent_location_ids, resolve_visible_ref, same_location_agent_ids


@dataclass(slots=True)
class TurnResult:
    event_ids: list[int] = field(default_factory=list)
    narration_event_ids: list[int] = field(default_factory=list)
    acted_agent_id: str | None = None
    acted_agent_ids: list[str] = field(default_factory=list)
    status: str = "ok"


class AgentLLMStalled(RuntimeError):
    def __init__(self, *, agent_id: str, event_id: int) -> None:
        super().__init__("agent llm stalled")
        self.agent_id = agent_id
        self.event_id = event_id


@dataclass(slots=True)
class RuntimeSettings:
    request_mode: str = "serial"
    display_mode: str = "batch"
    concurrency_limits: dict = field(default_factory=dict)


class TurnRunner:
    def __init__(self) -> None:
        self._round_robin_index: dict[str, int] = {}

    async def run_one_step(self, session: Session, world_id: str) -> TurnResult:
        world = session.get(World, world_id)
        if not world or world.status == "ended":
            return TurnResult(status="world_not_running")
        try:
            wake_event_ids = process_daily_economy_tick(session, world)
            wake_event_ids.extend(_wake_due_sleepers(session, world))
            wake_event_ids.extend(_wake_due_unconscious(session, world))
            task = reaction_queue.pop(world_id)
            agent = self._reaction_agent(session, world, task) if task else None
            if task and agent:
                return await self._run_single_agent_turn(session, world, agent, task=task, initial_event_ids=wake_event_ids)
            agents = self._regular_agent_batch(session, world)
            if agents:
                return await self._run_regular_batch(session, world, agents, initial_event_ids=wake_event_ids)
            return await self._no_active_agent_result(session, world, wake_event_ids)
        except AgentLLMStalled as exc:
            session.commit()
            return TurnResult(event_ids=[exc.event_id], acted_agent_id=exc.agent_id, acted_agent_ids=[], status="llm_stalled")

    async def _run_single_agent_turn(self, session: Session, world: World, agent: Agent, *, task: ReactionTask, initial_event_ids: list[int]) -> TurnResult:
        danger_ids, prep_status = await self._prepare_agent_for_turn(session, world, agent)
        danger_ids = initial_event_ids + danger_ids
        if prep_status != "ready":
            if danger_ids:
                session.commit()
            narration_event_ids = await maybe_create_narration(session, world, danger_ids, force=bool(danger_ids))
            session.flush()
            return TurnResult(
                event_ids=danger_ids,
                narration_event_ids=narration_event_ids,
                acted_agent_id=agent.agent_id,
                acted_agent_ids=[],
                status=prep_status,
            )

        action = _template_child_action(session, world, agent) or await self._choose_action(session, world, agent, reaction=True, trigger_text=task.trigger_text)
        if task.source_agent_id and action.tool_name == "ignore":
            action.params = {**action.params, "_ignored_source_agent_id": task.source_agent_id}
        result = execute_tool(session, world=world, actor=agent, tool_name=action.tool_name, params=action.params, reaction=True)
        all_event_ids = danger_ids + result.event_ids
        depth = task.chain_depth + 1
        self._enqueue_reactions(session, world, agent, result, depth)
        if all_event_ids:
            session.commit()
        schedule_daily_summary_tasks(session, world)
        session.commit()
        narration_event_ids = await maybe_create_narration(session, world, all_event_ids, force=result.importance >= 70)
        session.flush()
        return TurnResult(all_event_ids, narration_event_ids, agent.agent_id, [agent.agent_id])

    async def _run_regular_batch(self, session: Session, world: World, agents: list[Agent], *, initial_event_ids: list[int]) -> TurnResult:
        runtime = _runtime_settings(world)
        if runtime.request_mode == "parallel":
            return await self._run_regular_batch_parallel(session, world, agents, initial_event_ids=initial_event_ids, runtime=runtime)
        if runtime.display_mode == "per_agent":
            return await self._run_regular_batch_per_agent(session, world, agents, initial_event_ids=initial_event_ids)
        return await self._run_regular_batch_serial(session, world, agents, initial_event_ids=initial_event_ids)

    async def _run_regular_batch_serial(self, session: Session, world: World, agents: list[Agent], *, initial_event_ids: list[int]) -> TurnResult:
        base_time = world.current_world_time_minutes
        all_event_ids = list(initial_event_ids)
        planned: list[tuple[Agent, ActionChoice]] = []
        acted_agent_ids: list[str] = []
        max_end_time = base_time
        max_importance = 0

        for agent in agents:
            world.current_world_time_minutes = base_time
            danger_ids, prep_status = await self._prepare_agent_for_turn(session, world, agent)
            all_event_ids.extend(danger_ids)
            if prep_status != "ready":
                continue
            action = _template_child_action(session, world, agent) or await self._choose_action(session, world, agent, reaction=False, trigger_text=None)
            planned.append((agent, action))

        for agent, action in sorted(planned, key=lambda item: _batch_execution_priority(item[1].tool_name)):
            if agent.lifecycle_state not in {"alive", "critical"} or _is_sleeping(agent, world) or _is_unconscious(agent, world):
                continue
            world.current_world_time_minutes = base_time
            result = execute_tool(session, world=world, actor=agent, tool_name=action.tool_name, params=action.params, reaction=False)
            max_end_time = max(max_end_time, world.current_world_time_minutes)
            max_importance = max(max_importance, result.importance)
            all_event_ids.extend(result.event_ids)
            acted_agent_ids.append(agent.agent_id)
            self._enqueue_reactions(session, world, agent, result, depth=1)

        world.current_world_time_minutes = max_end_time
        if all_event_ids:
            session.commit()
        schedule_daily_summary_tasks(session, world)
        session.commit()
        narration_event_ids = await maybe_create_narration(session, world, all_event_ids, force=max_importance >= 70)
        session.flush()
        return TurnResult(
            event_ids=all_event_ids,
            narration_event_ids=narration_event_ids,
            acted_agent_id=acted_agent_ids[0] if acted_agent_ids else None,
            acted_agent_ids=acted_agent_ids,
            status="batch_ok" if acted_agent_ids else "batch_no_action",
        )

    async def _run_regular_batch_per_agent(self, session: Session, world: World, agents: list[Agent], *, initial_event_ids: list[int]) -> TurnResult:
        all_event_ids = list(initial_event_ids)
        acted_agent_ids: list[str] = []
        max_importance = 0
        if initial_event_ids:
            session.commit()
            await _broadcast_step_progress(world.world_id, initial_event_ids, [])

        for agent in agents:
            danger_ids, prep_status = await self._prepare_agent_for_turn(session, world, agent)
            if danger_ids:
                all_event_ids.extend(danger_ids)
                session.commit()
                await _broadcast_step_progress(world.world_id, danger_ids, [])
            if prep_status != "ready":
                continue
            action = _template_child_action(session, world, agent) or await self._choose_action(session, world, agent, reaction=False, trigger_text=None)
            if agent.lifecycle_state not in {"alive", "critical"} or _is_sleeping(agent, world) or _is_unconscious(agent, world):
                continue
            result = execute_tool(session, world=world, actor=agent, tool_name=action.tool_name, params=action.params, reaction=False)
            max_importance = max(max_importance, result.importance)
            all_event_ids.extend(result.event_ids)
            acted_agent_ids.append(agent.agent_id)
            self._enqueue_reactions(session, world, agent, result, depth=1)
            session.commit()
            await _broadcast_step_progress(world.world_id, result.event_ids, [agent.agent_id])

        schedule_daily_summary_tasks(session, world)
        session.commit()
        narration_event_ids = await maybe_create_narration(session, world, all_event_ids, force=max_importance >= 70)
        session.flush()
        if narration_event_ids:
            session.commit()
            await _broadcast_step_progress(world.world_id, narration_event_ids, [])
        return TurnResult(
            event_ids=all_event_ids,
            narration_event_ids=narration_event_ids,
            acted_agent_id=acted_agent_ids[0] if acted_agent_ids else None,
            acted_agent_ids=acted_agent_ids,
            status="serial_per_agent_ok" if acted_agent_ids else "serial_per_agent_no_action",
        )

    async def _run_regular_batch_parallel(self, session: Session, world: World, agents: list[Agent], *, initial_event_ids: list[int], runtime: RuntimeSettings) -> TurnResult:
        base_time = world.current_world_time_minutes
        all_event_ids = list(initial_event_ids)
        planned: list[tuple[Agent, ActionChoice]] = []
        llm_agent_ids: list[str] = []
        acted_agent_ids: list[str] = []
        max_end_time = base_time
        max_importance = 0

        for agent in agents:
            world.current_world_time_minutes = base_time
            danger_ids, prep_status = await self._prepare_agent_for_turn(session, world, agent)
            all_event_ids.extend(danger_ids)
            if prep_status != "ready":
                continue
            template_action = _template_child_action(session, world, agent)
            if template_action:
                planned.append((agent, template_action))
            else:
                llm_agent_ids.append(agent.agent_id)

        if all_event_ids:
            session.commit()

        choices = await asyncio.gather(
            *[
                self._choose_action_in_fresh_session(
                    world.world_id,
                    agent_id,
                    base_time=base_time,
                    concurrency_limits=runtime.concurrency_limits,
                )
                for agent_id in llm_agent_ids
            ]
        )
        for agent_id, action in choices:
            agent = session.get(Agent, agent_id)
            if agent:
                planned.append((agent, action))

        for agent, action in sorted(planned, key=lambda item: _batch_execution_priority(item[1].tool_name)):
            if agent.lifecycle_state not in {"alive", "critical"} or _is_sleeping(agent, world) or _is_unconscious(agent, world):
                continue
            world.current_world_time_minutes = base_time
            result = execute_tool(session, world=world, actor=agent, tool_name=action.tool_name, params=action.params, reaction=False)
            max_end_time = max(max_end_time, world.current_world_time_minutes)
            max_importance = max(max_importance, result.importance)
            all_event_ids.extend(result.event_ids)
            acted_agent_ids.append(agent.agent_id)
            self._enqueue_reactions(session, world, agent, result, depth=1)

        world.current_world_time_minutes = max_end_time
        if all_event_ids:
            session.commit()
        schedule_daily_summary_tasks(session, world)
        session.commit()
        narration_event_ids = await maybe_create_narration(session, world, all_event_ids, force=max_importance >= 70)
        session.flush()
        return TurnResult(
            event_ids=all_event_ids,
            narration_event_ids=narration_event_ids,
            acted_agent_id=acted_agent_ids[0] if acted_agent_ids else None,
            acted_agent_ids=acted_agent_ids,
            status="parallel_batch_ok" if acted_agent_ids else "parallel_batch_no_action",
        )

    async def _choose_action_in_fresh_session(self, world_id: str, agent_id: str, *, base_time: int, concurrency_limits: dict) -> tuple[str, ActionChoice]:
        with SessionLocal() as session:
            world = session.get(World, world_id)
            agent = session.get(Agent, agent_id)
            if not world or not agent:
                return agent_id, ActionChoice(tool_name="do_nothing", params={}, plan_summary="agent not available")
            world.current_world_time_minutes = base_time
            try:
                action = await self._choose_action(
                    session,
                    world,
                    agent,
                    reaction=False,
                    trigger_text=None,
                    concurrency_limits=concurrency_limits,
                )
                session.commit()
                return agent_id, action
            except AgentLLMStalled:
                session.commit()
                raise

    async def _prepare_agent_for_turn(self, session: Session, world: World, agent: Agent) -> tuple[list[int], str]:
        ensure_agent_home(session, world, agent)
        apply_time_decay(agent, world.current_world_time_minutes)
        danger_ids = apply_corpse_exposure(session, world, agent)
        danger_ids.extend(apply_danger_checks(session, world, agent))
        life_event_ids = await process_world_life_events(session, world, agent)
        danger_ids.extend(life_event_ids)
        if _is_unconscious(agent, world):
            return danger_ids, "agent_unconscious"
        if agent.lifecycle_state == "dead":
            _enqueue_death_reactions(session, world, agent, danger_ids)
            return danger_ids, "agent_dead"
        write_drive_state(world, agent)
        return danger_ids, "ready"

    def _enqueue_reactions(self, session: Session, world: World, agent: Agent, result: ExecutionResult, depth: int) -> None:
        if not _events_have_repeat_penalty(session, result.event_ids):
            reaction_ids = list(dict.fromkeys([*result.reaction_agent_ids, *_child_need_reaction_ids(session, world, agent, result.event_ids)]))
            for target_id in reaction_ids:
                if target_id != agent.agent_id:
                    reaction_queue.push(
                        world.world_id,
                        ReactionTask(target_id, _events_text(session, result.event_ids), depth, source_agent_id=agent.agent_id),
                        settings.max_reaction_chain,
                    )

    async def _no_active_agent_result(self, session: Session, world: World, wake_event_ids: list[int]) -> TurnResult:
        if _has_alive_agents(session, world):
            next_wake = _next_inactive_wake_time(session, world)
            if next_wake and next_wake > world.current_world_time_minutes:
                world.current_world_time_minutes = next_wake
                wake_event_ids.extend(process_daily_economy_tick(session, world))
                wake_event_ids.extend(_wake_due_sleepers(session, world))
                wake_event_ids.extend(_wake_due_unconscious(session, world))
                if wake_event_ids:
                    session.commit()
                schedule_daily_summary_tasks(session, world)
                session.commit()
                narration_event_ids = await maybe_create_narration(session, world, wake_event_ids, force=bool(wake_event_ids))
                session.flush()
                return TurnResult(event_ids=wake_event_ids, narration_event_ids=narration_event_ids, status="sleep_advanced")
            if wake_event_ids:
                session.commit()
                schedule_daily_summary_tasks(session, world)
                session.commit()
                narration_event_ids = await maybe_create_narration(session, world, wake_event_ids, force=True)
                session.flush()
                return TurnResult(event_ids=wake_event_ids, narration_event_ids=narration_event_ids, status="sleep_wake_only")
            return TurnResult(status="all_agents_sleeping")
        world.status = "ended"
        return TurnResult(event_ids=wake_event_ids, status="no_alive_agents")

    def _reaction_agent(self, session: Session, world: World, task: ReactionTask | None) -> Agent | None:
        if not task:
            return None
        agent = session.get(Agent, task.agent_id)
        if agent and agent.lifecycle_state in {"alive", "critical"} and not _is_sleeping(agent, world) and not _is_unconscious(agent, world):
            return agent
        return None

    def _next_regular_agent(self, session: Session, world: World) -> Agent | None:
        agents = self._regular_agent_batch(session, world)
        return agents[0] if agents else None

    def _regular_agent_batch(self, session: Session, world: World) -> list[Agent]:
        agents = list(
            session.execute(
                select(Agent)
                .where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))
                .order_by(Agent.created_at_world_time.asc(), Agent.agent_id.asc())
            ).scalars()
        )
        agents = [agent for agent in agents if not _is_sleeping(agent, world) and not _is_unconscious(agent, world)]
        if not agents:
            return []
        idx = self._round_robin_index.get(world.world_id, 0) % len(agents)
        self._round_robin_index[world.world_id] = idx + 1
        return agents[idx:] + agents[:idx]

    async def _choose_action(self, session: Session, world: World, agent: Agent, *, reaction: bool, trigger_text: str | None, concurrency_limits: dict | None = None) -> ActionChoice:
        urgent = _urgent_survival_action(session, agent, reaction=reaction)
        if urgent:
            return urgent
        exploration = _early_exploration_action(session, world, agent, reaction=reaction)
        if exploration:
            return exploration

        context = build_turn_context_with_options(session, world, agent, reaction=reaction, trigger_text=trigger_text)
        prompt = context.prompt
        action_options = context.action_options
        location = agent.location.location if agent.location else None
        tools = available_tools(agent, location, reaction=reaction, session=session)
        allowed = {tool.tool_name for tool in tools}
        language = world_language(world)
        output_language_rule = action_language_instruction(language)
        system = (
            "你是虚拟世界中的居民，只能通过本回合行动编号行动。"
            "你不能编造工具名、目标、地点、参数或数值变化。"
            "第一行只写行动头：[编号]；需要数值时写 [编号:数值]。"
            "如果行动需要说话或写作，从第二行开始直接写正文。"
            f"{output_language_rule}"
            "不要使用大括号结构，不要解释，不要 Markdown。"
            "不要把中文代词或临时编号和日语敬称混用；禁止写“你さん”“TAさん”“他さん”“她さん”“附近人物Aさん”。"
            "正文是你的自由发言/记录/提议空间，可以自然表达复杂情绪、误解、拒绝、试探、亲近或痛苦；"
            "后端只解析第一行行动头，不会用正则切分正文。"
            "你具备普通人的日常生活常识: 人需要定期吃饭、喝水、睡足觉、洗澡清洁、适当社交和放松；"
            "没钱吃饭或交租时应考虑工作、打零工、求助或其他可行办法。"
            "夜里和连续清醒很久时，睡眠非常重要，但系统不会替你决定是否睡觉；不睡会积累严重后果。"
            "夜间也可能出现社交、加班、偷窃等机会，犯罪结果和司法后果由后端硬规则判定。"
            "如果你选择加班换更多钱，必须清楚那是在牺牲睡眠、健康和情绪，不是免费收益。"
        )
        collective_core_prompt = _collective_core_prompt(world)
        if collective_core_prompt:
            system = f"【集体核心提示词】\n{collective_core_prompt}\n\n{system}"
        if agent.custom_system_prompt:
            system += f"\n用户给你的额外系统提示: {agent.custom_system_prompt}"

        result = await self._request_action_choice(
            agent,
            system_prompt=system,
            user_prompt=prompt,
            options=action_options,
            temperature=0.75,
            concurrency_limits=concurrency_limits or _runtime_settings(world).concurrency_limits,
        )
        if _record_llm_result(session, world, agent, result, phase="action_choice") and isinstance(result.parsed_object, ActionChoice):
            action = _align_sleep_intent_to_tool(session, world, agent, result.parsed_object, allowed=allowed, reaction=reaction)
            action = _align_adult_intimacy_intent_to_tool(session, world, agent, action, allowed=allowed, reaction=reaction)
            if action.tool_name in allowed:
                validation = validate_tool(
                    session,
                    actor=agent,
                    tool_name=action.tool_name,
                    params=action.params,
                    world_time=world.current_world_time_minutes,
                    reaction=reaction,
                    persist_visibility=False,
                )
                if validation.ok:
                    if _would_repeat_action(session, world, agent, action.tool_name):
                        repaired = await self._repair_action(
                            session,
                            world,
                            agent,
                            prompt=prompt,
                            system_prompt=system,
                            options=action_options,
                            attempted=action,
                            reason="你已经连续做了同类行动。继续重复会变得无聊，请换成不同类别的行动，比如移动、工作、阅读、整理补给、休息、写笔记或照顾身体需求。",
                            reaction=reaction,
                            concurrency_limits=concurrency_limits,
                        )
                        if repaired and not _would_repeat_action(session, world, agent, repaired.tool_name):
                            return repaired
                        varied = _varied_fallback_action(session, world, agent, allowed)
                        if varied:
                            return varied
                    if action_conflicts_with_pain(agent, _action_text(action)):
                        pain_repaired = await self._repair_action(
                            session,
                            world,
                            agent,
                            prompt=prompt,
                            system_prompt=system,
                            options=action_options,
                            attempted=action,
                            reason=pain_repair_reason(agent),
                            reaction=reaction,
                            concurrency_limits=concurrency_limits,
                        )
                        if pain_repaired:
                            return pain_repaired
                    return action
                repaired = await self._repair_action(
                    session,
                    world,
                    agent,
                    prompt=prompt,
                    system_prompt=system,
                    options=action_options,
                    attempted=action,
                    reason=validation.message or "行动参数不完整。",
                    reaction=reaction,
                    concurrency_limits=concurrency_limits,
                )
                if repaired:
                    return repaired
            else:
                repaired = await self._repair_action(
                    session,
                    world,
                    agent,
                    prompt=prompt,
                    system_prompt=system,
                    options=action_options,
                    attempted=action,
                    reason=f"{action.tool_name} 不在当前位置可用行动菜单中。",
                    reaction=reaction,
                    concurrency_limits=concurrency_limits,
                )
                if repaired:
                    return repaired
        varied = _varied_fallback_action(session, world, agent, allowed)
        if varied and not _would_repeat_action(session, world, agent, varied.tool_name):
            return varied
        return _fallback_action(session, world, agent, reaction=reaction, trigger_text=trigger_text)

    async def _request_action_choice(
        self,
        agent: Agent,
        *,
        system_prompt: str,
        user_prompt: str,
        options: list[ActionOption],
        temperature: float,
        concurrency_limits: dict | None = None,
    ) -> LLMResult:
        if not options:
            return LLMResult("", None, {}, 0, provider.provider_name, "当前没有可选行动。")
        result = await provider.complete_text(
            model_alias=agent.model_alias,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            model_name=agent.model_name,
            base_url=agent.llm_base_url,
            api_key=agent.llm_api_key,
            provider_name=agent.model_provider_name,
            concurrency_limits=concurrency_limits,
            **llm_runtime_kwargs(agent_llm_runtime(agent)),
        )
        parsed = _parse_action_choice_from_result(result, options, agent)
        if parsed:
            return LLMResult(result.raw_text, parsed, result.token_usage, result.latency_ms, result.provider_name)
        if result.error:
            return result
        repair_prompt = (
            "你的上一条回复没有被系统识别为行动头。\n"
            f"可选编号: {ids_hint(options)}。\n"
            f"上一条回复: {result.raw_text[:300]}\n"
            f"现在按格式输出：第一行 [编号] 或 [编号:数值]；如果需要说话/写作，第二行开始写正文。{action_language_instruction(world_language_for_agent(agent))}"
        )
        retry = await provider.complete_text(
            model_alias=agent.model_alias,
            system_prompt=system_prompt,
            user_prompt=repair_prompt,
            temperature=0.0,
            model_name=agent.model_name,
            base_url=agent.llm_base_url,
            api_key=agent.llm_api_key,
            provider_name=agent.model_provider_name,
            concurrency_limits=concurrency_limits,
            **llm_runtime_kwargs(agent_llm_runtime(agent)),
        )
        parsed_retry = _parse_action_choice_from_result(retry, options, agent)
        if parsed_retry:
            return LLMResult(retry.raw_text, parsed_retry, retry.token_usage, retry.latency_ms, retry.provider_name)
        raw = retry.raw_text or result.raw_text
        return LLMResult(raw, None, retry.token_usage or result.token_usage, retry.latency_ms or result.latency_ms, retry.provider_name or result.provider_name, "模型没有返回可用行动头。")

    async def _repair_action(
        self,
        session: Session,
        world: World,
        agent: Agent,
        *,
        prompt: str,
        system_prompt: str,
        options: list[ActionOption],
        attempted: ActionChoice,
        reason: str,
        reaction: bool,
        concurrency_limits: dict | None = None,
    ) -> ActionChoice | None:
        repair_prompt = f"""
{prompt}

【上一次行动被系统拒绝】
你刚才选择: {attempted.plan_summary or attempted.tool_name}
拒绝原因: {reason}

请重新从同一个行动编号菜单里选择一个更合适的编号。
第一行只写 [编号] 或 [编号:数值]。
如果你需要说话、解释、拒绝、告别或表达痛苦，从第二行开始写正文。
{action_language_instruction(world_language(world))}
如果系统指出你处于严重痛苦、濒死、恶臭、脱水、饥饿或崩溃状态，你可以强撑或苦笑，但不能把自己写得笑眯眯、轻松、悠闲、完全没事。
"""
        result = await self._request_action_choice(
            agent,
            system_prompt=system_prompt,
            user_prompt=repair_prompt,
            options=options,
            temperature=0.35,
            concurrency_limits=concurrency_limits or _runtime_settings(world).concurrency_limits,
        )
        if not _record_llm_result(session, world, agent, result, phase="repair_action") or not isinstance(result.parsed_object, ActionChoice):
            return None
        action = result.parsed_object
        allowed = {tool.tool_name for tool in available_tools(agent, agent.location.location if agent.location else None, reaction=reaction, session=session)}
        action = _align_sleep_intent_to_tool(session, world, agent, action, allowed=allowed, reaction=reaction)
        if action.tool_name not in allowed:
            return None
        validation = validate_tool(
            session,
            actor=agent,
            tool_name=action.tool_name,
            params=action.params,
            world_time=world.current_world_time_minutes,
            reaction=reaction,
            persist_visibility=False,
        )
        if not validation.ok or _would_repeat_action(session, world, agent, action.tool_name):
            return None
        return action



def _parse_action_choice_from_result(result: LLMResult, options: list[ActionOption], agent: Agent) -> ActionChoice | None:
    # LLM outputs are always plain chat-completion packets. parsed_object is ignored on purpose.
    packet = parse_action_packet(result.raw_text)
    if not packet:
        return None
    return packet_to_action_choice(packet, options, agent=agent)


def world_language_for_agent(agent: Agent) -> str:
    return world_language(agent.world)


def _localized(world: World, zh: str, en: str) -> str:
    return en if world_language(world) == "en" else zh

def _fallback_action(session: Session, world: World, agent: Agent, *, reaction: bool, trigger_text: str | None) -> ActionChoice:
    state = agent.dynamic_state
    urgent = _urgent_survival_action(session, agent, reaction=reaction)
    if urgent:
        return urgent
    visible_prompt, ref_map = build_turn_context(session, world, agent, reaction=reaction, trigger_text=trigger_text)
    refs = list(ref_map.keys())
    forced_response = _pending_forced_fallback_action(session, world, agent, ref_map) if reaction and refs else None
    if forced_response:
        return forced_response
    pending_response = _pending_social_fallback_action(session, world, agent, ref_map) if reaction and refs else None
    if pending_response:
        return pending_response
    if reaction and trigger_text and "介绍" in trigger_text and refs:
        if agent.intro_policy == "open" or (agent.intro_policy == "selective" and agent.traits.caution < 65):
            return ActionChoice(tool_name="introduce_self", params={"visible_ref": refs[0], "reveal_name": True, "reveal_gender": agent.gender_publicity, "speech": _localized(world, f"你好，我叫{agent.chosen_name}，很高兴认识你。", f"Hi, my name is {agent.chosen_name}. It's nice to meet you.")})
        return ActionChoice(tool_name="refuse_introduction", params={"visible_ref": refs[0], "speech": _localized(world, "抱歉，我现在还不太想透露名字。", "Sorry, I don't want to share my name yet.")})
    if reaction and refs:
        return ActionChoice(tool_name="speak_to_nearby", params={"speech": _localized(world, "我听见了。先让我确认一下这是不是在叫我。", "I heard that. Let me first make sure whether you were talking to me."), "tone": "neutral"})
    profile = profile_for_agent(agent)
    food_price = int(profile["food_price"])
    if state.hydration < float(profile["reaction_hydration"]) and "water" in (agent.location.location.tags_json if agent.location else []):
        return ActionChoice(tool_name="drink_water", params={})
    if state.satiety < float(profile["reaction_satiety"]) and "food_service" in (agent.location.location.tags_json if agent.location else []) and wallet_money(agent) >= food_price:
        return ActionChoice(tool_name="eat_food", params={})
    minute = world.current_world_time_minutes % 1440
    if not reaction and state.energy < 30 and (minute >= 21 * 60 or minute < 6 * 60):
        home_id = ((agent.wallet_json or {}).get("housing") or {}).get("home_location_id")
        if home_id and agent.location and agent.location.location_id != home_id:
            return ActionChoice(tool_name="return_home", params={"sleep_after_arrival": True, "sleep_hours": 8}, plan_summary="回到自己的住所并直接睡觉。")
        if home_id and agent.location and agent.location.location_id == home_id:
            return ActionChoice(tool_name="sleep", params={"sleep_hours": 8}, plan_summary="安排一段长睡眠。")
    if refs and random.Random(world.seed + world.current_world_time_minutes).random() < 0.45:
        return ActionChoice(tool_name="ask_visible_agent_to_introduce", params={"visible_ref": refs[0]})
    if refs:
        return ActionChoice(tool_name="speak_to_nearby", params={"speech": _localized(world, "你好，我刚到这里，想先了解一下周围。", "Hi, I just arrived here and want to understand the area first."), "tone": "friendly"})
    if agent.location:
        neighbors = adjacent_location_ids(session, agent.location.location)
        if neighbors:
            return ActionChoice(tool_name="wander", params={"location_id": random.choice(neighbors)})
    return ActionChoice(tool_name="do_nothing", params={})


def _pending_forced_fallback_action(session: Session, world: World, agent: Agent, ref_map: dict[str, str]) -> ActionChoice | None:
    visible_by_id = {agent_id: ref for ref, agent_id in ref_map.items()}
    request = choose_forced_action_for_fallback(session, agent, world.current_world_time_minutes)
    if not request:
        return None
    requester_id = str(request.get("from_agent_id") or "")
    visible_ref = visible_by_id.get(requester_id)
    if not visible_ref or not session.get(Agent, requester_id):
        return None
    from app.knowledge.relationships import get_relationship

    rel = get_relationship(session, agent.agent_id, requester_id)
    traits = agent.traits
    action_type = str(request.get("action_type") or "")
    base_params = {"visible_ref": visible_ref, "forced_action_id": request.get("forced_action_id"), "action_type": action_type}
    fear_conflict = rel.fear + rel.conflict
    warmth = rel.trust * 0.45 + rel.affection * 0.35 + rel.familiarity * 0.2
    caution = traits.caution if traits else 50
    empathy = traits.empathy if traits else 50
    if action_type == "adult_boundary":
        if caution + empathy >= 80:
            return ActionChoice(tool_name="protest_forced_action_visible_agent", params={**base_params, "speech": _localized(world, "停下。你不能这样越过我的边界。", "Stop. You cannot cross my boundaries like that.")}, plan_summary="明确抗议严重边界侵犯企图。")
        return ActionChoice(tool_name="dodge_forced_action_visible_agent", params=base_params, plan_summary="尝试躲开严重边界侵犯企图。")
    if fear_conflict >= 55 or caution >= 72 or warmth < 28:
        return ActionChoice(tool_name="dodge_forced_action_visible_agent", params=base_params, plan_summary="注意到对方没有先询问，先躲开。")
    if warmth >= 62 and fear_conflict < 35 and caution < 62:
        return ActionChoice(tool_name="allow_forced_action_visible_agent", params=base_params, plan_summary="虽然有些突然，但选择暂时不躲。")
    return ActionChoice(tool_name="protest_forced_action_visible_agent", params={**base_params, "speech": _localized(world, "先停一下。下次请先问我。", "Please stop for a moment. Next time, ask me first.")}, plan_summary="抗议未经同意的动作。")


def _pending_social_fallback_action(session: Session, world: World, agent: Agent, ref_map: dict[str, str]) -> ActionChoice | None:
    visible_by_id = {agent_id: ref for ref, agent_id in ref_map.items()}
    request = choose_social_request_for_fallback(session, agent, world.current_world_time_minutes)
    if not request:
        return None
    requester_id = str(request.get("from_agent_id") or "")
    visible_ref = visible_by_id.get(requester_id)
    if not visible_ref or not session.get(Agent, requester_id):
        return None
    from app.knowledge.relationships import get_relationship

    rel = get_relationship(session, agent.agent_id, requester_id)
    traits = agent.traits
    fear_conflict = rel.fear + rel.conflict
    warmth = rel.trust * 0.45 + rel.affection * 0.35 + rel.familiarity * 0.2
    empathy = traits.empathy if traits else 50
    caution = traits.caution if traits else 50
    request_type = str(request.get("request_type") or "")
    base_params = {"visible_ref": visible_ref, "request_id": request.get("request_id"), "request_type": request_type}
    threshold = 38 + max(0, caution - 50) * 0.25 if request_type in {"hug", "hold_hands", "date", "relationship"} else 26 + max(0, caution - 60) * 0.15
    if fear_conflict >= 70 or warmth + empathy * 0.15 < threshold:
        return ActionChoice(
            tool_name="decline_social_request_visible_agent",
            params={**base_params, "speech": _localized(world, "我听见你的请求了，但我现在不想这样做。请先尊重我的边界。", "I heard your request, but I don't want to do that right now. Please respect my boundaries first.")},
            plan_summary="回应待处理请求，但选择拒绝或推迟。",
        )
    return ActionChoice(
        tool_name="accept_social_request_visible_agent",
        params={**base_params, "speech": _localized(world, "我愿意。我们就这样做吧。", "I agree. Let's do that.")},
        plan_summary="接受对方刚才提出的请求。",
    )


def _batch_execution_priority(tool_name: str) -> int:
    # Social actions are resolved before movement so people who started in the same
    # place can still hear each other within the same simulated time slice.
    if tool_name in {
        "say_to_visible_agent",
        "speak_to_nearby",
        "compliment_visible_agent",
        "apologize_to_visible_agent",
        "introduce_self",
        "ask_visible_agent_to_introduce",
        "refuse_introduction",
        "wave_to_visible_agent",
        "casual_chat_visible_agent",
        "ask_about_needs",
        "comfort_visible_agent",
        "invite_visible_agent_to_walk",
        "ask_for_help_from_visible_agent",
        "set_boundary_visible_agent",
        "thank_visible_agent",
        "discuss_feelings_visible_agent",
        "accept_social_request_visible_agent",
        "decline_social_request_visible_agent",
        "force_hug_visible_agent",
        "force_hold_hands_visible_agent",
        "force_comfort_visible_agent",
        "force_help_visible_agent",
        "force_walk_together_visible_agent",
        "force_date_visible_agent",
        "force_relationship_claim_visible_agent",
        "attempt_forced_adult_boundary_visible_agent",
        "dodge_forced_action_visible_agent",
        "allow_forced_action_visible_agent",
        "protest_forced_action_visible_agent",
        "express_affection_visible_agent",
        "ask_date_visible_agent",
        "hold_hands_visible_agent",
        "hug_visible_agent",
        "confess_feelings_visible_agent",
        "define_relationship_visible_agent",
        "discuss_romantic_boundaries_visible_agent",
        "break_up_visible_agent",
        "repair_relationship_visible_agent",
        "request_adult_intimacy_visible_agent",
        "accept_adult_intimacy_visible_agent",
        "decline_adult_intimacy_visible_agent",
        "share_food_with_visible_agent",
        "share_water_with_visible_agent",
        "grant_personal_resource_permission_visible_agent",
        "call_community_meeting",
        "propose_social_rule",
        "support_social_rule",
        "oppose_social_rule",
    }:
        return 0
    if tool_name in {"move_to_location", "wander", "return_home", "sleep", "sleep_rough", "child_sleep"}:
        return 2
    return 1


def _is_unconscious(agent: Agent, world: World) -> bool:
    until = _unconscious_until(agent) or 0
    return until > world.current_world_time_minutes


def _template_child_action(session: Session, world: World, agent: Agent) -> ActionChoice | None:
    if agent.age_stage not in {"newborn", "infant", "toddler"}:
        return None
    state = agent.dynamic_state
    if not state:
        return ActionChoice(tool_name="cry_for_comfort", params={})

    # 婴幼儿不是成人决策器：他们主要通过哭、靠近、观察、睡眠、简单求助表达身体需求。
    if state.satiety < 72 or state.hydration < 72:
        return ActionChoice(tool_name="cry_for_food", params={})
    if state.energy < 35:
        return ActionChoice(tool_name="child_sleep", params={})
    if state.hygiene < 35 or state.stress > 68:
        return ActionChoice(tool_name="cry_for_comfort", params={})

    has_guardian = _visible_guardian_ref(session, world, agent)
    if agent.age_stage == "newborn":
        rng = random.Random(f"{world.seed}:{world.current_world_time_minutes}:{agent.agent_id}:newborn")
        return ActionChoice(tool_name="cry_for_comfort" if rng.random() < 0.65 else "child_sleep", params={})
    if agent.age_stage == "infant":
        return ActionChoice(tool_name="observe_parent" if has_guardian else "signal_need", params={})
    # toddler 已经会更主动地表示需求，但仍不能使用成人逻辑。
    if has_guardian:
        rng = random.Random(f"{world.seed}:{world.current_world_time_minutes}:{agent.agent_id}:toddler")
        return ActionChoice(tool_name="ask_help_child" if rng.random() < 0.45 else "observe_parent", params={})
    return ActionChoice(tool_name="signal_need", params={})


def _urgent_survival_action(session: Session, agent: Agent, *, reaction: bool = False) -> ActionChoice | None:
    state = agent.dynamic_state
    location = agent.location.location if agent.location else None
    if not state or not location:
        return None
    tags = set(location.tags_json or [])
    profile = profile_for_agent(agent)
    hydration_limit = float(profile["reaction_hydration"] if reaction else profile["urgent_hydration"])
    satiety_limit = float(profile["reaction_satiety"] if reaction else profile["urgent_satiety"])
    food_price = int(profile["food_price"])
    # 水和食物仍然是最硬的生存危机；睡眠只在接近身体崩溃时进入急迫分支，日常睡眠交给提示词和意图修复。
    if state.hydration <= hydration_limit:
        if _inventory_quantity(session, agent.agent_id, "瓶装水") + _inventory_quantity(session, agent.agent_id, "水壶") > 0:
            return ActionChoice(tool_name="drink_bottled_water", params={})
        if "water" in tags:
            return ActionChoice(tool_name="drink_water", params={})
        next_step = _next_step_toward_tag(session, location, "water")
        if next_step:
            return ActionChoice(tool_name="move_to_location", params={"location_id": next_step.location_id})
        return ActionChoice(tool_name="request_water_help", params={})
    if state.satiety <= satiety_limit:
        if _inventory_quantity(session, agent.agent_id, "便携食物") > 0:
            return ActionChoice(tool_name="eat_portable_food", params={})
        if "food_service" in tags and wallet_money(agent) >= food_price:
            return ActionChoice(tool_name="eat_food", params={})
        if wallet_money(agent) < food_price and state.energy >= 30:
            if "work" in tags:
                return ActionChoice(tool_name="do_odd_job", params={})
            next_work = _next_step_toward_tag(session, location, "work")
            if next_work:
                return ActionChoice(tool_name="move_to_location", params={"location_id": next_work.location_id})
        next_step = _next_step_toward_tag(session, location, "food_service")
        if next_step:
            return ActionChoice(tool_name="move_to_location", params={"location_id": next_step.location_id})
        return ActionChoice(tool_name="request_food_help", params={})
    energy_limit = float(profile["reaction_energy"] if reaction else profile["urgent_energy"])
    if state.energy <= energy_limit:
        hours = _recommended_sleep_hours(agent, minimum=7.0)
        if "home" in tags:
            return ActionChoice(tool_name="sleep", params={"sleep_hours": hours}, plan_summary="体力已经低到危险程度，决定真正睡一觉恢复。")
        home_id = ((agent.wallet_json or {}).get("housing") or {}).get("home_location_id")
        housing = (agent.wallet_json or {}).get("housing") or {}
        if home_id and not housing.get("homeless") and not reaction:
            return ActionChoice(tool_name="return_home", params={"sleep_after_arrival": True, "sleep_hours": hours}, plan_summary="体力接近耗尽，回家后直接睡。")
        return ActionChoice(tool_name="sleep_rough", params={"sleep_hours": hours}, plan_summary="体力已经撑不住，只能在当前地点露宿。")
    return None


def _recommended_sleep_hours(agent: Agent, *, minimum: float = 6.0) -> float:
    world_time = 0
    try:
        # 调用者通常已经有 world；这个函数只基于 agent 内部状态保守估算。
        raw_now = (agent.dynamic_state.last_decay_world_time if agent.dynamic_state else None)
        world_time = int(raw_now) if raw_now is not None else 0
    except (TypeError, ValueError):
        world_time = 0
    desires = agent.desires_json or {}
    raw_awake = desires.get("awake_since_world_time")
    try:
        awake_since = int(raw_awake) if raw_awake is not None else int(agent.created_at_world_time or 0)
    except (TypeError, ValueError):
        awake_since = world_time
    awake_hours = max(0.0, (world_time - awake_since) / 60)
    if agent.dynamic_state and agent.dynamic_state.energy <= 8:
        return max(minimum, 9.0)
    if awake_hours >= 22:
        return max(minimum, 9.0)
    if awake_hours >= 16:
        return max(minimum, 8.0)
    return max(minimum, 7.0)


def _action_text(action: ActionChoice) -> str:
    params = action.params or {}
    parts = [action.tool_name, action.plan_summary or ""]
    for key in ("speech", "content", "thought", "reason", "note"):
        value = params.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


def _has_sleep_intent(text: str) -> bool:
    lowered = text.lower()
    tokens = [
        "睡", "睡觉", "睡一觉", "睡眠", "入睡", "躺下", "困", "犯困", "疲惫", "累到", "撑不住", "休息一晚", "回家休息", "回家睡",
        "sleep", "go to bed", "tired", "exhausted",
    ]
    return any(token in lowered for token in tokens)


def _has_sleep_opt_out(text: str) -> bool:
    # 明确选择熬夜/继续行动时，不把它修成睡觉。这样保留高自由度。
    tokens = [
        "不睡", "先不睡", "暂时不睡", "不能睡", "不想睡", "熬夜", "通宵", "再撑", "继续工作", "继续加班", "继续聊", "守夜", "巡逻", "行动", "偷", "抢", "攻击",
        "stay awake", "not sleep", "keep working", "pull an all-nighter",
    ]
    return any(token in text.lower() for token in tokens)


ADULT_INTIMACY_ACTION_TOOLS = {
    "request_adult_intimacy_visible_agent",
    "accept_adult_intimacy_visible_agent",
    "decline_adult_intimacy_visible_agent",
    "attempt_forced_adult_boundary_visible_agent",
}


def _has_adult_intimacy_intent(text: str) -> bool:
    lowered = text.lower()
    tokens = [
        "成年亲密", "更亲密", "亲密相处", "亲密时光", "亲密一晚", "亲密关系",
        "进一步", "更进一步", "不只是拥抱", "不只是牵手", "一起过夜", "共度夜晚", "留宿",
        "今晚留下", "今晚别走", "只属于我们", "想和你睡", "一起睡", "发生关系",
        "adult intimacy", "spend the night", "sleep together", "be intimate",
    ]
    return any(token in lowered for token in tokens)


def _has_adult_intimacy_opt_out(text: str) -> bool:
    lowered = text.lower()
    tokens = [
        "不想", "不要", "不可以", "拒绝", "推迟", "以后再说", "只是朋友", "柏拉图", "不进行",
        "不愿意", "边界", "尊重我的边界", "stop", "no", "not ready", "not tonight",
    ]
    return any(token in lowered for token in tokens)


def _pending_intimacy_from(agent: Agent, requester_id: str) -> bool:
    for request in (agent.family_json or {}).get("pending_intimacy_requests", []):
        if request.get("from_agent_id") == requester_id and request.get("status") == "pending":
            return True
    return False


def _visible_ref_for_implied_adult_intimacy(session: Session, world: World, agent: Agent, action: ActionChoice) -> str | None:
    params = retarget_params_by_explicit_address(session, world, agent, action.tool_name, action.params or {})
    ref = str(params.get("visible_ref") or "").strip()
    if ref:
        return ref
    explicit = mentioned_visible_agent_ids(session, agent, world, _action_text(action))
    if len(explicit) == 1:
        return visible_ref_for_agent_id(session, agent, world, explicit[0])
    return None


def _align_adult_intimacy_intent_to_tool(session: Session, world: World, agent: Agent, action: ActionChoice, *, allowed: set[str], reaction: bool) -> ActionChoice:
    if action.tool_name in ADULT_INTIMACY_ACTION_TOOLS:
        return action
    text = _action_text(action)
    if not _has_adult_intimacy_intent(text) or _has_adult_intimacy_opt_out(text):
        return action
    visible_ref = _visible_ref_for_implied_adult_intimacy(session, world, agent, action)
    if not visible_ref:
        return action
    target = resolve_visible_ref(session, agent, visible_ref, world.current_world_time_minutes, persist=False)
    if not target or target.age_stage != "adult" or agent.age_stage != "adult":
        return action
    speech = "\n".join(str((action.params or {}).get(key) or "") for key in ("speech", "content", "note")).strip() or "我想和你抽象地进入更亲密的相处，可以吗？"
    if _pending_intimacy_from(agent, target.agent_id) and "accept_adult_intimacy_visible_agent" in allowed:
        return ActionChoice(tool_name="accept_adult_intimacy_visible_agent", params={"visible_ref": visible_ref, "speech": speech}, plan_summary="台词已经表达同意成年亲密，转为正式同意工具。")
    if "request_adult_intimacy_visible_agent" in allowed:
        return ActionChoice(tool_name="request_adult_intimacy_visible_agent", params={"visible_ref": visible_ref, "speech": speech}, plan_summary="台词已经表达成年亲密意图，转为正式请求工具。")
    return action


def _align_sleep_intent_to_tool(session: Session, world: World, agent: Agent, action: ActionChoice, *, allowed: set[str], reaction: bool) -> ActionChoice:
    text = _action_text(action)
    if not _has_sleep_intent(text) or _has_sleep_opt_out(text):
        return action
    # 如果它本来就选了睡眠工具，只补合理参数。
    hours = _recommended_sleep_hours(agent, minimum=7.0)
    if action.tool_name == "sleep":
        return ActionChoice(tool_name="sleep", params={**(action.params or {}), "sleep_hours": (action.params or {}).get("sleep_hours", hours)}, plan_summary=action.plan_summary)
    if action.tool_name == "sleep_rough":
        return ActionChoice(tool_name="sleep_rough", params={**(action.params or {}), "sleep_hours": (action.params or {}).get("sleep_hours", hours)}, plan_summary=action.plan_summary)
    if action.tool_name == "return_home":
        return ActionChoice(tool_name="return_home", params={**(action.params or {}), "sleep_after_arrival": True, "sleep_hours": (action.params or {}).get("sleep_hours", hours)}, plan_summary=action.plan_summary or "回家后直接睡觉。")
    tags = set(agent.location.location.tags_json or []) if agent.location else set()
    if "sleep" in allowed and "home" in tags:
        return ActionChoice(tool_name="sleep", params={"sleep_hours": hours}, plan_summary="刚才已经明确想睡觉，所以实际进入睡眠。")
    if "return_home" in allowed and not reaction:
        return ActionChoice(tool_name="return_home", params={"sleep_after_arrival": True, "sleep_hours": hours}, plan_summary="刚才已经明确想睡觉，所以回家后直接睡。")
    if "sleep_rough" in allowed:
        return ActionChoice(tool_name="sleep_rough", params={"sleep_hours": hours}, plan_summary="刚才已经明确想睡觉，但当前不在住所，于是选择露宿。")
    return action


def _early_exploration_action(session: Session, world: World, agent: Agent, *, reaction: bool = False) -> ActionChoice | None:
    if reaction or not agent.location:
        return None
    location = agent.location.location
    if "private" not in set(location.tags_json or []):
        return None
    recent_self_events = list(
        session.execute(
            select(Event)
            .where(
                Event.world_id == world.world_id,
                Event.actor_agent_id == agent.agent_id,
                Event.event_type.not_in(["narration", "narrator_failed", "tool_failed", "birth", "dream_summary"]),
            )
            .order_by(Event.event_id.desc())
            .limit(4)
        ).scalars()
    )
    if any(event.event_type == "move" for event in recent_self_events):
        return None
    non_birth_actions = [event for event in recent_self_events if event.event_type != "birth"]
    if len(non_birth_actions) < 1 and world.current_world_time_minutes < 20:
        return None
    for neighbor_id in adjacent_location_ids(session, location):
        if neighbor_id.endswith(":central_square"):
            return ActionChoice(tool_name="move_to_location", params={"location_id": neighbor_id}, plan_summary="离开小屋，去公共地点看看。")
    neighbors = adjacent_location_ids(session, location)
    if neighbors:
        return ActionChoice(tool_name="move_to_location", params={"location_id": neighbors[0]}, plan_summary="离开小屋，去附近走走。")
    return None


def _next_step_toward_tag(session: Session, start: Location, tag: str) -> Location | None:
    visited = {start.location_id}
    queue: deque[tuple[Location, list[str]]] = deque([(start, [])])
    while queue:
        location, path = queue.popleft()
        if path and tag in (location.tags_json or []):
            return session.get(Location, path[0])
        for neighbor_id in adjacent_location_ids(session, location):
            if neighbor_id in visited:
                continue
            neighbor = session.get(Location, neighbor_id)
            if not neighbor:
                continue
            visited.add(neighbor_id)
            queue.append((neighbor, path + [neighbor_id]))
    return None


def _inventory_quantity(session: Session, agent_id: str, item_name: str) -> int:
    rows = session.execute(
        select(Inventory)
        .join(Item, Item.item_id == Inventory.item_id)
        .where(Inventory.agent_id == agent_id, Item.name == item_name)
    ).scalars()
    return sum(inv.quantity for inv in rows)


def _visible_guardian_ref(session: Session, world: World, agent: Agent) -> bool:
    _, ref_map = build_turn_context(session, world, agent, reaction=False, trigger_text=None)
    guardians = set((agent.family_json or {}).get("guardian_agent_ids") or [])
    return any(agent_id in guardians for agent_id in ref_map.values())


def _events_have_repeat_penalty(session: Session, event_ids: list[int]) -> bool:
    for event_id in event_ids:
        event = session.get(Event, event_id)
        if event and (event.payload or {}).get("repeat_penalty"):
            return True
    return False


def _would_repeat_action(session: Session, world: World, agent: Agent, tool_name: str) -> bool:
    event_type = _predicted_event_type(tool_name)
    if not event_type or tool_name in _SURVIVAL_REPEAT_EXEMPT:
        return False
    recent = list(
        session.execute(
            select(Event)
            .where(
                Event.world_id == world.world_id,
                Event.actor_agent_id == agent.agent_id,
                Event.event_type.not_in(["narration", "narrator_failed", "tool_failed", "birth", "dream_summary"]),
            )
            .order_by(Event.event_id.desc())
            .limit(6)
        ).scalars()
    )
    consecutive = 0
    for event in recent:
        if event.event_type == event_type:
            consecutive += 1
        else:
            break
    if event_type in {"look", "self_status", "nothing"}:
        threshold = 1
    elif event_type == "dialogue":
        threshold = 2
    elif event_type in {"rest", "panic", "move", "memory_review", "inventory", "private_note", "meal_plan", "clean_clothes", "short_walk", "doodle", "breathing"}:
        threshold = 2
    else:
        threshold = 3
    return consecutive >= threshold


def _varied_fallback_action(session: Session, world: World, agent: Agent, allowed: set[str]) -> ActionChoice | None:
    state = agent.dynamic_state
    if not state:
        return None
    if (
        "move_to_location" in allowed
        and agent.location
        and "private" in set(agent.location.location.tags_json or [])
        and adjacent_location_ids(session, agent.location.location)
    ):
        return ActionChoice(tool_name="move_to_location", params={"location_id": adjacent_location_ids(session, agent.location.location)[0]})
    no_param_priority: list[str] = []
    if state.fun < 25:
        no_param_priority.extend(["read_quietly", "sketch_or_doodle", "take_short_walk", "practice_skill", "hum_to_self"])
    if state.stress > 45:
        no_param_priority.extend(["breathe_fresh_air", "meditate", "take_work_break", "rest"])
    if state.energy < 35:
        no_param_priority.extend(["sleep", "return_home", "sleep_rough", "take_work_break", "rest"])
    no_param_priority.extend(
        [
            "plan_next_meal",
            "check_supplies",
            "organize_inventory",
            "review_recent_memory",
            "plan_day",
            "write_private_note",
            "clean_clothes",
            "practice_skill",
            "read_quietly",
            "take_short_walk",
            "ignore",
        ]
    )
    for name in dict.fromkeys(no_param_priority):
        if name in allowed and not _would_repeat_action(session, world, agent, name):
            return ActionChoice(tool_name=name, params={})

    _, ref_map = build_turn_context(session, world, agent, reaction=False, trigger_text=None)
    refs = list(ref_map.keys())
    if refs:
        visible_priority = [
            ("walk_away_from_visible_agent", {}),
            ("set_boundary_visible_agent", {"speech": "我想先换个节奏，等会儿再继续聊。", "tone": "calm"}),
            ("ask_about_needs", {"speech": "先不反复闲聊了，你现在更需要食物、水、休息，还是换个地方？", "tone": "friendly"}),
            ("comfort_visible_agent", {"speech": "我们别一直重复同一句话，先慢慢做点实际的事。", "tone": "friendly"}),
        ]
        for name, extra in visible_priority:
            if name in allowed and not _would_repeat_action(session, world, agent, name):
                return ActionChoice(tool_name=name, params={"visible_ref": refs[0], **extra})

    if "move_to_location" in allowed and agent.location:
        neighbors = adjacent_location_ids(session, agent.location.location)
        if neighbors:
            destination_id = random.choice(neighbors)
            return ActionChoice(tool_name="move_to_location", params={"location_id": destination_id})
    if "do_nothing" in allowed:
        return ActionChoice(tool_name="do_nothing", params={})
    return None


_SURVIVAL_REPEAT_EXEMPT = {
    "eat_food",
    "drink_water",
    "eat_portable_food",
    "drink_bottled_water",
    "sleep",
    "sleep_rough",
    "fill_canteen",
    "pack_lunch",
    "buy_portable_food",
    "buy_bottled_water",
    "request_food_help",
    "request_water_help",
    "accept_community_aid",
}


_TOOL_EVENT_TYPES = {
    "look_around": "look",
    "observe_visible_agent": "observe",
    "check_self_status": "self_status",
    "move_to_location": "move",
    "return_home": "return_home",
    "wander": "move",
    "say_to_visible_agent": "dialogue",
    "speak_to_nearby": "dialogue",
    "compliment_visible_agent": "dialogue",
    "apologize_to_visible_agent": "dialogue",
    "introduce_self": "introduce_self",
    "ask_visible_agent_to_introduce": "ask_introduction",
    "refuse_introduction": "refuse_introduction",
    "wave_to_visible_agent": "gesture",
    "ignore": "ignore",
    "help_visible_agent": "help",
    "move_closer_to_visible_agent": "move_closer",
    "walk_away_from_visible_agent": "walk_away",
    "rest": "rest",
    "panic_pause": "panic",
    "do_nothing": "nothing",
    "write_diary": "diary",
    "add_memory": "memory",
    "tell_story_nearby": "story",
    "sing_nearby": "sing",
    "play_simple_game": "game",
    "check_supplies": "supplies",
    "take_work_break": "work_break",
    "complain_about_work": "work",
    "apply_for_job": "work",
    "do_odd_job": "work",
    "work_shift_cafeteria": "work",
    "work_shift_cook": "work",
    "work_shift_cleaner": "work",
    "work_overtime_shift": "work_overtime",
    "quit_job": "work",
    "stretch_body": "stretch",
    "plan_day": "plan",
    "meditate": "meditate",
    "tidy_room": "tidy",
    "read_quietly": "read",
    "practice_skill": "practice",
    "enjoy_scenery": "scenery",
    "hum_to_self": "hum",
    "review_recent_memory": "memory_review",
    "organize_inventory": "inventory",
    "write_private_note": "private_note",
    "plan_next_meal": "meal_plan",
    "clean_clothes": "clean_clothes",
    "take_short_walk": "short_walk",
    "sketch_or_doodle": "doodle",
    "breathe_fresh_air": "breathing",
    "casual_chat_visible_agent": "dialogue",
    "ask_about_needs": "dialogue",
    "comfort_visible_agent": "dialogue",
    "invite_visible_agent_to_walk": "dialogue",
    "invite_visible_agent_to_hot_spring": "dialogue",
    "ask_for_help_from_visible_agent": "dialogue",
    "set_boundary_visible_agent": "dialogue",
    "thank_visible_agent": "dialogue",
    "discuss_feelings_visible_agent": "dialogue",
    "accept_social_request_visible_agent": "social_interaction_completed",
    "decline_social_request_visible_agent": "social_request_declined",
    "express_affection_visible_agent": "romance",
    "ask_date_visible_agent": "romance",
    "hold_hands_visible_agent": "romance",
    "hug_visible_agent": "romance",
    "confess_feelings_visible_agent": "romance_confession",
    "define_relationship_visible_agent": "relationship",
    "discuss_romantic_boundaries_visible_agent": "boundary",
    "break_up_visible_agent": "relationship",
    "repair_relationship_visible_agent": "relationship_repair",
    "request_adult_intimacy_visible_agent": "adult_intimacy_request",
    "accept_adult_intimacy_visible_agent": "adult_intimacy",
    "decline_adult_intimacy_visible_agent": "adult_intimacy_declined",
    "attempt_petty_theft_visible_agent": "crime_petty_theft",
    "demand_money_visible_agent": "crime_robbery",
    "attack_visible_agent": "crime_attack",
    "report_unknown_theft": "law_report",
    "confront_visible_agent_about_crime": "dialogue",
    "report_known_crime_by_name": "law_report",
    "forgive_visible_agent_crime": "law_forgiveness",
    "jail_rest": "jail_rest",
    "jail_low_paid_work": "jail_work",
    "jail_reflect": "jail_reflect",
    "jail_write_letter": "jail_letter",
    "jail_wait_release": "jail_wait",
    "refuse_jail_work": "jail_refuse",
    "attempt_jail_escape": "jail_escape",
    "share_food_with_visible_agent": "gift",
    "share_water_with_visible_agent": "gift",
    "grant_personal_resource_permission_visible_agent": "permission_grant",
    "call_community_meeting": "governance_meeting",
    "propose_social_rule": "governance_proposal",
    "support_social_rule": "governance_support",
    "oppose_social_rule": "governance_oppose",
    "request_more_candidate_tools": "candidate_request",
    "explain_available_tools": "candidate_request",
    "inspect_visible_corpse": "corpse_inspect",
    "mourn_visible_corpse": "corpse_mourn",
    "report_visible_corpse": "corpse_report",
    "bury_visible_corpse": "corpse_buried",
    "avoid_corpse_area": "corpse_avoid",
    "cry_for_food": "child_need",
    "cry_for_comfort": "child_need",
    "child_sleep": "child_sleep",
    "be_carried": "child_need",
    "observe_parent": "child_observe",
    "reach_item": "child_reach",
    "signal_need": "child_need",
    "ask_help_child": "child_need",
    "follow_guardian": "child_follow",
    "learn_simple_words": "child_learn",
    "practice_child_tool": "child_practice",
}


def _predicted_event_type(tool_name: str) -> str | None:
    return _TOOL_EVENT_TYPES.get(tool_name)


def _enqueue_death_reactions(session: Session, world: World, dead_agent: Agent, event_ids: list[int]) -> None:
    if not event_ids:
        return
    trigger_text = _events_text(session, event_ids) or f"{dead_agent.chosen_name or '某位居民'}死了。"
    for survivor_id in same_location_agent_ids(session, dead_agent):
        reaction_queue.push(
            world.world_id,
            ReactionTask(survivor_id, f"你亲眼看见了这件事: {trigger_text} 遗体就在这个地点。", 0, source_agent_id=dead_agent.agent_id),
            settings.max_reaction_chain,
        )


def _child_need_reaction_ids(session: Session, world: World, child: Agent, event_ids: list[int]) -> list[str]:
    if child.age_stage not in {"newborn", "infant", "toddler", "child"} or not event_ids or not child.location:
        return []
    events = list(session.execute(select(Event).where(Event.event_id.in_(event_ids))).scalars())
    if not any(event.event_type == "child_need" for event in events):
        return []
    location_ids = {child.location.location_id}
    location_ids.update(adjacent_location_ids(session, child.location.location))
    rows = session.execute(
        select(Agent)
        .join(Agent.location)
        .where(
            Agent.world_id == world.world_id,
            Agent.agent_id != child.agent_id,
            Agent.lifecycle_state.in_(["alive", "critical"]),
            AgentLocation.location_id.in_(location_ids),
        )
    ).scalars()
    candidate_ids = [agent.agent_id for agent in rows if not _is_sleeping(agent, world) and not _is_unconscious(agent, world)]
    return child_caregiver_reaction_ids(session, world, child, include_adjacent=candidate_ids)[:4]


def _sleep_until(agent: Agent) -> int | None:
    value = (agent.desires_json or {}).get("sleep_until_world_time")
    try:
        until = int(value)
    except (TypeError, ValueError):
        return None
    return until if until > 0 else None


def _is_sleeping(agent: Agent, world: World) -> bool:
    until = _sleep_until(agent)
    return bool(until and until > world.current_world_time_minutes)


def _has_alive_agents(session: Session, world: World) -> bool:
    return bool(
        session.execute(
            select(Agent.agent_id).where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"])).limit(1)
        ).first()
    )


def _next_sleep_wake_time(session: Session, world: World) -> int | None:
    wake_times = []
    agents = session.execute(
        select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))
    ).scalars()
    for agent in agents:
        until = _sleep_until(agent)
        if until and until > world.current_world_time_minutes:
            wake_times.append(until)
    return min(wake_times) if wake_times else None


def _next_inactive_wake_time(session: Session, world: World) -> int | None:
    wake_times = []
    agents = session.execute(
        select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))
    ).scalars()
    for agent in agents:
        for until in (_sleep_until(agent), _unconscious_until(agent)):
            if until and until > world.current_world_time_minutes:
                wake_times.append(until)
    return min(wake_times) if wake_times else None


def _wake_due_sleepers(session: Session, world: World) -> list[int]:
    event_ids: list[int] = []
    agents = session.execute(
        select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))
    ).scalars()
    for agent in agents:
        until = _sleep_until(agent)
        if until and until <= world.current_world_time_minutes:
            event_ids.extend(complete_scheduled_sleep(session, world, agent))
    return event_ids


def _wake_due_unconscious(session: Session, world: World) -> list[int]:
    event_ids: list[int] = []
    agents = session.execute(
        select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))
    ).scalars()
    for agent in agents:
        until = _unconscious_until(agent)
        if until and until <= world.current_world_time_minutes:
            event_ids.extend(apply_danger_checks(session, world, agent))
    return event_ids


def _unconscious_until(agent: Agent) -> int | None:
    value = (agent.desires_json or {}).get("unconscious_until_world_time")
    try:
        until = int(value)
    except (TypeError, ValueError):
        return None
    return until if until > 0 else None


def _events_text(session: Session, event_ids: list[int]) -> str:
    events = [session.get(Event, event_id) for event_id in event_ids]
    parts: list[str] = []
    for event in events:
        if not event:
            continue
        speech = (event.payload or {}).get("speech")
        if isinstance(speech, str) and speech:
            speaker = session.get(Agent, event.actor_agent_id) if event.actor_agent_id else None
            parts.append(
                f"{speaker.chosen_name if speaker and speaker.chosen_name else '有人'}在同一地点说: “{speech}”。"
                "这句话不一定是对你说的，请根据称呼、内容和上下文判断是否需要回应；如果不是在叫你，可以不回应。"
            )
        else:
            parts.append(event.viewer_text)
    return " ".join(parts)


turn_runner = TurnRunner()


LLM_FAILURE_PAUSE_THRESHOLD = 3


def _collective_core_prompt(world: World) -> str:
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    return str(settings_json.get("collective_core_prompt") or "").strip()


def _runtime_settings(world: World) -> RuntimeSettings:
    settings_json = world.settings_json if isinstance(world.settings_json, dict) else {}
    request_mode = str(settings_json.get("agent_request_mode") or "serial")
    if request_mode not in {"serial", "parallel"}:
        request_mode = "serial"
    display_mode = str(settings_json.get("event_display_mode") or "batch")
    if request_mode == "parallel":
        display_mode = "batch"
    elif display_mode not in {"batch", "per_agent"}:
        display_mode = "batch"
    raw_limits = settings_json.get("llm_concurrency")
    limits = raw_limits if isinstance(raw_limits, dict) else {}
    return RuntimeSettings(
        request_mode=request_mode,
        display_mode=display_mode,
        concurrency_limits={
            "default_provider_limit": _positive_limit(limits.get("default_provider_limit")),
            "provider_limits": _positive_limit_map(limits.get("provider_limits")),
            "model_limits": _positive_limit_map(limits.get("model_limits")),
        },
    )


async def _broadcast_step_progress(world_id: str, event_ids: list[int], acted_agent_ids: list[str]) -> None:
    await manager.broadcast(
        world_id,
        {
            "type": "world_state_updated",
            "world_id": world_id,
            "result": {
                "status": "step_progress",
                "event_ids": event_ids,
                "acted_agent_ids": acted_agent_ids,
            },
        },
    )


def _positive_limit_map(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, int] = {}
    for key, value in raw.items():
        limit = _positive_limit(value)
        if limit > 0:
            result[str(key)] = limit
    return result


def _positive_limit(value: object) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def _record_llm_result(session: Session, world: World, agent: Agent, result: LLMResult, *, phase: str) -> bool:
    """Return True when an LLM request produced a usable object; pause after repeated failures."""
    ok = result.error is None and result.parsed_object is not None
    learning = dict(agent.tool_learning_json or {})
    learning.update(
        {
            "last_llm_raw_text": (result.raw_text or "")[:1200],
            "last_llm_phase": phase,
            "last_llm_provider_name": result.provider_name,
            "last_llm_latency_ms": result.latency_ms,
        }
    )
    if ok:
        if learning.get("llm_consecutive_failures"):
            learning["llm_consecutive_failures"] = 0
            learning["last_llm_error"] = None
        agent.tool_learning_json = learning
        return True

    failures = int(learning.get("llm_consecutive_failures") or 0) + 1
    model_name = agent.model_name or settings.model_name(agent.model_alias or "world_agent")
    base_url = agent.llm_base_url or settings.llm_base_url
    error = result.error or "模型没有返回可用行动头。"
    learning.update(
        {
            "llm_consecutive_failures": failures,
            "last_llm_error": error[:600],
            "last_llm_failed_at_world_time": world.current_world_time_minutes,
            "last_llm_failure_phase": phase,
            "last_llm_model_name": model_name,
            "last_llm_base_url": base_url,
        }
    )
    agent.tool_learning_json = learning
    if failures < LLM_FAILURE_PAUSE_THRESHOLD:
        return False

    world.status = "paused"
    event = create_event(
        session,
        world=world,
        event_type="llm_stalled",
        actor_agent_id=agent.agent_id,
        location_id=agent.location.location_id if agent.location else None,
        viewer_text=(
            f"{agent.chosen_name} 的 LLM 连续 {failures} 次没有正常回复。游戏已自动暂停；"
            "可以再次开始游戏重试，也可以在居民详情里更换这个 agent 的 LLM。"
        ),
        importance=95,
        color_class="danger",
        payload={
            "failure_count": failures,
            "error": error,
            "phase": phase,
            "model_name": model_name,
            "base_url": base_url,
        },
    )
    session.flush()
    raise AgentLLMStalled(agent_id=agent.agent_id, event_id=event.event_id)
