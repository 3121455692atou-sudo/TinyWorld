from __future__ import annotations

from typing import Any

from app.core.models import Agent, Location, World


BOARD_KEY = "location_notice_boards"
MAX_NOTICE_ENTRIES = 20
MAX_NOTICE_CONTENT = 500


def notice_board_entries(world: World, location_id: str | None) -> list[dict[str, Any]]:
    if not location_id:
        return []
    boards = (world.settings_json or {}).get(BOARD_KEY)
    if not isinstance(boards, dict):
        return []
    entries = boards.get(location_id)
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def notice_board_prompt_lines(world: World, location: Location | None) -> list[str]:
    if not location:
        return []
    entries = notice_board_entries(world, location.location_id)
    if not entries:
        return [f"{location.public_name} 的公示牌现在是空的。"]
    lines = [f"{location.public_name} 的公示牌上写着:"]
    for entry in entries[-8:]:
        content = str(entry.get("content") or "").strip()
        if content:
            lines.append(f"- {content[:220]}")
    return lines


def append_notice(world: World, location_id: str | None, actor: Agent, content: str) -> dict[str, Any]:
    if not location_id:
        raise ValueError("location_id is required")
    text = _clean_notice_content(content)
    if not text:
        raise ValueError("content is required")
    settings = dict(world.settings_json or {})
    boards = settings.get(BOARD_KEY)
    boards = dict(boards) if isinstance(boards, dict) else {}
    entries = boards.get(location_id)
    entries = list(entries) if isinstance(entries, list) else []
    entry = {
        "content": text,
        "author_agent_id": actor.agent_id,
        "world_time": world.current_world_time_minutes,
    }
    entries.append(entry)
    boards[location_id] = entries[-MAX_NOTICE_ENTRIES:]
    settings[BOARD_KEY] = boards
    world.settings_json = settings
    return entry


def clear_notice_board(world: World, location_id: str | None) -> int:
    if not location_id:
        return 0
    settings = dict(world.settings_json or {})
    boards = settings.get(BOARD_KEY)
    boards = dict(boards) if isinstance(boards, dict) else {}
    entries = boards.get(location_id)
    count = len(entries) if isinstance(entries, list) else 0
    boards[location_id] = []
    settings[BOARD_KEY] = boards
    world.settings_json = settings
    return count


def _clean_notice_content(content: str) -> str:
    text = " ".join(str(content or "").split())
    return text[:MAX_NOTICE_CONTENT]
