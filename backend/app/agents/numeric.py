"""Numeric boundaries shared by simulation state and imported content.

Action inputs are strict; legacy save reads can supply a documented fallback.
Neither path lets NaN compare as a full attribute bar or reach JSON storage.
"""
from __future__ import annotations

import math
from typing import Any


def require_finite(value: Any, name: str = "value") -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def finite_float(value: Any, default: float = 0.0) -> float:
    try:
        return require_finite(value)
    except ValueError:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default
