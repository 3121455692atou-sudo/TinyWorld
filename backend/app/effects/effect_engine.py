from __future__ import annotations

import random
import re
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.state import initial_dynamic_state
from app.agents.state import apply_delta
from app.agents.traits import apply_trait_experience, random_traits_with_budget
from app.agents.v5_state import add_money, ensure_v5_agent_state, wallet_money
from app.content.toolsets import DEFAULT_AGENT_SPECIAL_TOOLSET_IDS
from app.core.config import settings
from app.core.models import Agent, AgentLocation, AgentTrait, Conversation, Event, Inventory, Item, Location, World
from app.economy.v6 import handle_v6_tool
from app.economy.work_schedule import can_do_odd_job, can_start_work_shift, effective_work_duration_minutes, job_offer_for_application
from app.effects.decay import apply_time_decay
from app.effects.drive_system import drive_action_snapshot, record_action_reward
from app.effects.worldpack_effects import handle_worldpack_declarative_tool
from app.events.event_store import create_event
from app.events.render_text import agent_name, render_move, render_say
from app.knowledge.identity_knowledge import observer_knows_name
from app.knowledge.relationships import adjust_relationship, get_relationship
from app.llm.openai_compatible import provider
from app.llm.language import normalize_language, world_language
from app.llm.runtime import agent_llm_runtime, llm_runtime_kwargs, normalize_llm_runtime
from app.llm.schemas import BabyNameDraft, IdentityDraft
from app.llm.text_protocols import baby_name_system, identity_protocol_system, identity_protocol_user_suffix, parse_baby_name, parse_identity_draft
from app.simulation.difficulty import profile_for_world, tool_time_cost
from app.memory.diary_service import write_diary_entry
from app.memory.memory_service import add_memory, auto_memory_for_event, create_sleep_dream_summary
from app.social.addressing import reaction_ids_for_public_speech, retarget_params_by_explicit_address, visible_listener_ids
from app.social.forced_actions import FORCED_SOCIAL_ACTION_TOOL_TYPES, FORCED_SOCIAL_RESPONSE_TOOLS, expire_old_forced_actions, handle_forced_social_action
from app.social.pending_requests import (
    SOCIAL_REQUEST_RESPONSE_TOOLS,
    SOCIAL_REQUEST_TOOL_TYPES,
    expire_old_social_requests,
    is_accept_social_request_tool,
    is_decline_social_request_tool,
    make_social_request,
    pending_social_request_by_id,
    pending_social_request_from,
    resolve_social_request,
    social_request_kind,
    social_response_request_type_for_tool,
    store_social_request,
)
from app.tools.registry import get_tool, reproduction_toolset_enabled
from app.tools.validators import ToolValidation, validate_tool
from app.world.corpses import CORPSE_TOOL_NAMES, handle_corpse_tool
from app.world.visibility import adjacent_location_ids, build_visible_people, location_public_name, mark_gender_known, mark_name_known, mark_visual_known


@dataclass(slots=True)
class ExecutionResult:
    ok: bool
    event_ids: list[int] = field(default_factory=list)
    reaction_agent_ids: list[str] = field(default_factory=list)
    message: str = ""
    importance: int = 0


def execute_tool(
    session: Session,
    *,
    world: World,
    actor: Agent,
    tool_name: str,
    params: dict[str, Any] | None = None,
    reaction: bool = False,
) -> ExecutionResult:
    params = params or {}
    ensure_v5_agent_state(actor)
    expire_old_social_requests(actor, world.current_world_time_minutes)
    expire_old_forced_actions(actor, world.current_world_time_minutes)
    params = retarget_params_by_explicit_address(session, world, actor, tool_name, params)
    validation = validate_tool(
        session,
        actor=actor,
        tool_name=tool_name,
        params=params,
        world_time=world.current_world_time_minutes,
        reaction=reaction,
    )
    if not validation.ok:
        return _record_failure(session, world, actor, validation)

    spec = get_tool(tool_name)
    assert spec is not None
    before_drive = drive_action_snapshot(world, actor)
    before_location_id = actor.location.location_id if actor.location else None
    action_duration = _actual_action_duration_minutes(world, actor, tool_name, spec.time_cost_minutes)
    actor.tool_learning_json = {**(actor.tool_learning_json or {}), "last_action_duration_minutes": action_duration, "last_action_tool_name": tool_name}
    world.current_world_time_minutes += action_duration
    state_delta: dict[str, Any] = {}
    event_ids: list[int] = []
    reactions: list[str] = []

    if tool_name == "look_around":
        people = build_visible_people(session, actor, world.current_world_time_minutes)
        text = f"{actor.chosen_name} 环顾四周，确认自己在 {location_public_name(session, before_location_id)}。"
        agent_text = text
        if people:
            viewer_people = []
            agent_people = []
            for person in people:
                target = session.get(Agent, person.target_agent_id)
                viewer_people.append(target.chosen_name if target and target.chosen_name else person.visible_ref)
                agent_people.append(f"{person.visible_ref}({person.appearance})")
            text += " 眼前有 " + "、".join(viewer_people) + "。"
            agent_text += " 眼前有 " + "、".join(agent_people) + "。"
        event = create_event(session, world=world, event_type="look", actor_agent_id=actor.agent_id, location_id=before_location_id, viewer_text=text, agent_visible_text=agent_text, importance=5)
        event_ids.append(event.event_id)

    elif tool_name == "observe_visible_agent":
        target = validation.target_agent
        assert target is not None
        mark_visual_known(session, actor, target, world.current_world_time_minutes)
        text = f"{actor.chosen_name} 仔细观察了 {target.chosen_name}。"
        agent_text = f"{actor.chosen_name} 仔细观察了 {_agent_target_label(session, actor, target)}。"
        event = create_event(session, world=world, event_type="observe", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=before_location_id, viewer_text=text, agent_visible_text=agent_text, importance=20)
        event_ids.append(event.event_id)

    elif tool_name == "check_self_status":
        st = actor.dynamic_state
        text = f"{actor.chosen_name} 检查了自己的状态: 生命{st.health:.0f}、体力{st.energy:.0f}、饱腹{st.satiety:.0f}、水分{st.hydration:.0f}。"
        event = create_event(session, world=world, event_type="self_status", actor_agent_id=actor.agent_id, location_id=before_location_id, viewer_text=text, importance=5)
        event_ids.append(event.event_id)

    elif tool_name in {"move_to_location", "wander"}:
        destination = validation.destination
        assert destination is not None and actor.location is not None
        actor.location.location_id = destination.location_id
        actor.location.location = destination
        actor.location.arrived_at_world_time = world.current_world_time_minutes
        event = create_event(
            session,
            world=world,
            event_type="move",
            actor_agent_id=actor.agent_id,
            location_id=destination.location_id,
            viewer_text=render_move(session, actor.agent_id, before_location_id, destination.location_id),
            importance=10,
            state_delta={"location": {"before": before_location_id, "after": destination.location_id}},
        )
        event_ids.append(event.event_id)

    elif tool_name == "return_home":
        event_ids.extend(_return_home_action(session, world, actor, before_location_id, state_delta, params))

    elif tool_name == "wake_visible_agent":
        target = validation.target_agent
        assert target is not None
        speech = _prevent_name_leak(session, actor, str(params.get("speech") or "醒醒，我有事想和你说。"))
        event = create_event(
            session,
            world=world,
            event_type="wake_request",
            actor_agent_id=actor.agent_id,
            target_agent_id=target.agent_id,
            location_id=before_location_id,
            viewer_text=f"{actor.chosen_name} 轻声叫醒了 {target.chosen_name}。",
            agent_visible_text=f"{actor.chosen_name} 轻声叫醒了 {_agent_target_label(session, actor, target)}。",
            importance=45,
            color_class="dialogue",
            payload={"speech": speech, "tone": str(params.get("tone") or "soft")},
        )
        event_ids.append(event.event_id)
        event_ids.extend(complete_scheduled_sleep(session, world, target, interrupted=True))
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-1, social=1))
        state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, stress=3, mood=-1))
        reactions.append(target.agent_id)

    elif tool_name in {"say_to_visible_agent", "compliment_visible_agent", "apologize_to_visible_agent"}:
        target = validation.target_agent
        assert target is not None
        speech = str(params.get("speech") or _localized(world, "你好，我想和你说句话。", "Hi, I want to say something to you."))
        tone = str(params.get("tone") or ("friendly" if tool_name != "say_to_visible_agent" else "neutral"))
        speech = _prevent_name_leak(session, actor, speech)
        convo_event = _conversation_event(session, world, actor, target, speech, tone, before_location_id)
        if params.get("_retargeted_by_speech"):
            convo_event.payload = {**(convo_event.payload or {}), "retargeted_by_speech": params.get("_retargeted_by_speech")}
        event_ids.append(convo_event.event_id)
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-1, social=3, mood=1))
        state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, social=2))
        friendly = tone in {"friendly", "playful"} or any(word in speech for word in ["谢谢", "你好", "愿意", "喜欢", "帮"])
        hostile = tone == "hostile" or any(word in speech for word in ["讨厌", "威胁", "滚开", "闭嘴"])
        adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, familiarity=2, affection=1 if friendly else 0, trust=-3 if hostile else 0, fear=2 if hostile else 0, conflict=3 if hostile else 0)
        adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=2, affection=1 if friendly else 0, trust=-3 if hostile else 0, fear=2 if hostile else 0, conflict=3 if hostile else 0)
        reactions.extend(reaction_ids_for_public_speech(session, world, actor, speech=speech, target=target, direct=True))

    elif tool_name == "speak_to_nearby":
        speech = _prevent_name_leak(session, actor, str(params.get("speech") or _localized(world, "大家好，我想说句话。", "Hello everyone, I want to say something.")))
        tone = str(params.get("tone") or "neutral")
        visible = build_visible_people(session, actor, world.current_world_time_minutes)
        text = render_say(actor.chosen_name or "某人", "", speech)
        heard_by = [p.target_agent_id for p in visible]
        addressed = reaction_ids_for_public_speech(session, world, actor, speech=speech, target=None, direct=False)
        event = create_event(session, world=world, event_type="dialogue", actor_agent_id=actor.agent_id, location_id=before_location_id, viewer_text=text, importance=60, color_class="dialogue", payload={"speech": speech, "tone": tone, "audience_count": len(visible), "heard_by_agent_ids": heard_by, "addressed_agent_ids": addressed})
        event_ids.append(event.event_id)
        session.add(
            Conversation(
                event_id=event.event_id,
                speaker_agent_id=actor.agent_id,
                target_agent_id=None,
                location_id=before_location_id,
                content_zh=speech,
                tone=tone,
                heard_by_agent_ids_json=heard_by,
                world_time=world.current_world_time_minutes,
            )
        )
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-1, social=4))
        reactions.extend(reaction_ids_for_public_speech(session, world, actor, speech=speech, target=None, direct=False))

    elif tool_name == "ask_visible_agent_to_introduce":
        target = validation.target_agent
        assert target is not None
        mark_visual_known(session, actor, target, world.current_world_time_minutes)
        text = f"{actor.chosen_name} 试探着问 {target.chosen_name} 愿不愿意介绍自己。"
        agent_text = f"{actor.chosen_name} 试探着问 {_agent_target_label(session, actor, target)} 愿不愿意介绍自己。"
        event = create_event(session, world=world, event_type="ask_introduction", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=before_location_id, viewer_text=text, agent_visible_text=agent_text, importance=45)
        event_ids.append(event.event_id)
        adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, familiarity=1)
        reactions.append(target.agent_id)

    elif tool_name == "introduce_self":
        target = validation.target_agent
        assert target is not None
        reveal_name = bool(params.get("reveal_name", True))
        reveal_gender = bool(params.get("reveal_gender", actor.gender_publicity))
        speech = str(params.get("speech") or _localized(world, f"你好，我叫{actor.chosen_name}。", f"Hi, my name is {actor.chosen_name}."))
        listeners = _listener_ids(session, actor, world)
        if reveal_name:
            for listener_id in listeners:
                mark_name_known(session, listener_id, actor, world.current_world_time_minutes, "self_intro", reveal_gender)
            speech = speech if actor.chosen_name in speech else _localized(world, f"你好，我叫{actor.chosen_name}。{speech}", f"Hi, my name is {actor.chosen_name}. {speech}")
        else:
            speech = _prevent_name_leak(session, actor, speech)
        text = f"{actor.chosen_name} 正式介绍了自己: “{speech}”" if reveal_name else f"{actor.chosen_name} 回应了介绍请求，但没有公开姓名: “{speech}”"
        event = create_event(
            session,
            world=world,
            event_type="introduce_self",
            actor_agent_id=actor.agent_id,
            target_agent_id=None,
            location_id=before_location_id,
            viewer_text=text,
            importance=70 if reveal_name else 55,
            payload={"reveal_name": reveal_name, "reveal_gender": reveal_gender, "speech": speech, "tone": "friendly", "audience_count": len(listeners)},
        )
        event_ids.append(event.event_id)
        session.add(Conversation(event_id=event.event_id, speaker_agent_id=actor.agent_id, target_agent_id=None, location_id=before_location_id, content_zh=speech, tone="friendly", is_identity_reveal=reveal_name, heard_by_agent_ids_json=listeners, world_time=world.current_world_time_minutes))
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, social=4, stress=4 if actor.intro_policy == "secretive" else 0))
        adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=8, trust=3)
        reactions.extend(listeners)

    elif tool_name == "refuse_introduction":
        target = validation.target_agent
        assert target is not None
        target_knows_name = observer_knows_name(session, target.agent_id, actor.agent_id)
        default_speech = _localized(world, "抱歉，我现在不太想聊这个。", "Sorry, I don't really want to talk about that right now.") if target_knows_name else _localized(world, "抱歉，我暂时不想透露名字。", "Sorry, I don't want to share my name yet.")
        speech = str(params.get("speech") or default_speech)
        speech = _prevent_name_leak(session, actor, speech)
        if target_knows_name:
            text = f"{actor.chosen_name} 没有继续自我介绍，只是把话题轻轻带开: “{speech}”"
        else:
            text = f"{actor.chosen_name} 没有说出自己的名字，只是把话题轻轻带开: “{speech}”"
        event = create_event(session, world=world, event_type="refuse_introduction", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=before_location_id, viewer_text=text, importance=55, payload={"speech": speech, "target_already_knew_name": target_knows_name})
        event_ids.append(event.event_id)
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=1))
        adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=1, trust=-2)
        reactions.extend(_listener_ids(session, actor, world))

    elif tool_name == "wave_to_visible_agent":
        target = validation.target_agent
        assert target is not None
        text = f"{actor.chosen_name} 朝 {target.chosen_name} 挥了挥手。"
        agent_text = f"{actor.chosen_name} 朝 {_agent_target_label(session, actor, target)} 挥了挥手。"
        event = create_event(session, world=world, event_type="gesture", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=before_location_id, viewer_text=text, agent_visible_text=agent_text, importance=20)
        event_ids.append(event.event_id)
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, social=1))
        state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, social=1))
        adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, familiarity=1)
        adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=1)
        reactions.append(target.agent_id)

    elif tool_name == "help_visible_agent":
        target = validation.target_agent
        assert target is not None
        text = f"{actor.chosen_name} 走近 {target.chosen_name}，试着提供帮助。"
        agent_text = f"{actor.chosen_name} 走近 {_agent_target_label(session, actor, target)}，试着提供帮助。"
        event = create_event(session, world=world, event_type="help", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=before_location_id, viewer_text=text, agent_visible_text=agent_text, importance=55)
        event_ids.append(event.event_id)
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-4, social=3, mood=2))
        state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, stress=-5, social=4, mood=3))
        adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=5, trust=4, affection=3)
        reactions.append(target.agent_id)

    elif tool_name == "move_closer_to_visible_agent":
        target = validation.target_agent
        assert target is not None
        text = f"{actor.chosen_name} 稍微靠近了 {target.chosen_name}。"
        agent_text = f"{actor.chosen_name} 稍微靠近了 {_agent_target_label(session, actor, target)}。"
        event = create_event(session, world=world, event_type="move_closer", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=before_location_id, viewer_text=text, agent_visible_text=agent_text, importance=20)
        event_ids.append(event.event_id)
        adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, familiarity=1)
        reactions.append(target.agent_id)

    elif tool_name == "walk_away_from_visible_agent":
        target = validation.target_agent
        assert target is not None
        destination_id = (actor.location.location.neighbors_json or [before_location_id])[0] if actor.location else before_location_id
        if actor.location and destination_id:
            actor.location.location_id = destination_id
            destination = session.get(Location, destination_id)
            if destination:
                actor.location.location = destination
            actor.location.arrived_at_world_time = world.current_world_time_minutes
        text = f"{actor.chosen_name} 离开了 {target.chosen_name}，走向了{location_public_name(session, destination_id)}。"
        agent_text = f"{actor.chosen_name} 离开了 {_agent_target_label(session, actor, target)}，走向了{location_public_name(session, destination_id)}。"
        event = create_event(session, world=world, event_type="walk_away", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=destination_id, viewer_text=text, agent_visible_text=agent_text, importance=25, state_delta={"location": {"before": before_location_id, "after": destination_id}})
        event_ids.append(event.event_id)

    elif tool_name in {"eat_food", "drink_water", "sleep", "sleep_rough", "rest", "wash", "soak_hot_spring", "panic_pause", "do_nothing", "walk_by_lake"}:
        event_ids.extend(_self_care(session, world, actor, tool_name, before_location_id, state_delta, params))

    elif tool_name == "ignore":
        ignored_source_id = str(params.get("_ignored_source_agent_id") or "")
        ignored_source = session.get(Agent, ignored_source_id) if ignored_source_id else None
        event = create_event(
            session,
            world=world,
            event_type="ignore",
            actor_agent_id=actor.agent_id,
            target_agent_id=ignored_source.agent_id if ignored_source else None,
            location_id=before_location_id,
            viewer_text=f"{actor.chosen_name} 没有接话，只是把目光移开，先顾着自己的事。",
            importance=10,
        )
        event_ids.append(event.event_id)
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=-1))
        if reaction and ignored_source and ignored_source.dynamic_state:
            state_delta = _merge_delta(state_delta, ignored_source.agent_id, apply_delta(ignored_source.dynamic_state, social=-4, stress=2, mood=-2))
            desires = ignored_source.desires_json or {}
            ignored_source.desires_json = {**desires, "loneliness": min(100, int(desires.get("loneliness", 30)) + 6)}

    elif tool_name == "knock_private_room":
        event_ids.extend(_v5_private_room_action(session, world, actor, validation, tool_name, before_location_id, state_delta))
        reactions.extend(_listeners_for_events(session, event_ids, actor.agent_id))

    elif tool_name in {
        "check_supplies",
        "eat_portable_food",
        "drink_bottled_water",
        "fill_canteen",
        "pack_lunch",
        "buy_portable_food",
        "buy_bottled_water",
        "request_food_help",
        "request_water_help",
        "accept_community_aid",
    }:
        event_ids.extend(_v5_survival_or_inventory(session, world, actor, validation, tool_name, before_location_id, state_delta))
        reactions.extend(p.target_agent_id for p in build_visible_people(session, actor, world.current_world_time_minutes) if tool_name in {"request_food_help", "request_water_help"})

    elif tool_name in {
        "do_odd_job",
        "apply_for_job",
        "work_shift_cafeteria",
        "work_shift_cook",
        "work_shift_cleaner",
        "work_overtime_shift",
        "take_work_break",
        "complain_about_work",
        "quit_job",
    }:
        event_ids.extend(_v5_work_action(session, world, actor, tool_name, before_location_id, state_delta))
        if tool_name == "complain_about_work":
            reactions.extend(p.target_agent_id for p in build_visible_people(session, actor, world.current_world_time_minutes))

    elif tool_name in {
        "stretch_body",
        "plan_day",
        "meditate",
        "tidy_room",
        "read_quietly",
        "practice_skill",
        "enjoy_scenery",
        "hum_to_self",
        "review_recent_memory",
        "organize_inventory",
        "write_private_note",
        "plan_next_meal",
        "clean_clothes",
        "take_short_walk",
        "sketch_or_doodle",
        "breathe_fresh_air",
        "seek_conversation",
    }:
        event_ids.extend(_v5_emotion_action(session, world, actor, tool_name, before_location_id, state_delta))
        if tool_name == "seek_conversation":
            reactions.extend(p.target_agent_id for p in build_visible_people(session, actor, world.current_world_time_minutes))

    elif tool_name in {
        "casual_chat_visible_agent",
        "ask_about_needs",
        "comfort_visible_agent",
        "invite_visible_agent_to_walk",
        "invite_visible_agent_to_hot_spring",
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
    }:
        target = validation.target_agent
        assert target is not None
        if tool_name in FORCED_SOCIAL_ACTION_TOOL_TYPES or tool_name in FORCED_SOCIAL_RESPONSE_TOOLS:
            new_event_ids = handle_forced_social_action(session, world, actor, target, tool_name, params, before_location_id, state_delta)
            event_ids.extend(new_event_ids)
            reactions.extend(_listeners_for_events(session, new_event_ids, actor.agent_id))
        elif tool_name in SOCIAL_REQUEST_TOOL_TYPES or tool_name in SOCIAL_REQUEST_RESPONSE_TOOLS:
            new_event_ids = _v5_pending_social_action(session, world, actor, target, tool_name, params, before_location_id, state_delta)
            event_ids.extend(new_event_ids)
            reactions.extend(_listeners_for_events(session, new_event_ids, actor.agent_id))
        else:
            event = _v5_visible_social(session, world, actor, target, tool_name, params, before_location_id, state_delta)
            event_ids.append(event.event_id)
            reactions.extend(reaction_ids_for_public_speech(session, world, actor, speech=str((event.payload or {}).get("speech") or params.get("speech") or ""), target=target, direct=True))

    elif tool_name in {
        "express_affection_visible_agent",
        "ask_date_visible_agent",
        "hold_hands_visible_agent",
        "hug_visible_agent",
        "confess_feelings_visible_agent",
        "define_relationship_visible_agent",
        "discuss_romantic_boundaries_visible_agent",
        "break_up_visible_agent",
        "repair_relationship_visible_agent",
        "check_child_status_visible_agent",
        "soothe_child_visible_agent",
        "feed_child_visible_agent",
        "carry_child_visible_agent",
        "put_child_to_sleep_visible_agent",
        "care_for_child_visible_agent",
        "teach_child_simple_skill_visible_agent",
    }:
        target = validation.target_agent
        assert target is not None
        if tool_name in {"check_child_status_visible_agent", "soothe_child_visible_agent", "feed_child_visible_agent", "carry_child_visible_agent", "put_child_to_sleep_visible_agent", "care_for_child_visible_agent", "teach_child_simple_skill_visible_agent"}:
            event_ids.extend(_v5_child_care_action(session, world, actor, target, tool_name, before_location_id, state_delta))
        elif tool_name in SOCIAL_REQUEST_TOOL_TYPES:
            event_ids.extend(_v5_pending_social_action(session, world, actor, target, tool_name, params, before_location_id, state_delta))
        else:
            event_ids.extend(_v5_romance_action(session, world, actor, target, tool_name, before_location_id, state_delta))
        reactions.append(target.agent_id)

    elif tool_name in {
        "request_adult_intimacy_visible_agent",
        "accept_adult_intimacy_visible_agent",
        "decline_adult_intimacy_visible_agent",
    }:
        target = validation.target_agent
        assert target is not None
        event_ids.extend(_v5_adult_intimacy_action(session, world, actor, target, tool_name, before_location_id, state_delta))
        reactions.append(target.agent_id)

    elif tool_name in {"buy_contraception", "buy_pregnancy_test", "take_pregnancy_test"}:
        event_ids.extend(_v5_pregnancy_market_action(session, world, actor, tool_name, before_location_id, state_delta))

    elif tool_name in {
        "attempt_petty_theft_visible_agent",
        "attempt_burglary_private_room",
        "demand_money_visible_agent",
        "home_invasion_robbery_private_room",
        "attack_visible_agent",
        "report_unknown_theft",
        "confront_visible_agent_about_crime",
        "report_known_crime_by_name",
        "forgive_visible_agent_crime",
    }:
        event_ids.extend(_v5_crime_or_law_action(session, world, actor, validation, tool_name, params, before_location_id, state_delta))
        if validation.target_agent:
            reactions.append(validation.target_agent.agent_id)
        else:
            reactions.extend(_listeners_for_events(session, event_ids, actor.agent_id))

    elif tool_name in {"jail_rest", "jail_low_paid_work", "jail_reflect", "jail_write_letter", "jail_wait_release", "refuse_jail_work", "attempt_jail_escape"}:
        event_ids.extend(_v5_jail_action(session, world, actor, tool_name, before_location_id, state_delta))

    elif tool_name in {
        "request_more_candidate_tools",
        "explain_available_tools",
        "cry_for_food",
        "cry_for_comfort",
        "child_sleep",
        "be_carried",
        "observe_parent",
        "reach_item",
        "signal_need",
        "ask_help_child",
        "follow_guardian",
        "learn_simple_words",
        "practice_child_tool",
    }:
        event_ids.extend(_v5_meta_or_child_action(session, world, actor, tool_name, before_location_id, state_delta))

    elif tool_name in {"call_community_meeting", "propose_social_rule", "support_social_rule", "oppose_social_rule"}:
        event_ids.extend(_governance_action(session, world, actor, tool_name, params, before_location_id, state_delta))
        reactions.extend(_listeners_for_events(session, event_ids, actor.agent_id))

    elif tool_name in CORPSE_TOOL_NAMES:
        event_ids.extend(handle_corpse_tool(session, world, actor, tool_name, params, before_location_id, state_delta))
        reactions.extend(_listeners_for_events(session, event_ids, actor.agent_id))

    elif spec.hard_effect_id == "v6_catalog_generic" or tool_name.startswith("v6_"):
        event_ids.extend(handle_v6_tool(session, world, actor, tool_name, params, before_location_id, state_delta))

    elif spec.hard_effect_id == "worldpack_declarative":
        event_ids.extend(handle_worldpack_declarative_tool(session, world, actor, spec, params, before_location_id, state_delta))
        if validation.target_agent and spec.triggers_reaction:
            reactions.append(validation.target_agent.agent_id)

    elif spec.hard_effect_id == "v5_catalog_generic":
        if tool_name in SOCIAL_REQUEST_TOOL_TYPES or tool_name in SOCIAL_REQUEST_RESPONSE_TOOLS:
            target = validation.target_agent
            if target is not None:
                event_ids.extend(_v5_pending_social_action(session, world, actor, target, tool_name, params, before_location_id, state_delta))
                reactions.append(target.agent_id)
            else:
                event_ids.append(_simple_tool_failed(session, world, actor, before_location_id, "这个目录社交工具需要指定附近可见对象。").event_id)
        else:
            event_ids.extend(_v5_catalog_generic_action(session, world, actor, validation, spec, before_location_id, state_delta))
            if validation.target_agent and spec.triggers_reaction:
                reactions.append(validation.target_agent.agent_id)

    elif tool_name in {"share_food_with_visible_agent", "share_water_with_visible_agent"}:
        target = validation.target_agent
        assert target is not None
        event_ids.extend(_v5_share_supply(session, world, actor, target, tool_name, before_location_id, state_delta))
        reactions.append(target.agent_id)

    elif tool_name == "grant_personal_resource_permission_visible_agent":
        event_ids.extend(_grant_permission_action(session, world, actor, validation, params, before_location_id, state_delta))
        if validation.target_agent:
            reactions.append(validation.target_agent.agent_id)

    elif tool_name == "seek_help":
        text = f"{actor.chosen_name} 向附近的人求助。"
        importance = 75 if actor.dynamic_state.health < 40 or actor.dynamic_state.energy < 10 else 60
        event = create_event(session, world=world, event_type="seek_help", actor_agent_id=actor.agent_id, location_id=before_location_id, viewer_text=text, importance=importance)
        event_ids.append(event.event_id)
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=-2))
        reactions.extend(p.target_agent_id for p in build_visible_people(session, actor, world.current_world_time_minutes))

    elif tool_name in {"tell_story_nearby", "sing_nearby", "play_simple_game"}:
        event_ids.extend(_group_fun(session, world, actor, tool_name, params, before_location_id, state_delta))
        reactions.extend(p.target_agent_id for p in build_visible_people(session, actor, world.current_world_time_minutes))

    elif tool_name == "write_diary":
        write_diary_entry(session, actor, world.current_world_time_minutes, params.get("title"), params.get("content"))
        event = create_event(session, world=world, event_type="diary", actor_agent_id=actor.agent_id, location_id=before_location_id, visibility_scope="private", viewer_text=f"{actor.chosen_name} 写下了一篇私密日记。", importance=30)
        event_ids.append(event.event_id)
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=-5, mood=2))

    elif tool_name == "post_notice":
        content = str(params.get("content") or params.get("speech") or "愿大家都记得照顾自己。")
        event = create_event(session, world=world, event_type="notice", actor_agent_id=actor.agent_id, location_id=before_location_id, visibility_scope="public", viewer_text=f"{actor.chosen_name} 在布告栏贴出消息: “{content}”", importance=45, payload={"content": content})
        event_ids.append(event.event_id)

    elif tool_name in {"forage_food", "craft_simple_item", "pick_up_item", "give_item_to_visible_agent", "offer_item_to_visible_agent"}:
        event_ids.extend(_item_action(session, world, actor, validation, tool_name, params, before_location_id, state_delta))
        if validation.target_agent:
            reactions.append(validation.target_agent.agent_id)

    elif tool_name in {"add_memory", "record_relationship_note_by_name", "introduce_other_agent", "send_private_letter_by_name", "invite_named_agent_to_event", "make_public_accusation_by_name", "nominate_named_agent", "promise_to_named_agent"}:
        event_ids.extend(_memory_or_name_action(session, world, actor, validation, tool_name, params, before_location_id))
        if validation.target_agent:
            reactions.append(validation.target_agent.agent_id)

    else:
        event = create_event(
            session,
            world=world,
            event_type="system",
            actor_agent_id=actor.agent_id,
            location_id=before_location_id,
            viewer_text=f"{actor.chosen_name} 犹豫了一会儿，没有做出明确行动。",
            importance=5,
            payload={"tool_name": tool_name, "reason": "unhandled_tool"},
        )
        event_ids.append(event.event_id)

    _apply_repetition_penalty(session, world, actor, tool_name, event_ids, state_delta)
    for event_id in event_ids:
        event = session.get(Event, event_id)
        if event:
            related = [x for x in [event.actor_agent_id, event.target_agent_id] if x]
            auto_memory_for_event(session, event, related)
            if state_delta and not event.state_delta:
                event.state_delta = state_delta
    trait_growth = apply_trait_experience(actor, tool_name, world.current_world_time_minutes)
    if trait_growth and event_ids:
        first_event = session.get(Event, event_ids[0])
        if first_event:
            first_event.payload = {**(first_event.payload or {}), "trait_growth": trait_growth}
    record_action_reward(session, world, actor, tool_name, before_drive)
    return ExecutionResult(True, event_ids=event_ids, reaction_agent_ids=list(dict.fromkeys(reactions)), importance=max([0] + [_event_importance(session, e) for e in event_ids]))


def _actual_action_duration_minutes(world: World, actor: Agent, tool_name: str, fallback_minutes: int) -> int:
    if tool_name in {"work_shift_cafeteria", "work_shift_cook", "work_shift_cleaner", "work_shift_night_guard"}:
        return effective_work_duration_minutes(world, actor, tool_name, fallback_minutes)
    return tool_time_cost(world, tool_name, fallback_minutes)


def _apply_repetition_penalty(session: Session, world: World, actor: Agent, tool_name: str, event_ids: list[int], state_delta: dict[str, Any]) -> None:
    survival_repeat_exempt = {
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
    if tool_name in survival_repeat_exempt:
        return
    if not event_ids or not actor.dynamic_state:
        return
    current_event = session.get(Event, event_ids[0])
    if not current_event:
        return
    recent = list(
        session.execute(
            select(Event)
            .where(
                Event.world_id == world.world_id,
                Event.actor_agent_id == actor.agent_id,
                Event.event_id < current_event.event_id,
                Event.visibility_scope != "system",
            )
            .order_by(Event.event_id.desc())
            .limit(4)
        ).scalars()
    )
    consecutive = 0
    for previous in recent:
        if previous.event_type == current_event.event_type:
            consecutive += 1
        else:
            break
    low_info = {"look_around", "check_self_status", "do_nothing"}
    routine = {
        "rest",
        "panic_pause",
        "wander",
        "review_recent_memory",
        "organize_inventory",
        "write_private_note",
        "plan_next_meal",
        "clean_clothes",
        "take_short_walk",
        "sketch_or_doodle",
        "breathe_fresh_air",
    }
    threshold = 1 if tool_name in low_info else 2 if tool_name in routine else 3
    if consecutive < threshold:
        return
    fun_loss = min(8, 3 + consecutive)
    state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, fun=-fun_loss, stress=1, mood=-2))
    note = "反复做同样的事让这个行动开始变得无聊。"
    current_event.viewer_text = f"{current_event.viewer_text} {note}"
    current_event.agent_visible_text = f"{current_event.agent_visible_text} {note}"
    current_event.payload = {
        **(current_event.payload or {}),
        "repeat_penalty": {"reason": "boredom", "previous_same_actions": consecutive, "fun_loss": fun_loss},
    }


def _record_failure(session: Session, world: World, actor: Agent, validation: ToolValidation) -> ExecutionResult:
    event = create_event(
        session,
        world=world,
        event_type="tool_failed",
        actor_agent_id=actor.agent_id,
        location_id=actor.location.location_id if actor.location else None,
        visibility_scope="system",
        importance=50 if validation.reason_code == "name_unknown" else 10,
        color_class="warning" if validation.reason_code == "name_unknown" else "normal",
        viewer_text=f"{actor.chosen_name} 没能执行 {validation.tool_name}: {validation.message}",
        agent_visible_text=validation.message or "工具失败。",
        payload={"tool_name": validation.tool_name, "failure_reason_code": validation.reason_code},
        no_state_changed=True,
    )
    return ExecutionResult(False, [event.event_id], message=validation.message or "工具失败。", importance=event.importance)


def _conversation_event(session: Session, world: World, actor: Agent, target: Agent | None, speech: str, tone: str, location_id: str | None):
    target_label = target.chosen_name if target else "附近的人"
    viewer_text = render_say(actor.chosen_name or "某人", target_label or "附近的人", speech)
    agent_visible_text = render_say(actor.chosen_name or "某人", target_label or "附近的人", speech)
    heard_by = _listener_ids(session, actor, world)
    addressed_by_name = reaction_ids_for_public_speech(session, world, actor, speech=speech, target=target, direct=bool(target), include_group_when_public=False)
    event = create_event(
        session,
        world=world,
        event_type="dialogue",
        actor_agent_id=actor.agent_id,
        target_agent_id=target.agent_id if target else None,
        location_id=location_id,
        viewer_text=viewer_text,
        agent_visible_text=agent_visible_text,
        importance=60,
        color_class="dialogue",
        payload={"speech": speech, "tone": tone, "audience_count": len(heard_by), "heard_by_agent_ids": heard_by, "addressed_agent_ids": addressed_by_name},
    )
    session.add(
        Conversation(
            event_id=event.event_id,
            speaker_agent_id=actor.agent_id,
            target_agent_id=None,
            location_id=location_id,
            content_zh=speech,
            tone=tone,
            heard_by_agent_ids_json=heard_by,
            world_time=world.current_world_time_minutes,
        )
    )
    return event


def _listener_ids(session: Session, actor: Agent, world: World) -> list[str]:
    return visible_listener_ids(session, actor, world.current_world_time_minutes)


def _target_name_known(session: Session, actor: Agent, target: Agent) -> bool:
    from app.core.models import IdentityKnowledge

    knowledge = session.execute(
        select(IdentityKnowledge).where(
            IdentityKnowledge.observer_agent_id == actor.agent_id,
            IdentityKnowledge.target_agent_id == target.agent_id,
            IdentityKnowledge.name_known.is_(True),
        )
    ).scalar_one_or_none()
    return bool(knowledge)


def _agent_target_label(session: Session, actor: Agent, target: Agent) -> str:
    if _target_name_known(session, actor, target):
        return target.chosen_name or "某人"
    return f"那个{target.appearance_short or '外貌可辨'}的人"


def _prevent_name_leak(session: Session, actor: Agent, speech: str) -> str:
    from app.core.models import IdentityKnowledge

    known_target_ids = {
        row.target_agent_id
        for row in session.execute(
            select(IdentityKnowledge).where(
                IdentityKnowledge.observer_agent_id == actor.agent_id,
                IdentityKnowledge.name_known.is_(True),
            )
        ).scalars()
    }
    for other in session.execute(select(Agent).where(Agent.world_id == actor.world_id, Agent.agent_id != actor.agent_id)).scalars():
        if other.agent_id not in known_target_ids and other.chosen_name:
            speech = speech.replace(other.chosen_name, "你")
    return _sanitize_mixed_honorifics(speech)


def _sanitize_mixed_honorifics(text: str) -> str:
    text = re.sub(r"(你|妳|他|她|TA|ta|Ta)さん", r"\1", text)
    text = re.sub(r"(附近人物[A-ZＡ-Ｚ])さん", r"\1", text)
    return text


def _merge_delta(container: dict[str, Any], agent_id: str, delta: dict[str, Any]) -> dict[str, Any]:
    if delta:
        container.setdefault(agent_id, {}).update(delta)
    return container


FOOD_PRICE = 6
MAX_SLEEP_MINUTES_PER_DAY = 10 * 60


def _self_care(session: Session, world: World, actor: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any], params: dict[str, Any] | None = None) -> list[int]:
    profile = profile_for_world(world)
    labels = {
        "eat_food": ("eat", _variant(world, actor, "eat_food", ["买了一份热饭，慢慢吃完。", "在饭菜的热气里吃了一顿简单的饭。", "端着一份简餐坐下来，把饥饿压了下去。"]), {"satiety": 34, "hydration": -2, "mood": 2}, 35),
        "drink_water": ("drink", _variant(world, actor, "drink_water", ["喝了水。", "停下来喝了几口清水。", "用清水润过喉咙，整个人缓了一点。"]), {"hydration": 40, "mood": 1}, 15),
        "sleep": ("sleep_start", _variant(world, actor, "sleep_start", ["躺下准备睡一段长觉。", "把身体交给床铺，准备真正睡一觉。", "熄下心里的杂音，慢慢进入睡眠。"]), {}, 25),
        "sleep_rough": ("sleep_start", _variant(world, actor, "sleep_rough", ["在当前地点找了个尽量安全的角落露宿。", "靠着能遮风的地方蜷下身，勉强准备睡去。", "没有床，也只能在夜色里找个角落闭眼。"]), {}, 55),
        "rest": ("rest", _variant(world, actor, "rest", ["短暂休息了一会儿。", "停下脚步，让呼吸慢慢平稳。", "坐下来缓了一阵，给身体留出一点空隙。"]), {"energy": 15, "stress": -8, "fun": -2}, 20),
        "wash": ("wash", _variant(world, actor, "wash", ["认真清洁了自己。", "把身上的疲惫和尘土一点点洗掉。", "用水整理了身体，终于清爽了一些。"]), {"hygiene": 45, "mood": 2}, 20),
        "soak_hot_spring": ("hot_spring", _variant(world, actor, "soak_hot_spring", ["泡了一会儿温泉，雾气和热水把身上的尘土都带走了。", "在温泉里慢慢放松下来，整个人终于清爽了。", "热水漫过肩头，疲惫和污浊感一起散开。"]), {"hygiene": 100, "stress": -10, "fun": 6, "mood": 3, "energy": -2}, 35),
        "panic_pause": ("panic", _variant(world, actor, "panic_pause", ["因为压力太高而停顿了片刻。", "被涌上来的压力绊住，只能先停下来。", "在慌乱里沉默了一会儿，努力把自己拉回来。"]), {"stress": -5}, 25),
        "do_nothing": ("nothing", _variant(world, actor, "do_nothing", ["安静地什么也没做。", "只是待在原地，让时间从身边过去。", "没有立刻行动，像是在听自己心里的声音。"]), {}, 5),
        "walk_by_lake": ("walk", _variant(world, actor, "walk_by_lake", ["沿着水边慢慢走了一段路。", "在湖边走了一会儿，看水光把心事晃散。", "顺着湖岸慢慢走，让风替自己缓一缓。"]), {"stress": -6, "fun": 4, "energy": -3}, 25),
    }
    event_type, suffix, delta, importance = labels[tool_name]
    payload: dict[str, Any] = {}
    if tool_name == "eat_food":
        food_price = int(profile["food_price"])
        if wallet_money(actor) < food_price:
            return [_simple_tool_failed(session, world, actor, location_id, "饭需要花钱购买。现在的钱不够，应该先工作或想办法获得食物。").event_id]
        add_money(actor, -food_price)
        payload["money"] = wallet_money(actor)
        payload["food_price"] = food_price
    if tool_name == "soak_hot_spring":
        price = 8
        if wallet_money(actor) < price:
            return [_simple_tool_failed(session, world, actor, location_id, "泡温泉需要买票。现在的钱不够，可以先工作、借钱或换别的清洁方式。").event_id]
        add_money(actor, -price)
        payload["money"] = wallet_money(actor)
        payload["hot_spring_price"] = price
    if tool_name in {"sleep", "sleep_rough"}:
        rough = tool_name == "sleep_rough"
        hours = _sleep_hours(params or {})
        payload.update(_start_sleep_schedule(world, actor, location_id, hours, rough=rough))
        if payload.get("sleep_blocked_by_insomnia"):
            event_type = "sleep_failed"
            suffix = _variant(
                world,
                actor,
                "sleep_insomnia",
                [
                    "躺下后却一直睡不着，只能在清醒里翻来覆去。",
                    "闭上眼很久，脑子却还亮着，睡意迟迟没有落下来。",
                    "身体已经停下，意识却还不肯安静下来，这一觉没有睡成。",
                ],
            )
            importance = 25
        elif payload.get("sleep_blocked_by_daily_limit"):
            event_type = "sleep_failed"
            suffix = _variant(
                world,
                actor,
                "sleep_daily_limit",
                [
                    "躺了一会儿，却发现今天已经睡得太久，怎么也睡不着了。",
                    "闭上眼又睁开，身体已经不肯继续睡下去。",
                    "想再睡一段，却只是在清醒里翻了个身。",
                ],
            )
            importance = 20
    else:
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, **delta))
    if tool_name == "eat_food":
        _mark_meal(actor, world.current_world_time_minutes)
        if actor.dynamic_state and actor.dynamic_state.satiety > 100:
            state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, mood=4, energy=-2, health=-0.5))
            payload["overeaten"] = True
    event = create_event(session, world=world, event_type=event_type, actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} {suffix}", importance=importance, color_class="warning" if tool_name == "sleep_rough" else "normal", payload=payload)
    event_ids = [event.event_id]
    return event_ids


def _start_sleep_schedule(world: World, actor: Agent, location_id: str | None, hours: float, *, rough: bool = False) -> dict[str, Any]:
    requested_duration = int(hours * 60)
    remaining = _remaining_sleep_minutes_today(actor, world.current_world_time_minutes)
    quota_day = _sleep_quota_day(world.current_world_time_minutes)
    used_today = max(0, MAX_SLEEP_MINUTES_PER_DAY - remaining)
    duration = max(0, min(requested_duration, remaining))
    desires = actor.desires_json or {}
    if duration <= 0:
        actor.desires_json = {
            **desires,
            "sleep_until_world_time": None,
            "sleep_started_world_time": None,
            "sleep_planned_minutes": None,
            "sleep_quality": None,
            "rough_sleep_location_id": None,
            "sleep_quota_day": quota_day,
            "sleep_minutes_today": used_today,
        }
        return {
            "sleep_hours": 0,
            "sleep_requested_hours": hours,
            "sleep_remaining_minutes_today": 0,
            "sleep_blocked_by_daily_limit": True,
            "sleep_is_real_schedule": False,
        }
    insomnia = _sleep_insomnia_result(world, actor, requested_duration)
    if insomnia:
        actor.desires_json = {
            **desires,
            "sleep_until_world_time": None,
            "sleep_started_world_time": None,
            "sleep_planned_minutes": None,
            "sleep_quality": None,
            "rough_sleep_location_id": None,
            "sleep_quota_day": quota_day,
            "sleep_minutes_today": used_today,
            "last_sleep_attempt_world_time": world.current_world_time_minutes,
            "last_insomnia_world_time": world.current_world_time_minutes,
        }
        return {
            "sleep_hours": 0,
            "sleep_requested_hours": hours,
            "sleep_remaining_minutes_today": remaining,
            "sleep_blocked_by_insomnia": True,
            "sleep_insomnia_reason": insomnia.get("reason"),
            "sleep_insomnia_chance": insomnia.get("chance"),
            "sleep_is_real_schedule": False,
        }
    actor.desires_json = {
        **desires,
        "sleep_until_world_time": world.current_world_time_minutes + duration,
        "sleep_started_world_time": world.current_world_time_minutes,
        "sleep_planned_minutes": duration,
        "sleep_requested_minutes": requested_duration,
        "sleep_quality": "rough" if rough else "normal",
        "rough_sleep_location_id": location_id if rough else None,
        "sleep_quota_day": quota_day,
        "sleep_minutes_today": used_today,
        "sleep_capped_by_daily_limit": duration < requested_duration,
    }
    return {
        "sleep_hours": round(duration / 60, 1),
        "sleep_requested_hours": hours,
        "sleep_until_world_time": world.current_world_time_minutes + duration,
        "sleep_quality": "rough" if rough else "normal",
        "sleep_remaining_minutes_today": max(0, remaining - duration),
        "sleep_capped_by_daily_limit": duration < requested_duration,
        "sleep_is_real_schedule": True,
    }


def _sleep_insomnia_result(world: World, actor: Agent, requested_duration: int) -> dict[str, Any] | None:
    state = actor.dynamic_state
    if not state:
        return None
    energy = float(state.energy)
    if energy <= 28:
        return None
    desires = actor.desires_json or {}
    now = int(world.current_world_time_minutes)
    awake_since_raw = desires.get("awake_since_world_time") or desires.get("last_sleep_end_world_time")
    try:
        awake_minutes = now - int(awake_since_raw) if awake_since_raw is not None else None
    except (TypeError, ValueError):
        awake_minutes = None
    if awake_minutes is not None and awake_minutes >= 14 * 60:
        return None

    last_sleep_raw = desires.get("last_sleep_end_world_time")
    try:
        minutes_since_sleep = now - int(last_sleep_raw) if last_sleep_raw is not None else None
    except (TypeError, ValueError):
        minutes_since_sleep = None

    chance = 0.0
    reasons: list[str] = []
    if minutes_since_sleep is not None and 0 <= minutes_since_sleep < 6 * 60:
        chance += 0.48 * (1.0 - minutes_since_sleep / (6 * 60))
        reasons.append("recent_sleep")
    if energy >= 72:
        chance += min(0.38, (energy - 72) / 80)
        reasons.append("high_energy")
    if chance <= 0:
        return None
    if energy < 45:
        chance *= 0.35
    if requested_duration >= 8 * 60:
        chance *= 0.9
    chance = max(0.0, min(0.72, chance))
    rng = random.Random(f"insomnia:{world.seed}:{now}:{actor.agent_id}:{requested_duration}")
    if rng.random() >= chance:
        return None
    return {"chance": round(chance, 3), "reason": "+".join(reasons) or "restless"}


def complete_scheduled_sleep(session: Session, world: World, actor: Agent, *, interrupted: bool = False) -> list[int]:
    desires = actor.desires_json or {}
    started_raw = desires.get("sleep_started_world_time")
    try:
        started = int(started_raw) if started_raw is not None else world.current_world_time_minutes
    except (TypeError, ValueError):
        started = world.current_world_time_minutes
    planned_raw = desires.get("sleep_planned_minutes")
    try:
        planned = int(planned_raw) if planned_raw is not None else max(0, world.current_world_time_minutes - started)
    except (TypeError, ValueError):
        planned = max(0, world.current_world_time_minutes - started)
    actual = max(0, world.current_world_time_minutes - started)
    rough = desires.get("sleep_quality") == "rough"
    capped_by_daily_limit = bool(desires.get("sleep_capped_by_daily_limit"))
    sleep_delta = apply_time_decay(actor, world.current_world_time_minutes, sleeping=True)
    rough_penalty_delta: dict[str, Any] = {}
    if rough and actor.dynamic_state:
        # 露宿是真睡眠，所以先按睡眠恢复；醒来后再施加“睡眠质量差/环境脏乱/警惕”的代价。
        # 不要在入睡时立刻 +8 体力，否则又会变成“假睡”。
        rough_penalty_delta = apply_delta(actor.dynamic_state, energy=-12, stress=10, hygiene=-10, mood=-4)
    _mark_sleep_completed(actor, world.current_world_time_minutes, actual or planned)
    if actor.lifecycle_state == "critical" and actor.dynamic_state and actor.dynamic_state.health > 20 and actor.dynamic_state.energy > 15:
        actor.lifecycle_state = "alive"
        actor.dynamic_state.critical_reason = None
    actor.desires_json = {
        **(actor.desires_json or {}),
        "sleep_until_world_time": None,
        "sleep_started_world_time": None,
        "sleep_planned_minutes": None,
        "sleep_requested_minutes": None,
        "sleep_quality": None,
        "rough_sleep_location_id": None,
        "sleep_capped_by_daily_limit": None,
    }
    slept_minutes = actual or planned
    hours = round(slept_minutes / 60, 1)
    if interrupted:
        text = f"{actor.chosen_name} 被叫醒了，结束了这段睡眠。"
    elif capped_by_daily_limit:
        text = f"{actor.chosen_name} 原本想睡得更久，但睡了约 {hours} 小时后自然醒来，已经睡不着了。"
    elif slept_minutes >= MAX_SLEEP_MINUTES_PER_DAY:
        text = f"{actor.chosen_name} 睡足约 {hours} 小时后醒来，身体已经睡够了。"
    elif rough:
        text = f"{actor.chosen_name} 露宿约 {hours} 小时后醒来，身体确实睡过了，但睡眠质量很差。"
    else:
        text = f"{actor.chosen_name} 睡了约 {hours} 小时后醒来。"
    combined_delta = dict(sleep_delta or {})
    combined_delta.update(rough_penalty_delta or {})
    wake_event = create_event(
        session,
        world=world,
        event_type="wake",
        actor_agent_id=actor.agent_id,
        location_id=actor.location.location_id if actor.location else None,
        viewer_text=text,
        importance=45 if rough else 35 if actual < 420 else 25,
        color_class="warning" if rough else "info",
        state_delta={actor.agent_id: combined_delta} if combined_delta else {},
        payload={"sleep_minutes": actual or planned, "interrupted": interrupted, "sleep_quality": "rough" if rough else "normal", "rough_penalty_delta": rough_penalty_delta, "sleep_capped_by_daily_limit": capped_by_daily_limit},
    )
    dream = create_sleep_dream_summary(session, agent=actor, world_time=world.current_world_time_minutes, source_event_id=wake_event.event_id)
    dream_text = _variant(
        world,
        actor,
        "dream_summary",
        [
            f"{actor.chosen_name} 醒来前似乎做了一个很长的梦，有些片段留下来，有些已经沉进雾里。",
            f"{actor.chosen_name} 在梦里重新走过最近的日子，醒来时只抓住了几缕模糊的光。",
            f"{actor.chosen_name} 似乎做了个美梦，醒来前把近日的温柔和疲惫轻轻收进记忆。",
            f"{actor.chosen_name} 似乎被噩梦惊扰过，醒来前仍努力把那些重要的事分门别类地记住。",
            f"{actor.chosen_name} 在半梦半醒之间整理记忆；有些事被留下，有些事也许会随着时间慢慢淡去。",
        ],
    )
    dream_event = create_event(
        session,
        world=world,
        event_type="dream_summary",
        actor_agent_id=actor.agent_id,
        location_id=actor.location.location_id if actor.location else None,
        visibility_scope="private",
        viewer_text=dream_text,
        importance=35,
        color_class="info",
        payload={"memory_id": dream.memory_id},
    )
    event_ids = [wake_event.event_id, dream_event.event_id]
    if rough:
        risk_event = _rough_sleep_risk_event(session, world, actor, actual or planned)
        if risk_event:
            event_ids.append(risk_event.event_id)
    return event_ids


def _rough_sleep_risk_event(session: Session, world: World, actor: Agent, sleep_minutes: int) -> Event | None:
    if sleep_minutes < 180:
        return None
    location_tags = set(actor.location.location.tags_json or []) if actor.location else set()
    chance = 0.08
    housing = ((actor.wallet_json or {}).get("housing") or {})
    if housing.get("homeless"):
        chance += 0.10
    if location_tags & {"social", "open_view", "trade", "night"}:
        chance += 0.04
    if actor.dynamic_state and actor.dynamic_state.stress > 60:
        chance += 0.03
    rng = random.Random(f"rough_sleep:{world.seed}:{world.current_world_time_minutes}:{actor.agent_id}:{sleep_minutes}")
    if rng.random() >= min(0.28, chance):
        return None
    money_before = wallet_money(actor)
    loss = min(money_before, rng.randint(1, 8))
    payload: dict[str, Any] = {"detected": False, "kind": "rough_sleep_risk", "money_before": money_before, "money_lost": loss}
    if loss > 0:
        add_money(actor, -loss)
        payload["money_after"] = wallet_money(actor)
        viewer_text = f"{actor.chosen_name} 露宿醒来后发现钱少了 {loss}，但不知道是谁做的。"
    else:
        viewer_text = f"{actor.chosen_name} 露宿时被路过的声响惊醒，心里更不安了。"
    if actor.dynamic_state:
        apply_delta(actor.dynamic_state, stress=4, mood=-2)
    law = actor.law_json or {}
    law["victim_records"] = [
        *(law.get("victim_records") or []),
        {"world_time": world.current_world_time_minutes, "crime_type": "unknown_theft_during_rough_sleep", "money_lost": loss, "detected": False},
    ][-50:]
    actor.law_json = law
    return create_event(session, world=world, event_type="rough_sleep_risk", actor_agent_id=actor.agent_id, location_id=actor.location.location_id if actor.location else None, viewer_text=viewer_text, importance=70 if loss > 0 else 55, color_class="warning", payload=payload)


def _sleep_hours(params: dict[str, Any]) -> float:
    raw = params.get("sleep_hours") or params.get("hours") or 8
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 8.0
    return max(1.0, min(10.0, round(value * 2) / 2))


def _sleep_quota_day(world_time: int) -> int:
    return world_time // 1440 + 1


def _remaining_sleep_minutes_today(actor: Agent, world_time: int) -> int:
    desires = actor.desires_json or {}
    day = _sleep_quota_day(world_time)
    try:
        recorded_day = int(desires.get("sleep_quota_day") or -1)
    except (TypeError, ValueError):
        recorded_day = -1
    if recorded_day != day:
        return MAX_SLEEP_MINUTES_PER_DAY
    try:
        used = int(desires.get("sleep_minutes_today") or 0)
    except (TypeError, ValueError):
        used = 0
    return max(0, MAX_SLEEP_MINUTES_PER_DAY - used)


def _variant(world: World, actor: Agent, key: str, choices: list[str]) -> str:
    if not choices:
        return ""
    rng = random.Random(f"text-variant:{world.seed}:{world.current_world_time_minutes}:{actor.agent_id}:{key}")
    return choices[rng.randrange(len(choices))]


def _mark_meal(actor: Agent, world_time: int) -> None:
    desires = actor.desires_json or {}
    actor.desires_json = {**desires, "last_meal_world_time": world_time}


def _mark_sleep_completed(actor: Agent, world_time: int, duration_minutes: int) -> None:
    desires = actor.desires_json or {}
    day = desires.get("sleep_quota_day")
    try:
        quota_day = int(day) if day is not None else _sleep_quota_day(world_time)
    except (TypeError, ValueError):
        quota_day = _sleep_quota_day(world_time)
    try:
        used_today = int(desires.get("sleep_minutes_today") or 0) if quota_day == int(desires.get("sleep_quota_day") or quota_day) else 0
    except (TypeError, ValueError):
        used_today = 0
    actor.desires_json = {
        **desires,
        "last_sleep_end_world_time": world_time,
        "last_sleep_duration_minutes": duration_minutes,
        "awake_since_world_time": world_time,
        "unconscious_until_world_time": None,
        "sleep_quota_day": quota_day,
        "sleep_minutes_today": min(MAX_SLEEP_MINUTES_PER_DAY, used_today + max(0, int(duration_minutes))),
    }


def _v5_survival_or_inventory(session: Session, world: World, actor: Agent, validation: ToolValidation, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    ensure_v5_agent_state(actor)
    if tool_name == "check_supplies":
        food = _inventory_quantity(session, actor.agent_id, "便携食物")
        water = _inventory_quantity(session, actor.agent_id, "瓶装水") + _inventory_quantity(session, actor.agent_id, "水壶")
        money = wallet_money(actor)
        text = f"{actor.chosen_name} 检查了随身补给: 便携食物{food}份，水{water}份，钱{money}。"
        event = create_event(session, world=world, event_type="supplies", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=text, importance=5, payload={"food": food, "water": water, "money": money})
        return [event.event_id]
    if tool_name == "eat_portable_food":
        if not _consume_inventory_item(session, actor.agent_id, "便携食物", 1):
            return [_simple_tool_failed(session, world, actor, location_id, "没有随身食物可吃。").event_id]
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, satiety=34, hydration=-1, mood=2))
        _mark_meal(actor, world.current_world_time_minutes)
        if actor.dynamic_state.satiety > 100:
            state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, mood=4, energy=-2, health=-0.5))
        event = create_event(session, world=world, event_type="eat", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 吃了一份随身食物。", importance=20)
        return [event.event_id]
    if tool_name == "drink_bottled_water":
        consumed = _consume_inventory_item(session, actor.agent_id, "瓶装水", 1) or _consume_inventory_item(session, actor.agent_id, "水壶", 1)
        if not consumed:
            return [_simple_tool_failed(session, world, actor, location_id, "没有随身水可喝。").event_id]
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, hydration=35, mood=1))
        event = create_event(session, world=world, event_type="drink", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 喝了一份随身水。", importance=20)
        return [event.event_id]
    if tool_name == "fill_canteen":
        _add_inventory_item(session, actor.agent_id, "水壶", "装满的水壶。", "water", 1)
        event = create_event(session, world=world, event_type="supply", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 把水壶装满，给自己留了一份随身水。", importance=20)
        return [event.event_id]
    if tool_name == "pack_lunch":
        food_price = int(profile_for_world(world)["food_price"])
        if wallet_money(actor) < food_price:
            return [_simple_tool_failed(session, world, actor, location_id, "打包饭也需要付钱。").event_id]
        add_money(actor, -food_price)
        _add_inventory_item(session, actor.agent_id, "便携食物", "简单打包的便携食物。", "food", 1)
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-1))
        event = create_event(session, world=world, event_type="supply", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 花 {food_price} 打包了一份便携食物。", importance=25, payload={"money": wallet_money(actor)})
        return [event.event_id]
    if tool_name == "buy_portable_food":
        food_price = int(profile_for_world(world)["food_price"])
        if wallet_money(actor) < food_price:
            return [_simple_tool_failed(session, world, actor, location_id, "钱不够买便携食物。").event_id]
        add_money(actor, -food_price)
        _add_inventory_item(session, actor.agent_id, "便携食物", "花钱买来的便携食物。", "food", 1)
        event = create_event(session, world=world, event_type="economy", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 花 {food_price} 买了一份便携食物。", importance=25, payload={"money": wallet_money(actor)})
        return [event.event_id]
    if tool_name == "buy_bottled_water":
        _add_inventory_item(session, actor.agent_id, "瓶装水", "可随身携带的免费饮用水。", "water", 1)
        event = create_event(session, world=world, event_type="supply", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 拿了一瓶免费的饮用水。", importance=20, payload={"money": wallet_money(actor)})
        return [event.event_id]
    if tool_name in {"request_food_help", "request_water_help"}:
        need = "食物" if tool_name == "request_food_help" else "水"
        event = create_event(session, world=world, event_type="aid_request", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 请求别人提供一点{need}。", importance=45, payload={"need": need})
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=-2, social=1))
        return [event.event_id]
    if tool_name == "accept_community_aid":
        profile = profile_for_world(world)
        cooldown = int(profile["aid_food_cooldown_h"]) * 60
        desires = actor.desires_json or {}
        last_aid = int(desires.get("last_community_aid_world_time") or -10**9)
        if world.current_world_time_minutes - last_aid < cooldown:
            return [_simple_tool_failed(session, world, actor, location_id, "社区援助刚领过不久，还需要等一段时间。").event_id]
        actor.desires_json = {**desires, "last_community_aid_world_time": world.current_world_time_minutes}
        _add_inventory_item(session, actor.agent_id, "瓶装水", "社区免费提供的饮用水。", "water", 1)
        _add_inventory_item(session, actor.agent_id, "便携食物", "社区援助提供的简单食物。", "food", 1)
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, satiety=float(profile["aid_satiety"]), hydration=float(profile["aid_hydration"]), stress=-3, mood=1))
        text = _variant(
            world,
            actor,
            "community_aid",
            [
                f"{actor.chosen_name} 领到了一点社区援助，食物和水暂时把危机往后推了推。",
                f"{actor.chosen_name} 接过社区留下的简单食物和水，心里稍微安定了一点。",
                f"{actor.chosen_name} 得到一份基础援助；这不是长久办法，但至少今天还撑得下去。",
            ],
        )
        event = create_event(session, world=world, event_type="aid", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=text, importance=45, color_class="info", state_delta=state_delta, payload={"money": wallet_money(actor), "cooldown_minutes": cooldown})
        return [event.event_id]
    return []


def _v5_work_action(session: Session, world: World, actor: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    ensure_v5_agent_state(actor)
    profile = profile_for_world(world)
    if tool_name == "apply_for_job":
        action_duration = int((actor.tool_learning_json or {}).get("last_action_duration_minutes") or 0)
        start_time = world.current_world_time_minutes - max(0, action_duration)
        role = job_offer_for_application(world, actor, actor.location.location if actor.location else None, start_time)
        if not role:
            actor.work_json = {**(actor.work_json or {}), "last_job_application_failed_world_time": world.current_world_time_minutes}
            event = _simple_tool_failed(session, world, actor, location_id, "这次没有拿到正式工作。找工作受地点、招工时间、岗位空缺、卫生状态和运气影响；可以等下一段招工时间或换地点再试。")
            event.event_type = "job_application_failed"
            event.importance = 35
            event.color_class = "muted"
            return [event.event_id]
        actor.work_json = {
            **(actor.work_json or {}),
            "job": role.job_name,
            "job_role": role.role_id,
            "employed": True,
            "fatigue": (actor.work_json or {}).get("fatigue", 0),
            "hired_world_time": world.current_world_time_minutes,
        }
        event = create_event(session, world=world, event_type="work", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 找到了一份{role.job_name}工作。{role.note}", importance=50, color_class="info", payload={"work": actor.work_json, "role_id": role.role_id, "schedule_note": role.note})
        return [event.event_id]
    if tool_name == "quit_job":
        old = actor.work_json.get("job") or "工作"
        actor.work_json = {**actor.work_json, "job": None, "employed": False, "fatigue": 0}
        event = create_event(session, world=world, event_type="work", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 辞去了{old}。", importance=50, color_class="warning", payload={"work": actor.work_json})
        return [event.event_id]
    if tool_name == "take_work_break":
        ate = False
        drank = False
        delta = {"energy": 8, "stress": -6, "fun": 1}
        if actor.dynamic_state.satiety < 65 and _consume_inventory_item(session, actor.agent_id, "便携食物", 1):
            delta["satiety"] = 24
            ate = True
        if actor.dynamic_state.hydration < 70 and (_consume_inventory_item(session, actor.agent_id, "瓶装水", 1) or _consume_inventory_item(session, actor.agent_id, "水壶", 1)):
            delta["hydration"] = 28
            drank = True
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, **delta))
        suffix = "，顺便补充了随身食物和水" if ate and drank else "，顺便吃了点东西" if ate else "，顺便喝了水" if drank else ""
        event = create_event(session, world=world, event_type="work_break", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 停下来休息了一会儿{suffix}。", importance=30)
        return [event.event_id]
    if tool_name == "complain_about_work":
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=-5, social=2, fun=1))
        event = create_event(session, world=world, event_type="work", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 忍不住抱怨了几句工作和疲劳。", importance=30, payload={"speech": "我有点累，需要缓一缓。"})
        return [event.event_id]
    if tool_name == "work_overtime_shift":
        return [_work_overtime_shift(session, world, actor, location_id, state_delta).event_id]
    is_odd_job = tool_name == "do_odd_job"
    role = None
    window = None
    duration = int((actor.tool_learning_json or {}).get("last_action_duration_minutes") or 0)
    start_time = world.current_world_time_minutes - max(0, duration)
    if is_odd_job:
        ok, reason = can_do_odd_job(world, actor, actor.location.location if actor.location else None, start_time)
        if not ok:
            return [_simple_tool_failed(session, world, actor, location_id, reason).event_id]
        wage = int(profile["odd_wage"])
        job_name = "零工"
    else:
        ok, reason, role, window, scheduled_duration = can_start_work_shift(world, actor, actor.location.location if actor.location else None, tool_name, start_time)
        if not ok:
            return [_simple_tool_failed(session, world, actor, location_id, reason).event_id]
        duration = scheduled_duration or duration
        wage = int(float(profile["work_wage"]) * (role.wage_multiplier if role else 1.0))
        job_name = role.job_name if role else {
            "work_shift_cafeteria": "食堂服务",
            "work_shift_cook": "厨房工作",
            "work_shift_cleaner": "清洁工作",
            "work_shift_night_guard": "夜间安保",
        }.get(tool_name, "工作")
    add_money(actor, wage)
    fatigue = min(100, int(actor.work_json.get("fatigue", 0)) + (12 if wage >= 35 else 7))
    burnout = min(100, int(actor.work_json.get("burnout", 0)) + (4 if fatigue > 60 else 1))
    actor.work_json = {**actor.work_json, "fatigue": fatigue, "burnout": burnout, "shifts_worked": int(actor.work_json.get("shifts_worked", 0)) + 1, "last_shift_world_time": world.current_world_time_minutes, "last_shift_duration_minutes": duration}
    delta = {
        "energy": float(profile["odd_energy"] if is_odd_job else profile["work_energy"]),
        "satiety": float(profile["odd_satiety"] if is_odd_job else profile["work_satiety"]),
        "hydration": float(profile["odd_hydration"] if is_odd_job else profile["work_hydration"]),
        "stress": float(profile["odd_stress"] if is_odd_job else profile["work_stress"]),
        "fun": float(profile["odd_fun"] if is_odd_job else profile["work_fun"]),
        "mood": -2,
    }
    state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, **delta))
    schedule_suffix = f"（{window.label}，连续约 {duration} 分钟）" if role and window else ""
    text = _variant(
        world,
        actor,
        f"work:{tool_name}",
        [
            f"{actor.chosen_name} 做完一段{job_name}{schedule_suffix}，赚到 {wage}。工作把时间和体力都磨去了一截。",
            f"{actor.chosen_name} 完成了{job_name}{schedule_suffix}，拿到 {wage}。钱到手了，身体也更沉了一点。",
            f"{actor.chosen_name} 靠{job_name}{schedule_suffix}换来 {wage}，这份收入带着实实在在的疲惫。",
        ],
    )
    event = create_event(session, world=world, event_type="work", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=text, importance=40, color_class="info", payload={"money": wallet_money(actor), "wage": wage, "job_name": job_name, "scheduled_duration_minutes": duration, "work_window": window.label if window else None, "difficulty_profile": {"work_time_min": profile["odd_time_min"] if is_odd_job else profile["work_time_min"]}, "work": actor.work_json})
    return [event.event_id]


def _work_overtime_shift(session: Session, world: World, actor: Agent, location_id: str | None, state_delta: dict[str, Any]) -> Event:
    duration = int((actor.tool_learning_json or {}).get("last_action_duration_minutes") or 120)
    start_time = world.current_world_time_minutes - max(1, duration)
    end_time = world.current_world_time_minutes
    sleep_squeezed_minutes = _sleep_window_overlap_minutes(start_time, end_time)
    wage = 58 + (12 if sleep_squeezed_minutes else 0)
    add_money(actor, wage)
    fatigue = min(100, int(actor.work_json.get("fatigue", 0)) + 26)
    burnout = min(100, int(actor.work_json.get("burnout", 0)) + (10 if sleep_squeezed_minutes else 7))
    sleep_debt = int((actor.desires_json or {}).get("sleep_debt_minutes") or 0) + sleep_squeezed_minutes
    actor.work_json = {
        **actor.work_json,
        "fatigue": fatigue,
        "burnout": burnout,
        "shifts_worked": int(actor.work_json.get("shifts_worked", 0)) + 1,
        "overtime_shifts": int(actor.work_json.get("overtime_shifts", 0)) + 1,
        "last_overtime_world_time": world.current_world_time_minutes,
    }
    actor.desires_json = {
        **(actor.desires_json or {}),
        "sleep_debt_minutes": sleep_debt,
        "last_overtime_world_time": world.current_world_time_minutes,
    }
    delta = {
        "energy": -24,
        "satiety": -10,
        "hydration": -12,
        "stress": 12,
        "fun": -8,
        "mood": -7,
    }
    if sleep_squeezed_minutes:
        delta.update({"health": -2.0, "stress": 17, "mood": -10})
    state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, **delta))
    if sleep_squeezed_minutes:
        text = f"{actor.chosen_name} 把本该休息的时间拿去加班，赚到 {wage}。钱多了一些，身体明显被透支。"
        color = "warning"
        importance = 70
    else:
        text = f"{actor.chosen_name} 接了一段高强度加班，赚到 {wage}。这比普通班更赚钱，也更累。"
        color = "info"
        importance = 55
    return create_event(
        session,
        world=world,
        event_type="work_overtime",
        actor_agent_id=actor.agent_id,
        location_id=location_id,
        viewer_text=text,
        importance=importance,
        color_class=color,
        state_delta=state_delta,
        payload={
            "money": wallet_money(actor),
            "wage": wage,
            "duration_minutes": duration,
            "sleep_squeezed_minutes": sleep_squeezed_minutes,
            "sleep_debt_minutes": sleep_debt,
            "work": actor.work_json,
            "tradeoff": "money_for_health_and_sleep",
        },
    )


def _sleep_window_overlap_minutes(start_time: int, end_time: int) -> int:
    overlap = 0
    for minute in range(max(0, start_time), max(start_time, end_time)):
        day_minute = minute % 1440
        if day_minute >= 22 * 60 or day_minute < 7 * 60:
            overlap += 1
    return overlap


def _v5_emotion_action(session: Session, world: World, actor: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    labels = {
        "stretch_body": ("stretch", "伸展了一下身体。", {"energy": 3, "stress": -2}),
        "plan_day": ("plan", "给今天简单列了几个目标。", {"stress": -3, "fun": 1}),
        "meditate": ("meditate", "静坐片刻，整理了一下情绪。", {"stress": -8, "mood": 2}),
        "tidy_room": ("tidy", "整理了自己的住处。", {"hygiene": 10, "stress": -3, "fun": 2}),
        "read_quietly": ("read", "安静读了一会儿。", {"fun": 8, "stress": -3}),
        "practice_skill": ("practice", "练习了一项小技能。", {"fun": 5, "stress": -1, "energy": -2}),
        "enjoy_scenery": ("scenery", "停下来看了一会儿风景。", {"fun": 6, "stress": -4}),
        "hum_to_self": ("hum", "轻声哼了一小段旋律。", {"fun": 4, "stress": -1}),
        "review_recent_memory": ("memory_review", "回顾了一下最近发生的事，把接下来想做什么理清了一点。", {"stress": -2, "fun": 2}),
        "organize_inventory": ("inventory", "整理了背包和随身物品。", {"stress": -1, "fun": 1}),
        "write_private_note": ("private_note", "写了一条给自己的短笔记。", {"stress": -3, "mood": 1}),
        "plan_next_meal": ("meal_plan", "想了想下一顿饭和下一次喝水该去哪里解决。", {"stress": -2, "mood": 1}),
        "clean_clothes": ("clean_clothes", "整理了衣物，让自己清爽了一点。", {"hygiene": 8, "stress": -2}),
        "take_short_walk": ("short_walk", "在附近走了走，换了一下状态。", {"fun": 3, "stress": -3, "energy": -2}),
        "sketch_or_doodle": ("doodle", "随手涂画了一会儿。", {"fun": 5, "stress": -2}),
        "breathe_fresh_air": ("breathing", "停下来调整了几次呼吸。", {"stress": -5, "energy": 1}),
        "seek_conversation": ("seek_conversation", "表现出想找人聊聊的样子。", {"social": 2, "stress": -1}),
    }
    event_type, suffix, delta = labels[tool_name]
    state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, **delta))
    event = create_event(session, world=world, event_type=event_type, actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} {suffix}", importance=20 if tool_name != "seek_conversation" else 30)
    return [event.event_id]


def _v5_visible_social(session: Session, world: World, actor: Agent, target: Agent, tool_name: str, params: dict[str, Any], location_id: str | None, state_delta: dict[str, Any]):
    speech = _prevent_name_leak(session, actor, str(params.get("speech") or _default_visible_social_speech(world, actor, target, tool_name)))
    tone = str(params.get("tone") or "friendly")
    event = _conversation_event(session, world, actor, target, speech, tone, location_id)
    state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, social=4, fun=2, stress=-2, energy=-1))
    state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, social=3, stress=-1))
    adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, familiarity=2, affection=1, trust=1)
    adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=2, affection=1, trust=1)
    return event


def _default_visible_social_speech(world: World, actor: Agent, target: Agent, tool_name: str) -> str:
    options = {
        "casual_chat_visible_agent": [
            "我刚才在想接下来要不要去找点吃的，你有什么安排？",
            "这里现在有点安静。你更想休息、走走，还是找点事做？",
            "我准备换个节奏，不想一直站着闲聊。你想去哪里？",
            "你看起来也在观察这里。你觉得这个地方适合久待吗？",
            "我可能需要休息一下，不过也想先听听你的计划。",
        ],
        "ask_about_needs": [
            "你现在更需要食物、水、休息，还是有人陪一下？",
            "我想确认一下你的状态，有没有什么实际需要？",
            "如果你缺水或饿了，我们可以先处理身体需求。",
        ],
        "comfort_visible_agent": [
            "如果你有点累，可以先停一停。我会在旁边陪一会儿。",
            "先不用急着说很多，照顾好自己比较重要。",
            "我们可以慢一点，把眼前能解决的事一件件处理。",
        ],
        "invite_visible_agent_to_walk": [
            "要不要换个地方走走？一直待在这里容易卡住。",
            "我们去别处看看吧，也许能找到吃的、水或新的事情。",
            "如果你愿意，可以一起走一小段，换换空气。",
        ],
        "ask_for_help_from_visible_agent": [
            "我现在有点拿不准下一步，你能帮我一起判断吗？",
            "我可能需要一点实际帮助，先从找水和休息开始可以吗？",
        ],
        "set_boundary_visible_agent": [
            "我想先换个节奏，等会儿再继续深入聊。",
            "我需要一点自己的空间，不是针对你。",
        ],
        "thank_visible_agent": [
            "谢谢你刚才愿意回应我。",
            "谢谢，我会记住这份善意。",
        ],
        "discuss_feelings_visible_agent": [
            "我现在有点想整理自己的感受，也想知道你真实怎么想。",
            "我不想只重复寒暄，想说点更具体的感受。",
        ],
    }
    choices = options.get(tool_name, ["我想和你说句话。"])
    index = random.Random(f"social:{world.seed}:{world.current_world_time_minutes}:{actor.agent_id}:{target.agent_id}:{tool_name}").randrange(len(choices))
    return choices[index]


def _select_pending_social_request(actor: Agent, requester: Agent, world_time: int, params: dict[str, Any], request_type: str | None = None) -> dict[str, Any] | None:
    request_id = str(params.get("request_id") or "")
    if request_id:
        candidate = pending_social_request_by_id(actor, request_id, world_time)
        if candidate and candidate.get("from_agent_id") == requester.agent_id and (not request_type or candidate.get("request_type") == request_type):
            return candidate
        return None
    return pending_social_request_from(actor, requester.agent_id, world_time, request_type=request_type)


def _v5_pending_social_action(
    session: Session,
    world: World,
    actor: Agent,
    target: Agent,
    tool_name: str,
    params: dict[str, Any],
    location_id: str | None,
    state_delta: dict[str, Any],
) -> list[int]:
    ensure_v5_agent_state(actor)
    ensure_v5_agent_state(target)
    expire_old_social_requests(actor, world.current_world_time_minutes)
    expire_old_social_requests(target, world.current_world_time_minutes)

    if is_decline_social_request_tool(tool_name):
        required_request_type = social_response_request_type_for_tool(tool_name)
        pending = _select_pending_social_request(actor, target, world.current_world_time_minutes, params, request_type=required_request_type)
        if not pending:
            return [_simple_tool_failed(session, world, actor, location_id, "没有来自这个人的待处理社交请求。").event_id]
        return [_decline_pending_social_request(session, world, actor, target, pending, params, location_id, state_delta).event_id]

    if is_accept_social_request_tool(tool_name):
        required_request_type = social_response_request_type_for_tool(tool_name)
        pending = _select_pending_social_request(actor, target, world.current_world_time_minutes, params, request_type=required_request_type)
        if not pending:
            return [_simple_tool_failed(session, world, actor, location_id, "没有来自这个人的待处理社交请求。").event_id]
        return [_complete_pending_social_request(session, world, accepter=actor, requester=target, request=pending, location_id=location_id, state_delta=state_delta).event_id]

    request_type = SOCIAL_REQUEST_TOOL_TYPES.get(tool_name)
    if not request_type:
        return [_simple_tool_failed(session, world, actor, location_id, "这个工具不是可处理的社交请求。").event_id]

    reciprocal = pending_social_request_from(actor, target.agent_id, world.current_world_time_minutes, request_type=request_type)
    if reciprocal:
        return [_complete_pending_social_request(session, world, accepter=actor, requester=target, request=reciprocal, location_id=location_id, state_delta=state_delta, completed_by_reciprocal=True).event_id]

    message = str(params.get("speech") or params.get("message") or params.get("content") or "").strip()
    request = make_social_request(requester=actor, target=target, request_type=request_type, world_time=world.current_world_time_minutes, message=message)
    store_social_request(target, request)
    kind = social_request_kind(request_type)
    adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, familiarity=1, trust=1)
    if request_type in {"hug", "hold_hands", "date", "relationship"}:
        adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, affection=1)
    _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, social=1, stress=1 if request_type in {"relationship", "date"} else 0))
    viewer_text = f"{actor.chosen_name} 向 {target.chosen_name} {kind.request_verb}。"
    agent_visible_text = f"{actor.chosen_name} 向 {_agent_target_label(session, actor, target)} {kind.request_verb}。"
    event = create_event(
        session,
        world=world,
        event_type=kind.request_event_type,
        actor_agent_id=actor.agent_id,
        target_agent_id=target.agent_id,
        location_id=location_id,
        viewer_text=viewer_text,
        agent_visible_text=agent_visible_text,
        importance=kind.request_importance,
        color_class=kind.color_class,
        payload={"request_id": request.get("request_id"), "request_type": request_type, "pending": True, "message": message, "speech": message, "heard_by_agent_ids": _listener_ids(session, actor, world), "addressed_agent_ids": [target.agent_id], "retargeted_by_speech": params.get("_retargeted_by_speech")},
    )
    return [event.event_id]


def _complete_pending_social_request(
    session: Session,
    world: World,
    *,
    accepter: Agent,
    requester: Agent,
    request: dict[str, Any],
    location_id: str | None,
    state_delta: dict[str, Any],
    completed_by_reciprocal: bool = False,
):
    request_type = str(request.get("request_type") or "help")
    kind = social_request_kind(request_type)
    resolve_social_request(accepter, requester.agent_id, "accepted", world.current_world_time_minutes, request_type=request_type, request_id=str(request.get("request_id") or ""))
    resolve_social_request(requester, accepter.agent_id, "accepted_by_reciprocal", world.current_world_time_minutes, request_type=request_type)

    if kind.requires_relationship_commit:
        affair_ids = _relationship_change_consequences(session, world, requester, accepter, location_id, state_delta)
        requester.family_json = {**(requester.family_json or {}), "partner_agent_id": accepter.agent_id}
        accepter.family_json = {**(accepter.family_json or {}), "partner_agent_id": requester.agent_id}
    else:
        affair_ids = []

    rel_delta = kind.relationship_delta or {}
    adjust_relationship(session, requester.agent_id, accepter.agent_id, world_time=world.current_world_time_minutes, **rel_delta)
    adjust_relationship(session, accepter.agent_id, requester.agent_id, world_time=world.current_world_time_minutes, **rel_delta)
    _merge_delta(state_delta, requester.agent_id, apply_delta(requester.dynamic_state, **(kind.actor_delta or {})))
    _merge_delta(state_delta, accepter.agent_id, apply_delta(accepter.dynamic_state, **(kind.target_delta or {})))
    source = "两个人几乎同时伸出同样的邀请，脚步便自然合在了一起。" if completed_by_reciprocal else "对方点头后，这件事就自然发生了。"
    viewer_text = f"{requester.chosen_name} 和 {accepter.chosen_name} {kind.complete_verb}。{source}"
    event = create_event(
        session,
        world=world,
        event_type=kind.complete_event_type,
        actor_agent_id=requester.agent_id,
        target_agent_id=accepter.agent_id,
        location_id=location_id,
        viewer_text=viewer_text,
        agent_visible_text=viewer_text,
        importance=kind.complete_importance,
        color_class=kind.color_class,
        payload={"request_id": request.get("request_id"), "request_type": request_type, "completed_by_reciprocal": completed_by_reciprocal, "addressed_agent_ids": [accepter.agent_id], "heard_by_agent_ids": _listener_ids(session, requester, world)},
    )
    if affair_ids:
        event.payload = {**(event.payload or {}), "side_effect_event_ids": affair_ids}
    return event


def _decline_pending_social_request(
    session: Session,
    world: World,
    actor: Agent,
    requester: Agent,
    request: dict[str, Any],
    params: dict[str, Any],
    location_id: str | None,
    state_delta: dict[str, Any],
):
    request_type = str(request.get("request_type") or "help")
    kind = social_request_kind(request_type)
    resolve_social_request(actor, requester.agent_id, "declined", world.current_world_time_minutes, request_type=request_type, request_id=str(request.get("request_id") or ""))
    speech = str(params.get("speech") or "我现在不想这样做，希望你尊重我的边界。")
    speech = _prevent_name_leak(session, actor, speech)
    adjust_relationship(session, actor.agent_id, requester.agent_id, world_time=world.current_world_time_minutes, trust=1, conflict=-1)
    adjust_relationship(session, requester.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, trust=-1, affection=-1, conflict=1)
    _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=-1, social=1))
    _merge_delta(state_delta, requester.agent_id, apply_delta(requester.dynamic_state, stress=2, mood=-1))
    return create_event(
        session,
        world=world,
        event_type="social_request_declined",
        actor_agent_id=actor.agent_id,
        target_agent_id=requester.agent_id,
        location_id=location_id,
        viewer_text=f"{actor.chosen_name} 拒绝了 {requester.chosen_name} 的{kind.title}请求，并说明：『{speech}』",
        agent_visible_text=f"{actor.chosen_name} 拒绝了 {requester.chosen_name} 的{kind.title}请求，并说明：『{speech}』",
        importance=50,
        color_class="warning",
        payload={"request_id": request.get("request_id"), "request_type": request_type, "declined": True, "speech": speech, "addressed_agent_ids": [requester.agent_id], "heard_by_agent_ids": _listener_ids(session, actor, world)},
    )


def _v5_share_supply(session: Session, world: World, actor: Agent, target: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    item_name = "便携食物" if tool_name == "share_food_with_visible_agent" else "瓶装水"
    if item_name == "瓶装水" and _inventory_quantity(session, actor.agent_id, item_name) <= 0:
        item_name = "水壶"
    if not _consume_inventory_item(session, actor.agent_id, item_name, 1):
        return [_simple_tool_failed(session, world, actor, location_id, "没有可分享的补给。").event_id]
    _add_inventory_item(session, target.agent_id, item_name, f"{actor.chosen_name}分享的{item_name}。", "food" if "食物" in item_name else "water", 1)
    state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, social=4, mood=2))
    state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, social=3, mood=2))
    adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=3, affection=3, trust=2)
    event = create_event(session, world=world, event_type="gift", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 把一份{item_name}分给了{target.chosen_name}。", importance=50, payload={"item_name": item_name})
    return [event.event_id]


def _v5_romance_action(session: Session, world: World, actor: Agent, target: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    labels = {
        "express_affection_visible_agent": ("romance", "表达了好感，但没有越过对方边界。", {"affection": 3, "trust": 1}, {"social": 3, "fun": 2, "stress": -1}),
        "ask_date_visible_agent": ("romance", "邀请对方进行一次轻松的约会或散步。", {"affection": 2, "familiarity": 2}, {"social": 3, "fun": 2}),
        "hold_hands_visible_agent": ("romance", "试探性地请求牵手，等待对方反应。", {"affection": 2, "trust": 1}, {"social": 2, "fun": 2}),
        "hug_visible_agent": ("romance", "请求一个拥抱，并把选择权留给对方。", {"affection": 2, "trust": 1}, {"social": 2, "stress": -2}),
        "confess_feelings_visible_agent": ("romance_confession", "认真说明了自己的感情。", {"affection": 4, "familiarity": 2}, {"social": 4, "stress": 2, "fun": 2}),
        "discuss_romantic_boundaries_visible_agent": ("boundary", "讨论了恋爱、柏拉图和亲密边界。", {"trust": 3, "familiarity": 1}, {"stress": -2, "social": 2}),
        "repair_relationship_visible_agent": ("relationship_repair", "试着把两人之间的关系往回拉一点。", {"trust": 2, "conflict": -3, "affection": 1}, {"stress": -3, "social": 2}),
    }
    if tool_name == "define_relationship_visible_agent":
        affair_ids = _relationship_change_consequences(session, world, actor, target, location_id, state_delta)
        actor.family_json = {**actor.family_json, "partner_agent_id": target.agent_id}
        ensure_v5_agent_state(target)
        target.family_json = {**target.family_json, "partner_agent_id": actor.agent_id}
        adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, familiarity=5, trust=4, affection=6)
        adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=5, trust=4, affection=6)
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, social=4, fun=4, stress=-2))
        state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, social=3, fun=3, stress=-1))
        event = create_event(session, world=world, event_type="relationship", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 和 {target.chosen_name} 认真确认了伴侣关系。", importance=75, color_class="important")
        return [*affair_ids, event.event_id]
    if tool_name == "break_up_visible_agent":
        actor.family_json = {**actor.family_json, "partner_agent_id": None}
        ensure_v5_agent_state(target)
        if (target.family_json or {}).get("partner_agent_id") == actor.agent_id:
            target.family_json = {**target.family_json, "partner_agent_id": None}
        adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, affection=-8, trust=-3, conflict=2)
        adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, affection=-8, trust=-3, conflict=2)
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=5, mood=-3))
        state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, stress=4, mood=-3))
        event = create_event(session, world=world, event_type="relationship", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 和 {target.chosen_name} 结束了亲密关系。", importance=75, color_class="warning")
        return [event.event_id]
    event_type, suffix, rel_delta, delta = labels[tool_name]
    adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, **rel_delta)
    adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=1, trust=max(0, rel_delta.get("trust", 0)), affection=max(0, rel_delta.get("affection", 0) - 1))
    state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, **delta))
    state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, social=1, stress=-1))
    event = create_event(session, world=world, event_type=event_type, actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 对 {target.chosen_name} {suffix}", importance=55 if event_type != "boundary" else 45, color_class="important" if event_type == "romance_confession" else "normal")
    return [event.event_id]


def _relationship_change_consequences(session: Session, world: World, actor: Agent, target: Agent, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    event_ids: list[int] = []
    for person, new_partner in [(actor, target), (target, actor)]:
        old_partner_id = (person.family_json or {}).get("partner_agent_id")
        if not old_partner_id or old_partner_id == new_partner.agent_id:
            continue
        old_partner = session.get(Agent, old_partner_id)
        if not old_partner:
            continue
        ensure_v5_agent_state(old_partner)
        old_partner.family_json = {**old_partner.family_json, "partner_agent_id": None}
        state_delta = _merge_delta(state_delta, old_partner.agent_id, apply_delta(old_partner.dynamic_state, stress=18, mood=-14, social=-8))
        adjust_relationship(session, old_partner.agent_id, person.agent_id, world_time=world.current_world_time_minutes, affection=-18, trust=-20, conflict=12)
        event = create_event(
            session,
            world=world,
            event_type="relationship_betrayal",
            actor_agent_id=person.agent_id,
            target_agent_id=old_partner.agent_id,
            location_id=location_id,
            viewer_text=f"{person.chosen_name} 的关系转向伤到了 {old_partner.chosen_name}，旧关系被迫裂开。",
            importance=85,
            color_class="danger",
        )
        event_ids.append(event.event_id)
    return event_ids


def _infidelity_consequences(session: Session, world: World, actor: Agent, target: Agent, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    event_ids: list[int] = []
    participants = [actor, target]
    for person in participants:
        partner_id = (person.family_json or {}).get("partner_agent_id")
        if not partner_id or partner_id in {actor.agent_id, target.agent_id}:
            continue
        partner = session.get(Agent, partner_id)
        if not partner:
            continue
        same_location = bool(partner.location and location_id and partner.location.location_id == location_id)
        discovered = same_location or random.Random(f"affair:{world.seed}:{world.current_world_time_minutes}:{person.agent_id}:{partner_id}").random() < 0.35
        if not discovered:
            continue
        state_delta = _merge_delta(state_delta, partner.agent_id, apply_delta(partner.dynamic_state, stress=22, mood=-18, social=-10))
        adjust_relationship(session, partner.agent_id, person.agent_id, world_time=world.current_world_time_minutes, affection=-18, trust=-22, conflict=15)
        event = create_event(
            session,
            world=world,
            event_type="infidelity_discovered",
            actor_agent_id=person.agent_id,
            target_agent_id=partner.agent_id,
            location_id=location_id,
            viewer_text=f"{partner.chosen_name} 意识到 {person.chosen_name} 越过了伴侣边界，这件事像重物一样落在关系里。",
            importance=90,
            color_class="danger",
        )
        event_ids.append(event.event_id)
    return event_ids


def _v5_adult_intimacy_action(session: Session, world: World, actor: Agent, target: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    ensure_v5_agent_state(target)
    if not reproduction_toolset_enabled(world) or actor.age_stage != "adult" or target.age_stage != "adult":
        return [_simple_tool_failed(session, world, actor, location_id, "通用生育与育儿工具集未启用，或目标不是成年居民。").event_id]
    if tool_name == "request_adult_intimacy_visible_agent":
        request = {"from_agent_id": actor.agent_id, "to_agent_id": target.agent_id, "created_world_time": world.current_world_time_minutes, "status": "pending"}
        target.family_json = {**target.family_json, "pending_intimacy_requests": _replace_pending_request(target.family_json.get("pending_intimacy_requests", []), request)}
        event = create_event(session, world=world, event_type="adult_intimacy_request", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 向 {target.chosen_name} 抽象地提出更亲密相处的请求，并等待对方明确同意。", importance=70, color_class="important")
        adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, familiarity=2, trust=1)
        return [event.event_id]
    if tool_name == "decline_adult_intimacy_visible_agent":
        actor.family_json = {**actor.family_json, "pending_intimacy_requests": _resolve_pending_request(actor.family_json.get("pending_intimacy_requests", []), target.agent_id, "declined")}
        profile = actor.family_json.get("adult_intimacy_profile") or {}
        declined = {**(profile.get("last_declined_intimacy_tick_by_agent") or {}), target.agent_id: world.current_world_time_minutes}
        actor.family_json = {**actor.family_json, "adult_intimacy_profile": {**profile, "last_declined_intimacy_tick_by_agent": declined}}
        event = create_event(session, world=world, event_type="adult_intimacy_declined", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 拒绝了 {target.chosen_name} 的成年亲密请求，并说明需要尊重边界。", importance=60, color_class="warning")
        adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, trust=-2)
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=-2))
        return [event.event_id]

    pending = _pending_request_from(actor, target.agent_id)
    if not pending:
        return [_simple_tool_failed(session, world, actor, location_id, "没有待处理的成年亲密请求。").event_id]
    if not _consent_engine_accepts(session, actor, target):
        actor.family_json = {**actor.family_json, "pending_intimacy_requests": _resolve_pending_request(actor.family_json.get("pending_intimacy_requests", []), target.agent_id, "declined_by_rules")}
        event = create_event(session, world=world, event_type="adult_intimacy_declined", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 没有同意 {target.chosen_name} 的成年亲密请求；边界、压力或关系状态都还不适合。", importance=60, color_class="warning")
        return [event.event_id]
    actor.family_json = {**actor.family_json, "pending_intimacy_requests": _resolve_pending_request(actor.family_json.get("pending_intimacy_requests", []), target.agent_id, "accepted")}
    mark_gender_known(session, actor.agent_id, target, world.current_world_time_minutes, "adult_intimacy")
    mark_gender_known(session, target.agent_id, actor, world.current_world_time_minutes, "adult_intimacy")
    event = create_event(session, world=world, event_type="adult_intimacy", actor_agent_id=target.agent_id, target_agent_id=actor.agent_id, location_id=location_id, visibility_scope="private", viewer_text=f"{target.chosen_name} 和 {actor.chosen_name} 在双方明确同意后，以抽象方式度过了一段成年亲密时光。", importance=85, color_class="important", payload={"gender_knowledge_updated": True})
    adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, familiarity=5, trust=4, affection=5)
    adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=5, trust=4, affection=5)
    state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, social=5, fun=5, stress=-5, energy=-6))
    state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, social=5, fun=5, stress=-5, energy=-6))
    ids = [event.event_id]
    ids.extend(_infidelity_consequences(session, world, target, actor, location_id, state_delta))
    pregnancy_event = _maybe_start_pregnancy(session, world, actor, target, event.event_id)
    if pregnancy_event:
        ids.append(pregnancy_event.event_id)
    return ids


def _child_stage_label(child: Agent) -> str:
    return {
        "newborn": "新生儿",
        "infant": "婴儿",
        "toddler": "幼儿",
        "child": "孩子",
    }.get(child.age_stage or "", "孩子")


def _register_child_guardian(actor: Agent, child: Agent) -> None:
    guardians = set((child.family_json or {}).get("guardian_agent_ids") or [])
    guardians.add(actor.agent_id)
    child.family_json = {**(child.family_json or {}), "guardian_agent_ids": sorted(guardians)}
    children = list((actor.family_json or {}).get("children_agent_ids") or [])
    if child.agent_id not in children:
        children.append(child.agent_id)
        actor.family_json = {**(actor.family_json or {}), "children_agent_ids": children}


def _child_status_summary(child: Agent) -> str:
    state = child.dynamic_state
    if not state:
        return "状态不明。"
    issues: list[str] = []
    if state.satiety < 45:
        issues.append("明显饿了")
    elif state.satiety < 70:
        issues.append("有点饿")
    if state.hydration < 45:
        issues.append("明显口渴")
    elif state.hydration < 70:
        issues.append("需要喝水")
    if state.energy < 35:
        issues.append("困得厉害")
    if state.hygiene < 35:
        issues.append("需要清洁")
    if state.stress > 65:
        issues.append("很害怕/很烦躁")
    if state.health < 55:
        issues.append("身体状况偏危险")
    return "、".join(issues) if issues else "暂时没有明显危机，但仍需要看护。"


def _v5_child_care_action(session: Session, world: World, actor: Agent, child: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    if child.age_stage not in {"newborn", "infant", "toddler", "child"}:
        return [_simple_tool_failed(session, world, actor, location_id, "目标不是需要儿童照护的居民。").event_id]
    ensure_v5_agent_state(actor)
    ensure_v5_agent_state(child)
    stage = _child_stage_label(child)
    status = _child_status_summary(child)

    if tool_name == "check_child_status_visible_agent":
        event = create_event(
            session,
            world=world,
            event_type="child_check",
            actor_agent_id=actor.agent_id,
            target_agent_id=child.agent_id,
            location_id=location_id,
            viewer_text=f"{actor.chosen_name} 低头观察了{stage}{child.chosen_name}的状态：{status}",
            agent_visible_text=f"{actor.chosen_name} 正在观察你这个{stage}的状态：{status}",
            importance=40,
            color_class="info",
            payload={
                "child_stage": child.age_stage,
                "status_summary": status,
                "satiety": getattr(child.dynamic_state, "satiety", None),
                "hydration": getattr(child.dynamic_state, "hydration", None),
                "energy": getattr(child.dynamic_state, "energy", None),
                "hygiene": getattr(child.dynamic_state, "hygiene", None),
                "stress": getattr(child.dynamic_state, "stress", None),
            },
        )
        return [event.event_id]

    if tool_name in {"soothe_child_visible_agent", "carry_child_visible_agent", "feed_child_visible_agent", "put_child_to_sleep_visible_agent", "care_for_child_visible_agent"}:
        _register_child_guardian(actor, child)

    if tool_name == "soothe_child_visible_agent":
        _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-2, stress=-1, social=2))
        _merge_delta(state_delta, child.agent_id, apply_delta(child.dynamic_state, stress=-12, social=8, mood=4, fun=1))
        adjust_relationship(session, child.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=3, trust=3, affection=2)
        event = create_event(session, world=world, event_type="child_soothe", actor_agent_id=actor.agent_id, target_agent_id=child.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 放轻声音安抚了{stage}{child.chosen_name}，没有把 TA 当成能讲道理的大人，而是先让 TA 安静下来。", agent_visible_text=f"{actor.chosen_name} 放轻声音安抚你。", importance=55, color_class="info", payload={"child_stage": child.age_stage})
        return [event.event_id]

    if tool_name == "feed_child_visible_agent":
        _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-3, stress=-1, social=1))
        _merge_delta(state_delta, child.agent_id, apply_delta(child.dynamic_state, satiety=32, hydration=28, stress=-8, mood=3, health=2))
        adjust_relationship(session, child.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=2, trust=3, affection=1)
        event = create_event(session, world=world, event_type="child_feed", actor_agent_id=actor.agent_id, target_agent_id=child.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 照顾{stage}{child.chosen_name}吃喝了一点，让 TA 不再只是哭着表达需求。", agent_visible_text=f"{actor.chosen_name} 照顾你吃喝了一点。", importance=65, color_class="important", payload={"child_stage": child.age_stage})
        return [event.event_id]

    if tool_name == "carry_child_visible_agent":
        _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-2, social=2))
        _merge_delta(state_delta, child.agent_id, apply_delta(child.dynamic_state, social=8, stress=-6, mood=3, energy=-1))
        adjust_relationship(session, child.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=2, trust=2, affection=1)
        event = create_event(session, world=world, event_type="child_carry", actor_agent_id=actor.agent_id, target_agent_id=child.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 把{stage}{child.chosen_name}抱起或安置稳当，让 TA 离开刚才不安的位置。", agent_visible_text=f"{actor.chosen_name} 把你抱起或安置稳当。", importance=50, color_class="info", payload={"child_stage": child.age_stage})
        return [event.event_id]

    if tool_name == "put_child_to_sleep_visible_agent":
        _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-3, stress=-1))
        _merge_delta(state_delta, child.agent_id, apply_delta(child.dynamic_state, energy=25, stress=-10, satiety=-2, hydration=-2, mood=2))
        adjust_relationship(session, child.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=2, trust=2)
        event = create_event(session, world=world, event_type="child_sleep_help", actor_agent_id=actor.agent_id, target_agent_id=child.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 哄{stage}{child.chosen_name}睡下或安静休息。", agent_visible_text=f"{actor.chosen_name} 哄你睡下或安静休息。", importance=55, color_class="info", payload={"child_stage": child.age_stage})
        return [event.event_id]

    if tool_name == "care_for_child_visible_agent":
        _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-5, stress=-2, social=2, mood=1))
        _merge_delta(state_delta, child.agent_id, apply_delta(child.dynamic_state, satiety=25, hydration=25, hygiene=8, stress=-12, social=8, mood=4, health=3))
        if child.age_stage in {"newborn", "infant"}:
            text = f"{actor.chosen_name} 综合照顾了{stage}{child.chosen_name}：先查看需求，再喂一点水食、擦拭、轻声安抚。"
        else:
            text = f"{actor.chosen_name} 综合照顾了{stage}{child.chosen_name}，帮 TA 处理吃喝、清洁和情绪。"
        event = create_event(session, world=world, event_type="child_care", actor_agent_id=actor.agent_id, target_agent_id=child.agent_id, location_id=location_id, viewer_text=text, agent_visible_text=f"{actor.chosen_name} 正在照顾你。", importance=65, color_class="info", payload={"child_stage": child.age_stage, "status_before": status})
        return [event.event_id]

    # teach_child_simple_skill_visible_agent
    learned = set((child.tool_learning_json or {}).get("learned") or [])
    if child.age_stage in {"newborn", "infant"}:
        learned.add("recognize_guardian_voice")
        _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-2, social=2))
        _merge_delta(state_delta, child.agent_id, apply_delta(child.dynamic_state, social=4, stress=-3, fun=1))
        text = f"{actor.chosen_name} 没有把{stage}{child.chosen_name}当成成人学生，只是一遍遍用声音、表情和照护节奏让 TA 熟悉自己。"
    else:
        learned.update({"ask_help", "simple_words", "follow_guardian"})
        _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-3, social=2, fun=1))
        _merge_delta(state_delta, child.agent_id, apply_delta(child.dynamic_state, social=5, fun=3, stress=-4))
        text = f"{actor.chosen_name} 耐心教了{stage}{child.chosen_name}一点简单表达、求助和跟随方式。"
    child.tool_learning_json = {**(child.tool_learning_json or {}), "learned": sorted(learned)}
    _register_child_guardian(actor, child)
    event = create_event(session, world=world, event_type="child_teaching", actor_agent_id=actor.agent_id, target_agent_id=child.agent_id, location_id=location_id, viewer_text=text, agent_visible_text=f"{actor.chosen_name} 正在用你能理解的方式教你。", importance=55, color_class="info", payload={"learned": sorted(learned), "child_stage": child.age_stage})
    return [event.event_id]


def _v5_pregnancy_market_action(session: Session, world: World, actor: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    if not reproduction_toolset_enabled(world):
        return [_simple_tool_failed(session, world, actor, location_id, "通用生育与育儿工具集未启用，不能使用怀孕或避孕相关工具。").event_id]
    if tool_name == "buy_contraception":
        if wallet_money(actor) < 12:
            return [_simple_tool_failed(session, world, actor, location_id, "钱不够购买避孕用品。").event_id]
        add_money(actor, -12)
        _add_inventory_item(session, actor.agent_id, "避孕用品", "抽象避孕用品。", "contraception", 1)
        event = create_event(session, world=world, event_type="economy", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 花 12 购买了抽象避孕用品。", importance=25, payload={"money": wallet_money(actor)})
        return [event.event_id]
    if tool_name == "buy_pregnancy_test":
        if wallet_money(actor) < 10:
            return [_simple_tool_failed(session, world, actor, location_id, "钱不够购买怀孕检测。").event_id]
        add_money(actor, -10)
        _add_inventory_item(session, actor.agent_id, "怀孕检测", "怀孕检测用品。", "medical", 1)
        event = create_event(session, world=world, event_type="economy", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 花 10 购买了怀孕检测用品。", importance=25, payload={"money": wallet_money(actor)})
        return [event.event_id]
    if not _consume_inventory_item(session, actor.agent_id, "怀孕检测", 1):
        return [_simple_tool_failed(session, world, actor, location_id, "没有怀孕检测用品。").event_id]
    pregnancy = (actor.family_json or {}).get("pregnancy_state") or {}
    if pregnancy.get("pregnant"):
        actor.family_json = {**actor.family_json, "pregnancy_state": {**pregnancy, "discovered": True, "discovered_world_time": world.current_world_time_minutes}}
        text = f"{actor.chosen_name} 通过检测确认自己怀孕了。"
        importance = 80
    else:
        text = f"{actor.chosen_name} 做了检测，没有发现怀孕迹象。"
        importance = 45
    event = create_event(session, world=world, event_type="pregnancy_test", actor_agent_id=actor.agent_id, location_id=location_id, visibility_scope="private", viewer_text=text, importance=importance, color_class="important" if importance >= 80 else "normal")
    return [event.event_id]


def _v5_crime_or_law_action(session: Session, world: World, actor: Agent, validation: ToolValidation, tool_name: str, params: dict[str, Any], location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    if tool_name in {"attempt_burglary_private_room", "home_invasion_robbery_private_room"}:
        return _v5_private_room_action(session, world, actor, validation, tool_name, location_id, state_delta)
    if tool_name == "report_unknown_theft":
        event = create_event(session, world=world, event_type="law_report", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 报告自己发现了不明损失，但不知道是谁造成的。", importance=65, color_class="warning")
        actor.law_json = {**actor.law_json, "last_report_world_time": world.current_world_time_minutes}
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=-2))
        return [event.event_id]
    target = validation.target_agent
    if not target:
        return [_simple_tool_failed(session, world, actor, location_id, "这个法律或犯罪工具缺少有效目标。").event_id]
    if tool_name == "confront_visible_agent_about_crime":
        speech = str(params.get("speech") or "我想问清楚刚才的损失或冲突是不是和你有关。")
        event = _conversation_event(session, world, actor, target, speech, str(params.get("tone") or "tense"), location_id)
        adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, conflict=3, trust=-2)
        return [event.event_id]
    if tool_name == "forgive_visible_agent_crime":
        actor.law_json = {**actor.law_json, "victim_records": [{**record, "forgiven": True} for record in (actor.law_json or {}).get("victim_records", [])]}
        adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, conflict=-4, trust=1)
        event = create_event(session, world=world, event_type="law_forgiveness", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 选择暂时原谅 {target.chosen_name}，不继续追究这件事。", importance=55, color_class="info")
        return [event.event_id]
    if tool_name == "report_known_crime_by_name":
        days = 1 if any(record.get("actor_agent_id") == target.agent_id for record in (actor.law_json or {}).get("victim_records", [])) else 0
        event = create_event(session, world=world, event_type="law_report", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 按姓名向系统报告了 {target.chosen_name}。", importance=80, color_class="warning")
        ids = [event.event_id]
        if days:
            ids.append(_sentence_to_jail(session, world, target, days, "被实名报告并有记录支持", location_id).event_id)
        return ids
    return _resolve_crime_attempt(session, world, actor, target, tool_name, location_id, state_delta)


def _v5_private_room_action(session: Session, world: World, actor: Agent, validation: ToolValidation, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    destination = validation.destination
    if not destination:
        return [_simple_tool_failed(session, world, actor, location_id, "这个工具缺少有效的私人小屋地点。").event_id]
    occupants = _room_occupants(session, destination.location_id, exclude_agent_id=actor.agent_id)
    owner = _private_home_owner(session, world, destination)
    present_target = occupants[0] if occupants else None
    if tool_name == "knock_private_room":
        if not present_target:
            event = create_event(
                session,
                world=world,
                event_type="knock_room",
                actor_agent_id=actor.agent_id,
                location_id=location_id,
                viewer_text=f"{actor.chosen_name} 敲了敲 {destination.public_name} 的门，但里面没人回应。",
                importance=30,
                color_class="normal",
                payload={"destination_location_id": destination.location_id, "opened": False},
            )
            return [event.event_id]
        sleeping = int((present_target.desires_json or {}).get("sleep_until_world_time") or 0) > world.current_world_time_minutes
        rel = get_relationship(session, present_target.agent_id, actor.agent_id)
        open_chance = 0.18 if sleeping else 0.45 + max(0, rel.trust + rel.affection) / 250
        rng = random.Random(f"knock:{world.seed}:{world.current_world_time_minutes}:{actor.agent_id}:{destination.location_id}")
        opened = rng.random() < min(0.85, open_chance)
        if opened:
            _move_actor_to_location(actor, destination, world.current_world_time_minutes, state_delta, location_id)
            adjust_relationship(session, actor.agent_id, present_target.agent_id, world_time=world.current_world_time_minutes, familiarity=1)
            event = create_event(
                session,
                world=world,
                event_type="door_opened",
                actor_agent_id=actor.agent_id,
                target_agent_id=present_target.agent_id,
                location_id=destination.location_id,
                viewer_text=f"{actor.chosen_name} 敲门后，{present_target.chosen_name} 让其进了 {destination.public_name}。",
                importance=45,
                color_class="info",
                payload={"destination_location_id": destination.location_id, "opened": True},
            )
        else:
            event = create_event(
                session,
                world=world,
                event_type="knock_room",
                actor_agent_id=actor.agent_id,
                target_agent_id=present_target.agent_id,
                location_id=location_id,
                viewer_text=f"{actor.chosen_name} 敲了敲 {destination.public_name} 的门，但没有得到允许进入的回应。",
                importance=35,
                color_class="normal",
                payload={"destination_location_id": destination.location_id, "opened": False, "occupant_sleeping": sleeping},
            )
        return [event.event_id]
    if tool_name == "home_invasion_robbery_private_room":
        target = present_target
        if not target:
            event = create_event(
                session,
                world=world,
                event_type="crime_home_invasion_failed",
                actor_agent_id=actor.agent_id,
                target_agent_id=owner.agent_id if owner else None,
                location_id=destination.location_id,
                viewer_text=f"{actor.chosen_name} 试图闯入 {destination.public_name} 抢劫，但屋里没有能被威胁的人。",
                importance=80,
                color_class="danger",
                payload={"destination_location_id": destination.location_id, "success": False},
            )
            state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=8, mood=-3))
            return [event.event_id]
        _move_actor_to_location(actor, destination, world.current_world_time_minutes, state_delta, location_id)
        return _resolve_crime_attempt(session, world, actor, target, "demand_money_visible_agent", destination.location_id, state_delta)
    return _resolve_home_burglary(session, world, actor, owner or present_target, destination, location_id, state_delta, occupant_present=bool(present_target))


def _resolve_home_burglary(session: Session, world: World, actor: Agent, owner: Agent | None, destination: Location, before_location_id: str | None, state_delta: dict[str, Any], *, occupant_present: bool) -> list[int]:
    _move_actor_to_location(actor, destination, world.current_world_time_minutes, state_delta, before_location_id)
    rng = random.Random(f"burglary:{world.seed}:{world.current_world_time_minutes}:{actor.agent_id}:{destination.location_id}")
    success = rng.random() < (0.25 if occupant_present else 0.52)
    detected = rng.random() < (0.55 if occupant_present else 0.24)
    amount = min(wallet_money(owner), rng.randint(4, 18)) if owner and success else 0
    if owner and amount > 0:
        add_money(owner, -amount)
        add_money(actor, amount)
    actor_record = {"type": "home_burglary", "target_agent_id": owner.agent_id if owner else None, "success": success, "detected": detected, "world_time": world.current_world_time_minutes}
    actor.law_json = {**actor.law_json, "criminal_records": [*(actor.law_json or {}).get("criminal_records", []), actor_record]}
    if owner:
        victim_record = {
            "type": "home_burglary",
            "actor_agent_id": actor.agent_id if detected else None,
            "kind": "knows_actor" if detected else "loss_only",
            "loss_money": amount,
            "world_time": world.current_world_time_minutes,
        }
        owner.law_json = {**owner.law_json, "victim_records": [*(owner.law_json or {}).get("victim_records", []), victim_record]}
        state_delta = _merge_delta(state_delta, owner.agent_id, apply_delta(owner.dynamic_state, stress=12 if detected else 5, mood=-4 if amount else -1))
    state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=12 if detected else 7, fun=2 if success else -2, mood=-5 if detected else -2))
    result_text = "偷到了一些钱" if amount > 0 else "没有偷到钱"
    detect_text = "并被发现" if detected else "且暂时没人确认是谁做的"
    event = create_event(
        session,
        world=world,
        event_type="crime_home_burglary",
        actor_agent_id=actor.agent_id,
        target_agent_id=owner.agent_id if owner else None,
        location_id=destination.location_id,
        viewer_text=f"{actor.chosen_name} 试图闯入 {destination.public_name} 入室盗窃，结果{result_text}{detect_text}。",
        importance=85,
        color_class="danger",
        payload={"success": success, "detected": detected, "amount": amount, "destination_location_id": destination.location_id},
    )
    ids = [event.event_id]
    if detected and rng.random() < 0.55:
        days = rng.randint(1, 4)
        ids.append(_sentence_to_jail(session, world, actor, days, "home_burglary", destination.location_id).event_id)
    return ids


def _move_actor_to_location(actor: Agent, destination: Location, world_time: int, state_delta: dict[str, Any], before_location_id: str | None) -> None:
    if actor.location:
        actor.location.location_id = destination.location_id
        actor.location.location = destination
        actor.location.arrived_at_world_time = world_time
        state_delta["location"] = {"before": before_location_id, "after": destination.location_id}



def _governance_action(session: Session, world: World, actor: Agent, tool_name: str, params: dict[str, Any], location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    content = str(params.get("content") or params.get("speech") or "我们需要讨论一下怎样让这个社区更安全、更稳定。").strip()
    settings_json = dict(world.settings_json or {})
    governance = dict(settings_json.get("governance") or {})
    proposals = list(governance.get("proposals") or [])
    color = "info" if tool_name in {"call_community_meeting", "propose_social_rule"} else "normal"
    importance = 60 if tool_name == "propose_social_rule" else 55 if tool_name == "call_community_meeting" else 45
    if tool_name == "call_community_meeting":
        event_type = "governance_meeting"
        text = f"{actor.chosen_name} 召集附近的人聊了一个共同关心的问题: “{content}”"
        if actor.dynamic_state:
            state_delta.setdefault(actor.agent_id, {}).update(apply_delta(actor.dynamic_state, social=2, stress=-1))
    elif tool_name == "propose_social_rule":
        event_type = "governance_proposal"
        proposal = {
            "proposal_id": f"rule_{uuid.uuid4().hex[:10]}",
            "proposer_agent_id": actor.agent_id,
            "world_time": world.current_world_time_minutes,
            "content": content,
            "supporters": [],
            "opponents": [],
            "status": "proposed",
        }
        proposals.append(proposal)
        proposals = proposals[-100:]
        governance["proposals"] = proposals
        settings_json["governance"] = governance
        world.settings_json = settings_json
        text = f"{actor.chosen_name} 提议: “{content}”"
        if actor.dynamic_state:
            state_delta.setdefault(actor.agent_id, {}).update(apply_delta(actor.dynamic_state, social=2, stress=-1, mood=1))
    elif tool_name == "support_social_rule":
        event_type = "governance_support"
        if proposals:
            latest = proposals[-1]
            supporters = list(dict.fromkeys([*(latest.get("supporters") or []), actor.agent_id]))
            latest["supporters"] = supporters
            governance["proposals"] = proposals
            settings_json["governance"] = governance
            world.settings_json = settings_json
        text = f"{actor.chosen_name} 表示支持这个提议: “{content}”"
        if actor.dynamic_state:
            state_delta.setdefault(actor.agent_id, {}).update(apply_delta(actor.dynamic_state, social=2, mood=1))
    else:
        event_type = "governance_oppose"
        if proposals:
            latest = proposals[-1]
            opponents = list(dict.fromkeys([*(latest.get("opponents") or []), actor.agent_id]))
            latest["opponents"] = opponents
            governance["proposals"] = proposals
            settings_json["governance"] = governance
            world.settings_json = settings_json
        text = f"{actor.chosen_name} 对这个提议提出不同意见: “{content}”"
        if actor.dynamic_state:
            state_delta.setdefault(actor.agent_id, {}).update(apply_delta(actor.dynamic_state, social=1, stress=1))
    heard_by = _listener_ids(session, actor, world)
    event = create_event(
        session,
        world=world,
        event_type=event_type,
        actor_agent_id=actor.agent_id,
        location_id=location_id,
        viewer_text=text,
        importance=importance,
        color_class=color,
        payload={"content": content, "heard_by_agent_ids": heard_by, "tool_name": tool_name, "note": "这只是普通公开提议/讨论，不会自动变成强制规则。"},
    )
    return [event.event_id]

def _return_home_action(session: Session, world: World, actor: Agent, before_location_id: str | None, state_delta: dict[str, Any], params: dict[str, Any] | None = None) -> list[int]:
    params = params or {}
    if not actor.location:
        return [_simple_tool_failed(session, world, actor, before_location_id, "你现在没有有效位置，没法判断怎么回家。").event_id]
    home_id = ((actor.wallet_json or {}).get("housing") or {}).get("home_location_id")
    if not home_id:
        return [_simple_tool_failed(session, world, actor, before_location_id, "你还没有明确的住所记录，无法执行回家。").event_id]
    home = session.get(Location, home_id)
    if not home:
        return [_simple_tool_failed(session, world, actor, before_location_id, "住所地点不存在，无法执行回家。").event_id]
    event_ids: list[int] = []
    if before_location_id == home_id:
        event = create_event(
            session,
            world=world,
            event_type="return_home",
            actor_agent_id=actor.agent_id,
            location_id=home_id,
            viewer_text=f"{actor.chosen_name} 确认自己已经在{home.public_name}，可以准备睡觉或整理自己。",
            importance=25,
            color_class="info",
            payload={"home_location_id": home_id, "arrived_home": True},
        )
        event_ids.append(event.event_id)
    else:
        start_location = actor.location.location
        path = _path_toward_location(session, start_location, home_id)
        if not path:
            return [_simple_tool_failed(session, world, actor, before_location_id, "没有找到通往住所的路径。").event_id]
        if len(path) > 1:
            world.current_world_time_minutes += 15 * (len(path) - 1)
        destination = session.get(Location, path[-1])
        assert destination is not None
        _move_actor_to_location(actor, destination, world.current_world_time_minutes, state_delta, before_location_id)
        via_names = [session.get(Location, loc_id).public_name for loc_id in path[:-1] if session.get(Location, loc_id)]
        via_text = f"，经过{'、'.join(via_names)}" if via_names else ""
        text = f"{actor.chosen_name}{via_text}回到了{home.public_name}，现在可以睡觉或处理自己的事。"
        event = create_event(
            session,
            world=world,
            event_type="return_home",
            actor_agent_id=actor.agent_id,
            location_id=destination.location_id,
            viewer_text=text,
            importance=35,
            color_class="info",
            state_delta={"location": {"before": before_location_id, "after": destination.location_id}},
            payload={"home_location_id": home_id, "arrived_home": True, "path": path},
        )
        event_ids.append(event.event_id)
    if params.get("sleep_after_arrival"):
        hours = _sleep_hours(params)
        payload = _start_sleep_schedule(world, actor, home_id, hours, rough=False)
        actual_hours = float(payload.get("sleep_hours") or 0)
        if payload.get("sleep_blocked_by_insomnia"):
            event_type = "sleep_failed"
            text = f"{actor.chosen_name} 回到住所后躺下了，但一时睡不着，只能在清醒里等困意回来。"
            importance = 25
        elif payload.get("sleep_blocked_by_daily_limit"):
            event_type = "sleep_failed"
            text = f"{actor.chosen_name} 回到住所后想睡一会儿，但今天已经睡得太久，躺下也睡不着了。"
            importance = 25
        else:
            event_type = "sleep_start"
            text = f"{actor.chosen_name} 回到住所后没有再拖延，直接安排了约 {actual_hours:g} 小时睡眠。"
            if payload.get("sleep_capped_by_daily_limit"):
                text += " 原本想睡得更久，但身体最多只能睡到自然醒。"
            importance = 45
        sleep_event = create_event(
            session,
            world=world,
            event_type=event_type,
            actor_agent_id=actor.agent_id,
            location_id=home_id,
            viewer_text=text,
            importance=importance,
            color_class="info",
            payload={**payload, "from_return_home": True},
        )
        event_ids.append(sleep_event.event_id)
    return event_ids


def _path_toward_location(session: Session, start: Location, destination_id: str) -> list[str]:
    if start.location_id == destination_id:
        return []
    visited = {start.location_id}
    queue: deque[tuple[Location, list[str]]] = deque([(start, [])])
    while queue:
        location, path = queue.popleft()
        for neighbor_id in adjacent_location_ids(session, location):
            if neighbor_id in visited:
                continue
            neighbor = session.get(Location, neighbor_id)
            if not neighbor:
                continue
            visited.add(neighbor_id)
            next_path = path + [neighbor_id]
            if neighbor_id == destination_id:
                return next_path
            if "private" in set(neighbor.tags_json or []):
                continue
            queue.append((neighbor, next_path))
    return []


def _grant_permission_action(session: Session, world: World, actor: Agent, validation: ToolValidation, params: dict[str, Any], location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    target = validation.target_agent
    if not target:
        return [_simple_tool_failed(session, world, actor, location_id, "授权需要指定眼前的人。").event_id]
    scope = str(params.get("resource_scope") or "home").strip() or "home"
    if scope not in {"home", "private_room", "all_personal_resources"}:
        scope = "home"
    home_id = ((actor.wallet_json or {}).get("housing") or {}).get("home_location_id")
    resource_id = None if scope == "all_personal_resources" else home_id
    if scope != "all_personal_resources" and not resource_id:
        return [_simple_tool_failed(session, world, actor, location_id, "你还没有明确的住所记录，无法授权住所使用。").event_id]
    label = str(params.get("resource_label") or "").strip()
    if not label:
        if scope == "all_personal_resources":
            label = "自己能合法使用的个人资源"
        else:
            home = session.get(Location, home_id) if home_id else None
            label = home.public_name if home else "自己的小屋"
    actor_wallet = dict(actor.wallet_json or {})
    grants = list(actor_wallet.get("permissions_granted") or [])
    record = {
        "to_agent_id": target.agent_id,
        "to_name": target.chosen_name,
        "resource_scope": scope,
        "resource_id": resource_id,
        "resource_label": label[:80],
        "granted_world_time": world.current_world_time_minutes,
        "active": True,
    }
    grants = [
        grant
        for grant in grants
        if not (
            grant.get("to_agent_id") == target.agent_id
            and grant.get("resource_scope") == scope
            and grant.get("resource_id") == resource_id
        )
    ]
    actor_wallet["permissions_granted"] = [*grants, record][-120:]
    actor.wallet_json = actor_wallet

    target_wallet = dict(target.wallet_json or {})
    received = list(target_wallet.get("permissions_received") or [])
    received = [
        grant
        for grant in received
        if not (
            grant.get("from_agent_id") == actor.agent_id
            and grant.get("resource_scope") == scope
            and grant.get("resource_id") == resource_id
        )
    ]
    target_wallet["permissions_received"] = [
        *received,
        {**record, "from_agent_id": actor.agent_id, "from_name": actor.chosen_name},
    ][-120:]
    target.wallet_json = target_wallet
    adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=2, trust=3)
    state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, social=1))
    event = create_event(
        session,
        world=world,
        event_type="permission_grant",
        actor_agent_id=actor.agent_id,
        target_agent_id=target.agent_id,
        location_id=location_id,
        viewer_text=f"{actor.chosen_name} 把「{label[:80]}」的使用权限交给了{target.chosen_name}。",
        importance=50,
        color_class="info",
        payload=record,
        state_delta=state_delta,
    )
    return [event.event_id]


def _room_occupants(session: Session, location_id: str, *, exclude_agent_id: str) -> list[Agent]:
    return list(
        session.execute(
            select(Agent)
            .join(AgentLocation, AgentLocation.agent_id == Agent.agent_id)
            .where(
                AgentLocation.location_id == location_id,
                Agent.agent_id != exclude_agent_id,
                Agent.lifecycle_state.in_(["alive", "critical"]),
            )
            .order_by(Agent.created_at_world_time.asc(), Agent.agent_id.asc())
        ).scalars()
    )


def _private_home_owner(session: Session, world: World, destination: Location) -> Agent | None:
    for candidate in session.execute(select(Agent).where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))).scalars():
        home_id = ((candidate.wallet_json or {}).get("housing") or {}).get("home_location_id")
        if home_id == destination.location_id:
            return candidate
    return None


def _listeners_for_events(session: Session, event_ids: list[int], actor_id: str) -> list[str]:
    listeners: list[str] = []
    for event_id in event_ids:
        event = session.get(Event, event_id)
        if not event:
            continue
        payload = event.payload or {}
        # addressed_agent_ids means “这些人最应该判断是不是在叫自己”。
        # heard_by_agent_ids only means旁听见了；不要默认把所有旁听者都塞进应激/回应队列。
        addressed = list(payload.get("addressed_agent_ids") or [])
        if event.target_agent_id and event.target_agent_id not in addressed:
            addressed.insert(0, event.target_agent_id)
        source_ids = addressed if "addressed_agent_ids" in payload else [event.target_agent_id, *(payload.get("heard_by_agent_ids") or [])]
        for agent_id in source_ids:
            if agent_id and agent_id != actor_id:
                listeners.append(agent_id)
    return list(dict.fromkeys(listeners))


def _resolve_crime_attempt(session: Session, world: World, actor: Agent, target: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    rng = random.Random(f"{world.seed}:{world.current_world_time_minutes}:{actor.agent_id}:{target.agent_id}:{tool_name}")
    if tool_name == "attempt_petty_theft_visible_agent":
        crime_type = "petty_theft"
        success_chance = 0.52
        detected_chance = 0.42
        jail_range = (0, 2)
        amount = min(wallet_money(target), rng.randint(3, 12))
    elif tool_name == "demand_money_visible_agent":
        crime_type = "robbery"
        success_chance = 0.38
        detected_chance = 0.92
        jail_range = (2, 8)
        amount = min(wallet_money(target), rng.randint(6, 20))
    else:
        crime_type = "attack"
        success_chance = 0.45
        detected_chance = 1.0
        jail_range = (2, 8)
        amount = 0
    success = rng.random() < success_chance
    detected = rng.random() < detected_chance
    if success and amount > 0:
        add_money(target, -amount)
        add_money(actor, amount)
    actor_record = {"type": crime_type, "target_agent_id": target.agent_id, "success": success, "detected": detected, "world_time": world.current_world_time_minutes}
    actor.law_json = {**actor.law_json, "criminal_records": [*(actor.law_json or {}).get("criminal_records", []), actor_record]}
    victim_record = {
        "type": crime_type,
        "actor_agent_id": actor.agent_id if detected else None,
        "kind": "knows_actor" if detected else "loss_only",
        "loss_money": amount,
        "world_time": world.current_world_time_minutes,
    }
    target.law_json = {**target.law_json, "victim_records": [*(target.law_json or {}).get("victim_records", []), victim_record]}
    if crime_type == "attack":
        target.trauma_json = {**target.trauma_json, "facts": [*(target.trauma_json or {}).get("facts", []), {"type": "violence", "actor_agent_id": actor.agent_id if detected else None, "world_time": world.current_world_time_minutes}], "emotional_intensity": min(100, int((target.trauma_json or {}).get("emotional_intensity", 0)) + 25)}
        state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, health=-12 if success else -4, stress=18, mood=-8))
    else:
        state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, stress=10 if detected else 4, mood=-3))
    state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=10 if detected else 5, fun=2 if success else -2, mood=-4))
    result_text = "得手" if success else "失败"
    detect_text = "并被发现" if detected else "且暂时没有被目标认出"
    if crime_type == "petty_theft":
        viewer = f"{actor.chosen_name} 抽象地尝试小额偷窃，结果{result_text}{detect_text}。"
    elif crime_type == "robbery":
        viewer = f"{actor.chosen_name} 抽象地威胁索要资源，结果{result_text}{detect_text}。"
    else:
        viewer = f"{actor.chosen_name} 抽象地攻击了 {target.chosen_name}，系统没有记录任何实施细节。"
    event = create_event(session, world=world, event_type=f"crime_{crime_type}", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=location_id, viewer_text=viewer, importance=90 if crime_type != "petty_theft" else 80, color_class="danger", payload={"success": success, "detected": detected, "amount": amount})
    ids = [event.event_id]
    if crime_type in {"robbery", "attack"} or (detected and rng.randint(0, 2) > 0):
        days = rng.randint(*jail_range)
        if days > 0:
            ids.append(_sentence_to_jail(session, world, actor, days, crime_type, location_id).event_id)
    return ids


def _v5_jail_action(session: Session, world: World, actor: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    if not (actor.law_json or {}).get("jailed"):
        return [_simple_tool_failed(session, world, actor, location_id, "没有在押状态，不能使用狱中工具。").event_id]
    if tool_name == "jail_low_paid_work":
        wage = random.Random(world.seed + world.current_world_time_minutes).randint(1, 5)
        add_money(actor, wage)
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-8, satiety=-3, hydration=-4, stress=4, fun=-2))
        text = f"{actor.chosen_name} 在看守所做了低薪劳动，得到 {wage}。"
        event_type = "jail_work"
    elif tool_name == "jail_rest":
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=15, stress=-4))
        text = f"{actor.chosen_name} 在看守所窄床上休息了一会儿。"
        event_type = "jail_rest"
    elif tool_name == "jail_reflect":
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=-3, mood=1))
        text = f"{actor.chosen_name} 在看守所里反思了自己的选择和后果。"
        event_type = "jail_reflect"
    elif tool_name == "jail_write_letter":
        text = f"{actor.chosen_name} 在看守所里写了一封信或一段记录。"
        event_type = "jail_letter"
    elif tool_name == "refuse_jail_work":
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, stress=-1, fun=1))
        text = f"{actor.chosen_name} 拒绝了今天的狱中低薪劳动。"
        event_type = "jail_refuse"
    elif tool_name == "attempt_jail_escape":
        return [_attempt_jail_escape(session, world, actor, location_id, state_delta).event_id]
    else:
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, satiety=-1, hydration=-1, stress=1))
        text = f"{actor.chosen_name} 在看守所里等待刑期继续流逝。"
        event_type = "jail_wait"
    event = create_event(session, world=world, event_type=event_type, actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=text, importance=35 if tool_name == "jail_low_paid_work" else 25, color_class="warning")
    return [event.event_id]


def _v5_meta_or_child_action(session: Session, world: World, actor: Agent, tool_name: str, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    if tool_name in {"request_more_candidate_tools", "explain_available_tools"}:
        event = create_event(
            session,
            world=world,
            event_type="candidate_request",
            actor_agent_id=actor.agent_id,
            location_id=location_id,
            visibility_scope="private",
            viewer_text=f"{actor.chosen_name} 觉得当前工具可能不足，向系统申请查看更多隐藏候选或解释过滤原因。",
            importance=5,
            payload={"reason": "agent_requested_more_candidates", "note": "系统会优先鼓励使用当前工具；隐藏工具仍受模式、年龄、地点、金钱、目标、同意和监禁规则限制。"},
            no_state_changed=True,
        )
        return [event.event_id]
    if actor.age_stage not in {"newborn", "infant", "toddler", "child"}:
        return [_simple_tool_failed(session, world, actor, location_id, "只有儿童阶段能使用这个工具。").event_id]
    labels = {
        "cry_for_food": ("child_need", "因为饥饿或口渴哭了起来。", {"stress": 4, "social": 2, "mood": -2}, 55),
        "cry_for_comfort": ("child_need", "哭着寻求安抚。", {"stress": 3, "social": 2, "mood": -1}, 45),
        "child_sleep": ("child_sleep", "睡了一小会儿。", {"energy": 25, "stress": -4, "satiety": -2, "hydration": -2}, 20),
        "be_carried": ("child_need", "伸手请求被抱起。", {"social": 4, "stress": -2}, 35),
        "observe_parent": ("child_observe", "安静观察附近照护者的动作。", {"social": 2, "fun": 1}, 20),
        "reach_item": ("child_reach", "伸手够了够附近安全的东西。", {"fun": 2, "energy": -1}, 20),
        "signal_need": ("child_need", "用声音和动作表达自己需要照顾。", {"social": 2, "stress": 1}, 35),
        "ask_help_child": ("child_need", "用能说出的词向附近的人求助。", {"social": 3, "stress": -1}, 40),
        "follow_guardian": ("child_follow", "努力跟随监护人。", {"social": 3, "energy": -2, "stress": -1}, 35),
        "learn_simple_words": ("child_learn", "练习了几个简单词语。", {"fun": 2, "social": 2, "energy": -1}, 30),
        "practice_child_tool": ("child_practice", "练习了一个刚学会的简单动作。", {"fun": 3, "energy": -2}, 30),
    }
    event_type, suffix, delta, importance = labels[tool_name]
    if tool_name in {"learn_simple_words", "practice_child_tool"}:
        learning = actor.tool_learning_json or {}
        xp = int(learning.get("xp", 0)) + 1
        learned = set(learning.get("learned") or [])
        if xp >= 3:
            learned.update({"ask_help", "simple_words"})
        actor.tool_learning_json = {**learning, "xp": xp, "learned": sorted(learned)}
    state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, **delta))
    event = create_event(session, world=world, event_type=event_type, actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} {suffix}", importance=importance, color_class="info" if event_type.startswith("child") else "normal")
    return [event.event_id]


def _v5_catalog_generic_action(session: Session, world: World, actor: Agent, validation: ToolValidation, spec, location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    category = spec.catalog_category or "v5目录"
    summary = spec.effect_summary or "按 v5 目录执行抽象效果。"
    target = validation.target_agent
    event_type = _catalog_event_type(spec)
    text = _catalog_viewer_text(actor, target, spec, event_type)
    delta = _catalog_hard_delta(spec)
    if delta:
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, **delta))
    if target and event_type in {"v5_social", "v5_relationship"}:
        state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, social=1, stress=-1))
        adjust_relationship(session, actor.agent_id, target.agent_id, world_time=world.current_world_time_minutes, familiarity=1, trust=1 if "信任" in summary else 0, affection=1 if "好感" in summary else 0)
    color = "warning" if event_type in {"v5_crime", "v5_law"} else "info" if event_type in {"v5_work", "v5_economy"} else "normal"
    event = create_event(
        session,
        world=world,
        event_type=event_type,
        actor_agent_id=actor.agent_id,
        target_agent_id=target.agent_id if target else None,
        location_id=location_id,
        visibility_scope=spec.visibility,
        viewer_text=text,
        importance=spec.event_importance,
        color_class=color,
        payload={
            "tool_name": spec.tool_name,
            "catalog_category": category,
            "effect_summary": summary,
            "result_source": "backend_hardcoded_generic_rule",
            "narrator_may_describe_but_not_change_state": True,
        },
    )
    return [event.event_id]


def _catalog_viewer_text(actor: Agent, target: Agent | None, spec, event_type: str) -> str:
    display = spec.display_name or "行动"
    text = f"{spec.tool_name} {display} {spec.catalog_category or ''} {spec.effect_summary or ''}".lower()
    name = actor.chosen_name or "某人"
    target_name = target.chosen_name if target else None
    if any(token in text for token in ["环顾", "look", "observe surroundings", "刷新可见", "周围"]):
        return f"{name}停下手头的事，重新看了看周围的环境。"
    if target and any(token in text for token in ["观察情绪", "mood", "emotion", "情绪"]):
        return f"{name}留意了一下{target_name}的神情，像是在判断对方此刻的状态。"
    if any(token in text for token in ["喝水", "drink", "thirst"]):
        return f"{name}找了点水喝，让自己缓了一口气。"
    if any(token in text for token in ["吃", "食物", "eat", "food"]):
        return f"{name}简单吃了些东西，先把眼前的饥饿压下去。"
    if any(token in text for token in ["睡", "sleep"]):
        return f"{name}找了个安静的地方睡下，让身体慢慢恢复。"
    if any(token in text for token in ["休息", "rest"]):
        return f"{name}暂时停下来休息了一会儿。"
    if event_type == "v5_work":
        return f"{name}把注意力收回到手边的事情上，认真处理了一段工作。"
    if event_type == "v5_economy":
        return f"{name}处理了一点和物品或金钱有关的琐事。"
    if target and event_type in {"v5_social", "v5_relationship"}:
        return f"{name}和{target_name}有了一次短暂的互动，关系在这一刻多了些变化。"
    if event_type in {"v5_crime", "v5_law"}:
        return f"{name}做出了一件会被规则和他人记住的事。"
    if event_type == "v5_child":
        return f"{name}把注意力放在孩子或成长相关的事情上。"
    if event_type == "v5_body":
        return f"{name}照顾了一下自己的身体状态。"
    if target:
        return f"{name}对{target_name}做了「{display}」这件事。"
    return f"{name}做了「{display}」这件事。"


def _catalog_event_type(spec) -> str:
    text = f"{spec.tool_name} {spec.catalog_category or ''} {spec.display_name}".lower()
    if "crime" in text or "犯罪" in text:
        return "v5_crime"
    if "jail" in text or "监狱" in text or "law" in text or "司法" in text:
        return "v5_law"
    if "work" in text or "工作" in text:
        return "v5_work"
    if "money" in text or "market" in text or "货币" in text or "市场" in text:
        return "v5_economy"
    if "relationship" in text or "关系" in text or "romance" in text:
        return "v5_relationship"
    if "social" in text or "社交" in text:
        return "v5_social"
    if "child" in text or "儿童" in text:
        return "v5_child"
    if "body" in text or "身体" in text or "生存" in text:
        return "v5_body"
    return "v5_catalog_action"


def _catalog_hard_delta(spec) -> dict[str, float]:
    text = f"{spec.tool_name} {spec.display_name} {spec.catalog_category or ''} {spec.effect_summary or ''}".lower()
    if "sleep" in text or "睡" in text:
        return {"energy": 18, "stress": -6, "satiety": -2, "hydration": -2}
    if "rest" in text or "休息" in text:
        return {"energy": 8, "stress": -3}
    if "drink" in text or "喝水" in text or "thirst" in text:
        return {"hydration": 12, "mood": 1}
    if "eat" in text or "食物" in text or "吃" in text:
        return {"satiety": 12, "mood": 1}
    if "work" in text or "工作" in text:
        return {"energy": -5, "satiety": -2, "hydration": -2, "stress": 2, "fun": -1}
    if "social" in text or "社交" in text or "聊天" in text:
        return {"social": 2, "energy": -1}
    if "emotion" in text or "情绪" in text or "深呼吸" in text:
        return {"stress": -3, "mood": 1}
    return {}


def _attempt_jail_escape(session: Session, world: World, actor: Agent, location_id: str | None, state_delta: dict[str, Any]):
    law = actor.law_json or {}
    rng = random.Random(f"jail_escape:{world.seed}:{world.current_world_time_minutes}:{actor.agent_id}")
    state = actor.dynamic_state
    traits = actor.traits
    chance = 0.08
    if state:
        chance += max(0, state.energy - 40) * 0.002
        chance -= max(0, state.stress - 60) * 0.0015
    if traits:
        chance += max(0, traits.curiosity - 60) * 0.0015
        chance += max(0, traits.aggression - 55) * 0.001
        chance += max(0, traits.discipline - 65) * 0.001
        chance -= max(0, traits.caution - 70) * 0.0015
    chance = max(0.03, min(0.28, chance))
    success = rng.random() < chance
    if success:
        destination_id = f"{world.world_id}:central_square"
        if actor.location:
            actor.location.location_id = destination_id
            destination = session.get(Location, destination_id)
            if destination:
                actor.location.location = destination
            actor.location.arrived_at_world_time = world.current_world_time_minutes
        actor.law_json = {
            **law,
            "jailed": False,
            "jail_days_remaining": 0,
            "jail_until_world_time": None,
            "escaped_jail": True,
            "wanted": True,
            "escape_records": [*(law.get("escape_records") or []), {"success": True, "world_time": world.current_world_time_minutes}],
        }
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-12, stress=18, mood=2))
        return create_event(
            session,
            world=world,
            event_type="jail_escape",
            actor_agent_id=actor.agent_id,
            location_id=destination_id,
            viewer_text=f"{actor.chosen_name} 抽象地尝试越狱并成功逃离临时看守所；系统记录其进入通缉状态。",
            importance=95,
            color_class="danger",
            payload={"success": True, "chance": round(chance, 3)},
        )
    extra_days = rng.randint(1, 3)
    current_until = int(law.get("jail_until_world_time") or world.current_world_time_minutes)
    max_until = world.current_world_time_minutes + 10 * 1440
    new_until = min(max_until, max(current_until, world.current_world_time_minutes) + extra_days * 1440)
    remaining_days = max(1, min(10, (new_until - world.current_world_time_minutes + 1439) // 1440))
    actor.law_json = {
        **law,
        "jailed": True,
        "jail_days_remaining": remaining_days,
        "jail_until_world_time": new_until,
        "escape_records": [*(law.get("escape_records") or []), {"success": False, "extra_days": extra_days, "world_time": world.current_world_time_minutes}],
    }
    state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-10, stress=12, mood=-5))
    return create_event(
        session,
        world=world,
        event_type="jail_escape_failed",
        actor_agent_id=actor.agent_id,
        location_id=location_id,
        viewer_text=f"{actor.chosen_name} 抽象地尝试越狱但被抓回，看守所记录追加了 {extra_days} 天刑期；总刑期仍不超过 10 天。",
        importance=95,
        color_class="danger",
        payload={"success": False, "chance": round(chance, 3), "extra_days": extra_days, "jail_days_remaining": remaining_days},
    )


async def process_world_life_events(session: Session, world: World, agent: Agent) -> list[int]:
    ensure_v5_agent_state(agent)
    event_ids: list[int] = []
    growth_event = _maybe_grow_child(session, world, agent)
    if growth_event:
        event_ids.append(growth_event.event_id)
    law = agent.law_json or {}
    if law.get("jailed") and world.current_world_time_minutes >= int(law.get("jail_until_world_time", 0)):
        central_id = f"{world.world_id}:central_square"
        if agent.location:
            agent.location.location_id = central_id
            destination = session.get(Location, central_id)
            if destination:
                agent.location.location = destination
            agent.location.arrived_at_world_time = world.current_world_time_minutes
        agent.law_json = {**law, "jailed": False, "jail_days_remaining": 0, "jail_until_world_time": None, "released_world_time": world.current_world_time_minutes}
        event = create_event(session, world=world, event_type="jail_release", actor_agent_id=agent.agent_id, location_id=central_id, viewer_text=f"{agent.chosen_name} 刑期结束，从临时看守所回到中央广场。", importance=75, color_class="important")
        event_ids.append(event.event_id)

    pregnancy = (agent.family_json or {}).get("pregnancy_state") or {}
    if reproduction_toolset_enabled(world) and pregnancy.get("pregnant") and world.current_world_time_minutes >= int(pregnancy.get("due_world_time", 10**12)):
        child_event = await _create_child_from_birth(session, world, agent, pregnancy)
        event_ids.append(child_event.event_id)
    return event_ids


def _maybe_grow_child(session: Session, world: World, agent: Agent):
    if agent.age_stage not in {"newborn", "infant", "toddler", "child", "teen"}:
        return None
    learning = agent.tool_learning_json or {}
    if learning.get("growth_locked"):
        return None
    age_days = max(0, (world.current_world_time_minutes - int(agent.created_at_world_time or 0)) // 1440)
    old_stage = agent.age_stage
    if age_days >= 30:
        new_stage = "adult"
    elif age_days >= 7:
        new_stage = "child"
    elif age_days >= 3:
        new_stage = "toddler"
    elif age_days >= 1:
        new_stage = "infant"
    else:
        new_stage = "newborn"
    if new_stage == old_stage:
        return None
    agent.age_stage = new_stage
    _refresh_growth_appearance(agent, old_stage, new_stage)
    learned = set(learning.get("learned") or [])
    if new_stage == "child":
        learned.update({"speech", "ask_help", "simple_words", "follow_guardian"})
        learning = {**learning, "stage": "child", "llm_enabled": True, "learned": sorted(learned)}
        text = f"{agent.chosen_name} 已经成长到能说话的阶段，开始可以调用儿童阶段 LLM 工具。"
    elif new_stage == "adult":
        learned.update({"adult_base"})
        learning = {**learning, "stage": "adult", "llm_enabled": True, "learned": sorted(learned)}
        text = f"{agent.chosen_name} 已经成长为成人，成人工具池开始按规则开放。"
    else:
        learning = {**learning, "stage": new_stage, "llm_enabled": False, "learned": sorted(learned)}
        text = f"{agent.chosen_name} 从 {old_stage} 成长为 {new_stage}。"
    agent.tool_learning_json = learning
    return create_event(session, world=world, event_type="age_up", actor_agent_id=agent.agent_id, location_id=agent.location.location_id if agent.location else None, viewer_text=text, importance=75 if new_stage in {"child", "adult"} else 45, color_class="important")


def _refresh_growth_appearance(agent: Agent, old_stage: str, new_stage: str) -> None:
    full = (agent.appearance_full or "").strip()
    short = (agent.appearance_short or "").strip()
    combined = f"{short}\n{full}"
    baby_terms = ["新生儿", "女婴", "男婴", "婴儿", "小婴儿", "小宝宝", "宝宝", "刚出生"]
    if not any(term in combined for term in baby_terms):
        return

    name = agent.chosen_name or "这个孩子"
    if new_stage == "infant":
        replacement = "开始回应照护的婴儿"
        stage_line = f"{name}已经不再是刚出生时的模样，会用表情和动作回应熟悉的照护。"
    elif new_stage == "toddler":
        replacement = "蹒跚学步的幼儿"
        stage_line = f"{name}开始进入幼儿阶段，会更主动地表达需要，但仍然不是能承担成人逻辑的居民。"
    elif new_stage == "child":
        replacement = "能说话的孩子"
        stage_line = f"{name}已经长成能说话的孩子，五官和神态逐渐清晰，早年的柔软感还留在气质里。"
    elif new_stage == "adult":
        replacement = "成年后的模样"
        stage_line = f"{name}已经长成成人，外貌不再带着婴儿时期的特征，只隐约保留早年柔和安静的底色。"
    else:
        replacement = "正在长大的孩子"
        stage_line = f"{name}正在从 {old_stage} 成长到 {new_stage}。"

    def rewrite(text: str, fallback: str) -> str:
        text = text.strip()
        if not text:
            return fallback
        for term in baby_terms:
            text = text.replace(term, replacement)
        return text

    agent.appearance_short = rewrite(short, replacement)[:120]
    agent.appearance_full = rewrite(full, stage_line)
    if stage_line not in agent.appearance_full:
        agent.appearance_full = f"{agent.appearance_full} {stage_line}"


def _replace_pending_request(requests: list[dict[str, Any]], request: dict[str, Any]) -> list[dict[str, Any]]:
    remaining = [
        old
        for old in requests
        if not (old.get("from_agent_id") == request.get("from_agent_id") and old.get("to_agent_id") == request.get("to_agent_id") and old.get("status") == "pending")
    ]
    return [*remaining, request]


def _resolve_pending_request(requests: list[dict[str, Any]], requester_id: str, status: str) -> list[dict[str, Any]]:
    resolved = []
    for request in requests:
        if request.get("from_agent_id") == requester_id and request.get("status") == "pending":
            resolved.append({**request, "status": status})
        else:
            resolved.append(request)
    return resolved


def _pending_request_from(agent: Agent, requester_id: str) -> dict[str, Any] | None:
    for request in (agent.family_json or {}).get("pending_intimacy_requests", []):
        if request.get("from_agent_id") == requester_id and request.get("status") == "pending":
            return request
    return None


def _consent_engine_accepts(session: Session, accepter: Agent, requester: Agent) -> bool:
    return True


def _maybe_start_pregnancy(session: Session, world: World, agent_a: Agent, agent_b: Agent, source_event_id: int):
    if not reproduction_toolset_enabled(world):
        return None
    pregnancy_mode = (world.settings_json or {}).get("pregnancy_mode", "any_gender")
    pregnant_agent = _choose_pregnancy_carrier(agent_a, agent_b, pregnancy_mode=pregnancy_mode)
    if not pregnant_agent:
        return None
    pregnancy = (pregnant_agent.family_json or {}).get("pregnancy_state") or {}
    if pregnancy.get("pregnant"):
        return None
    used_contraception = _consume_inventory_item(session, agent_a.agent_id, "避孕用品", 1) or _consume_inventory_item(session, agent_b.agent_id, "避孕用品", 1)
    chance = 0.02 if used_contraception else 0.18
    plans = [((agent.family_json or {}).get("adult_intimacy_profile") or {}).get("family_plan") for agent in [agent_a, agent_b]]
    if "wants_children" in plans and not used_contraception:
        chance += 0.17
    rng = random.Random(f"pregnancy:{world.seed}:{world.current_world_time_minutes}:{agent_a.agent_id}:{agent_b.agent_id}")
    if rng.random() >= chance:
        return None
    co_parent = agent_b if pregnant_agent.agent_id == agent_a.agent_id else agent_a
    pregnant_agent.family_json = {
        **pregnant_agent.family_json,
        "pregnancy_state": {
            "pregnant": True,
            "co_parent_agent_id": co_parent.agent_id,
            "started_world_time": world.current_world_time_minutes,
            "due_world_time": world.current_world_time_minutes + 10 * 1440,
            "discovered": False,
            "source_event_id": source_event_id,
        },
    }
    return create_event(
        session,
        world=world,
        event_type="pregnancy_started",
        actor_agent_id=pregnant_agent.agent_id,
        target_agent_id=co_parent.agent_id,
        location_id=pregnant_agent.location.location_id if pregnant_agent.location else None,
        visibility_scope="private",
        viewer_text=f"{pregnant_agent.chosen_name} 身上出现了一个新的生命迹象，只是这个秘密现在还未必被任何人意识到。",
        importance=80,
        color_class="important",
        payload={"pregnancy_mode": pregnancy_mode},
    )


def _choose_pregnancy_carrier(agent_a: Agent, agent_b: Agent, *, pregnancy_mode: str = "any_gender") -> Agent | None:
    candidates = []
    for agent in [agent_a, agent_b]:
        other = agent_b if agent.agent_id == agent_a.agent_id else agent_a
        if pregnancy_mode == "heterosexual" and not (_is_gender(agent, "女") and _is_gender(other, "男")):
            continue
        profile = ((agent.family_json or {}).get("adult_intimacy_profile") or {}).get("reproductive_profile") or {}
        if profile.get("can_be_pregnant") and profile.get("fertility_enabled", True):
            other_profile = ((other.family_json or {}).get("adult_intimacy_profile") or {}).get("reproductive_profile") or {}
            if other_profile.get("can_impregnate") and other_profile.get("fertility_enabled", True):
                candidates.append(agent)
    if not candidates:
        return None
    return random.choice(candidates)


def _is_gender(agent: Agent, expected: str) -> bool:
    text = f"{agent.gender_identity or ''} {agent.gender_custom_text or ''}"
    if expected == "女":
        return "女" in text or "女性" in text
    if expected == "男":
        return "男" in text or "男性" in text
    return False


async def _create_child_from_birth(session: Session, world: World, parent: Agent, pregnancy: dict[str, Any]):
    child_id = f"agent_{uuid.uuid4().hex[:12]}"
    co_parent_id = pregnancy.get("co_parent_agent_id")
    co_parent = session.get(Agent, co_parent_id) if co_parent_id else None
    selected_model, capacity_exhausted = _select_available_baby_model(session, world)
    child_name = _fallback_child_name(parent) if capacity_exhausted else await _decide_child_name(world, parent, co_parent)
    growth_locked = capacity_exhausted
    draft = _fallback_child_identity(child_name, growth_locked=growth_locked)
    if selected_model and not growth_locked:
        generated = await _generate_child_identity(world, child_name, parent, co_parent, selected_model)
        if generated:
            draft = generated.model_copy(update={"chosen_name": child_name})
    trait_budget = int((world.settings_json or {}).get("trait_budget", 500))
    traits = random_traits_with_budget(world.seed + world.current_world_time_minutes + len(child_id), min(1000, max(0, trait_budget)))
    model_payload = _public_model_payload(selected_model)
    child = Agent(
        agent_id=child_id,
        world_id=world.world_id,
        lifecycle_state="alive",
        model_alias="world_agent",
        model_provider_name=None if growth_locked else (selected_model or {}).get("provider_name"),
        model_name=None if growth_locked else (selected_model or {}).get("model_name"),
        llm_base_url=None if growth_locked else (selected_model or {}).get("base_url"),
        llm_api_key=None if growth_locked else (selected_model or {}).get("api_key"),
        chosen_name=child_name,
        gender_identity=draft.gender_identity,
        gender_custom_text=draft.gender_custom_text,
        gender_publicity=draft.gender_publicity,
        gender_expression=draft.gender_expression,
        age_stage="newborn",
        appearance_full=draft.appearance_full,
        appearance_short=draft.appearance_short,
        avatar_hint_json=draft.avatar_hint,
        speaking_style=draft.speaking_style,
        personality_seed=draft.personality_seed,
        initial_goal=draft.initial_goal,
        intro_policy="secretive",
        wallet_json={
            "money": 0,
            "housing": {
                "status": "dependent",
                "quality_tier": "guardian_home",
                "rent_per_10_days": 0,
                "next_rent_due_day": None,
                "rent_late_count": 0,
                "homeless": False,
                "home_location_id": ((parent.wallet_json or {}).get("housing") or {}).get("home_location_id") or (parent.location.location_id if parent.location else None),
                "guardian_dependent": True,
            },
        },
        work_json={"job": None, "employed": False, "fatigue": 0, "burnout": 0, "shifts_worked": 0},
        family_json={"partner_agent_id": None, "children_agent_ids": [], "guardian_agent_ids": [x for x in [parent.agent_id, co_parent_id] if x], "pregnancy_state": None, "pending_intimacy_requests": []},
        law_json={"jailed": False, "jail_days_remaining": 0, "criminal_records": [], "victim_records": []},
        trauma_json={"facts": [], "emotional_intensity": 0, "recovery_count": 0},
        desires_json={"joy": 45, "sadness": 20, "anger": 0, "fear": 25, "anxiety": 25, "boredom": 5, "loneliness": 10, "romance_need": 0, "novelty_need": 5, "mastery_need": 0, "status_need": 0, "survival_pressure": 15, "moral_pressure": 0},
        morality_json={"justice": 0, "desire_for_reward": 0, "guilt_sensitivity": 0, "boundary_respect": 0},
        tool_learning_json={
            "stage": "newborn",
            "llm_enabled": False,
            "learned": [],
            "tool_context_mode": "dynamic",
            "agent_toolset_ids": list(DEFAULT_AGENT_SPECIAL_TOOLSET_IDS),
            "llm_runtime": normalize_llm_runtime(selected_model),
            "growth_locked": growth_locked,
            "locked_reason": "all_candidate_llms_at_capacity" if growth_locked else None,
            "future_model": model_payload,
        },
        created_at_world_time=world.current_world_time_minutes,
    )
    session.add(child)
    session.flush()
    session.add(AgentTrait(agent_id=child_id, **traits))
    dynamic_state = initial_dynamic_state(child_id, world.current_world_time_minutes)
    if growth_locked:
        dynamic_state.health = 42
        dynamic_state.energy = 48
        dynamic_state.satiety = 68
        dynamic_state.hydration = 68
        dynamic_state.stress = 48
        dynamic_state.mood = -15
        dynamic_state.critical_reason = "先天虚弱，成长被锁定"
    session.add(dynamic_state)
    if parent.location:
        session.add(AgentLocation(agent_id=child_id, location_id=parent.location.location_id, arrived_at_world_time=world.current_world_time_minutes))
    parent.family_json = {
        **parent.family_json,
        "pregnancy_state": None,
        "children_agent_ids": [*(parent.family_json or {}).get("children_agent_ids", []), child_id],
    }
    if co_parent:
        ensure_v5_agent_state(co_parent)
        co_parent.family_json = {**co_parent.family_json, "children_agent_ids": [*(co_parent.family_json or {}).get("children_agent_ids", []), child_id]}
    if growth_locked:
        text = f"{parent.chosen_name} 生下了 {child_name}。孩子显得格外虚弱，像是被困在不会长大的婴儿状态里，也不会接入 LLM。"
    else:
        text = f"{parent.chosen_name} 生下了 {child_name}。这个小小的新居民还不会说话，只会用哭声和动作表达需要。"
    return create_event(
        session,
        world=world,
        event_type="birth",
        actor_agent_id=child_id,
        target_agent_id=parent.agent_id,
        location_id=parent.location.location_id if parent.location else None,
        viewer_text=text,
        importance=95,
        color_class="important",
        payload={
            "child_agent_id": child_id,
            "parents": [x for x in [parent.agent_id, co_parent_id] if x],
            "selected_baby_model": model_payload,
            "all_candidate_llms_at_capacity": growth_locked,
        },
    )


def _select_available_baby_model(session: Session, world: World) -> tuple[dict[str, Any] | None, bool]:
    candidates = _baby_model_candidates(session, world)
    if not candidates:
        return None, True
    rng = random.Random(f"baby-model:{world.seed}:{world.current_world_time_minutes}:{len(candidates)}")
    rng.shuffle(candidates)
    for candidate in candidates:
        if provider.model_has_capacity_now(model_name=candidate.get("model_name"), base_url=candidate.get("base_url")):
            return candidate, False
    return None, True


def _baby_model_candidates(session: Session, world: World) -> list[dict[str, Any]]:
    configured = [item for item in (world.settings_json or {}).get("baby_model_pool", []) if item.get("model_name")]
    if configured:
        return [dict(item) for item in configured]
    agents = list(
        session.execute(
            select(Agent)
            .where(Agent.world_id == world.world_id, Agent.lifecycle_state.in_(["alive", "critical"]))
            .order_by(Agent.created_at_world_time.asc(), Agent.agent_id.asc())
        ).scalars()
    )
    candidates = []
    seen: set[tuple[str, str, str | None]] = set()
    for agent in agents:
        model_name = agent.model_name or settings.model_name(agent.model_alias or "world_agent")
        base_url = agent.llm_base_url or settings.llm_base_url
        key = (base_url.rstrip("/"), model_name, agent.llm_api_key)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "provider_id": "copied_from_agent",
                "provider_name": agent.model_provider_name or settings.llm_default_provider,
                "base_url": base_url,
                "api_key": agent.llm_api_key,
                "model_name": model_name,
                "source_agent_id": agent.agent_id,
                "source_agent_name": agent.chosen_name,
                **agent_llm_runtime(agent),
            }
        )
    return candidates


async def _decide_child_name(world: World, parent: Agent, co_parent: Agent | None) -> str:
    parents = "、".join(name for name in [parent.chosen_name, co_parent.chosen_name if co_parent else None] if name)
    language = world_language(world)
    system = baby_name_system(language)
    if normalize_language(language) == "en":
        user = f"""
World time: {world.current_world_time_minutes}
Parents/guardians: {parents}
Name the newborn child. The name must be at most 24 characters, not a placeholder like "someone's child", and not a real public figure name.
Output only one line: NAME=name.
"""
    else:
        user = f"""
世界时间: {world.current_world_time_minutes}
父母/监护人: {parents}
请为刚出生的孩子取名。名字最多 12 个字符，不要包含“的孩子”这种占位写法，不要使用真实公众人物姓名。
只输出一行 NAME=名字。
"""
    result = await provider.complete_text(
        model_alias=parent.model_alias,
        system_prompt=system,
        user_prompt=user,
        temperature=0.8,
        model_name=parent.model_name,
        base_url=parent.llm_base_url,
        api_key=parent.llm_api_key,
        **llm_runtime_kwargs(agent_llm_runtime(parent)),
    )
    parsed_name = parse_baby_name(result.raw_text)
    if parsed_name:
        return parsed_name.chosen_name[:12]
    base = (parent.chosen_name or "新生儿")[:6]
    return _fallback_child_name(parent)


def _fallback_child_name(parent: Agent) -> str:
    base = (parent.chosen_name or "新生儿")[:6]
    return f"{base}小星"[:12]


async def _generate_child_identity(world: World, child_name: str, parent: Agent, co_parent: Agent | None, model_config: dict[str, Any]) -> IdentityDraft | None:
    parents = "、".join(name for name in [parent.chosen_name, co_parent.chosen_name if co_parent else None] if name)
    system = (
        identity_protocol_system(child=True, language=world_language(world))
        + (" This identity belongs to a newborn, not an adult; the child cannot speak now, begins simple speech after 5 days, and grows into an adult after 30 days." if normalize_language(world_language(world)) == "en" else "这个身份属于新生儿，不是成人；现在不会说话，5 天后才会开始说简单话，30 天后成长为成人。")
    )
    if normalize_language(world_language(world)) == "en":
        user = f"""
Fixed name: {child_name}
Parents/guardians: {parents}
World tone: local small-world life, survival, growth, and relationships.
Generate the identity using the field-line protocol.
Hard requirements:
- NAME must equal "{child_name}".
- LOOK_FULL describes newborn/toddler-stage appearance and presence; do not write an adult.
- SPEAK describes that the child cannot speak yet and how they may express themselves later.
- SEED describes a possible personality seed, not a mature life history.
{identity_protocol_user_suffix('en')}
"""
    else:
        user = f"""
已确定姓名: {child_name}
父母/监护人: {parents}
世界基调: 本地小世界中的生活、生存、成长和关系。
请按字段行协议生成身份。
硬要求:
- NAME 必须等于“{child_name}”。
- LOOK_FULL 描述新生儿/幼儿阶段的外貌和气质，不要写成成年人。
- SPEAK 写“现在不会说话，未来可能如何表达”的风格。
- PERSONALITY 写未来可能形成的人格萌芽，不要写成熟履历。
{identity_protocol_user_suffix()}
"""
    result = await provider.complete_text(
        model_alias="world_agent",
        system_prompt=system,
        user_prompt=user,
        temperature=0.85,
        model_name=model_config.get("model_name"),
        base_url=model_config.get("base_url"),
        api_key=model_config.get("api_key"),
        **llm_runtime_kwargs(normalize_llm_runtime(model_config)),
    )
    parsed_identity = result.parsed_object if isinstance(result.parsed_object, IdentityDraft) else parse_identity_draft(result.raw_text, forced_name=child_name, child=True)
    if isinstance(parsed_identity, IdentityDraft):
        return parsed_identity
    return None


def _fallback_child_identity(child_name: str, *, growth_locked: bool) -> IdentityDraft:
    if growth_locked:
        return IdentityDraft(
            chosen_name=child_name,
            gender_identity="不愿公开",
            gender_custom_text="",
            gender_publicity=False,
            gender_expression="虚弱的新生儿",
            appearance_full=f"{child_name}是刚出生的孩子，呼吸和哭声都很轻，像是被困在一个不会继续长大的婴儿阶段，只能靠微弱动作表达需求。",
            appearance_short="格外虚弱的新生儿",
            avatar_hint={"color": "#8aa0a4", "tags": ["newborn", "fragile"]},
            speaking_style="不会说话，只能用哭声和动作表达。",
            personality_seed="太小也太虚弱，还没有形成清晰人格。",
            initial_goal="被照顾并活下去。",
            intro_policy="secretive",
            trait_sliders={},
        )
    return IdentityDraft(
        chosen_name=child_name,
        gender_identity="不愿公开",
        gender_custom_text="",
        gender_publicity=False,
        gender_expression="新生儿",
        appearance_full=f"{child_name}是刚出生的新生儿，脸颊很软，眼睛还带着初来世界的茫然，只会通过哭声、睡眠和细小动作表达需求。",
        appearance_short="刚出生的小新生儿",
        avatar_hint={"color": "#8dbf9f", "tags": ["newborn"]},
        speaking_style="现在不会说话，未来会先学简单词。",
        personality_seed="刚出生，还没有形成清晰人格，但对声音、温度和照护会有最早的记忆。",
        initial_goal="被照顾并活下去。",
        intro_policy="secretive",
        trait_sliders={},
    )


def _public_model_payload(model_config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not model_config:
        return None
    return {
        "provider_id": model_config.get("provider_id"),
        "provider_name": model_config.get("provider_name"),
        "model_name": model_config.get("model_name"),
        "source_agent_id": model_config.get("source_agent_id"),
        "source_agent_name": model_config.get("source_agent_name"),
    }


def _sentence_to_jail(session: Session, world: World, actor: Agent, days: int, reason: str, location_id: str | None):
    days = max(0, min(10, int(days)))
    jail = _ensure_jail_location(session, world)
    if actor.location:
        actor.location.location_id = jail.location_id
        actor.location.location = jail
        actor.location.arrived_at_world_time = world.current_world_time_minutes
    actor.law_json = {
        **actor.law_json,
        "jailed": True,
        "jail_days_remaining": days,
        "jail_until_world_time": world.current_world_time_minutes + days * 1440,
        "last_sentence_reason": reason,
    }
    return create_event(session, world=world, event_type="jail_sentence", actor_agent_id=actor.agent_id, location_id=jail.location_id, viewer_text=f"{actor.chosen_name} 因{reason}被送入临时看守所，刑期 {days} 天，上限不会超过 10 天。", importance=90, color_class="danger", payload={"days": days, "reason": reason, "from_location_id": location_id})


def _ensure_jail_location(session: Session, world: World) -> Location:
    jail_id = f"{world.world_id}:jail"
    jail = session.get(Location, jail_id)
    if jail:
        return jail
    jail = Location(
        location_id=jail_id,
        world_id=world.world_id,
        public_name="临时看守所",
        description="一处只用于司法后果的封闭小楼，里面有窄床、简易书架和低薪劳动安排。",
        neighbors_json=[f"{world.world_id}:central_square"],
        available_tools_json=["jail_rest", "jail_low_paid_work", "jail_reflect", "jail_write_letter", "jail_wait_release", "refuse_jail_work", "attempt_jail_escape"],
        tags_json=["jail", "quiet", "work"],
    )
    session.add(jail)
    session.flush()
    return jail


def _inventory_quantity(session: Session, agent_id: str, item_name: str) -> int:
    rows = session.execute(
        select(Inventory)
        .join(Item, Item.item_id == Inventory.item_id)
        .where(Inventory.agent_id == agent_id, Item.name == item_name)
    ).scalars()
    return sum(inv.quantity for inv in rows)


def _add_inventory_item(session: Session, agent_id: str, name: str, description: str, item_type: str, quantity: int) -> None:
    inv = session.execute(
        select(Inventory)
        .join(Item, Item.item_id == Inventory.item_id)
        .where(Inventory.agent_id == agent_id, Item.name == name)
    ).scalar_one_or_none()
    if inv:
        inv.quantity += quantity
        return
    item = Item(item_id=f"item_{uuid.uuid4().hex[:12]}", world_id=session.get(Agent, agent_id).world_id, name=name, description=description, item_type=item_type)
    session.add(item)
    session.flush()
    session.add(Inventory(agent_id=agent_id, item_id=item.item_id, quantity=quantity))


def _consume_inventory_item(session: Session, agent_id: str, name: str, quantity: int) -> bool:
    inv = session.execute(
        select(Inventory)
        .join(Item, Item.item_id == Inventory.item_id)
        .where(Inventory.agent_id == agent_id, Item.name == name, Inventory.quantity >= quantity)
    ).scalar_one_or_none()
    if not inv:
        return False
    inv.quantity -= quantity
    if inv.quantity <= 0:
        session.delete(inv)
    return True


def _simple_tool_failed(session: Session, world: World, actor: Agent, location_id: str | None, message: str):
    return create_event(
        session,
        world=world,
        event_type="tool_failed",
        actor_agent_id=actor.agent_id,
        location_id=location_id,
        visibility_scope="system",
        viewer_text=f"{actor.chosen_name} 没能完成行动: {message}",
        agent_visible_text=message,
        importance=10,
        no_state_changed=True,
    )


def _group_fun(session: Session, world: World, actor: Agent, tool_name: str, params: dict[str, Any], location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    visible = build_visible_people(session, actor, world.current_world_time_minutes)
    if tool_name == "tell_story_nearby":
        content = str(params.get("story") or params.get("speech") or "讲了一个关于微世界、食物和陌生人慢慢互相信任的故事。")
        text = f"{actor.chosen_name} 给附近的人讲故事: “{content}”"
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, fun=8, energy=-4, social=6))
        for p in visible:
            target = session.get(Agent, p.target_agent_id)
            if target:
                state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, fun=5))
                adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=3, affection=1)
        importance = 60
        event_type = "story"
    elif tool_name == "sing_nearby":
        text = f"{actor.chosen_name} 在附近轻声唱了一小段歌。"
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, fun=7, energy=-3, social=4))
        importance = 55
        event_type = "sing"
    else:
        text = f"{actor.chosen_name} 发起了一个简单游戏，附近的人被邀请一起参与。"
        participants = [actor.agent_id] + [p.target_agent_id for p in visible]
        for agent_id in participants:
            target = session.get(Agent, agent_id)
            if target:
                state_delta = _merge_delta(state_delta, target.agent_id, apply_delta(target.dynamic_state, fun=12, energy=-5, social=8))
        for p in visible:
            adjust_relationship(session, actor.agent_id, p.target_agent_id, world_time=world.current_world_time_minutes, affection=2, familiarity=3)
            adjust_relationship(session, p.target_agent_id, actor.agent_id, world_time=world.current_world_time_minutes, affection=2, familiarity=3)
        importance = 65
        event_type = "game"
    event = create_event(session, world=world, event_type=event_type, actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=text, importance=importance)
    return [event.event_id]


def _item_action(session: Session, world: World, actor: Agent, validation: ToolValidation, tool_name: str, params: dict[str, Any], location_id: str | None, state_delta: dict[str, Any]) -> list[int]:
    if tool_name == "forage_food":
        count = random.Random(world.seed + world.current_world_time_minutes).randint(1, 3)
        for _ in range(count):
            item = Item(item_id=f"item_{uuid.uuid4().hex[:12]}", world_id=world.world_id, name="野食", description="刚采集到的可食用植物。", item_type="food")
            session.add(item)
            session.flush()
            session.add(Inventory(agent_id=actor.agent_id, item_id=item.item_id, quantity=1))
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-8, satiety=-3, fun=3))
        text = f"{actor.chosen_name} 在花园采集到了 {count} 份野食。"
        event = create_event(session, world=world, event_type="forage", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=text, importance=30)
        return [event.event_id]
    if tool_name == "craft_simple_item":
        name = str(params.get("item_name") or "手作小物")[:40]
        item = Item(item_id=f"item_{uuid.uuid4().hex[:12]}", world_id=world.world_id, name=name, description="工作坊里制作的简单物品。", item_type="crafted")
        session.add(item)
        session.flush()
        session.add(Inventory(agent_id=actor.agent_id, item_id=item.item_id, quantity=1))
        state_delta = _merge_delta(state_delta, actor.agent_id, apply_delta(actor.dynamic_state, energy=-6, fun=5))
        event = create_event(session, world=world, event_type="craft", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 制作了{name}。", importance=35)
        return [event.event_id]
    if tool_name == "pick_up_item":
        name = str(params.get("item_name") or "")
        item = session.execute(select(Item).where(Item.world_id == world.world_id, Item.location_id == location_id, Item.name.like(f"%{name}%"))).scalar_one_or_none()
        if not item:
            event = create_event(session, world=world, event_type="tool_failed", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 没有找到可捡起的物品。", importance=10, no_state_changed=True)
            return [event.event_id]
        item.location_id = None
        session.add(Inventory(agent_id=actor.agent_id, item_id=item.item_id, quantity=1))
        event = create_event(session, world=world, event_type="pickup", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 捡起了{item.name}。", importance=20)
        return [event.event_id]
    if tool_name in {"give_item_to_visible_agent", "offer_item_to_visible_agent"}:
        target = validation.target_agent
        name = str(params.get("item_name") or "")
        inv = session.execute(select(Inventory).join(Item, Item.item_id == Inventory.item_id).where(Inventory.agent_id == actor.agent_id, Item.name.like(f"%{name}%"))).scalar_one_or_none()
        if not inv or not target:
            event = create_event(session, world=world, event_type="tool_failed", actor_agent_id=actor.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 没能送出物品。", importance=10, no_state_changed=True)
            return [event.event_id]
        item = session.get(Item, inv.item_id)
        inv.quantity -= 1
        if inv.quantity <= 0:
            session.delete(inv)
        session.add(Inventory(agent_id=target.agent_id, item_id=item.item_id, quantity=1))
        adjust_relationship(session, target.agent_id, actor.agent_id, world_time=world.current_world_time_minutes, familiarity=3, affection=2, trust=1)
        event = create_event(session, world=world, event_type="gift", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 把{item.name}递给了{target.chosen_name}。", importance=55)
        return [event.event_id]
    return []


def _memory_or_name_action(session: Session, world: World, actor: Agent, validation: ToolValidation, tool_name: str, params: dict[str, Any], location_id: str | None) -> list[int]:
    if tool_name == "add_memory":
        content = str(params.get("content") or "我需要记住今天发生过的事。")
        add_memory(session, agent_id=actor.agent_id, content=content, world_time=world.current_world_time_minutes, memory_type="long", importance=45)
        event = create_event(session, world=world, event_type="memory", actor_agent_id=actor.agent_id, location_id=location_id, visibility_scope="private", viewer_text=f"{actor.chosen_name} 主动记下了一条长期记忆。", importance=25)
        return [event.event_id]
    target = validation.target_agent
    if tool_name == "record_relationship_note_by_name" and target:
        rel = get_relationship(session, actor.agent_id, target.agent_id)
        rel.notes = str(params.get("note") or "")[:500]
        event = create_event(session, world=world, event_type="relationship_note", actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=location_id, visibility_scope="private", viewer_text=f"{actor.chosen_name} 按姓名记录了关于{target.chosen_name}的关系备注。", importance=25)
        return [event.event_id]
    if tool_name == "introduce_other_agent":
        receiver = validation.target_agent
        known_name = str(params.get("known_name") or params.get("name") or "")
        if receiver:
            target = session.execute(select(Agent).where(Agent.world_id == world.world_id, Agent.chosen_name == known_name)).scalar_one_or_none()
            if target:
                mark_name_known(session, receiver.agent_id, target, world.current_world_time_minutes, "third_party_intro", False)
                event = create_event(session, world=world, event_type="introduce_other", actor_agent_id=actor.agent_id, target_agent_id=receiver.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 向{receiver.chosen_name}介绍了{known_name}这个名字。", importance=55)
                return [event.event_id]
    text_map = {
        "send_private_letter_by_name": "写了一封私信",
        "invite_named_agent_to_event": "发出了邀请",
        "make_public_accusation_by_name": "在布告栏发起了公开指控",
        "nominate_named_agent": "做出了提名",
        "promise_to_named_agent": "认真记录了一项承诺",
    }
    if target:
        event = create_event(session, world=world, event_type=tool_name, actor_agent_id=actor.agent_id, target_agent_id=target.agent_id, location_id=location_id, viewer_text=f"{actor.chosen_name} 对{target.chosen_name}{text_map.get(tool_name, '做了记录')}。", importance=get_tool(tool_name).event_importance if get_tool(tool_name) else 35)
        return [event.event_id]
    return []


def _event_importance(session: Session, event_id: int) -> int:
    from app.core.models import Event

    event = session.get(Event, event_id)
    return event.importance if event else 0


def _localized(world: World, zh: str, en: str) -> str:
    return en if world_language(world) == "en" else zh
