from __future__ import annotations

from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Agent, IdentityKnowledge, World
from app.world.visibility import build_visible_people, resolve_visible_ref

# Public words that make a line obviously addressed to the whole scene.
_GROUP_ADDRESS_WORDS = {
    "大家", "各位", "所有人", "有人", "谁", "哪位", "你们", "诸位", "朋友们", "在场的人",
}

# Words that usually mean the speaker is asking the scene, not silently targeting
# a random visible agent.
_OPEN_REQUEST_WORDS = {
    "帮帮我", "救命", "能不能帮", "谁能", "有人能", "需要帮助", "需要水", "需要食物", "请帮忙",
}

_BABY_STAGES = {"newborn", "infant", "toddler"}

# Tools whose target is mostly conversational. If the text explicitly names one
# visible known person that differs from the AOHP-bound visible_ref, the backend
# may retarget before validation. This repairs “A 说的是 B，编号却绑成 C”的常见 LLM slip.
RETARGETABLE_VISIBLE_SPEECH_TOOLS = {
    "say_to_visible_agent",
    "wake_visible_agent",
    "compliment_visible_agent",
    "apologize_to_visible_agent",
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
    "force_hug_visible_agent",
    "force_hold_hands_visible_agent",
    "force_comfort_visible_agent",
    "force_help_visible_agent",
    "force_walk_together_visible_agent",
    "force_date_visible_agent",
    "force_relationship_claim_visible_agent",
    "attempt_forced_adult_boundary_visible_agent",
}


def visible_listener_ids(session: Session, actor: Agent, world_time: int) -> list[str]:
    """All same-scene listeners who can hear/see a public event.

    This is an observation list, not a reaction list.  The world may display that
    everyone heard something, but only addressed/relevant people should be queued
    into an immediate LLM reaction.  That separation prevents unrelated agents
    from treating every help/comfort line as if it were aimed at them.
    """
    return [person.target_agent_id for person in build_visible_people(session, actor, world_time)]


def _known_target_ids(session: Session, actor: Agent) -> set[str]:
    # mark_name_known can be called moments before this helper in the same turn;
    # flush pending changes so SQL filtering by name_known sees the fresh fact.
    session.flush()
    rows = session.execute(
        select(IdentityKnowledge.target_agent_id).where(
            IdentityKnowledge.observer_agent_id == actor.agent_id,
            IdentityKnowledge.name_known.is_(True),
        )
    ).scalars()
    return set(rows)


def mentioned_visible_agent_ids(session: Session, actor: Agent, world: World, text: str) -> list[str]:
    """Visible agents explicitly addressed by known name or visible ref.

    Important boundary: this helper does *not* let leaked unknown real names steer
    targeting. A name only counts if the actor actually knows it, or if the text
    says the visible temporary ref such as “附近人物A”.
    """
    if not text:
        return []
    known_ids = _known_target_ids(session, actor)
    result: list[str] = []
    for person in build_visible_people(session, actor, world.current_world_time_minutes, persist=False):
        if person.target_agent_id == actor.agent_id:
            continue
        if person.visible_ref and person.visible_ref in text:
            result.append(person.target_agent_id)
            continue
        if person.target_agent_id in known_ids and person.known_name and person.known_name != "未知" and person.known_name in text:
            result.append(person.target_agent_id)
    return list(dict.fromkeys(result))


def speech_addresses_group(text: str) -> bool:
    text = (text or "").strip()
    return any(word in text for word in _GROUP_ADDRESS_WORDS | _OPEN_REQUEST_WORDS)


def visible_ref_for_agent_id(session: Session, actor: Agent, world: World, target_agent_id: str) -> str | None:
    for person in build_visible_people(session, actor, world.current_world_time_minutes, persist=False):
        if person.target_agent_id == target_agent_id:
            return person.visible_ref
    return None


def retarget_params_by_explicit_address(session: Session, world: World, actor: Agent, tool_name: str, params: dict) -> dict:
    """Repair AOHP target if speech explicitly calls a different visible person.

    The action number remains the model's chosen *kind* of action, but if the body
    text clearly says “桃枝，……” while the bound visible_ref points to 许澈, the
    real target should be 桃枝.  We only retarget when exactly one known visible
    target is explicit; group speech and ambiguous multiple names are left alone.
    """
    if tool_name not in RETARGETABLE_VISIBLE_SPEECH_TOOLS:
        return params
    speech = str(params.get("speech") or params.get("message") or params.get("content") or "")
    if not speech:
        return params
    explicit = mentioned_visible_agent_ids(session, actor, world, speech)
    if len(explicit) != 1:
        return params
    intended_id = explicit[0]
    current_ref = str(params.get("visible_ref") or "")
    current = resolve_visible_ref(session, actor, current_ref, world.current_world_time_minutes, persist=False) if current_ref else None
    if current and current.agent_id == intended_id:
        return params
    new_ref = visible_ref_for_agent_id(session, actor, world, intended_id)
    if not new_ref:
        return params
    new_params = dict(params)
    new_params["visible_ref"] = new_ref
    # If this is an accept/decline/dodge response, keep request IDs aligned with
    # the corrected target when the intended person has exactly one matching
    # pending item. Otherwise validation will fail safely rather than responding
    # to the wrong person.
    if new_params.get("request_id"):
        try:
            from app.social.pending_requests import incoming_social_requests

            req_type = str(new_params.get("request_type") or "")
            candidates = [
                req for req in incoming_social_requests(actor, world.current_world_time_minutes)
                if req.get("from_agent_id") == intended_id and (not req_type or req.get("request_type") == req_type)
            ]
            if len(candidates) == 1:
                new_params["request_id"] = candidates[0].get("request_id")
                new_params["request_type"] = candidates[0].get("request_type")
        except Exception:
            pass
    if new_params.get("forced_action_id"):
        try:
            from app.social.forced_actions import incoming_forced_actions

            action_type = str(new_params.get("action_type") or "")
            candidates = [
                req for req in incoming_forced_actions(actor, world.current_world_time_minutes)
                if req.get("from_agent_id") == intended_id and (not action_type or req.get("action_type") == action_type)
            ]
            if len(candidates) == 1:
                new_params["forced_action_id"] = candidates[0].get("forced_action_id")
                new_params["action_type"] = candidates[0].get("action_type")
        except Exception:
            pass
    new_params["_retargeted_by_speech"] = {
        "from_visible_ref": current_ref,
        "to_visible_ref": new_ref,
        "to_agent_id": intended_id,
        "reason": "speech_explicit_known_name_or_visible_ref",
    }
    return new_params


def reaction_ids_for_public_speech(
    session: Session,
    world: World,
    actor: Agent,
    *,
    speech: str,
    target: Agent | None = None,
    direct: bool = False,
    include_group_when_public: bool = True,
) -> list[str]:
    """Choose who should immediately react to a spoken event.

    Everyone in the scene may hear the event; this function only returns people
    likely to feel addressed enough for an immediate reaction turn.
    - Direct visible_ref tools always include the bound target.
    - Calling a visible character's known name/ref also includes that character.
    - Public/group wording includes all ordinary listeners.
    - Babies/toddlers do not enter adult-style reaction chains; they keep their
      template baby logic instead.
    """
    listener_ids = visible_listener_ids(session, actor, world.current_world_time_minutes)
    ids: list[str] = []
    if direct and target is not None:
        ids.append(target.agent_id)
    mentioned = mentioned_visible_agent_ids(session, actor, world, speech)
    ids.extend(mentioned)
    # Public speech has two modes:
    # - explicitly calling one visible known/ref person -> that person should react first;
    #   bystanders only hear it, they do not get dragged into an immediate response.
    # - open/group wording or no explicit target -> the scene may react.
    # This fixes A clearly talking to B while C suddenly treats it as aimed at C.
    if include_group_when_public and (speech_addresses_group(speech) or (not direct and not mentioned)):
        ids.extend(listener_ids)

    filtered: list[str] = []
    for agent_id in ids:
        if agent_id == actor.agent_id or agent_id in filtered:
            continue
        agent = session.get(Agent, agent_id)
        if not agent or agent.lifecycle_state not in {"alive", "critical"}:
            continue
        if agent.age_stage in _BABY_STAGES:
            continue
        filtered.append(agent_id)
    return filtered


def child_caregiver_reaction_ids(session: Session, world: World, child: Agent, *, include_adjacent: Iterable[str]) -> list[str]:
    """Adults/older children who should notice a baby/child need event.

    Guardians are ordered first.  Newborns/infants/toddlers are excluded so one
    crying baby does not make another baby try adult care behavior.
    """
    guardians = set((child.family_json or {}).get("guardian_agent_ids") or [])
    candidates: list[Agent] = []
    for agent_id in include_adjacent:
        if agent_id == child.agent_id:
            continue
        agent = session.get(Agent, agent_id)
        if not agent or agent.lifecycle_state not in {"alive", "critical"}:
            continue
        if agent.age_stage in _BABY_STAGES:
            continue
        candidates.append(agent)
    candidates.sort(key=lambda item: (0 if item.agent_id in guardians else 1, 0 if item.age_stage == "adult" else 1, item.agent_id))
    return [agent.agent_id for agent in candidates]
