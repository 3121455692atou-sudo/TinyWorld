"""Offline, reproducible integration scenarios for the real simulation pipeline.

Only the external text provider and websocket transport are replaced. The provider
reads the rendered action menu and emits AOHP text; parsing, validation, effects,
time decay, daily economy, scheduling and SQLite persistence remain real.
"""
from __future__ import annotations

from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
import importlib
import math
import random
import re
from typing import Any, Iterator
from unittest.mock import patch

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.state import DYNAMIC_FIELDS, field_upper_bound, initial_dynamic_state
from app.core import database
from app.core.models import Agent, AgentLocation, AgentTrait, Event, Inventory, Item, Location, Relationship, World
from app.effects.effect_engine import ACTION_FAILURE_EVENT_TYPES
from app.llm.openai_compatible import provider
from app.llm.provider_base import LLMResult
from app.llm.schemas import TRAIT_NAMES
from app.simulation.reaction_queue import reaction_queue
from app.simulation.scheduler import SimulationManager
from app.simulation.turn_runner import TurnRunner
from app.world.seed_world import seed_locations


@dataclass(slots=True)
class MenuLine:
    number: str
    label: str
    hints: str
    targets: tuple[str, ...] = ()

    def packet(self, *, target: str | None = None, body: str | None = None) -> str:
        value = target or (self.targets[0] if self.targets else "8" if "小时" in self.hints else "1" if "值=" in self.hints else "")
        header = f"[{self.number}{':' + value if value else ''}]"
        text = body or ("今天先照顾好自己，再去看看周围。" if "正文" in self.hints else "我现在有些累，先处理眼前的事情。")
        if "关键词" in self.hints:
            text = "面包"
        return f"{header}\n{text if any(mark in self.hints for mark in ('台词', '正文', '关键词')) else '-'}"


def read_menu(prompt: str) -> list[MenuLine]:
    """Read only menu lines the model can see, without registry/ORM access."""
    options: dict[str, MenuLine] = {}
    current: MenuLine | None = None
    for line in prompt.splitlines():
        match = re.match(r"^(\d{2,3})\s+(.+)$", line.strip())
        if match:
            label, _, hints = match[2].partition(" [")
            current = MenuLine(match[1], label, hints)
            options[current.number] = current
        elif current and line.strip().startswith("目标:"):
            current.targets = tuple(re.findall(r"(?:目标:\s*|；)(\d+)=", line.strip()))
    return list(options.values())


def menu_packet(prompt: str, label: str, **kwargs: str) -> str:
    """Useful for focused race-condition tests using the same rendered protocol."""
    candidates = read_menu(prompt)
    option = next((item for item in candidates if item.label == label), None)
    if option is None:
        option = next((item for item in candidates if label in item.label), None)
    assert option is not None, f"Action {label!r} absent from menu: {[item.label for item in candidates]}"
    return option.packet(**kwargs)


class DeterministicResidentProvider:
    """A modest survival policy, deliberately imperfect enough to exercise repairs.

    It does not know backend tool names or hidden state. Distinct seeds change
    movement, discretionary activities and speech targets. Regular malformed
    replies exercise the real AOHP retry path without network calls.
    """

    def __init__(self, seed: int, *, malformed_every: int = 17) -> None:
        self.rng = random.Random(seed)
        self.malformed_every = malformed_every
        self.calls = 0
        self.malformed_replies = 0
        self.repair_calls = 0
        self.selections: Counter[str] = Counter()
        self.actor_calls: Counter[str] = Counter()
        self.last_packets: dict[str, str] = {}
        self.previous_labels: dict[str, str] = {}
        self.menu_sizes: list[int] = []

    async def complete_text(self, *args: Any, **kwargs: Any) -> LLMResult:
        prompt = str(kwargs.get("user_prompt") or "")
        actor = str(kwargs.get("model_name") or "resident")
        options = read_menu(prompt)
        assert options, "Unexpected provider call without a resident action menu"
        self.calls += 1
        self.actor_calls[actor] += 1
        self.menu_sizes.append(len(options))
        protocol_repair = "上一条回复没有被系统识别" in prompt
        action_repair = "上一次行动被系统拒绝" in prompt
        if protocol_repair:
            self.repair_calls += 1
            packet = self.last_packets.get(actor)
            assert packet, "Protocol repair did not follow an injected invalid reply"
            return LLMResult(packet, None, {}, 1, "offline-regression")
        if action_repair:
            self.repair_calls += 1
        option = self._choose(prompt, options, actor, repairing=action_repair)
        target = self.rng.choice(option.targets) if option.targets else None
        packet = option.packet(target=target)
        self.last_packets[actor] = packet
        self.previous_labels[actor] = option.label
        self.selections[option.label] += 1
        if not action_repair and self.malformed_every and self.calls % self.malformed_every == 0:
            self.malformed_replies += 1
            return LLMResult("我还在考虑，下一条再按行动格式回答。", None, {}, 1, "offline-regression")
        return LLMResult(packet, None, {}, 1, "offline-regression")

    def _choose(self, prompt: str, options: list[MenuLine], actor: str, *, repairing: bool) -> MenuLine:
        values = {key: float(value) for key, value in re.findall(r"\b(health|energy|satiety|hydration|hygiene|social|fun|stress|money)=(-?\d+(?:\.\d+)?)", prompt)}
        clock = re.search(r"^时间:\s*第\d+天\s+(\d{2}):(\d{2})", prompt, flags=re.MULTILINE)
        night = bool(clock and (int(clock[1]) >= 22 or int(clock[1]) < 6))
        previous = self.previous_labels.get(actor)
        candidates = [item for item in options if not repairing or item.label != previous]
        candidates = candidates or options

        def first(*labels: str) -> MenuLine | None:
            for label in labels:
                match = next((item for item in candidates if item.label == label), None)
                if match:
                    return match
            return None

        priorities: list[tuple[bool, tuple[str, ...]]] = [
            (values.get("hydration", 100) < 65, ("喝瓶装水", "喝水", "去喝水", "去公共食堂", "去湖边", "去林间小屋", "接受社区援助")),
            (values.get("satiety", 100) < 62 and values.get("money", 0) < 10, ("吃随身食物", "接受社区援助", "做零工")),
            (values.get("satiety", 100) < 62, ("吃随身食物", "吃食物", "去吃饭", "去公共食堂", "接受社区援助")),
            (values.get("energy", 100) < 42 or night, ("睡觉", "回家后直接睡觉", "露宿睡觉", "短休息", "回到自己的住所", "去林间小屋")),
            (values.get("hygiene", 100) < 38, ("清洁", "医务室清洗", "整理衣物", "回到自己的住所", "去林间小屋")),
            (values.get("money", 100) < 28, ("做零工", "接受社区援助")),
        ]
        for needed, labels in priorities:
            chosen = first(*labels) if needed else None
            if chosen:
                return chosen
        # Rest and movement make simulated time advance. Social and diary actions
        # remain in the mix, so the run also exercises memories and reaction queues.
        activities = [
            item for item in candidates
            if item.label in {"短休息", "安静阅读", "写日记", "整理衣物", "湖边散步", "做零工", "静坐整理情绪", "环顾四周", "向附近说话/公开说话"}
            or item.label in {f"去{name}" for name in ("公共食堂", "图书馆", "花园", "林间小屋", "湖边", "工作坊", "医务室", "中央广场")}
        ]
        if repairing:
            alternatives = [item for item in activities if item.label != previous]
            if alternatives:
                activities = alternatives
        if activities:
            return self.rng.choice(activities)
        return first("什么也不做", "短休息") or candidates[0]


def seed_simulation_world(session: Session, *, world_id: str, seed: int, residents: int = 4, mode: str = "batch") -> tuple[World, list[Agent]]:
    rng = random.Random(seed)
    world = World(
        world_id=world_id, name="Offline regression world", status="running", seed=seed,
        current_world_time_minutes=8 * 60,
        settings_json={
            "narrator_enabled": False, "image_generation": {"enabled": False},
            "event_display_mode": "per_agent" if mode == "per_agent" else "batch",
            "agent_request_mode": "parallel" if mode == "parallel" else "serial",
            "reproduction_enabled": False, "survival_difficulty": "NORMAL",
        },
    )
    session.add(world)
    session.flush()
    seed_locations(session, world_id)
    agents = []
    for index in range(residents):
        agent_id = f"{world_id}_resident_{index}"
        actor = Agent(
            agent_id=agent_id, world_id=world_id, lifecycle_state="alive", age_stage="adult",
            model_alias="world_agent", model_name=f"offline_resident_{index}",
            chosen_name=f"居民{index + 1}", appearance_full=f"穿{index + 1}号外套的成年人。",
            appearance_short=f"{index + 1}号外套", speaking_style="简短", personality_seed="先照顾身体，也想探索社区。",
            initial_goal="有规律地生活。", wallet_json={"money": (0, 20, 80, 250)[index % 4]},
        )
        session.add(actor)
        session.flush()
        session.add(AgentTrait(agent_id=agent_id, **{name: rng.randrange(30, 76) for name in TRAIT_NAMES}))
        state = initial_dynamic_state(agent_id, world.current_world_time_minutes)
        state.satiety = rng.randrange(30, 70)
        state.hydration = rng.randrange(32, 76)
        state.energy = rng.randrange(45, 85)
        session.add(state)
        session.add(AgentLocation(agent_id=agent_id, location_id=f"{world_id}:central_square", arrived_at_world_time=world.current_world_time_minutes))
        # A finite resource is consumed through the real inventory tools.
        for kind, name in (("food", "便携食物"), ("water", "瓶装水")):
            item_id = f"{agent_id}_{kind}"
            session.add(Item(item_id=item_id, world_id=world_id, name=name, description="回归测试初始补给", item_type=kind))
            session.add(Inventory(agent_id=agent_id, item_id=item_id, quantity=1))
        agents.append(actor)
    session.commit()
    return world, agents


@dataclass
class SimulationReport:
    seed: int
    mode: str
    residents: int
    provider: str = "deterministic_mock_no_network"
    rounds: int = 0
    simulated_minutes: int = 0
    calendar_days_crossed: int = 0
    action_attempts: int = 0
    provider_calls: int = 0
    protocol_faults: int = 0
    repair_calls: int = 0
    max_menu_options: int = 0
    persisted_clock_regressions: int = 0
    max_clock_regression_minutes: int = 0
    max_consecutive_no_time_advance_rounds: int = 0
    event_types: dict[str, int] = field(default_factory=dict)
    failed_actions_by_tool: dict[str, int] = field(default_factory=dict)
    failure_reason_codes: dict[str, int] = field(default_factory=dict)
    selected_actions: dict[str, int] = field(default_factory=dict)
    statuses: dict[str, int] = field(default_factory=dict)
    terminal_status: str = "round_limit"
    final_agents: list[dict[str, Any]] = field(default_factory=list)


class SimulationFailure(AssertionError):
    """A reproducible failure with a small, synthetic state snapshot."""

    def __init__(self, message: str, diagnostics: dict[str, Any]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


def _failure_diagnostics(world_id: str) -> dict[str, Any]:
    """Capture only fixture state and event identifiers, never provider config."""
    snapshot: dict[str, Any] = {}
    try:
        with database.SessionLocal() as session:
            world = session.get(World, world_id)
            snapshot["persisted_world_time"] = world.current_world_time_minutes if world else None
            snapshot["residents"] = []
            for actor in session.scalars(select(Agent).where(Agent.world_id == world_id).order_by(Agent.agent_id)):
                learning = actor.tool_learning_json or {}
                desires = actor.desires_json or {}
                audit = learning.get("tool_audit_history") or []
                snapshot["residents"].append({
                    "agent_id": actor.agent_id,
                    "lifecycle": actor.lifecycle_state,
                    "location_id": actor.location.location_id if actor.location else None,
                    "state": {name: value if not isinstance(value, float) or math.isfinite(value) else str(value) for name in DYNAMIC_FIELDS if (value := getattr(actor.dynamic_state, name, None)) is not None},
                    "sleep_until": desires.get("sleep_until_world_time"),
                    "unconscious_until": desires.get("unconscious_until_world_time"),
                    "last_action_tool": learning.get("last_action_tool_name"),
                    "last_provider_phase": learning.get("last_llm_phase"),
                    "last_provider_world_time": learning.get("last_llm_world_time"),
                    "last_provider_request_failed": bool(learning.get("last_llm_error")),
                    "menu_tool_names": [item.get("tool_name") for item in audit[-1].get("menu", [])] if audit else [],
                })
            snapshot["recent_events"] = [{
                "event_id": event.event_id,
                "world_time": event.world_time,
                "event_type": event.event_type,
                "actor_agent_id": event.actor_agent_id,
                "tool_name": (event.payload or {}).get("tool_name"),
                "failure_reason_code": (event.payload or {}).get("failure_reason_code"),
            } for event in session.scalars(select(Event).where(Event.world_id == world_id).order_by(Event.event_id.desc()).limit(20))]
    except Exception as error:
        # A damaged database must not hide the original simulation failure.
        snapshot["diagnostic_error_type"] = type(error).__name__
    return snapshot


def assert_world_invariants(session: Session, world_id: str, *, min_time: int, event_ids: list[int] = ()) -> list[dict[str, Any]]:
    world = session.get(World, world_id)
    assert world is not None
    now = world.current_world_time_minutes
    assert isinstance(now, int) and now >= min_time, f"World clock went backwards: {min_time} -> {now}"
    actors = list(session.scalars(select(Agent).where(Agent.world_id == world_id)))
    actor_ids = {actor.agent_id for actor in actors}
    snapshots = []
    for actor in actors:
        state = actor.dynamic_state
        assert state is not None and actor.traits is not None
        for name in DYNAMIC_FIELDS:
            value = getattr(state, name)
            lower = -100 if name == "mood" else 0
            assert math.isfinite(value) and lower <= value <= field_upper_bound(name), (actor.agent_id, name, value)
        for name in TRAIT_NAMES:
            value = getattr(actor.traits, name)
            assert math.isfinite(value) and 0 <= value <= 100, (actor.agent_id, name, value)
        assert 0 <= state.last_decay_world_time <= now, (actor.agent_id, state.last_decay_world_time, now)
        for name in ("zero_satiety_since", "zero_hydration_since", "zero_energy_since"):
            value = getattr(state, name)
            assert value is None or 0 <= value <= now, (actor.agent_id, name, value, now)
        money = (actor.wallet_json or {}).get("money", 0)
        assert isinstance(money, (int, float)) and math.isfinite(money) and money >= 0, (actor.agent_id, money)
        assert actor.location and actor.location.location.world_id == world_id, actor.agent_id
        history = (actor.tool_learning_json or {}).get("tool_audit_history", [])
        assert len(history) <= 5
        for audit in history:
            names = [item["tool_name"] for item in audit["menu"]]
            assert len(names) == len(set(names)) and len(names) <= 140
        snapshots.append({"agent_id": actor.agent_id, "lifecycle": actor.lifecycle_state, "money": money, **{name: round(getattr(state, name), 4) for name in DYNAMIC_FIELDS}})
    for row, item in session.execute(select(Inventory, Item).join(Item, Inventory.item_id == Item.item_id).where(Inventory.agent_id.in_(actor_ids))):
        assert row.quantity >= 0 and item.world_id == world_id
    for relation in session.scalars(select(Relationship).where(Relationship.observer_agent_id.in_(actor_ids))):
        target = session.get(Agent, relation.target_agent_id)
        assert target and target.world_id == world_id
        for name in ("familiarity", "trust", "affection", "fear", "conflict"):
            value = getattr(relation, name)
            lower = -100 if name == "affection" else 0
            assert math.isfinite(value) and lower <= value <= 100, (name, value)
    for event_id in event_ids:
        event = session.get(Event, event_id)
        assert event and event.world_id == world_id
        assert event.actor_agent_id is None or event.actor_agent_id in actor_ids
        assert event.target_agent_id is None or event.target_agent_id in actor_ids
        assert event.world_time <= now, (event.event_id, event.world_time, now)
        _assert_finite_json(event.state_delta, path=f"event[{event_id}].state_delta")
    return snapshots


def _assert_finite_json(value: Any, *, path: str) -> None:
    if isinstance(value, float):
        assert math.isfinite(value), (path, value)
    elif isinstance(value, dict):
        for key, child in value.items():
            _assert_finite_json(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_finite_json(child, path=f"{path}[{index}]")


@contextmanager
def offline_simulation(provider_stub: Any, *, broadcaster: Any = None) -> Iterator[SimulationManager]:
    """Use the real scheduler with fresh runner queues and a hard network guard."""
    scheduler_module = importlib.import_module("app.simulation.scheduler")
    runner = TurnRunner()

    async def discard_broadcast(*args: Any, **kwargs: Any) -> None:
        return None

    def network_forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Offline simulation attempted network access")

    with ExitStack() as stack:
        stack.enter_context(patch.object(provider, "complete_text", provider_stub.complete_text))
        stack.enter_context(patch.object(scheduler_module, "turn_runner", runner))
        stack.enter_context(patch("app.api.websocket.manager.broadcast", broadcaster or discard_broadcast))
        stack.enter_context(patch.object(httpx.Client, "send", network_forbidden))
        stack.enter_context(patch.object(httpx.AsyncClient, "send", network_forbidden))
        yield SimulationManager()


async def run_simulation(*, seed: int, rounds: int = 120, residents: int = 4, mode: str = "batch", malformed_every: int = 17) -> SimulationReport:
    """Run in the currently configured isolated DB, reopening it after every step."""
    world_id = f"world_sim_{seed}_{mode}"
    reaction_queue.clear(world_id)
    with database.SessionLocal() as session:
        world, _agents = seed_simulation_world(session, world_id=world_id, seed=seed, residents=residents, mode=mode)
        start_time = world.current_world_time_minutes
    fake = DeterministicResidentProvider(seed, malformed_every=malformed_every)
    report = SimulationReport(seed, mode, residents)
    statuses: Counter[str] = Counter()
    final_clock = start_time
    persisted_clock = start_time
    stagnant_rounds = 0

    async def observe_broadcast(_world_id: str, message: dict[str, Any]) -> None:
        nonlocal persisted_clock
        # A separate session observes only committed DB state, just like an API
        # snapshot request during a long batch of resident actions.
        with database.SessionLocal() as observer:
            world = observer.get(World, world_id)
            assert world is not None
            clock = world.current_world_time_minutes
            if clock < persisted_clock:
                report.persisted_clock_regressions += 1
                report.max_clock_regression_minutes = max(report.max_clock_regression_minutes, persisted_clock - clock)
            persisted_clock = clock
        if message.get("type") == "world_state_updated":
            assert "world" in message and "left_snapshot" in message

    try:
        with offline_simulation(fake, broadcaster=observe_broadcast) as manager:
            for iteration in range(rounds):
                result: dict[str, Any] | None = None
                try:
                    result = await manager.step(world_id)
                    statuses[result["status"]] += 1
                    report.action_attempts += len(result["acted_agent_ids"])
                    with database.SessionLocal() as observer:
                        report.final_agents = assert_world_invariants(observer, world_id, min_time=final_clock, event_ids=result["event_ids"])
                        world = observer.get(World, world_id)
                        assert world is not None
                        stagnant_rounds = stagnant_rounds + 1 if world.current_world_time_minutes == final_clock else 0
                        report.max_consecutive_no_time_advance_rounds = max(report.max_consecutive_no_time_advance_rounds, stagnant_rounds)
                        final_clock = world.current_world_time_minutes
                    assert report.persisted_clock_regressions == 0, (report.persisted_clock_regressions, report.max_clock_regression_minutes)
                    report.rounds += 1
                    if result["status"] in {"world_not_running", "no_alive_agents"}:
                        report.terminal_status = result["status"]
                        break
                    assert stagnant_rounds < 10, f"No simulated time advanced for {stagnant_rounds} consecutive rounds"
                except Exception as error:
                    diagnostics = {
                        "seed": seed, "mode": mode, "round": iteration + 1,
                        "world_time": final_clock, "error_type": type(error).__name__,
                        "invariant_error": str(error)[:800],
                        "provider_calls": fake.calls,
                        "last_selected_labels": dict(fake.previous_labels),
                        "statuses": dict(statuses),
                        "last_result": {key: result.get(key) for key in ("status", "acted_agent_ids", "event_ids")} if result else None,
                        "persisted_clock_regressions": report.persisted_clock_regressions,
                        "consecutive_no_time_advance_rounds": stagnant_rounds,
                        **_failure_diagnostics(world_id),
                    }
                    raise SimulationFailure(f"Simulation failed: seed={seed}, mode={mode}, round={iteration + 1}, time={final_clock}", diagnostics) from error
        with database.SessionLocal() as observer:
            report.event_types = dict(Counter(observer.scalars(select(Event.event_type).where(Event.world_id == world_id))))
            failures = list(observer.scalars(select(Event).where(Event.world_id == world_id, Event.event_type.in_(ACTION_FAILURE_EVENT_TYPES))))
            report.failed_actions_by_tool = dict(Counter((event.payload or {}).get("tool_name") or "unknown" for event in failures))
            # Some in-world failures predate explicit reason codes. Keep their
            # event type as a named fallback, never guess a reason from prose.
            report.failure_reason_codes = dict(Counter((event.payload or {}).get("failure_reason_code") or f"event:{event.event_type}" for event in failures))
        report.simulated_minutes = final_clock - start_time
        report.calendar_days_crossed = final_clock // 1440 - start_time // 1440
        report.provider_calls = fake.calls
        report.protocol_faults = fake.malformed_replies
        report.repair_calls = fake.repair_calls
        report.max_menu_options = max(fake.menu_sizes, default=0)
        report.selected_actions = dict(fake.selections)
        report.statuses = dict(statuses)
        return report
    finally:
        reaction_queue.clear(world_id)
