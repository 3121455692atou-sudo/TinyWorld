from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class World(Base):
    __tablename__ = "worlds"

    world_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="setup")
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    current_world_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    agents: Mapped[list["Agent"]] = relationship(back_populates="world", cascade="all, delete-orphan")


class Agent(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.world_id"), index=True)
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False, default="shell")
    model_alias: Mapped[str] = mapped_column(String(40), nullable=False, default="world_agent")
    model_provider_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_provider_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    llm_base_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    llm_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_configured_name: Mapped[bool] = mapped_column(Boolean, default=False)
    chosen_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    gender_identity: Mapped[str | None] = mapped_column(String(24), nullable=True)
    gender_custom_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    gender_publicity: Mapped[bool] = mapped_column(Boolean, default=True)
    gender_expression: Mapped[str | None] = mapped_column(String(80), nullable=True)
    age_stage: Mapped[str] = mapped_column(String(24), default="adult")
    appearance_full: Mapped[str | None] = mapped_column(Text, nullable=True)
    appearance_short: Mapped[str | None] = mapped_column(String(120), nullable=True)
    avatar_hint_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    speaking_style: Mapped[str | None] = mapped_column(String(160), nullable=True)
    personality_seed: Mapped[str | None] = mapped_column(Text, nullable=True)
    initial_goal: Mapped[str | None] = mapped_column(String(200), nullable=True)
    intro_policy: Mapped[str] = mapped_column(String(24), default="selective")
    wallet_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    work_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    family_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    law_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    trauma_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    desires_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    morality_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tool_learning_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at_world_time: Mapped[int] = mapped_column(Integer, default=0)
    death_at_world_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    death_cause: Mapped[str | None] = mapped_column(String(240), nullable=True)

    world: Mapped[World] = relationship(back_populates="agents")
    traits: Mapped["AgentTrait"] = relationship(back_populates="agent", cascade="all, delete-orphan")
    dynamic_state: Mapped["AgentDynamicState"] = relationship(back_populates="agent", cascade="all, delete-orphan")
    location: Mapped["AgentLocation"] = relationship(back_populates="agent", cascade="all, delete-orphan")


class AgentTrait(Base):
    __tablename__ = "agent_traits"

    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), primary_key=True)
    openness: Mapped[int] = mapped_column(Integer, default=50)
    caution: Mapped[int] = mapped_column(Integer, default=50)
    sociability: Mapped[int] = mapped_column(Integer, default=50)
    empathy: Mapped[int] = mapped_column(Integer, default=50)
    curiosity: Mapped[int] = mapped_column(Integer, default=50)
    discipline: Mapped[int] = mapped_column(Integer, default=50)
    aggression: Mapped[int] = mapped_column(Integer, default=20)
    honesty: Mapped[int] = mapped_column(Integer, default=50)
    creativity: Mapped[int] = mapped_column(Integer, default=50)
    neuroticism: Mapped[int] = mapped_column(Integer, default=50)

    agent: Mapped[Agent] = relationship(back_populates="traits")


class AgentDynamicState(Base):
    __tablename__ = "agent_dynamic_state"

    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), primary_key=True)
    health: Mapped[float] = mapped_column(Float, default=100)
    energy: Mapped[float] = mapped_column(Float, default=80)
    satiety: Mapped[float] = mapped_column(Float, default=75)
    hydration: Mapped[float] = mapped_column(Float, default=75)
    hygiene: Mapped[float] = mapped_column(Float, default=70)
    social: Mapped[float] = mapped_column(Float, default=50)
    fun: Mapped[float] = mapped_column(Float, default=50)
    stress: Mapped[float] = mapped_column(Float, default=20)
    mood: Mapped[float] = mapped_column(Float, default=10)
    last_decay_world_time: Mapped[int] = mapped_column(Integer, default=0)
    critical_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    zero_satiety_since: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zero_hydration_since: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zero_energy_since: Mapped[int | None] = mapped_column(Integer, nullable=True)

    agent: Mapped[Agent] = relationship(back_populates="dynamic_state")


class Location(Base):
    __tablename__ = "locations"

    location_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.world_id"), index=True)
    public_name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    neighbors_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    available_tools_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    visibility_radius: Mapped[int] = mapped_column(Integer, default=0)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)


class AgentLocation(Base):
    __tablename__ = "agent_locations"

    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), primary_key=True)
    location_id: Mapped[str] = mapped_column(ForeignKey("locations.location_id"), index=True)
    arrived_at_world_time: Mapped[int] = mapped_column(Integer, default=0)

    agent: Mapped[Agent] = relationship(back_populates="location")
    location: Mapped[Location] = relationship()


class IdentityKnowledge(Base):
    __tablename__ = "identity_knowledge"
    __table_args__ = (UniqueConstraint("observer_agent_id", "target_agent_id", name="uq_identity_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    observer_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    target_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    visual_known: Mapped[bool] = mapped_column(Boolean, default=False)
    appearance_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    appearance_confidence: Mapped[int] = mapped_column(Integer, default=0)
    name_known: Mapped[bool] = mapped_column(Boolean, default=False)
    known_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    name_confidence: Mapped[int] = mapped_column(Integer, default=0)
    name_learned_via: Mapped[str | None] = mapped_column(String(40), nullable=True)
    gender_known: Mapped[bool] = mapped_column(Boolean, default=False)
    known_gender_text: Mapped[str | None] = mapped_column(String(120), nullable=True)
    first_seen_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_name_learned_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Relationship(Base):
    __tablename__ = "relationships"
    __table_args__ = (UniqueConstraint("observer_agent_id", "target_agent_id", name="uq_relationship_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    observer_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    target_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    familiarity: Mapped[float] = mapped_column(Float, default=0)
    trust: Mapped[float] = mapped_column(Float, default=50)
    affection: Mapped[float] = mapped_column(Float, default=0)
    fear: Mapped[float] = mapped_column(Float, default=0)
    conflict: Mapped[float] = mapped_column(Float, default=0)
    relationship_label: Mapped[str] = mapped_column(String(40), default="陌生")
    last_interaction_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Memory(Base):
    __tablename__ = "memories"

    memory_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    source_event_id: Mapped[int | None] = mapped_column(ForeignKey("events.event_id"), nullable=True)
    memory_type: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, default=20)
    visibility: Mapped[str] = mapped_column(String(24), default="private")
    created_world_time: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Event(Base):
    __tablename__ = "events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.world_id"), index=True)
    world_time: Mapped[int] = mapped_column(Integer, index=True)
    real_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    actor_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.agent_id"), nullable=True, index=True)
    target_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.agent_id"), nullable=True, index=True)
    location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.location_id"), nullable=True, index=True)
    visibility_scope: Mapped[str] = mapped_column(String(24), default="public")
    importance: Mapped[int] = mapped_column(Integer, default=10, index=True)
    color_class: Mapped[str] = mapped_column(String(24), default="normal")
    viewer_text: Mapped[str] = mapped_column(Text, nullable=False)
    agent_visible_text: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    state_delta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    no_state_changed: Mapped[bool] = mapped_column(Boolean, default=False)


class Conversation(Base):
    __tablename__ = "conversations"

    utterance_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.event_id"), index=True)
    speaker_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    target_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.agent_id"), nullable=True, index=True)
    location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.location_id"), nullable=True)
    content_zh: Mapped[str] = mapped_column(Text, nullable=False)
    tone: Mapped[str] = mapped_column(String(24), default="neutral")
    is_identity_reveal: Mapped[bool] = mapped_column(Boolean, default=False)
    heard_by_agent_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    world_time: Mapped[int] = mapped_column(Integer, index=True)


class Item(Base):
    __tablename__ = "items"

    item_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.world_id"), index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    item_type: Mapped[str] = mapped_column(String(40), default="misc")
    location_id: Mapped[str | None] = mapped_column(ForeignKey("locations.location_id"), nullable=True, index=True)
    created_event_id: Mapped[int | None] = mapped_column(ForeignKey("events.event_id"), nullable=True)


class Inventory(Base):
    __tablename__ = "inventories"
    __table_args__ = (UniqueConstraint("agent_id", "item_id", name="uq_inventory_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.item_id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)


class NarratorRun(Base):
    __tablename__ = "narrator_runs"

    narrator_run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.world_id"), index=True)
    trigger_type: Mapped[str] = mapped_column(String(40), default="batch")
    input_event_ids_json: Mapped[list[int]] = mapped_column(JSON, default=list)
    summary_title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    narration: Mapped[str | None] = mapped_column(Text, nullable=True)
    tone: Mapped[str] = mapped_column(String(24), default="calm")
    importance: Mapped[int] = mapped_column(Integer, default=40)
    created_world_time: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
