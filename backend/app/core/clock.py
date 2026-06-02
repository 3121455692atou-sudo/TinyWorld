from __future__ import annotations


def format_world_time(minutes: int) -> str:
    day = minutes // 1440 + 1
    minute_of_day = minutes % 1440
    hour = minute_of_day // 60
    minute = minute_of_day % 60
    return f"第{day}天 {hour:02d}:{minute:02d}"


def current_day(minutes: int) -> int:
    return minutes // 1440 + 1

