from __future__ import annotations

import pytest

from app.core.models import Event, Location, Memory
from app.effects.effect_engine import execute_tool
from app.events.event_store import create_event
from app.knowledge.perception import build_turn_context
from app.tests.conftest import make_world
from app.tools.registry import available_tools
from app.tools.validators import validate_tool
from app.world.werewolf import (
    handle_werewolf_tool,
    initialize_werewolf_game,
    sync_werewolf_phase,
    werewolf_current_discussion_actor_id,
    werewolf_final_speech_actor_id,
    werewolf_menu_tool_names,
    werewolf_phase,
    werewolf_state,
    werewolf_tool_allowed,
)
from app.world.seed_world import world_location_id


def _agent_by_role(world, agents, role: str):
    roles = werewolf_state(world)["roles"]
    return next(agent for agent in agents if roles.get(agent.agent_id) == role)


def test_day_one_agent_prompt_has_only_flyer_briefing_for_non_wolves(db):
    world, agents = make_world(db, 4)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_role_assignment": {
            "mode": "manual",
            "manual_roles": ["werewolf", "seer", "coroner", "villager"],
        },
    }
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    db.commit()

    seer = agents[1]
    prompt, _refs = build_turn_context(db, world, seer)
    setup_event = db.query(Event).filter(Event.world_id == world.world_id, Event.event_type == "werewolf_setup").one()

    assert "村庄房间里的传单只写着" in prompt
    assert "预言家1个" in prompt
    assert "验尸官1个" in prompt
    assert "守卫0个" in prompt
    assert "没有解释这些称号的用途" in prompt
    assert "狼人存在于村中" not in prompt
    assert "你的隐藏身份固定事实" not in prompt
    assert "另一个人自称同职业就是强冲突线索" not in prompt
    assert f"{agents[0].chosen_name}是狼人" not in prompt
    assert "狼人同伴" not in prompt
    assert (setup_event.payload or {}).get("observer_can_see_roles") is False
    modern_life_terms = ["钱包/工作", "经济压力", "房租", "找工作", "打零工", "加班", "证券", "broker_equity"]
    assert not [term for term in modern_life_terms if term in prompt]
    assert (seer.desires_json or {}).get("werewolf") is None
    assert werewolf_menu_tool_names(db, world, seer) == set()


def test_day_one_wolf_prompt_has_private_role_without_public_reveal(db):
    world, agents = make_world(db, 4)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_role_assignment": {
            "mode": "manual",
            "manual_roles": ["werewolf", "seer", "coroner", "villager"],
        },
    }
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    db.commit()

    wolf = agents[0]
    prompt, _refs = build_turn_context(db, world, wolf)

    assert "只有你知道：你的隐藏身份是狼人" in prompt
    assert "对其他居民来说，这里公开看起来仍只是一个普通村庄" in prompt
    assert "当前你只知道这里是一个普通村庄" not in prompt
    assert "其他居民还不知道狼人存在" in prompt
    assert "狼人存在于村中" not in prompt
    assert ((wolf.desires_json or {}).get("werewolf") or {}).get("role") == "werewolf"
    assert werewolf_state(world).get("public_revealed") is False


def test_role_personality_tilt_preserves_original_persona_after_reveal(db):
    world, agents = make_world(db, 4)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_role_assignment": {
            "mode": "manual",
            "manual_roles": ["werewolf", "idiot", "seer", "villager"],
        },
    }
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state["role_reveal_reason"] = "测试公开"
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    db.commit()

    idiot = agents[1]
    prompt, _refs = build_turn_context(db, world, idiot)

    assert "初始目标: 先了解世界。" in prompt
    assert "你的身份是：白痴" in prompt
    assert "向傻傻的、迟钝的、天然的" in prompt
    assert "这个倾向不能顶掉原本人设" in prompt


def test_public_morning_hunter_and_idiot_tools_are_available_in_village_square(db):
    world, agents = make_world(db, 4)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_role_assignment": {
            "mode": "manual",
            "manual_roles": ["werewolf", "hunter", "idiot", "villager"],
        },
    }
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state["role_reveal_reason"] = "测试公开"
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    square = db.get(Location, world_location_id(world.world_id, "village_square"))
    assert square is not None
    for agent in agents:
        agent.location.location_id = square.location_id
        agent.location.location = square
    db.commit()

    hunter_tools = {spec.tool_name for spec in available_tools(agents[1], square, session=db)}
    idiot_tools = {spec.tool_name for spec in available_tools(agents[2], square, session=db)}

    assert "werewolf_hunter_shoot_by_name" in hunter_tools
    assert "werewolf_idiot_reveal_self" in idiot_tools


def test_witch_save_revives_latest_night_victim_and_removes_corpse_record(db):
    world, agents = make_world(db, 4)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_role_assignment": {
            "mode": "manual",
            "manual_roles": ["werewolf", "witch", "villager", "villager"],
        },
    }
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state["role_reveal_reason"] = "测试公开"
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    db.commit()

    wolf, witch, victim = agents[0], agents[1], agents[2]
    world.current_world_time_minutes = 22 * 60
    sync_werewolf_phase(db, world)
    kill_events = handle_werewolf_tool(db, world, wolf, "werewolf_kill_by_name", {}, target=victim)
    assert any(db.get(Event, event_id).event_type == "werewolf_night_kill" for event_id in kill_events if db.get(Event, event_id))
    assert victim.lifecycle_state == "dead"
    assert (world.settings_json or {}).get("corpse_records")
    assert "werewolf_witch_save_latest" in werewolf_menu_tool_names(db, world, witch)

    save_events = handle_werewolf_tool(db, world, witch, "werewolf_witch_save_latest", {})

    assert any(db.get(Event, event_id).event_type == "werewolf_witch_save" for event_id in save_events if db.get(Event, event_id))
    assert victim.lifecycle_state == "alive"
    assert not (world.settings_json or {}).get("corpse_records")
    assert werewolf_state(world)["night_kills"]["1"]["blocked"] is True
    world.current_world_time_minutes = 24 * 60 + 8 * 60
    morning_events = sync_werewolf_phase(db, world)
    event_types = {db.get(Event, event_id).event_type for event_id in morning_events if db.get(Event, event_id)}
    assert "werewolf_body_found" not in event_types


def test_medium_reports_latest_dead_alignment(db):
    world, agents = make_world(db, 4)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_role_assignment": {
            "mode": "manual",
            "manual_roles": ["werewolf", "medium", "villager", "villager"],
        },
    }
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state["role_reveal_reason"] = "测试公开"
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    agents[0].lifecycle_state = "dead"
    agents[0].death_cause = "测试死亡"
    agents[0].death_at_world_time = 9 * 60
    db.commit()

    medium = agents[1]
    world.current_world_time_minutes = 22 * 60
    sync_werewolf_phase(db, world)
    event_ids = handle_werewolf_tool(db, world, medium, "werewolf_medium_check_latest", {})
    event = next(db.get(Event, event_id) for event_id in event_ids if db.get(Event, event_id).event_type == "werewolf_medium_report")

    assert "狼人阵营" in (event.agent_visible_text or "")
    assert "狼人阵营" in werewolf_state(world)["medium_reports"]["1"][medium.agent_id]


def test_hunter_shot_and_idiot_vote_spare_resolve(db):
    world, agents = make_world(db, 4)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_role_assignment": {
            "mode": "manual",
            "manual_roles": ["werewolf", "hunter", "idiot", "villager"],
        },
    }
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state["role_reveal_reason"] = "测试公开"
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    db.commit()

    hunter, idiot, wolf = agents[1], agents[2], agents[0]
    reveal_events = handle_werewolf_tool(db, world, idiot, "werewolf_idiot_reveal_self", {})
    assert any(db.get(Event, event_id).event_type == "werewolf_idiot_reveal" for event_id in reveal_events if db.get(Event, event_id))

    world.current_world_time_minutes = 24 * 60 + 18 * 60
    sync_werewolf_phase(db, world)
    vote_events: list[int] = []
    for voter in agents:
        vote_events.extend(handle_werewolf_tool(db, world, voter, "werewolf_vote_by_name", {}, target=idiot))
    assert idiot.lifecycle_state == "alive"
    assert any(db.get(Event, event_id).event_type == "werewolf_idiot_spared" for event_id in vote_events if db.get(Event, event_id))

    shot_events = handle_werewolf_tool(db, world, hunter, "werewolf_hunter_shoot_by_name", {}, target=wolf)

    assert wolf.lifecycle_state == "dead"
    assert any(db.get(Event, event_id).event_type == "werewolf_hunter_shot" for event_id in shot_events if db.get(Event, event_id))
    assert (world.settings_json or {}).get("corpse_records")


def test_seer_prompt_keeps_self_role_and_role_count_when_someone_else_claims_seer(db):
    world, agents = make_world(db, 4)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_role_assignment": {
            "mode": "manual",
            "manual_roles": ["werewolf", "seer", "coroner", "villager"],
        },
    }
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    wolf = agents[0]
    seer = agents[1]
    create_event(
        db,
        world=world,
        event_type="werewolf_speech",
        actor_agent_id=wolf.agent_id,
        target_agent_id=seer.agent_id,
        location_id=wolf.location.location_id if wolf.location else None,
        viewer_text=f"{wolf.chosen_name}在圆桌上声称：我是预言家，昨晚已经查验过别人。",
        agent_visible_text=f"{wolf.chosen_name}在圆桌上声称：我是预言家，昨晚已经查验过别人。",
        payload={"speech": "我是预言家，昨晚已经查验过别人。"},
    )
    db.commit()

    prompt, _refs = build_turn_context(db, world, seer)

    assert f"{wolf.chosen_name}在圆桌上声称：我是预言家" in prompt
    assert "你的隐藏身份固定事实：你的身份是：预言家" in prompt
    assert "预言家1个" in prompt
    assert "另一个人自称同职业就是强冲突线索" in prompt


def test_werewolf_role_counts_config_randomizes_requested_counts(db):
    world, agents = make_world(db, 4)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_role_assignment": {
            "mode": "counts",
            "counts": {"werewolf": 1, "seer": 1, "coroner": 1, "guard": 0, "villager": 0},
        },
    }
    world.current_world_time_minutes = 8 * 60

    initialize_werewolf_game(db, world)

    counts = {}
    for role in werewolf_state(world)["roles"].values():
        counts[role] = counts.get(role, 0) + 1
    assert counts == {"werewolf": 1, "seer": 1, "coroner": 1, "villager": 1}


def test_werewolf_manual_role_config_uses_agent_order(db):
    world, agents = make_world(db, 4)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_role_assignment": {
            "mode": "manual",
            "manual_roles": ["werewolf", "seer", "guard", "villager"],
        },
    }
    world.current_world_time_minutes = 8 * 60

    initialize_werewolf_game(db, world)

    roles = werewolf_state(world)["roles"]
    assert [roles[agent.agent_id] for agent in agents] == ["werewolf", "seer", "guard", "villager"]


def test_werewolf_auto_role_pool_only_uses_selected_and_available_roles(db):
    world, _agents = make_world(db, 4)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_role_assignment": {
            "mode": "auto",
            "auto_roles": ["villager", "werewolf", "witch"],
        },
    }
    world.current_world_time_minutes = 8 * 60

    initialize_werewolf_game(db, world)

    assigned = set(werewolf_state(world)["roles"].values())
    assert "werewolf" in assigned
    assert "witch" not in assigned
    assert not (assigned & {"seer", "coroner", "guard", "hunter", "medium", "idiot"})


def test_werewolf_reasoning_tool_upserts_and_deletes_editable_private_memory(db):
    world, agents = make_world(db, 4)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_role_assignment": {
            "mode": "manual",
            "manual_roles": ["werewolf", "seer", "guard", "villager"],
        },
    }
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    seer = agents[1]
    target = agents[0]
    assert "werewolf_record_reasoning" in werewolf_menu_tool_names(db, world, seer)

    first = execute_tool(
        db,
        world=world,
        actor=seer,
        tool_name="werewolf_record_reasoning",
        params={"known_name": target.chosen_name, "content": "身份=狼人；理由=假跳预言家且本轮预言家只有1个。"},
    )
    assert first.ok
    active = db.query(Memory).filter(
        Memory.agent_id == seer.agent_id,
        Memory.memory_type == "werewolf_reasoning",
        Memory.archived.is_(False),
    ).all()
    assert len(active) == 1
    assert f"对{target.chosen_name}的身份推理：身份=狼人" in active[0].content

    updated = execute_tool(
        db,
        world=world,
        actor=seer,
        tool_name="werewolf_record_reasoning",
        params={"known_name": target.chosen_name, "content": "身份=平民；理由=刚才的假跳可能是误听，暂时撤回狼人判断。"},
    )
    assert updated.ok
    active = db.query(Memory).filter(
        Memory.agent_id == seer.agent_id,
        Memory.memory_type == "werewolf_reasoning",
        Memory.archived.is_(False),
    ).all()
    assert len(active) == 1
    assert "身份=平民" in active[0].content
    assert "假跳预言家且本轮预言家只有1个" not in active[0].content
    assert ((seer.desires_json or {}).get("werewolf") or {}).get("reasoning_notes", {}).get(target.agent_id)

    deleted = execute_tool(
        db,
        world=world,
        actor=seer,
        tool_name="werewolf_record_reasoning",
        params={"known_name": target.chosen_name, "content": "删除"},
    )
    assert deleted.ok
    assert not db.query(Memory).filter(
        Memory.agent_id == seer.agent_id,
        Memory.memory_type == "werewolf_reasoning",
        Memory.archived.is_(False),
    ).all()
    assert not ((seer.desires_json or {}).get("werewolf") or {}).get("reasoning_notes", {}).get(target.agent_id)


def test_wolf_pack_mismatch_requires_shared_discussion_before_retry(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "werewolf",
        agents[2].agent_id: "villager",
        agents[3].agent_id: "seer",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {
        **(world.settings_json or {}),
        "werewolf_state": state,
        "werewolf_observer_roles": state["roles"],
    }
    db.commit()

    world.current_world_time_minutes = 24 * 60 + 22 * 60
    sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (2, "night")

    wolf_a, wolf_b = agents[0], agents[1]
    target_a, target_b = agents[2], agents[3]
    assert werewolf_menu_tool_names(db, world, wolf_a) == {"werewolf_wolf_discuss"}
    ok, reason, _message = werewolf_tool_allowed(db, world, wolf_a, "werewolf_kill_by_name")
    assert not ok
    assert reason == "werewolf_discussion_required"

    handle_werewolf_tool(db, world, wolf_a, "werewolf_wolf_discuss", {"speech": f"我觉得可以先看{target_a.chosen_name}，但要听你的判断。"})
    assert werewolf_menu_tool_names(db, world, wolf_a) == set()
    handle_werewolf_tool(db, world, wolf_b, "werewolf_wolf_discuss", {"speech": f"我更怀疑{target_b.chosen_name}，先提名看看是否一致。"})
    assert "werewolf_kill_by_name" in werewolf_menu_tool_names(db, world, wolf_a)

    first_events = handle_werewolf_tool(db, world, wolf_a, "werewolf_kill_by_name", {}, target=target_a)
    assert not first_events or not any((db.get(Event, event_id).event_type if db.get(Event, event_id) else "") == "werewolf_night_kill" for event_id in first_events)

    mismatch_events = handle_werewolf_tool(db, world, wolf_b, "werewolf_kill_by_name", {}, target=target_b)
    assert any((db.get(Event, event_id).event_type if db.get(Event, event_id) else "") == "werewolf_wolf_consensus_failed" for event_id in mismatch_events)
    assert target_a.lifecycle_state != "dead"
    assert target_b.lifecycle_state != "dead"
    assert werewolf_state(world).get("wolf_consensus_need_discussion", {}).get("2") is True
    assert werewolf_menu_tool_names(db, world, wolf_a) == {"werewolf_wolf_discuss"}

    handle_werewolf_tool(db, world, wolf_a, "werewolf_wolf_discuss", {"speech": f"刚才我选的是{target_a.chosen_name}，但我们不一致，所以这次必须统一。"})
    assert werewolf_menu_tool_names(db, world, wolf_a) == set()
    handle_werewolf_tool(db, world, wolf_b, "werewolf_wolf_discuss", {"speech": f"我同意统一选{target_a.chosen_name}，不要再各选各的。"})
    assert werewolf_state(world).get("wolf_consensus_need_discussion", {}).get("2") is False
    assert "werewolf_kill_by_name" in werewolf_menu_tool_names(db, world, wolf_a)

    handle_werewolf_tool(db, world, wolf_a, "werewolf_kill_by_name", {}, target=target_a)
    kill_events = handle_werewolf_tool(db, world, wolf_b, "werewolf_kill_by_name", {}, target=target_a)
    assert any((db.get(Event, event_id).event_type if db.get(Event, event_id) else "") == "werewolf_night_kill" for event_id in kill_events)
    assert target_a.lifecycle_state == "dead"


def test_wolf_night_kill_win_preserves_final_speech_state(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "werewolf",
        agents[2].agent_id: "villager",
        agents[3].agent_id: "seer",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {
        **(world.settings_json or {}),
        "werewolf_state": state,
        "werewolf_observer_roles": state["roles"],
    }
    db.commit()

    world.current_world_time_minutes = 24 * 60 + 22 * 60
    sync_werewolf_phase(db, world)
    wolf_a, wolf_b = agents[0], agents[1]
    target = agents[2]
    handle_werewolf_tool(db, world, wolf_a, "werewolf_wolf_discuss", {"speech": f"我提议今晚选{target.chosen_name}。"})
    handle_werewolf_tool(db, world, wolf_b, "werewolf_wolf_discuss", {"speech": f"同意，今晚统一选{target.chosen_name}。"})
    handle_werewolf_tool(db, world, wolf_a, "werewolf_kill_by_name", {}, target=target)
    kill_events = handle_werewolf_tool(db, world, wolf_b, "werewolf_kill_by_name", {}, target=target)

    event_types = {db.get(Event, event_id).event_type for event_id in kill_events if db.get(Event, event_id)}
    assert "werewolf_night_kill" in event_types
    assert "werewolf_game_decided" in event_types
    assert target.lifecycle_state == "dead"
    assert werewolf_state(world).get("winner") == "狼人阵营"
    assert werewolf_final_speech_actor_id(db, world) in {wolf_a.agent_id, wolf_b.agent_id}
    assert world.status != "ended"

    world.current_world_time_minutes = 2 * 24 * 60 + 8 * 60
    followup_events = sync_werewolf_phase(db, world)
    followup_types = {db.get(Event, event_id).event_type for event_id in followup_events if db.get(Event, event_id)}
    assert "werewolf_body_found" not in followup_types
    assert "werewolf_phase" not in followup_types
    assert werewolf_state(world).get("winner") == "狼人阵营"


def test_exiled_player_is_remembered_and_removed_from_wolf_targets(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "villager",
        agents[2].agent_id: "villager",
        agents[3].agent_id: "seer",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    db.commit()

    world.current_world_time_minutes = 24 * 60 + 18 * 60
    sync_werewolf_phase(db, world)
    target = agents[1]
    for voter in agents:
        handle_werewolf_tool(db, world, voter, "werewolf_vote_by_name", {}, target=target)
    db.commit()

    assert target.lifecycle_state == "dead"
    wolf_memory_text = "\n".join(
        memory.content
        for memory in db.query(Memory).filter(Memory.agent_id == agents[0].agent_id).order_by(Memory.memory_id).all()
    )
    assert f"第2天投票结果：{target.chosen_name}已经被白天投票放逐出局" in wolf_memory_text
    assert "不要再把这个人当作可行动目标" in wolf_memory_text

    world.current_world_time_minutes = 24 * 60 + 22 * 60
    prompt, _refs = build_turn_context(db, world, agents[0])
    assert f"{target.chosen_name}(白天投票放逐出局)" in prompt
    assert "已死亡或被放逐者不能再发言、投票、被投票、被夜袭、被查验或被守护" in prompt
    private_line = next(line for line in prompt.splitlines() if "今晚可夜袭目标只能从当前存活且不是狼人同伴的人里选" in line)
    assert target.chosen_name not in private_line
    assert agents[2].chosen_name in private_line
    assert agents[3].chosen_name in private_line


def test_vote_resolves_at_eighteen_then_returns_to_free_activity(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "villager",
        agents[2].agent_id: "villager",
        agents[3].agent_id: "seer",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    db.commit()

    vote_minute = 24 * 60 + 18 * 60
    world.current_world_time_minutes = vote_minute
    sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (2, "voting")

    target = agents[1]
    for voter in agents:
        vote_target = agents[2] if voter.agent_id == target.agent_id else target
        result = execute_tool(db, world=world, actor=voter, tool_name="werewolf_vote_by_name", params={"known_name": vote_target.chosen_name})
        assert result.ok
        assert world.current_world_time_minutes == vote_minute

    assert target.lifecycle_state == "dead"
    assert werewolf_phase(world) == (2, "morning")
    free_activity_events = sync_werewolf_phase(db, world)
    phase_texts = [
        db.get(Event, event_id).viewer_text
        for event_id in free_activity_events
        if db.get(Event, event_id) and db.get(Event, event_id).event_type == "werewolf_phase"
    ]
    assert any("18:00到22:00恢复自由活动" in text for text in phase_texts)
    assert not any("清晨发生的死亡事件" in text for text in phase_texts)
    assert "werewolf_vote_by_name" not in werewolf_menu_tool_names(db, world, agents[0])
    names = {tool.tool_name for tool in available_tools(agents[0], agents[0].location.location, session=db)}
    assert "werewolf_vote_by_name" not in names
    assert "speak_to_nearby" in names
    assert not any(name.startswith(("market_", "tool_market_", "v6_")) for name in names)
    assert not {"apply_for_job", "do_odd_job", "work_shift_cafeteria", "work_overtime_shift", "complain_about_work"} & names
    assert "gift_item_to_visible_agent" not in names
    blocked = validate_tool(db, actor=agents[0], tool_name="v6_read_market_news", params={"ticker": "MGL"}, world_time=world.current_world_time_minutes)
    assert not blocked.ok
    assert blocked.reason_code == "non_modern_life_tool_blocked"
    assert blocked.message == "当前世界观未启用现代生活工具集，现代集市、金融、雇佣和 v6 经济工具不会开放。"


@pytest.mark.parametrize(
    "role_order",
    [
        ["werewolf", "seer", "coroner", "villager"],
        ["seer", "werewolf", "villager", "coroner"],
        ["villager", "coroner", "seer", "werewolf"],
    ],
)
def test_iterated_werewolf_game_flow_starts_hidden_until_first_body_found(db, role_order):
    world, agents = make_world(db, 4)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_role_assignment": {"mode": "manual", "manual_roles": role_order},
    }
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    db.commit()

    wolf = _agent_by_role(world, agents, "werewolf")
    seer = _agent_by_role(world, agents, "seer")

    world.current_world_time_minutes = 12 * 60
    assert werewolf_phase(world) == (1, "morning")
    assert werewolf_menu_tool_names(db, world, seer) == set()
    assert (seer.desires_json or {}).get("werewolf") is None
    prompt, _refs = build_turn_context(db, world, seer)
    assert "村庄房间里的传单只写着" in prompt
    assert "狼人存在于村中" not in prompt
    assert "你的隐藏身份固定事实" not in prompt

    world.current_world_time_minutes = 22 * 60
    night_events = sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (1, "night")
    assert werewolf_menu_tool_names(db, world, seer) == set()
    assert "werewolf_kill_by_name" in werewolf_menu_tool_names(db, world, wolf)
    assert any((db.get(Event, event_id).event_type if db.get(Event, event_id) else "") == "sleep_start" for event_id in night_events)
    victim = next(agent for agent in agents if agent.agent_id not in {wolf.agent_id, seer.agent_id})
    kill_events = handle_werewolf_tool(db, world, wolf, "werewolf_kill_by_name", {}, target=victim)
    hidden_kill_events = [db.get(Event, event_id) for event_id in kill_events if db.get(Event, event_id) and db.get(Event, event_id).event_type == "werewolf_night_kill_hidden"]
    assert len(hidden_kill_events) == 1
    assert (hidden_kill_events[0].payload or {}).get("agent_facing_locked") is True
    assert victim.lifecycle_state == "dead"
    assert (world.settings_json or {}).get("corpse_records", [{}])[0].get("cause") == "未知夜间袭击"

    world.current_world_time_minutes = 24 * 60 + 8 * 60
    morning_events = sync_werewolf_phase(db, world)
    morning_events += sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (2, "morning")
    notice_events = [db.get(Event, event_id) for event_id in morning_events if db.get(Event, event_id) and db.get(Event, event_id).event_type == "werewolf_notice_board"]
    assert len(notice_events) == 1
    assert notice_events[0].viewer_text == "清晨，村庄广场的告示牌上浮现血红字“狼人存在于村中”。所有幸存者都能看到，并且被某种力量确信这句话是真的。"
    body_events = [db.get(Event, event_id) for event_id in morning_events if db.get(Event, event_id) and db.get(Event, event_id).event_type == "werewolf_body_found"]
    assert len(body_events) == 1
    assert body_events[0].target_agent_id == victim.agent_id
    assert (world.settings_json or {}).get("corpse_records", [{}])[0].get("cause") == "狼人夜间袭击"
    assert werewolf_state(world).get("public_revealed") is True
    assert ((wolf.desires_json or {}).get("werewolf") or {}).get("role") == "werewolf"

    world.current_world_time_minutes = 24 * 60 + 12 * 60
    sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (2, "discussion")
    living_order = [agent.agent_id for agent in agents if agent.lifecycle_state != "dead"]
    spoken_order: list[str] = []
    while True:
        current_id = werewolf_current_discussion_actor_id(db, world)
        if not current_id:
            break
        speaker = next(agent for agent in agents if agent.agent_id == current_id)
        spoken_order.append(speaker.agent_id)
        menu = werewolf_menu_tool_names(db, world, speaker)
        assert menu == {"werewolf_speak"}
        speech_events = handle_werewolf_tool(
            db,
            world,
            speaker,
            "werewolf_speak",
            {"speech": f"昨晚{victim.chosen_name}遇害，尸体是今天的核心线索。我要听完所有人的说法再投票。"},
        )
        assert any((db.get(Event, event_id).event_type if db.get(Event, event_id) else "") == "werewolf_speech" for event_id in speech_events)
        assert "werewolf_end_speech" not in werewolf_menu_tool_names(db, world, speaker)
        assert "werewolf_rebut" not in werewolf_menu_tool_names(db, world, speaker)
    assert spoken_order == living_order
    assert world.current_world_time_minutes == 24 * 60 + 12 * 60

    world.current_world_time_minutes = 24 * 60 + 18 * 60
    sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (2, "voting")
    for agent in agents:
        if agent.lifecycle_state != "dead":
            handle_werewolf_tool(db, world, agent, "werewolf_vote_by_name", {}, target=wolf)
    db.commit()
    assert wolf.lifecycle_state == "dead"
    state = werewolf_state(world)
    assert state.get("winner") == "人类阵营"
    assert world.status != "ended"


def test_werewolf_morning_announcements_reuse_existing_events_when_state_is_stale(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "villager",
        agents[2].agent_id: "villager",
        agents[3].agent_id: "seer",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state["day"] = 1
    state["phase"] = "night"
    state["night_kills"] = {
        "1": {
            "target_agent_id": agents[1].agent_id,
            "blocked": False,
            "location_id": agents[1].location.location_id,
        }
    }
    state["wolf_notice_announced"] = {}
    state["body_found_announced"] = {}
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    world.current_world_time_minutes = 24 * 60 + 8 * 60
    agents[1].lifecycle_state = "dead"

    notice = create_event(
        db,
        world=world,
        event_type="werewolf_notice_board",
        viewer_text="清晨，村庄广场的告示牌上浮现血红字“狼人存在于村中”。所有幸存者都能看到，并且被某种力量确信这句话是真的。",
        payload={"day": 2, "wolves_alive": True, "wolf_count": 1, "must_discuss": True},
    )
    body = create_event(
        db,
        world=world,
        event_type="werewolf_body_found",
        target_agent_id=agents[1].agent_id,
        viewer_text=f"清晨，幸存者发现{agents[1].chosen_name}昨夜遭到狼人袭击出局，遗体在集体宿舍。这件事成为今天圆桌必须讨论的核心线索。",
        payload={"day": 2, "night": 1, "target_agent_id": agents[1].agent_id, "location_id": agents[1].location.location_id},
    )

    event_ids = sync_werewolf_phase(db, world)

    event_types = [db.get(Event, event_id).event_type for event_id in event_ids if db.get(Event, event_id)]
    assert "werewolf_notice_board" not in event_types
    assert "werewolf_body_found" not in event_types
    assert db.query(Event).filter(Event.world_id == world.world_id, Event.event_type == "werewolf_notice_board").count() == 1
    assert db.query(Event).filter(Event.world_id == world.world_id, Event.event_type == "werewolf_body_found").count() == 1
    assert werewolf_state(world)["wolf_notice_announced"]["2"]["event_id"] == notice.event_id
    assert werewolf_state(world)["body_found_announced"]["2"]["event_id"] == body.event_id


def test_single_wolf_night_skips_private_discussion_before_and_after_public_reveal(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)

    wolf = _agent_by_role(world, agents, "werewolf")
    world.current_world_time_minutes = 22 * 60
    sync_werewolf_phase(db, world)
    assert werewolf_state(world).get("public_revealed") is False
    assert "werewolf_kill_by_name" in werewolf_menu_tool_names(db, world, wolf)
    assert "werewolf_wolf_discuss" not in werewolf_menu_tool_names(db, world, wolf)
    victim = next(agent for agent in agents if agent.agent_id != wolf.agent_id)
    handle_werewolf_tool(db, world, wolf, "werewolf_kill_by_name", {}, target=victim)

    world.current_world_time_minutes = 24 * 60 + 8 * 60
    sync_werewolf_phase(db, world)
    assert werewolf_state(world).get("public_revealed") is True

    world.current_world_time_minutes = 24 * 60 + 22 * 60
    sync_werewolf_phase(db, world)
    menu = werewolf_menu_tool_names(db, world, wolf)
    assert "werewolf_kill_by_name" in menu
    assert "werewolf_wolf_discuss" not in menu
    ok, reason, _message = werewolf_tool_allowed(db, world, wolf, "werewolf_wolf_discuss")
    assert not ok
    assert reason == "werewolf_single_wolf_no_discussion"
    assert ((wolf.desires_json or {}).get("werewolf") or {}).get("known_wolves") == []


def test_guarded_unrevealed_night_without_death_keeps_village_ordinary(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)

    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "guard",
        agents[2].agent_id: "villager",
        agents[3].agent_id: "seer",
    }
    state["public_revealed"] = False
    state["roles_revealed_to_agents"] = False
    state["day"] = 1
    state["phase"] = "night"
    state["night_kills"] = {"1": {"target_agent_id": agents[2].agent_id, "blocked": True}}
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    world.current_world_time_minutes = 24 * 60 + 8 * 60
    db.commit()

    morning_events = sync_werewolf_phase(db, world)
    event_types = [db.get(Event, event_id).event_type for event_id in morning_events if db.get(Event, event_id)]
    assert "werewolf_notice_board" not in event_types
    assert "werewolf_body_found" not in event_types
    assert werewolf_state(world).get("public_revealed") is False

    world.current_world_time_minutes = 24 * 60 + 12 * 60
    sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (2, "discussion")
    assert werewolf_current_discussion_actor_id(db, world) is None


@pytest.mark.anyio
async def test_werewolf_win_runs_final_llm_speech_before_ending(db, monkeypatch):
    from app.llm.openai_compatible import provider
    from app.llm.provider_base import LLMResult
    from app.simulation.turn_runner import TurnRunner

    world, agents = make_world(db, 3)
    world.status = "running"
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 24 * 60 + 18 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "villager",
        agents[2].agent_id: "villager",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    db.commit()

    for voter in agents:
        if voter.lifecycle_state != "dead":
            handle_werewolf_tool(db, world, voter, "werewolf_vote_by_name", {}, target=agents[0])
    db.commit()

    assert werewolf_state(world).get("winner") == "人类阵营"
    assert world.status == "running"

    async def complete_text(**kwargs):
        return LLMResult("终于结束了。我们至少把最后的危险挡下来了。", None, {}, 1, "test")

    monkeypatch.setattr(provider, "complete_text", complete_text)

    runner = TurnRunner()
    result = await runner.run_one_step(db, world.world_id)
    db.commit()

    assert result.status == "werewolf_final_speech"
    assert db.get(type(world), world.world_id).status == "running"
    result = await runner.run_one_step(db, world.world_id)
    db.commit()

    assert result.status == "werewolf_final_speech"
    assert db.query(Event).filter(Event.world_id == world.world_id, Event.event_type == "werewolf_final_speech").count() == 2
    assert db.get(type(world), world.world_id).status == "ended"


@pytest.mark.anyio
async def test_werewolf_final_speech_empty_llm_does_not_use_fallback(db, monkeypatch):
    from app.llm.openai_compatible import provider
    from app.llm.provider_base import LLMResult
    from app.simulation.turn_runner import TurnRunner

    world, agents = make_world(db, 3)
    world.status = "running"
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 24 * 60 + 22 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "villager",
        agents[2].agent_id: "villager",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state["winner"] = "狼人阵营"
    state["final_speech_order"] = [agent.agent_id for agent in agents]
    state["final_speeches"] = {}
    state["final_speeches_complete"] = False
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    db.commit()

    async def complete_text(**kwargs):
        return LLMResult("", None, {}, 1, "test", "timeout")

    monkeypatch.setattr(provider, "complete_text", complete_text)

    result = await TurnRunner().run_one_step(db, world.world_id)
    db.commit()

    assert result.status == "werewolf_final_speech_retry"
    assert db.query(Event).filter(Event.world_id == world.world_id, Event.event_type == "werewolf_final_speech").count() == 0
    assert werewolf_final_speech_actor_id(db, world) == agents[0].agent_id
    assert db.get(type(world), world.world_id).status == "running"


@pytest.mark.anyio
async def test_werewolf_final_speech_truncated_text_is_retried(db, monkeypatch):
    from app.llm.openai_compatible import provider
    from app.llm.provider_base import LLMResult
    from app.simulation.turn_runner import TurnRunner

    world, agents = make_world(db, 3)
    world.status = "running"
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 24 * 60 + 22 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "villager",
        agents[2].agent_id: "villager",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state["winner"] = "狼人阵营"
    state["final_speech_order"] = [agent.agent_id for agent in agents]
    state["final_speeches"] = {}
    state["final_speeches_complete"] = False
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    db.commit()

    async def complete_text(**kwargs):
        return LLMResult("哎呀呀，果然最后留下的还是我呢，真的", "哎呀呀，果然最后留下的还是我呢，真的", {}, 1, "test")

    monkeypatch.setattr(provider, "complete_text", complete_text)

    result = await TurnRunner().run_one_step(db, world.world_id)
    db.commit()

    assert result.status == "werewolf_final_speech_retry"
    assert db.query(Event).filter(Event.world_id == world.world_id, Event.event_type == "werewolf_final_speech").count() == 0
    assert werewolf_final_speech_actor_id(db, world) == agents[0].agent_id


def test_roundtable_sync_wakes_sleepers_so_discussion_can_run(db):
    from app.simulation.turn_runner import TurnRunner

    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)
    state = werewolf_state(world)
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}

    world.current_world_time_minutes = 24 * 60 + 12 * 60
    for agent in agents:
        agent.desires_json = {
            **(agent.desires_json or {}),
            "sleep_until_world_time": world.current_world_time_minutes + 300,
            "sleep_started_world_time": world.current_world_time_minutes - 60,
            "sleep_planned_minutes": 360,
        }
    db.flush()

    event_ids = sync_werewolf_phase(db, world)
    assert werewolf_phase(world) == (2, "discussion")
    assert any((db.get(Event, event_id).event_type if db.get(Event, event_id) else "") == "wake" for event_id in event_ids)
    assert all(not ((agent.desires_json or {}).get("sleep_until_world_time")) for agent in agents)

    current_id = werewolf_current_discussion_actor_id(db, world)
    batch = TurnRunner()._regular_agent_batch(db, world)
    assert current_id
    assert [agent.agent_id for agent in batch] == [current_id]


@pytest.mark.anyio
async def test_day_three_discussion_recovers_missing_day_state_and_forces_speech(db, monkeypatch):
    from app.core.config import settings
    from app.llm.openai_compatible import provider
    from app.llm.provider_base import LLMResult
    from app.simulation.turn_runner import TurnRunner

    monkeypatch.setattr(settings, "narrator_enabled", False)
    world, agents = make_world(db, 4)
    world.status = "running"
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)

    living_ids = [agent.agent_id for agent in agents]
    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "villager",
        agents[2].agent_id: "seer",
        agents[3].agent_id: "guard",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state["day"] = 3
    state["phase"] = "discussion"
    state["speech_order"] = living_ids
    state["current_speaker_index"] = len(living_ids)
    state["speech_counts"] = {"2": {agent_id: 1 for agent_id in living_ids}, "3": {}}
    state["speech_ended"] = {"2": {agent_id: True for agent_id in living_ids}, "3": {}}
    state["votes"] = {"2": {agents[0].agent_id: agents[1].agent_id, agents[1].agent_id: agents[0].agent_id}}
    state["vote_resolved"] = {"2": True}
    world.current_world_time_minutes = 2 * 24 * 60 + 12 * 60
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    db.commit()

    async def complete_text(**kwargs):
        return LLMResult("[01]\n我会按今天的新一轮线索重新说明怀疑。前一天的发言已经结束，但今天不能跳过圆桌。", None, {}, 1, "test")

    monkeypatch.setattr(provider, "complete_text", complete_text)

    result = await TurnRunner().run_one_step(db, world.world_id)
    db.commit()

    event_types = [db.get(Event, event_id).event_type for event_id in result.event_ids if db.get(Event, event_id)]
    assert "werewolf_speech" in event_types
    assert "look" not in event_types
    assert "self_status" not in event_types
    refreshed_state = werewolf_state(db.get(type(world), world.world_id))
    assert "3" in (refreshed_state.get("speech_counts") or {})
    assert "3" in (refreshed_state.get("speech_ended") or {})
    assert refreshed_state.get("speech_order") == living_ids
    assert int(refreshed_state.get("current_speaker_index") or 0) >= 1


def test_vote_win_short_circuits_to_final_speeches_without_night_actions(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)

    state = werewolf_state(world)
    state["roles"] = {
        agents[0].agent_id: "werewolf",
        agents[1].agent_id: "werewolf",
        agents[2].agent_id: "villager",
        agents[3].agent_id: "seer",
    }
    state["public_revealed"] = True
    state["roles_revealed_to_agents"] = True
    state["day"] = 2
    state["phase"] = "voting"
    state["votes"] = {
        "2": {
            agents[0].agent_id: agents[2].agent_id,
            agents[1].agent_id: agents[2].agent_id,
            agents[2].agent_id: agents[0].agent_id,
            agents[3].agent_id: agents[2].agent_id,
        }
    }
    state["vote_resolved"] = {}
    world.current_world_time_minutes = 24 * 60 + 22 * 60
    world.settings_json = {**(world.settings_json or {}), "werewolf_state": state}
    db.commit()

    event_ids = sync_werewolf_phase(db, world)
    db.commit()

    event_types = {db.get(Event, event_id).event_type for event_id in event_ids if db.get(Event, event_id)}
    assert "werewolf_exile" in event_types
    assert "werewolf_game_decided" in event_types
    assert "sleep_start" not in event_types
    assert "werewolf_night_kill_hidden" not in event_types
    assert "werewolf_night_kill" not in event_types
    assert "werewolf_body_found" not in event_types
    assert werewolf_state(world).get("winner") == "狼人阵营"
    assert werewolf_final_speech_actor_id(db, world) in {agents[0].agent_id, agents[1].agent_id}
    for agent in agents:
        if agent.lifecycle_state != "dead":
            assert not ((agent.desires_json or {}).get("sleep_until_world_time"))


def test_werewolf_vending_machine_exposes_only_narrow_market_tools(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True, "core_toolset_enabled": True}
    world.current_world_time_minutes = 8 * 60
    initialize_werewolf_game(db, world)

    vending_id = world_location_id(world.world_id, "vending_machine")
    vending = db.get(Location, vending_id)
    assert vending is not None
    assert "werewolf_vending" in set(vending.tags_json or [])
    assert "trade" in set(vending.tags_json or [])

    square = db.get(Location, world_location_id(world.world_id, "village_square"))
    cafeteria = db.get(Location, world_location_id(world.world_id, "cafeteria"))
    assert square and vending_id in set(square.neighbors_json or [])
    if cafeteria:
        assert vending_id in set(cafeteria.neighbors_json or [])

    actor = agents[0]
    actor.location.location_id = vending_id
    actor.location.location = vending
    db.flush()

    names = {spec.tool_name for spec in available_tools(actor, vending, session=db)}
    assert {"market_search_goods", "market_recommend_goods", "market_buy_goods", "eat_inventory_food"}.issubset(names)
    assert "apply_for_job" not in names
    assert "work_shift_cafeteria" not in names
    assert "v6_read_market_news" not in names
    assert "gift_item_to_visible_agent" not in names
    assert "transfer_item_to_visible_agent" not in names
    assert "place_inventory_item" not in names

    allowed = validate_tool(db, actor=actor, tool_name="market_buy_goods", params={"item_query": "茶"}, world_time=world.current_world_time_minutes)
    assert allowed.ok

    actor.location.location_id = square.location_id
    actor.location.location = square
    db.flush()
    blocked = validate_tool(db, actor=actor, tool_name="market_buy_goods", params={"item_query": "茶"}, world_time=world.current_world_time_minutes)
    assert not blocked.ok
    assert blocked.reason_code == "non_modern_life_tool_blocked"
