from __future__ import annotations


DEFAULT_IMPORTANCE = {
    "move": 10,
    "look": 5,
    "observe": 20,
    "self_status": 5,
    "dialogue": 60,
    "eat": 15,
    "drink": 15,
    "warning": 35,
    "first_seen": 40,
    "ask_introduction": 45,
    "refuse_introduction": 55,
    "introduce_self": 70,
    "gift": 55,
    "story": 60,
    "game": 65,
    "seek_help": 60,
    "critical": 85,
    "death": 100,
    "narrator": 50,
}


def color_for_importance(importance: int, event_type: str) -> str:
    if event_type == "death":
        return "death"
    if event_type == "dialogue":
        return "dialogue"
    if event_type == "narration":
        return "narrator"
    if importance >= 85:
        return "danger"
    if importance >= 70:
        return "important"
    if importance >= 45:
        return "warning"
    if importance >= 25:
        return "info"
    return "normal"
