"""Context packing only: never rewrite an agent's speech or tool choices."""
from __future__ import annotations

import json
import re
from typing import Any

DEFAULT_CONTEXT_WINDOW_TOKENS = 256_000
HAIKU_CONTEXT_CEILING = 99_000
FRAMING_RESERVE = 2048


def is_haiku_55(model: str) -> bool:
    return bool(re.search(r"haiku[-_.]?5[-_.]?5(?:\D|$)", model.lower()))


def effective_context_limit(model: str, configured: int = DEFAULT_CONTEXT_WINDOW_TOKENS) -> int:
    return min(configured, HAIKU_CONTEXT_CEILING) if is_haiku_55(model) else configured


def text_token_upper_bound(text: str) -> int:
    # No provider tokenizer is available locally. Count UTF-8 bytes rather than
    # claiming an approximate tokenizer count is safe at a billing boundary.
    return len(text.encode("utf-8"))


def pack_text_context(payload: dict[str, Any], configured: int) -> str | None:
    """Keep fixed instructions intact; discard oldest whole memory entries first.

    Memory entries are emitted oldest-to-newest. Other input (including manual
    prompts) is never silently shortened. Input + framing + completion must fit.
    """
    model = str(payload.get("model") or "")
    limit = effective_context_limit(model, configured)
    output = int(payload.get("max_tokens") or 8192)
    if is_haiku_55(model):
        output = min(output, 8192)
    if is_haiku_55(model) or payload.get("max_tokens"):
        payload["max_tokens"] = max(1, output)
    messages = payload["messages"]

    def size() -> int:
        return text_token_upper_bound(json.dumps(messages, ensure_ascii=False)) + FRAMING_RESERVE + output

    if size() < limit:
        return None
    for message in messages:
        if message.get("role") != "user" or not isinstance(message.get("content"), str):
            continue
        text = message["content"]
        for opening, closing in (("【记忆】\n", "\n【记忆使用规则】"), ("MEMORY\n", "\nMEMORY USE RULES")):
            if opening not in text or closing not in text.split(opening, 1)[1]:
                continue
            before, memory = text.split(opening, 1)
            memory, after = memory.split(closing, 1)
            entries = memory.strip().splitlines()
            excess = size() - limit + 1
            dropped = 0
            while entries and dropped < excess:
                dropped += text_token_upper_bound(json.dumps(entries.pop(0), ensure_ascii=False)) + 2
            message["content"] = before + opening + "\n".join(entries) + closing + after
            # JSON escaping can differ slightly from the per-entry accounting.
            while entries and size() >= limit:
                entries.pop(0)
                message["content"] = before + opening + "\n".join(entries) + closing + after
            break
    if size() >= limit:
        return f"上下文预算保护：固定提示和输出预留已达到 {limit:,} 上限，本次未发送。请降低输出上限或缩短固定提示。"
    return None
