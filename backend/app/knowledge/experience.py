"""Personal evidence, shared by normal turns and ending speeches."""
from sqlalchemy import select

from app.core.clock import format_world_time
from app.core.models import Event, IdentityKnowledge, Location, Memory
from app.knowledge.event_access import agent_can_access_event
from app.llm.context_budget import text_token_upper_bound
from app.llm.runtime import agent_llm_generation
from app.llm.language import world_language, english_safe_label, english_safe_sentence, location_label

# These are executed results, not a resident's assertions or intentions.
PERSONAL_RESULT_TYPES = {
    "werewolf_guard_protect", "werewolf_seer_check", "werewolf_coroner_report",
    "werewolf_medium_report", "werewolf_witch_save", "werewolf_witch_poison",
    "werewolf_night_pass", "corpse_inspect", "corpse_seen", "corpse_buried",
    "move", "return_home", "knock_room", "door_opened", "room_entered_for_inspection",
}


def _initial_room_assignment_lines(session, world, agent):
    if not (world.settings_json or {}).get("werewolf_mode_enabled") or agent.world_id != world.world_id:
        return []
    # Read opening assignments, never today's wallet, location or life status.
    # Only initial acquaintances share this setup knowledge; later encounters do
    # not silently reveal an address. Introduction tags can change after setup.
    rows = session.execute(select(Event, IdentityKnowledge).join(IdentityKnowledge,
        IdentityKnowledge.target_agent_id == Event.actor_agent_id).where(
            Event.world_id == world.world_id, Event.event_type == "birth",
            IdentityKnowledge.observer_agent_id == agent.agent_id,
            IdentityKnowledge.name_known.is_(True),
            IdentityKnowledge.first_name_learned_at <= Event.world_time,
        ).order_by(Event.event_id))
    english = world_language(world) == "en"
    assignments, seen = [], set()
    for event, knowledge in rows:
        if event.actor_agent_id in seen or not knowledge.known_name:
            continue
        home_id = (event.payload or {}).get("home_location_id")
        home = session.get(Location, home_id) if home_id else None
        if not home or home.world_id != world.world_id:
            continue
        seen.add(event.actor_agent_id)
        name = english_safe_label(knowledge.known_name, fallback=event.actor_agent_id) if english else knowledge.known_name
        assignments.append(f"{name}: {location_label(home, 'en')}" if english else f"{name}：{home.public_name}")
    if not assignments:
        return []
    if english:
        return ["[Initial room allocation] " + "; ".join(assignments) + ". These opening assignments do not tell you who is currently inside."]
    return ["【入住时的房间分配】" + "；".join(assignments) + "。这是入住分配信息，不代表对方现在在房内。"]


def personal_experience_context(session, world, agent, *, include_memories=False):
    lines = [f"【你的个人经历与依据】你是{agent.chosen_name}。",
             f"性格：{agent.personality_seed or ''}；说话习惯：{agent.speaking_style or ''}。",
             "行动结果是已执行记录；发言只证明某人说过，不能证明其内容属实。推理、计划、个人笔记仍是你的判断。",
             "同意一起调查不等于已经抵达；要实际移动、查看或清理，请选择相应行动，等返回结果后再描述经历。"]
    english = world_language(world) == "en"
    if english:
        lines = [f"[Your personal experiences] You are {english_safe_label(agent.chosen_name, fallback=agent.agent_id)}.",
                 f"Personality: {english_safe_sentence(agent.personality_seed)} Speaking style: {english_safe_sentence(agent.speaking_style)}",
                 "Executed results record actual actions. Speech proves only that someone made a claim. Notes, plans and deductions remain your own judgments.",
                 "Agreeing to investigate is not arrival. Select movement, inspection or cleanup and wait for its result before describing it as an experience."]
    from app.world.doors import nearby_door_prompt_lines
    lines.extend(_initial_room_assignment_lines(session, world, agent))
    lines.extend(nearby_door_prompt_lines(session, world, agent))
    base = select(Event).where(Event.world_id == world.world_id, Event.actor_agent_id == agent.agent_id,
                               Event.event_type.in_(PERSONAL_RESULT_TYPES))
    # A long walk must not evict the most recent actual guard/seer result.
    results = list(session.scalars(base.where(Event.event_type.like("werewolf_%"))
        .order_by(Event.world_time.desc(), Event.event_id.desc()).limit(60)))
    results += list(session.scalars(base.where(~Event.event_type.like("werewolf_%"))
        .order_by(Event.world_time.desc(), Event.event_id.desc()).limit(12)))
    for event in sorted(results, key=lambda e: (e.world_time, e.event_id), reverse=True):
        if agent_can_access_event(session, world, agent.agent_id, event):
            if english:
                lines.append(f"- [Executed #{event.event_id}, world minute {event.world_time}, {event.event_type}] {english_safe_sentence(event.agent_visible_text or event.viewer_text)}")
                continue
            lines.append(f"- [已执行 #{event.event_id} {format_world_time(event.world_time)}] {event.agent_visible_text or event.viewer_text}")
    query = select(Memory).where(Memory.agent_id == agent.agent_id)
    if not include_memories:
        query = query.where(Memory.memory_type.in_(["identity", "relationship"]))
    budget = agent_llm_generation(agent, world)["context_window_tokens"] // 2
    used = text_token_upper_bound('\n'.join(lines))
    for memory in session.scalars(query.order_by(Memory.created_world_time.desc(), Memory.memory_id.desc())):
        if memory.source_event_id:
            source = session.get(Event, memory.source_event_id)
            if source is None or not agent_can_access_event(session, world, agent.agent_id, source):
                continue
        line = f"- [个人记录 {format_world_time(memory.created_world_time)} 来源#{memory.source_event_id or '个人设定/笔记'}] {memory.content}"
        if english:
            line = f"- [Personal record, world minute {memory.created_world_time}, source #{memory.source_event_id or 'personal setting/note'}] {english_safe_sentence(memory.content)}"
        cost = text_token_upper_bound(line)
        if used + cost > budget:
            break
        used += cost
        lines.append(line)
    return '\n'.join(lines)
