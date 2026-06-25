from __future__ import annotations

from sqlalchemy import select

from app.api.serializers import event_to_dict
from app.core.models import Event, IdentityKnowledge, Location, Memory
from app.effects.effect_engine import execute_tool
from app.economy.v6 import MARKET_TICKERS, ensure_v6_agent_state
from app.events.event_store import create_event
from app.knowledge.perception import build_turn_context, _memory_prompt_lines
from app.simulation.turn_runner import _clean_final_speech_text, _contains_out_of_world_final_speech
from app.world.werewolf import _role_list_for_count, _resolve_day_vote, initialize_werewolf_game, werewolf_final_speech_prompt, werewolf_menu_tool_names, werewolf_phase, werewolf_state

from conftest import make_world


def test_generic_help_transports_unconscious_person_to_medical_room(db):
    world, (helper, patient) = make_world(db, 2)
    helper.location.location_id = f"{world.world_id}:central_square"
    patient.location.location_id = f"{world.world_id}:central_square"
    patient.lifecycle_state = "critical"
    patient.dynamic_state.energy = 0
    patient.dynamic_state.health = 12
    patient.dynamic_state.critical_reason = "energy_depleted"
    patient.desires_json = {"unconscious_until_world_time": world.current_world_time_minutes + 180}
    prompt, refs = build_turn_context(db, world, helper)
    assert "背/扶去医务室" in prompt or "帮助眼前的人" in prompt
    ref = next(ref for ref, target_id in refs.items() if target_id == patient.agent_id)

    result = execute_tool(db, world=world, actor=helper, tool_name="help_visible_agent", params={"visible_ref": ref, "speech": f"{ref}，你看起来很危险，我先扶你去医务室。"})

    assert result.ok
    event = db.get(Event, result.event_ids[0])
    assert event.event_type == "escort_to_medical"
    assert "试着提供帮助" not in event.viewer_text
    assert helper.location.location_id.endswith(":medical_room")
    assert patient.location.location_id == helper.location.location_id
    assert helper.dynamic_state.energy < 90


def test_assisted_meal_can_rescue_starving_person_in_food_or_medical_scene(db):
    world, (helper, patient) = make_world(db, 2)
    cafeteria = db.get(Location, f"{world.world_id}:cafeteria")
    assert cafeteria is not None
    helper.location.location_id = cafeteria.location_id
    helper.location.location = cafeteria
    patient.location.location_id = cafeteria.location_id
    patient.location.location = cafeteria
    helper.wallet_json = {"money": 40}
    patient.dynamic_state.satiety = 4
    patient.dynamic_state.hydration = 8
    patient.dynamic_state.energy = 6
    db.flush()
    prompt, refs = build_turn_context(db, world, helper)
    ref = next(ref for ref, target_id in refs.items() if target_id == patient.agent_id)

    result = execute_tool(db, world=world, actor=helper, tool_name="help_visible_agent", params={"visible_ref": ref, "speech": f"{ref}，我先给你买点饭水，你慢慢吃。"})

    assert result.ok
    event = db.get(Event, result.event_ids[0])
    assert event.event_type == "assisted_meal"
    assert patient.dynamic_state.satiety > 30
    assert patient.dynamic_state.hydration > 30
    assert helper.wallet_json["money"] < 40


def test_market_news_can_be_read_before_broker_account_exists(db):
    world, (agent,) = make_world(db, 1)
    ensure_v6_agent_state(agent)
    wallet = dict(agent.wallet_json or {})
    wallet.pop("broker_account", None)
    wallet["money"] = 10
    agent.wallet_json = wallet
    ticker = next(iter(MARKET_TICKERS))

    result = execute_tool(db, world=world, actor=agent, tool_name="v6_read_market_news", params={"ticker": ticker})

    assert result.ok
    event = db.get(Event, result.event_ids[0])
    assert event.event_type == "v6_stock_research"
    assert event.payload["broker_exists"] is False
    assert "还没有证券账户" in event.viewer_text
    assert "工具调用格式错误" not in event.viewer_text


def test_werewolf_setup_reveals_public_briefing_and_keeps_assignments_hidden(db):
    world, agents = make_world(db, 4)
    world.settings_json = {"werewolf_mode_enabled": True}
    world.current_world_time_minutes = 18 * 60

    event_ids = initialize_werewolf_game(db, world)

    assert event_ids
    state = werewolf_state(world)
    assert set(state["roles"].keys()) == {agent.agent_id for agent in agents}
    assert (world.settings_json or {}).get("werewolf_observer_roles")
    for observer in agents:
        known = db.execute(select(IdentityKnowledge).where(IdentityKnowledge.observer_agent_id == observer.agent_id)).scalars().all()
        assert [row for row in known if row.name_known]
        assert ((observer.desires_json or {}).get("werewolf") or {}).get("role")
    assert werewolf_state(world).get("public_revealed") is True
    assert "werewolf_record_reasoning" in werewolf_menu_tool_names(db, world, agents[0])
    assert "werewolf_vote_no_execution" not in werewolf_menu_tool_names(db, world, agents[0])


def test_werewolf_daily_phase_schedule_and_role_counts(db):
    world, _agents = make_world(db, 1)
    world.settings_json = {"werewolf_mode_enabled": True}

    world.current_world_time_minutes = 8 * 60
    assert werewolf_phase(world) == (1, "morning")
    world.current_world_time_minutes = 11 * 60 + 59
    assert werewolf_phase(world) == (1, "morning")
    world.current_world_time_minutes = 12 * 60
    assert werewolf_phase(world) == (1, "morning")
    world.current_world_time_minutes = 16 * 60
    assert werewolf_phase(world) == (1, "morning")
    world.current_world_time_minutes = 18 * 60
    assert werewolf_phase(world) == (1, "morning")
    world.current_world_time_minutes = 22 * 60
    assert werewolf_phase(world) == (1, "night")
    world.current_world_time_minutes = 24 * 60 + 8 * 60
    assert werewolf_phase(world) == (2, "morning")
    world.current_world_time_minutes = 24 * 60 + 12 * 60
    assert werewolf_phase(world) == (2, "discussion")
    world.current_world_time_minutes = 24 * 60 + 16 * 60
    assert werewolf_phase(world) == (2, "discussion")
    world.current_world_time_minutes = 24 * 60 + 18 * 60
    assert werewolf_phase(world) == (2, "voting")
    world.current_world_time_minutes = 24 * 60 + 22 * 60
    assert werewolf_phase(world) == (2, "night")

    assert _role_list_for_count(5).count("werewolf") == 1
    assert _role_list_for_count(6).count("werewolf") == 2
    assert _role_list_for_count(9).count("werewolf") == 3
    assert _role_list_for_count(13).count("werewolf") == 4


def test_werewolf_final_speech_prompt_is_in_world_not_game(db):
    world, agents = make_world(db, 2)
    wolf, human = agents
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_state": {
            "roles": {wolf.agent_id: "werewolf", human.agent_id: "villager"},
            "winner": "狼人阵营",
            "final_speeches": {},
        },
    }

    system_prompt, user_prompt = werewolf_final_speech_prompt(db, world, wolf)
    combined = system_prompt + "\n" + user_prompt

    assert "这只是游戏" not in combined
    assert "玩家" not in combined
    assert "开局" not in combined
    assert "玩得开心" not in combined
    assert "不是在玩游戏" not in combined
    assert "村庄" in combined
    assert "真实" in combined


def test_werewolf_final_speech_rejects_out_of_world_game_terms_without_rewriting():
    raw = "哈，终于不用再装下去了！我从游戏开始就是狼人。别难过，这只是个游戏，但你们确实太容易被骗了。谢谢你们让我玩得这么开心，下次记得多长点眼睛哦！"

    cleaned = _clean_final_speech_text(raw)

    assert "游戏" in cleaned
    assert "玩得" in cleaned
    assert "下次" in cleaned
    assert _contains_out_of_world_final_speech(cleaned)
    assert not _contains_out_of_world_final_speech("终于不用再装下去了。我就是藏在你们身边的狼人。你们的怀疑太晚了。")


def test_werewolf_first_day_has_no_vote_but_second_day_exiles(db):
    world, agents = make_world(db, 4)
    world.settings_json = {
        "werewolf_mode_enabled": True,
        "werewolf_state": {
            "roles": {agent.agent_id: "villager" for agent in agents},
            "votes": {
                "1": {
                    agents[0].agent_id: "__no_execution__",
                    agents[1].agent_id: "__no_execution__",
                    agents[2].agent_id: agents[0].agent_id,
                    agents[3].agent_id: agents[0].agent_id,
                },
                "2": {},
            },
            "vote_resolved": {},
        },
    }

    first_day_events = _resolve_day_vote(db, world, 1, force=True)
    assert agents[0].lifecycle_state != "dead"
    assert any((db.get(Event, event_id).event_type if db.get(Event, event_id) else "") == "werewolf_no_vote_first_day" for event_id in first_day_events)

    second_day_events = _resolve_day_vote(db, world, 2, force=True)
    assert agents[0].lifecycle_state == "dead"
    assert any((db.get(Event, event_id).event_type if db.get(Event, event_id) else "") == "werewolf_exile" for event_id in second_day_events)


def test_public_serializer_removes_backend_feedback_even_if_payload_contains_it(db):
    world, (agent,) = make_world(db, 1)
    raw = "工具调用格式错误: 当前尝试的工具是 move_to_location。请重新选择一个参数完整且符合当前地点/目标的工具。"
    event = create_event(
        db,
        world=world,
        event_type="tool_failed",
        actor_agent_id=agent.agent_id,
        viewer_text=raw,
        agent_visible_text=raw,
        payload={"tool_name": "move_to_location", "failure_reason_code": "private_room_blocked", "llm_feedback": raw, "message": raw},
    )

    public = event_to_dict(event, db)
    dumped = str(public)
    assert "工具调用格式错误" not in dumped
    assert "当前尝试的工具" not in dumped
    assert "llm_feedback" not in dumped
    assert "tool_name" not in dumped
    assert public["payload"] == {}


def test_memory_lines_keep_continuity_for_key_events_without_bloating_everything(db):
    world, (agent,) = make_world(db, 1)
    rows = [
        Memory(agent_id=agent.agent_id, memory_type="short", content="第1天吃了一顿普通饭。", importance=8, created_world_time=10),
        Memory(agent_id=agent.agent_id, memory_type="pregnancy", content="第2天得知新的生命迹象，需要后续照顾。", importance=80, created_world_time=20),
        Memory(agent_id=agent.agent_id, memory_type="werewolf", content="第3天圆桌上，桃枝声称自己是预言家。", importance=75, created_world_time=30),
        Memory(agent_id=agent.agent_id, memory_type="relationship", content="第4天答应和林见舟一起照顾孩子。", importance=65, created_world_time=40),
        Memory(agent_id=agent.agent_id, memory_type="short", content="刚刚听到有人在邻近地点求助。", importance=35, created_world_time=50),
    ]
    db.add_all(rows)
    db.commit()

    lines = _memory_prompt_lines(rows, limit=4, language="zh")
    joined = "\n".join(lines)
    assert "新的生命迹象" in joined
    assert "桃枝声称自己是预言家" in joined
    assert "一起照顾孩子" in joined
    assert "邻近地点求助" in joined
    assert "普通饭" not in joined
    assert len(lines) == 4
