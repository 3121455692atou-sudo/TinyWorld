"""Two-character expressed-emotion → stat nudge system.

Agents may *optionally* tag a speech or meal action with a two-character emotion
(e.g. ``情绪：开心``). They are never told it changes their stats — they are only
invited to express how they feel. When the expressed word matches an entry in
``data/emotion_effects.json`` with a non-empty delta, that delta nudges the
character's soft emotional stats (mood / stress / social / fun). Unmatched or
not-yet-tuned words are silently ignored — the turn proceeds normally.

The delta table ships with a small curated starter set; the remaining ~3300
words are present with empty deltas to be filled in later per
``EMOTION_EFFECTS_SPEC.md``.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "emotion_effects.json"

# Only these soft emotional stats may be nudged by an expressed emotion.
EMOTION_STAT_FIELDS = ("mood", "stress", "social", "fun")

# Matches an explicitly tagged two-character (Chinese) emotion the agent may add
# to a speech/meal action, e.g. "情绪：开心" / "（情绪：难过）" / "[情绪:好吃]". The
# trailing negative lookahead enforces *exactly* two characters — a longer word
# like "开开心心" is rejected rather than truncated.
_EMOTION_RE = re.compile(r"[（(\[]?\s*情绪\s*[：:]\s*([一-龥]{2})(?![一-龥])\s*[）)\]]?")


@lru_cache(maxsize=1)
def load_emotion_effects() -> dict[str, dict[str, int]]:
    """Load the emotion → stat-delta table, keeping only non-empty integer deltas."""
    try:
        raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    cleaned: dict[str, dict[str, int]] = {}
    if not isinstance(raw, dict):
        return cleaned
    for word, delta in raw.items():
        if not isinstance(delta, dict):
            continue
        nudges = {
            field: int(value)
            for field, value in delta.items()
            if field in EMOTION_STAT_FIELDS and isinstance(value, (int, float)) and int(value)
        }
        if nudges:
            cleaned[str(word)] = nudges
    return cleaned


def extract_expressed_emotion(text: str | None) -> tuple[str | None, str]:
    """Pull a tagged two-character emotion out of ``text``.

    Returns ``(emotion or None, text_without_the_tag)`` so callers can keep the
    spoken line clean while still reacting to the feeling behind it.
    """
    if not text:
        return None, text or ""
    match = _EMOTION_RE.search(text)
    if not match:
        return None, text
    emotion = match.group(1)
    stripped = (text[: match.start()] + text[match.end() :]).strip()
    return emotion, stripped


def emotion_effect_delta(emotion: str | None) -> dict[str, int]:
    """Stat delta for an expressed emotion, or empty when unknown/untuned."""
    if not emotion:
        return {}
    return dict(load_emotion_effects().get(emotion, {}))
