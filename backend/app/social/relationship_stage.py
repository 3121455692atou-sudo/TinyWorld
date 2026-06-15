from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Agent, Relationship, World
from app.social.intervention_crush import INTERVENTION_CRUSH_ROMANCE_TOOLS, has_active_intervention_crush


# Tools whose availability depends on the relationship with a concrete visible target.
# Generic speech remains available; these are stateful relationship/family transitions
# that should not appear for strangers just because somebody is nearby.
RELATIONSHIP_STAGE_TOOL_NAMES: set[str] = {
    "ask_date_visible_agent",
    "hold_hands_visible_agent",
    "hug_visible_agent",
    "confess_feelings_visible_agent",
    "define_relationship_visible_agent",
    "break_up_visible_agent",
    "repair_relationship_visible_agent",
    "request_adult_intimacy_visible_agent",
}

NEGATIVE_RELATIONSHIP_TOOL_NAMES: set[str] = {
    "express_dislike_visible_agent",
    "criticize_behavior_visible_agent",
    "reject_closeness_visible_agent",
}

ROMANCE_REQUEST_TOOL_NAMES: set[str] = {
    "ask_date_visible_agent",
    "hold_hands_visible_agent",
    "hug_visible_agent",
    "confess_feelings_visible_agent",
    "define_relationship_visible_agent",
}

PARTNER_FAMILY_PLANNING_TOOL_NAMES: set[str] = {
    "request_adult_intimacy_visible_agent",
    "buy_contraception",
    "buy_pregnancy_test",
    "take_pregnancy_test",
    "tool_pregnancy_take_test",
    "tool_pregnancy_prepare_birth",
    "tool_birth_call_for_help",
    "tool_birth_give_birth",
    "tool_birth_name_child",
    "tool_birth_register_parent",
    "tool_birth_collect_baby_supplies",
    "tool_birth_ask_community_support",
}

_ROMANTIC_LABEL_TOKENS = ("恋人", "伴侣", "夫妻", "妻子", "丈夫", "爱人", "约会", "交往", "暧昧", "亲密")
_PARTNER_LABEL_TOKENS = ("恋人", "伴侣", "夫妻", "妻子", "丈夫", "爱人", "交往")


@dataclass(frozen=True, slots=True)
class RelationshipSnapshot:
    target_id: str
    familiarity: float = 0.0
    trust: float = 50.0
    affection: float = 0.0
    fear: float = 0.0
    conflict: float = 0.0
    relationship_label: str = "陌生"
    reverse_affection: float = 0.0
    reverse_trust: float = 50.0
    reverse_conflict: float = 0.0
    partner: bool = False

    @property
    def romantic_label(self) -> bool:
        return any(token in (self.relationship_label or "") for token in _ROMANTIC_LABEL_TOKENS)

    @property
    def committed_label(self) -> bool:
        return any(token in (self.relationship_label or "") for token in _PARTNER_LABEL_TOKENS)

    @property
    def affinity_score(self) -> float:
        score = self.affection * 1.15 + self.trust * 0.45 + self.familiarity * 0.30
        score += self.reverse_affection * 0.35 + self.reverse_trust * 0.15
        score -= self.conflict * 1.25 + self.fear * 0.60 + self.reverse_conflict * 0.45
        if self.partner or self.committed_label:
            score += 70
        elif self.romantic_label:
            score += 28
        return score

    @property
    def has_tension(self) -> bool:
        return self.conflict >= 25 or self.reverse_conflict >= 25 or self.fear >= 35 or self.trust <= 25 or self.affection <= -10


@dataclass(frozen=True, slots=True)
class RelationshipMenuContext:
    has_visible_partner: bool = False
    has_high_affection_candidate: bool = False
    has_romance_candidate: bool = False
    has_relationship_tension: bool = False
    has_intervention_crush_candidate: bool = False
    best_affinity_score: float = 0.0


def relationship_snapshot(session: Session, actor: Agent, target: Agent | str | None) -> RelationshipSnapshot:
    target_id = target.agent_id if isinstance(target, Agent) else str(target or "")
    if not target_id or target_id == actor.agent_id:
        return RelationshipSnapshot(target_id=target_id)
    rel = session.execute(
        select(Relationship).where(
            Relationship.observer_agent_id == actor.agent_id,
            Relationship.target_agent_id == target_id,
        )
    ).scalar_one_or_none()
    reverse = session.execute(
        select(Relationship).where(
            Relationship.observer_agent_id == target_id,
            Relationship.target_agent_id == actor.agent_id,
        )
    ).scalar_one_or_none()
    partner_id = (actor.family_json or {}).get("partner_agent_id")
    target_partner_id = ((target.family_json or {}) if isinstance(target, Agent) else {}).get("partner_agent_id")
    partner = bool(partner_id == target_id or target_partner_id == actor.agent_id)
    return RelationshipSnapshot(
        target_id=target_id,
        familiarity=float(rel.familiarity if rel else 0),
        trust=float(rel.trust if rel else 50),
        affection=float(rel.affection if rel else 0),
        fear=float(rel.fear if rel else 0),
        conflict=float(rel.conflict if rel else 0),
        relationship_label=str(rel.relationship_label if rel else "陌生"),
        reverse_affection=float(reverse.affection if reverse else 0),
        reverse_trust=float(reverse.trust if reverse else 50),
        reverse_conflict=float(reverse.conflict if reverse else 0),
        partner=partner,
    )


def relationship_menu_context(session: Session, actor: Agent, target_ids: set[str]) -> RelationshipMenuContext:
    has_partner = False
    has_high = False
    has_romance = False
    has_tension = False
    has_crush = False
    best = 0.0
    for target_id in target_ids:
        target = session.get(Agent, target_id)
        if not target:
            continue
        snap = relationship_snapshot(session, actor, target)
        has_partner = has_partner or snap.partner or snap.committed_label
        has_high = has_high or _ready_to_define_relationship(snap)
        has_romance = has_romance or _ready_for_low_pressure_romance(snap)
        has_tension = has_tension or snap.has_tension
        has_crush = has_crush or has_active_intervention_crush(actor, target.agent_id, getattr(actor.world, "current_world_time_minutes", None))
        best = max(best, snap.affinity_score)
    return RelationshipMenuContext(
        has_visible_partner=has_partner,
        has_high_affection_candidate=has_high,
        has_romance_candidate=has_romance,
        has_relationship_tension=has_tension,
        has_intervention_crush_candidate=has_crush,
        best_affinity_score=best,
    )


def has_committed_partner(agent: Agent) -> bool:
    return bool((agent.family_json or {}).get("partner_agent_id"))


def relationship_tool_allowed_for_target(
    session: Session,
    world: World | None,
    actor: Agent,
    target: Agent | None,
    tool_name: str,
) -> bool:
    if tool_name not in RELATIONSHIP_STAGE_TOOL_NAMES:
        return True
    if not target or target.agent_id == actor.agent_id:
        return False
    if target.lifecycle_state == "dead":
        return False
    snap = relationship_snapshot(session, actor, target)
    if (
        tool_name in INTERVENTION_CRUSH_ROMANCE_TOOLS
        and actor.age_stage == "adult"
        and target.age_stage == "adult"
        and has_active_intervention_crush(actor, target.agent_id, world)
    ):
        return snap.conflict < 60 and snap.fear < 70
    if tool_name == "repair_relationship_visible_agent":
        return snap.has_tension
    if tool_name == "break_up_visible_agent":
        return snap.partner or snap.committed_label or (snap.romantic_label and (snap.conflict >= 15 or snap.affection <= 15))
    if tool_name == "request_adult_intimacy_visible_agent":
        if actor.age_stage != "adult" or target.age_stage != "adult":
            return False
        if snap.partner or snap.committed_label:
            return snap.trust >= 42 and snap.conflict < 40 and snap.fear < 60
        return _ready_for_adult_intimacy_without_label(snap)
    if tool_name == "define_relationship_visible_agent":
        if actor.age_stage != "adult" or target.age_stage != "adult":
            return False
        # Already confirmed partners should see family/intimacy/break-up tools, not another
        # relationship-confirmation request.
        if snap.partner or snap.committed_label:
            return False
        return _ready_to_define_relationship(snap)
    if tool_name == "confess_feelings_visible_agent":
        return _ready_to_confess(snap)
    if tool_name in {"hold_hands_visible_agent", "hug_visible_agent"}:
        return snap.partner or snap.committed_label or _ready_for_touch_request(snap)
    if tool_name == "ask_date_visible_agent":
        return _ready_for_low_pressure_romance(snap)
    return True


def target_sort_key_for_tool(session: Session, actor: Agent, target_id: str, tool_name: str) -> tuple[float, str]:
    target = session.get(Agent, target_id)
    snap = relationship_snapshot(session, actor, target or target_id)
    bonus = 0.0
    if target and tool_name in INTERVENTION_CRUSH_ROMANCE_TOOLS and has_active_intervention_crush(actor, target.agent_id, getattr(actor.world, "current_world_time_minutes", None)):
        bonus += 180 if tool_name == "confess_feelings_visible_agent" else 140
    if tool_name == "define_relationship_visible_agent" and _ready_to_define_relationship(snap):
        bonus += 120
    elif tool_name == "request_adult_intimacy_visible_agent" and (snap.partner or snap.committed_label):
        bonus += 120
    elif tool_name in {"ask_date_visible_agent", "hold_hands_visible_agent", "hug_visible_agent", "confess_feelings_visible_agent"} and snap.affection >= 40:
        bonus += 60
    return (-(snap.affinity_score + bonus), target_id)


def relationship_option_priority(session: Session, actor: Agent, option_tool_name: str, target_ids: list[str] | None = None) -> int | None:
    target_ids = target_ids or []
    snaps: list[RelationshipSnapshot] = []
    for target_id in target_ids:
        target = session.get(Agent, target_id)
        if target:
            snaps.append(relationship_snapshot(session, actor, target))
    partner_visible = any(snap.partner or snap.committed_label for snap in snaps)
    high_ready = any(_ready_to_define_relationship(snap) for snap in snaps)
    romance_ready = any(_ready_for_low_pressure_romance(snap) for snap in snaps)
    crush_ready = False
    for target_id in target_ids:
        target = session.get(Agent, target_id)
        if target and has_active_intervention_crush(actor, target.agent_id, getattr(actor.world, "current_world_time_minutes", None)):
            crush_ready = True
            break
    if option_tool_name in {"accept_social_request_visible_agent", "decline_social_request_visible_agent", "accept_adult_intimacy_visible_agent", "decline_adult_intimacy_visible_agent"}:
        return 4
    if option_tool_name == "confess_feelings_visible_agent" and crush_ready:
        return 5
    if option_tool_name == "define_relationship_visible_agent" and high_ready:
        return 6
    if option_tool_name == "request_adult_intimacy_visible_agent" and (partner_visible or any(_ready_for_adult_intimacy_without_label(snap) for snap in snaps)):
        return 7
    if option_tool_name == "confess_feelings_visible_agent" and any(_ready_to_confess(snap) for snap in snaps):
        return 8
    if option_tool_name in {"ask_date_visible_agent", "hold_hands_visible_agent", "hug_visible_agent"} and romance_ready:
        return 10
    if option_tool_name in {"ask_date_visible_agent", "hold_hands_visible_agent", "hug_visible_agent"} and crush_ready:
        return 7
    if option_tool_name in {"buy_contraception", "buy_pregnancy_test", "take_pregnancy_test"} and has_committed_partner(actor):
        return 12
    if option_tool_name.startswith("tool_birth_") or option_tool_name.startswith("tool_pregnancy_"):
        pregnancy = (actor.family_json or {}).get("pregnancy_state") or {}
        if isinstance(pregnancy, dict) and pregnancy.get("pregnant"):
            return 11
        if has_committed_partner(actor):
            return 22
    return None


def _ready_for_low_pressure_romance(snap: RelationshipSnapshot) -> bool:
    # A date/low-pressure social request is still a real pending request, but it
    # should not be treated like commitment. Keep it available unless the relation
    # is actively unsafe or hostile; ordering decides whether it is prominent.
    return snap.conflict < 45 and snap.fear < 60


def _ready_for_touch_request(snap: RelationshipSnapshot) -> bool:
    # Hug/hand-holding are consent-request tools, not relationship-stage locks.
    # They should remain callable for ordinary social tests and low-stakes scenes,
    # while still disappearing for hostile/fearful targets.
    return snap.conflict < 45 and snap.fear < 60 and snap.trust >= 25


def _ready_to_confess(snap: RelationshipSnapshot) -> bool:
    if snap.conflict >= 30 or snap.fear >= 45 or snap.trust < 42:
        return False
    return bool(snap.affection >= 55 and snap.familiarity >= 28)


def _ready_to_define_relationship(snap: RelationshipSnapshot) -> bool:
    if snap.conflict >= 25 or snap.fear >= 35:
        return False
    if snap.affection <= 0:
        return False
    return bool(snap.affection >= 75 and snap.trust >= 58 and snap.familiarity >= 38)


def _ready_for_adult_intimacy_without_label(snap: RelationshipSnapshot) -> bool:
    if snap.conflict >= 20 or snap.fear >= 30:
        return False
    return bool(snap.affection >= 82 and snap.trust >= 65 and snap.familiarity >= 50)
