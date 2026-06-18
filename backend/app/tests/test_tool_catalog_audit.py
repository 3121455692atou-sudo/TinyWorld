from __future__ import annotations

from collections import Counter

from app.agents.state import initial_dynamic_state
from app.content.presets import WEREWOLF_WORLDVIEW
from app.core.models import Agent, AgentLocation, AgentTrait, Event, IdentityKnowledge, Inventory, Item, Location, World
from app.llm.action_options import build_action_options
from app.effects.effect_engine import execute_tool
from app.tools.registry import AGENT_FACING_DISABLED_TOOL_NAMES, TOOL_SPECS, available_tools
from app.tools.tool_specs import REDUNDANT_LLM_EXPRESSION_CATALOG_IDS, REMOVED_AGENT_FACING_CATALOG_IDS, SOFT_EXPRESSION_CORE_TOOL_IDS
from app.tools.validators import tool_requires_speech, validate_tool
from app.world.seed_world import private_home_location, seed_world_content, world_location_id
from app.world.visibility import build_visible_people


_AGENT_FACING_PREFIX_DENY = ("system_", "tool_meta_", "system_filter_", "v6_system_", "tool_romance_", "tool_adult_")
_DUPLICATE_CORE_TOOL_IDS = set(REMOVED_AGENT_FACING_CATALOG_IDS)
_SUPPORTED_TARGET_POLICIES = {"none", "visible_ref", "known_name", "item", "location"}


def _add_agent(session, world: World, idx: int, location_id: str, home_location_id: str) -> Agent:
    agent = Agent(
        agent_id=f"agent_{idx}",
        world_id=world.world_id,
        lifecycle_state="alive",
        model_alias="world_agent",
        chosen_name=["甲", "乙", "丙", "丁"][idx],
        gender_identity="不愿公开",
        gender_publicity=True,
        gender_expression="中性",
        appearance_full="测试居民，衣着朴素，正在观察周围。",
        appearance_short=f"测试居民{idx}",
        avatar_hint_json={},
        speaking_style="简短",
        personality_seed="谨慎但愿意交流。",
        initial_goal="参与测试。",
        intro_policy="open",
        wallet_json={"money": 80, "housing": {"home_location_id": home_location_id}},
        tool_learning_json={"tool_context_mode": "dynamic"},
    )
    session.add(agent)
    session.flush()
    session.add(AgentTrait(agent_id=agent.agent_id))
    session.add(initial_dynamic_state(agent.agent_id, 0))
    session.add(AgentLocation(agent_id=agent.agent_id, location_id=location_id, arrived_at_world_time=0))
    return agent


def _make_werewolf_private_room_world(session):
    world = World(
        world_id="world_tool_audit",
        name="工具审计狼人杀村",
        status="paused",
        seed=7788,
        current_world_time_minutes=20 * 60,
        settings_json={"worldview_id": "werewolf_game_worldview", "core_toolset_enabled": True},
    )
    session.add(world)
    session.flush()
    seed_world_content(session, world.world_id, worldview=WEREWOLF_WORLDVIEW)
    for idx in range(2):
        session.merge(private_home_location(world.world_id, idx, WEREWOLF_WORLDVIEW))
    session.flush()
    dormitory = world_location_id(world.world_id, "dormitory")
    a0 = _add_agent(session, world, 0, dormitory, world_location_id(world.world_id, "villager_room_1"))
    a1 = _add_agent(session, world, 1, dormitory, world_location_id(world.world_id, "villager_room_2"))
    session.add(IdentityKnowledge(observer_agent_id=a0.agent_id, target_agent_id=a1.agent_id, known_name=a1.chosen_name, name_known=True, first_seen_at=0, last_seen_at=0))
    session.flush()
    return world, a0, a1


def test_registered_tool_catalog_is_agent_facing_and_bindable():
    """Programmatic one-by-one audit of registered tools.

    The runtime still has hundreds of tools, but every registered entry should be a real
    agent-facing option with a supported parameter policy. Internal candidate/debug notes and
    abstract duplicates of hard-coded movement/sleep/eat/work tools are deliberately pruned
    before registration.
    """
    failures: list[str] = []
    for name, spec in sorted(TOOL_SPECS.items()):
        if name.startswith(_AGENT_FACING_PREFIX_DENY):
            failures.append(f"{name}: internal prefix leaked into TOOL_SPECS")
        if name in _DUPLICATE_CORE_TOOL_IDS:
            failures.append(f"{name}: duplicate abstract catalog tool should be pruned")
        if "工具候选" in str(spec.catalog_category or "") or "场景过滤" in str(spec.catalog_category or ""):
            failures.append(f"{name}: candidate-filter design note should be pruned")
        if spec.target_policy not in _SUPPORTED_TARGET_POLICIES:
            failures.append(f"{name}: unsupported target_policy={spec.target_policy}")
        if not spec.display_name or not spec.description_for_llm:
            failures.append(f"{name}: empty display/description")
        if spec.time_cost_minutes < 0:
            failures.append(f"{name}: negative time cost")
    assert not failures, "\n".join(failures[:80])


def test_communicative_catalog_tools_require_visible_speech(db):
    world, actor, _other = _make_werewolf_private_room_world(db)
    visible = build_visible_people(db, actor, world.current_world_time_minutes, persist=False)
    target_ref = visible[0].visible_ref

    assert tool_requires_speech("tool_social_greet_visible", TOOL_SPECS["tool_social_greet_visible"])
    assert tool_requires_speech("tool_group_propose_activity", TOOL_SPECS["tool_group_propose_activity"])
    assert tool_requires_speech("v6_respond_to_fans", TOOL_SPECS["v6_respond_to_fans"])

    target_params = {"visible_ref": target_ref}
    missing = validate_tool(db, actor=actor, tool_name="tool_social_greet_visible", params=target_params, world_time=world.current_world_time_minutes, persist_visibility=False)
    assert not missing.ok
    assert missing.reason_code == "missing_speech"

    missing_group_speech = validate_tool(
        db,
        actor=actor,
        tool_name="tool_group_propose_activity",
        params={},
        world_time=world.current_world_time_minutes,
        persist_visibility=False,
    )
    assert not missing_group_speech.ok
    assert missing_group_speech.reason_code == "missing_speech"


def test_private_rooms_are_not_plain_move_targets_from_dormitory(db):
    world, actor, other = _make_werewolf_private_room_world(db)
    location = db.get(Location, world_location_id(world.world_id, "dormitory"))
    assert location is not None
    tools = available_tools(actor, location, session=db)
    visible = build_visible_people(db, actor, world.current_world_time_minutes, persist=False)
    ref_map = {person.visible_ref: person.target_agent_id for person in visible}
    options = build_action_options(db, world, actor, tools, ref_map, limit=260)
    move_targets = {option.params.get("location_id") for option in options if option.tool_name in {"move_to_location", "wander"}}
    assert world_location_id(world.world_id, "villager_room_2") not in move_targets
    assert world_location_id(world.world_id, "villager_room_1") in move_targets or any(option.tool_name == "return_home" for option in options)


def test_explicit_private_room_tools_still_have_private_targets_when_allowed(db):
    world, actor, other = _make_werewolf_private_room_world(db)
    # Simulate survival pressure so burglary tools pass the registry gate; the test is not
    # endorsing the action, only ensuring explicit private-room tools are the only menu path
    # to someone else's room.
    actor.dynamic_state.satiety = 5
    actor.dynamic_state.hydration = 10
    actor.dynamic_state.stress = 85
    actor.traits.aggression = 80
    db.flush()
    location = db.get(Location, world_location_id(world.world_id, "dormitory"))
    tools = available_tools(actor, location, session=db)
    visible = build_visible_people(db, actor, world.current_world_time_minutes, persist=False)
    ref_map = {person.visible_ref: person.target_agent_id for person in visible}
    options = build_action_options(db, world, actor, tools, ref_map, limit=260)
    other_room = world_location_id(world.world_id, "villager_room_2")
    plain = [option for option in options if option.params.get("location_id") == other_room and option.tool_name in {"move_to_location", "wander"}]
    explicit = [option for option in options if option.params.get("location_id") == other_room and option.tool_name in {"knock_private_room", "attempt_burglary_private_room", "home_invasion_robbery_private_room"}]
    assert not plain
    assert explicit
    for option in explicit:
        result = validate_tool(db, actor=actor, tool_name=option.tool_name, params=option.params, world_time=world.current_world_time_minutes, persist_visibility=False)
        assert result.ok, f"{option.tool_name}: {result.reason_code} {result.message}"



def test_disabled_meta_tools_are_never_agent_facing_and_rejected(db):
    world, actor, _other = _make_werewolf_private_room_world(db)
    location = db.get(Location, world_location_id(world.world_id, "dormitory"))
    tools = available_tools(actor, location, session=db)
    names = {spec.tool_name for spec in tools}
    leaked = sorted(names & AGENT_FACING_DISABLED_TOOL_NAMES)
    assert not leaked, f"disabled/internal tools leaked into menu: {leaked[:20]}"

    result = validate_tool(
        db,
        actor=actor,
        tool_name="request_more_candidate_tools",
        params={},
        world_time=world.current_world_time_minutes,
        persist_visibility=False,
    )
    assert not result.ok
    assert result.reason_code == "tool_disabled"


def test_expression_only_tools_are_pruned_or_redirected_to_speech(db):
    """Pure feelings/preferences should be spoken, not tool-called.

    This preserves capability boundaries while reducing menu noise: stateful tools
    such as requests, care, work, crime, voting and relationship confirmation stay;
    redundant phrasing tools disappear or redirect to canonical speech/note tools.
    """
    absent = sorted(name for name in REDUNDANT_LLM_EXPRESSION_CATALOG_IDS if name in TOOL_SPECS)
    assert not absent, f"expression-only catalog tools should be pruned: {absent[:40]}"
    assert "tool_emotion_cry" not in TOOL_SPECS
    assert "tool_social_answer_feeling" not in TOOL_SPECS
    assert "tool_romance_hint_affection" not in TOOL_SPECS
    assert "tool_romance_ask_openness" not in TOOL_SPECS
    assert "tool_adult_request_sexual_intimacy" not in TOOL_SPECS
    assert "tool_social_set_boundary" not in TOOL_SPECS
    assert "tool_parent_work_for_child" not in TOOL_SPECS
    assert "tool_market_buy_baby_supplies" not in TOOL_SPECS
    assert "v6_choose_security_over_romance" not in TOOL_SPECS
    assert "v6_feel_envy_of_rich_agent" not in TOOL_SPECS

    # Canonical capabilities remain available.
    for name in ["say_to_visible_agent", "speak_to_nearby", "write_private_note", "add_memory", "ask_date_visible_agent", "define_relationship_visible_agent"]:
        assert name in TOOL_SPECS

    for name in SOFT_EXPRESSION_CORE_TOOL_IDS:
        assert name in AGENT_FACING_DISABLED_TOOL_NAMES


def test_direct_private_room_failure_is_system_only_not_public_spam(db):
    world, actor, other = _make_werewolf_private_room_world(db)
    other_room_id = world_location_id(world.world_id, "villager_room_2")
    result = execute_tool(db, world=world, actor=actor, tool_name="move_to_location", params={"location_id": other_room_id})
    assert not result.ok
    assert result.event_ids
    event = db.get(Event, result.event_ids[0])
    assert event is not None
    assert event.event_type == "tool_failed"
    assert event.visibility_scope == "system"
    assert event.importance <= 1
    assert "私人空间" not in (event.viewer_text or "")
    assert "工具调用格式错误" not in (event.viewer_text or "")
    assert (event.payload or {}).get("failure_reason_code") == "private_room_blocked"
    assert (event.payload or {}).get("destination_location_id") == other_room_id

def test_available_tools_catalog_has_diverse_real_domains(db):
    world, actor, _other = _make_werewolf_private_room_world(db)
    # Move to normal day plaza so dynamic catalog routing is not restricted by structured
    # werewolf night/vote phases.
    world.current_world_time_minutes = 9 * 60
    actor.location.location_id = world_location_id(world.world_id, "village_square")
    actor.dynamic_state.satiety = 35
    actor.dynamic_state.hydration = 35
    actor.dynamic_state.social = 20
    db.flush()
    location = actor.location.location
    specs = available_tools(actor, location, session=db)
    counts = Counter(spec.hard_effect_id for spec in specs)
    names = {spec.tool_name for spec in specs}
    assert counts["v5_catalog_generic"] >= 10
    assert {"look_around", "check_self_status", "speak_to_nearby"} <= names
    assert not any(name.startswith("system_") or name.startswith("tool_meta_") for name in names)
    assert not any(name in _DUPLICATE_CORE_TOOL_IDS for name in names)


def _make_universal_tool_world(session):
    world = World(
        world_id="world_tool_validate",
        name="工具逐项验证世界",
        status="paused",
        seed=9901,
        current_world_time_minutes=10 * 60,
        settings_json={"core_toolset_enabled": True, "reproduction_enabled": True},
    )
    session.add(world)
    all_tags = sorted(
        {
            "home",
            "quiet",
            "water",
            "food_service",
            "food",
            "trade",
            "market",
            "work",
            "craft",
            "medical",
            "social",
            "open_view",
            "learning",
            "library",
            "nature",
            "natural_food",
            "hot_spring",
            "hot_spring_lobby",
            "notice",
            "public_record",
            "corpse",
            "werewolf_day",
            "werewolf_night",
        }
        | {tag for spec in TOOL_SPECS.values() for tag in (spec.required_location_tags or [])}
    )
    hub = Location(
        location_id=f"{world.world_id}:hub",
        world_id=world.world_id,
        public_name="万能测试大厅",
        description="用于逐项测试工具参数绑定的公共大厅。",
        neighbors_json=[f"{world.world_id}:public", f"{world.world_id}:home_actor", f"{world.world_id}:home_other"],
        available_tools_json=list(TOOL_SPECS.keys()),
        tags_json=all_tags,
        visibility_radius=1,
    )
    public = Location(
        location_id=f"{world.world_id}:public",
        world_id=world.world_id,
        public_name="公共测试点",
        description="公共相邻地点。",
        neighbors_json=[hub.location_id],
        available_tools_json=[],
        tags_json=["social", "open_view", "water"],
        visibility_radius=1,
    )
    home_actor = Location(
        location_id=f"{world.world_id}:home_actor",
        world_id=world.world_id,
        public_name="甲的测试房间",
        description="测试用个人房间。",
        neighbors_json=[hub.location_id],
        available_tools_json=[],
        tags_json=["home", "quiet", "water", "private"],
    )
    home_other = Location(
        location_id=f"{world.world_id}:home_other",
        world_id=world.world_id,
        public_name="乙的测试房间",
        description="测试用他人房间。",
        neighbors_json=[hub.location_id],
        available_tools_json=[],
        tags_json=["home", "quiet", "water", "private"],
    )
    session.add_all([hub, public, home_actor, home_other])
    session.flush()
    actor = _add_agent(session, world, 0, hub.location_id, home_actor.location_id)
    target = _add_agent(session, world, 1, hub.location_id, home_other.location_id)
    actor.wallet_json = {
        "money": 500,
        "bank_balance": 500,
        "housing": {"home_location_id": home_actor.location_id, "next_rent_due_day": 9, "rent_per_10_days": 30},
        "broker_account": {"cash": 200, "equity": 200, "positions": {}, "margin_enabled": True, "short_enabled": True},
        "liabilities": [{"loan_id": "test", "principal_remaining": 50, "minimum_payment_daily": 2, "default_state": "current"}],
        "assets": [{"asset_type": "luxury_item", "market_value": 80}, {"asset_type": "bicycle", "market_value": 60}],
        "vehicles": [{"type": "bicycle", "condition": 80}, {"type": "car", "fuel": 20, "condition": 80}],
        "creator_profile": {"drafts": ["video"], "audience_size": 50},
        "hedonic_state": {"luxury_threshold": 30},
        "economy_profile": {"risk_tolerance": 80, "financial_literacy": 80, "debt_stress": 50},
    }
    actor.family_json = {
        "pending_intimacy_requests": [{"from_agent_id": target.agent_id, "status": "pending"}],
        "pregnancy_state": {"pregnant": True},
    }
    actor.law_json = {
        "victim_records": [{"kind": "loss_only", "actor_agent_id": target.agent_id}],
        "criminal_records": [{"type": "test"}],
        "recent_case": True,
    }
    actor.dynamic_state.health = 85
    actor.dynamic_state.energy = 90
    actor.dynamic_state.satiety = 90
    actor.dynamic_state.hydration = 90
    actor.dynamic_state.hygiene = 90
    actor.dynamic_state.social = 30
    actor.dynamic_state.fun = 30
    actor.dynamic_state.stress = 40
    actor.traits.aggression = 80
    actor.traits.curiosity = 80
    actor.traits.sociability = 80
    actor.traits.empathy = 80
    session.add(IdentityKnowledge(observer_agent_id=actor.agent_id, target_agent_id=target.agent_id, known_name=target.chosen_name, name_known=True, visual_known=True, first_seen_at=0, last_seen_at=0))
    item = Item(item_id="item_tool_audit", world_id=world.world_id, name="测试物品", description="测试用物品", item_type="misc", location_id=hub.location_id)
    session.add(item)
    session.flush()
    session.add(Inventory(agent_id=actor.agent_id, item_id=item.item_id, quantity=2))
    session.flush()
    return world, actor, target, hub, public, home_other


def _representative_params_for_tool(name: str, spec, target: Agent, public: Location, private_other: Location) -> dict:
    params: dict = {}
    if spec.target_policy == "visible_ref":
        params["visible_ref"] = "附近人物A"
    elif spec.target_policy == "known_name":
        params["known_name"] = target.chosen_name
    elif spec.target_policy == "item":
        params["item_name"] = "测试物品"
    elif spec.target_policy == "location":
        params["location_id"] = private_other.location_id if name in {"knock_private_room", "attempt_burglary_private_room", "home_invasion_robbery_private_room"} else public.location_id
    if name in {"sleep", "sleep_rough", "return_home"}:
        params.setdefault("sleep_hours", 1)
    if name == "return_home":
        params.setdefault("sleep_after_arrival", False)
    if name.startswith("v6_"):
        params.setdefault("amount", 10)
        params.setdefault("ticker", "MGL")
        params.setdefault("stock_symbol", "MGL")
        params.setdefault("symbol", "MGL")
    if "speech" not in params:
        params["speech"] = "我先把这件事说明白。"
    if "content" not in params:
        params["content"] = "测试中整理一条清楚的内容。"
    if "note" not in params:
        params["note"] = "测试笔记。"
    return params


_EXPECTED_CONTEXTUAL_FAILURES = {
    "werewolf_disabled",
    "werewolf_phase_blocked",
    "werewolf_role_blocked",
    "werewolf_not_current_speaker",
    "werewolf_not_rebuttal_turn",
    "werewolf_no_debate",
    "werewolf_rebuttal_pending",
    "werewolf_legacy_discussion_tool",
    "werewolf_no_execution_removed",
    "werewolf_single_wolf_no_discussion",
    "werewolf_wolf_discussion_done",
    "work_schedule_blocked",
    "daily_sleep_limit",
    "pregnancy_restricted",
    "age_blocked",
    "toolset_disabled",
    "agent_toolset_disabled",
    "missing_infidelity_response",
    "bad_lifecycle",
    "not_enough_money",
    "no_broker_account",
    "broker_missing",
    "stock_position_missing",
    "not_enough_broker_cash",
    "no_location",
    "corpse_not_found",
    "missing_corpse_ref",
    "no_visible_corpse",
    "missing_social_request",
    "missing_forced_action",
    "corpse_not_visible",
    "social_request_missing",
    "forced_action_missing",
    "no_pending_request",
    "no_pending_intimacy_request",
    "target_sleeping",
    "target_not_sleeping",
    "target_not_child",
    "child_target_blocked",
    "missing_known_name",
    "target_self_blocked",
    "target_dead",
    "werewolf_target_is_wolf",
    "tool_disabled",
    "tool_disabled_soft_expression",
    "relationship_stage_blocked",
    "generic_catalog_noop_disabled",
    "v6_state_blocked",
}



def test_representative_menu_options_validate_after_resolving_targets_and_text(db):
    world, actor, target, hub, public, private_other = _make_universal_tool_world(db)
    scenarios = [
        ("normal", {}),
        ("hungry", {"satiety": 20, "hydration": 25}),
        ("medical", {"health": 35, "energy": 25}),
    ]
    for _scenario_name, state_patch in scenarios:
        for key, value in state_patch.items():
            setattr(actor.dynamic_state, key, value)
        db.flush()
        tools = available_tools(actor, hub, session=db)
        visible = build_visible_people(db, actor, world.current_world_time_minutes, persist=False)
        ref_map = {person.visible_ref: person.target_agent_id for person in visible}
        options = build_action_options(db, world, actor, tools, ref_map, limit=300)
        failures: list[str] = []
        for option in options:
            params = dict(option.params)
            if option.target_choices:
                params.update(dict(option.target_choices[0].get("params") or {}))
            if option.value_slot and option.default_value is not None:
                params[option.value_slot] = option.default_value
            if option.text_slot:
                params[option.text_slot] = "我会把这件事说明白。"
            result = validate_tool(db, actor=actor, tool_name=option.tool_name, params=params, world_time=world.current_world_time_minutes, persist_visibility=False)
            if not result.ok:
                failures.append(f"{option.tool_name}: {result.reason_code} {result.message}")
        assert not failures, "Menu option validation failures after resolving target/text slots:\n" + "\n".join(failures[:80])


def test_each_registered_tool_accepts_representative_binding_or_expected_context_gate(db):
    world, actor, target, _hub, public, private_other = _make_universal_tool_world(db)
    failures: list[str] = []
    checked = 0
    for name, spec in sorted(TOOL_SPECS.items()):
        checked += 1
        params = _representative_params_for_tool(name, spec, target, public, private_other)
        result = validate_tool(db, actor=actor, tool_name=name, params=params, world_time=world.current_world_time_minutes, persist_visibility=False)
        if result.ok:
            continue
        if result.reason_code in _EXPECTED_CONTEXTUAL_FAILURES:
            continue
        failures.append(f"{name}: {result.reason_code} {result.message}")
    # The catalog is intentionally smaller after pruning expression-only tools.  A
    # high lower bound still catches accidental over-pruning, while allowing the menu
    # to stop pretending every possible sentence is a distinct hard action.
    assert 650 <= checked <= 790
    assert not failures, "Unexpected binding failures after per-tool audit:\n" + "\n".join(failures[:120])
