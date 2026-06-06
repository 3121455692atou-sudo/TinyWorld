from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Any

from app.core.models import Agent
from app.llm.language import normalize_language, world_language
from app.llm.schemas import ActionChoice


@dataclass(slots=True)
class ActionOption:
    """A concrete, pre-validated action choice shown to the LLM.

    The model chooses option_id only. Backend owns tool_name, target ids, location ids,
    inventory ids, stock tickers, and all hard-rule parameters.

    AOHP v2 intentionally keeps free speech *outside* regex delimiters. The parser reads
    only the first action header line, then passes the remaining body through as text.
    """

    option_id: int
    label: str
    tool_name: str
    params: dict[str, Any] = field(default_factory=dict)
    value_slot: str | None = None
    text_slot: str | None = None
    text_required: bool = False
    min_value: float | None = None
    max_value: float | None = None
    default_value: float | int | str | None = None
    value_hint: str | None = None
    tone: str | None = None
    risk_note: str | None = None
    tags: tuple[str, ...] = ()
    target_choices: tuple[dict[str, Any], ...] = ()


@dataclass(slots=True)
class ParsedActionPacket:
    option_id: int
    value_text: str
    text: str


@dataclass(slots=True)
class ParsedActionResult:
    action: ActionChoice | None
    error: str | None = None
    packet: ParsedActionPacket | None = None
    option: ActionOption | None = None


# AOHP v2 standard format:
#   [17]
#   natural Chinese speech/body continues here, untouched by delimiters
#
# Optional numeric/target value goes in the header:
#   [08:8]
#   [08 8]
#   08 8        (accepted as a recovery-friendly shorthand)
#
# The free text body deliberately has no closing marker. This avoids delimiter leakage
# into Chinese dialogue and prevents punctuation-heavy speech from being mis-parsed.
_HEADER_RE = re.compile(
    r"^\s*(?:```(?:text)?\s*)?"
    r"\[(?P<option_id>\d{1,3})(?:(?:\s*[:：]\s*|\s+)(?P<value>[^\]\r\n]{1,48}))?\][^\S\r\n]*"
    r"(?P<inline>[^\r\n]*)"
    r"(?:\r?\n(?P<body>.*))?\s*$",
    flags=re.IGNORECASE | re.DOTALL,
)

# Accept a non-preferred but common model variant. We keep this strict: it only parses a
# header-like first line, never comma-separated natural speech.
_ACTION_LINE_RE = re.compile(
    r"^\s*(?:ACTION|ACT|行动|编号|选项)\s*[:=：]\s*(?P<option_id>\d{1,3})"
    r"(?:\s+(?:VALUE|值|数值|目标)\s*[:=：]?\s*(?P<value>[^\r\n]{1,48}))?\s*"
    r"(?:\r?\n(?P<body>.*))?\s*$",
    flags=re.IGNORECASE | re.DOTALL,
)

_BARE_HEADER_RE = re.compile(
    r"^\s*(?P<option_id>\d{1,3})(?:\s+(?P<value>\d{1,3}|[一二两三四五六七八九十]{1,3}))?\s*"
    r"(?:\r?\n(?P<body>.*))?\s*$",
    flags=re.IGNORECASE | re.DOTALL,
)

_PROTOCOL_NOISE_LINE_RE = re.compile(
    r"(?im)^[^\S\r\n]*(?:pmml[^\S\r\n]+)?prompt[^\S\r\n]+end[^\S\r\n]+marker[^\S\r\n]*$"
)
_PROTOCOL_NOISE_INLINE_RE = re.compile(
    r"(?i)\b(?:pmml[^\S\r\n]+)?prompt[^\S\r\n]+end[^\S\r\n]+marker\b"
)

_CHINESE_NUMBERS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def action_system_prompt(language: str = "zh") -> str:
    if normalize_language(language) == "en":
        return (
            "You are a resident in a virtual world. Choose exactly one numbered action option for this turn. "
            "The first line must be an action header: [number], [number:target-number] when the option lists targets, or [number:value] when the option needs a value. The shorthand 'number target-number' is also accepted. "
            "If the option lists targets, choose only one target number from the indented target line. If the option needs speech or writing, put the natural English body from the second line onward. "
            "Do not use braces, JSON-like objects, Markdown, explanations, tool names, target IDs, location IDs, or parameter names. "
            "The action number already binds the backend tool, target, location, corpse, item, stock ticker, and hard-rule parameters. "
            "You only choose the number and freely write what this character actually says or writes. "
        )
    return (
        "你是虚拟世界中的居民，只能从本回合【行动选项】里选一个编号。"
        "第一行只写行动头：[编号]；如果选项列出目标编号，就写 [编号:目标编号]，也可以简写成 编号 目标编号；如果需要数值，就写 [编号:数值]。"
        "目标编号只能从行动选项下方的目标列表里选一个；如果行动需要说话或写作，从第二行开始直接写中文正文；正文不要加引号，不要写成结构化对象。"
        "不要使用大括号结构，不要解释，不要 Markdown。"
        "行动编号已经绑定工具、目标、地点和参数；你只负责选择编号，以及在正文里自然表达自己想说/写的话。"
    )


def option_with_id(option: ActionOption, idx: int) -> ActionOption:
    return replace(option, option_id=idx)


def format_action_options_for_prompt(options: list[ActionOption], *, language: str = "zh") -> str:
    english = normalize_language(language) == "en"
    lines: list[str] = []
    for option in options:
        suffixes: list[str] = []
        if option.value_slot:
            hint = option.value_hint
            if not hint:
                if option.value_slot == "sleep_hours":
                    hint = "hours" if english else "小时"
                elif option.value_slot in {"amount", "money"}:
                    hint = "amount" if english else "金额"
                elif option.value_slot in {"quantity", "shares"}:
                    hint = "quantity" if english else "数量"
                else:
                    hint = option.value_slot
            if english:
                hint = {"小时": "hours", "金额": "amount", "数量": "quantity"}.get(str(hint), str(hint))
                suffixes.append(f"value={hint}")
            else:
                suffixes.append(f"值={hint}")
        if option.text_slot:
            suffixes.append("body" if english and option.text_slot in {"content", "note", "proposal"} else "speech" if english else "正文" if option.text_slot in {"content", "note", "proposal"} else "台词")
        if option.target_choices:
            suffixes.insert(0, "target=number" if english else "目标=编号")
        if option.risk_note:
            suffixes.append("risk" if english else option.risk_note)
        for tag in option.tags:
            mapped = {"风险": "risk", "负收益": "costly", "世界观": "world"}.get(tag, tag) if english else tag
            if mapped not in suffixes:
                suffixes.append(mapped)
        hint = f" [{' / '.join(suffixes)}]" if suffixes else ""
        lines.append(f"{option.option_id:02d} {option.label}{hint}")
        if option.target_choices:
            rendered_targets = []
            for choice in option.target_choices[:24]:
                choice_id = choice.get("id")
                choice_label = str(choice.get("label") or choice_id)
                rendered_targets.append(f"{choice_id}={choice_label}")
            target_prefix = "   Targets: " if english else "   目标: "
            lines.append(target_prefix + "；".join(rendered_targets))
    return "\n".join(lines)


def parse_action_packet(raw: str) -> ParsedActionPacket | None:
    text = _normalize_raw_packet(raw)
    if not text:
        return None

    match = _HEADER_RE.match(text)
    if match:
        try:
            option_id = int(match.group("option_id"))
        except (TypeError, ValueError):
            return None
        value = _clean_header_value(match.group("value") or "-")
        body = match.group("body")
        inline = match.group("inline") or ""
        free_text = body if body is not None and body.strip() else inline
        return ParsedActionPacket(option_id=option_id, value_text=value, text=_clean_body_text(free_text))

    match = _ACTION_LINE_RE.match(text)
    if match:
        try:
            option_id = int(match.group("option_id"))
        except (TypeError, ValueError):
            return None
        return ParsedActionPacket(
            option_id=option_id,
            value_text=_clean_header_value(match.group("value") or "-"),
            text=_clean_body_text(match.group("body") or ""),
        )

    # Recovery-friendly shorthand for the two-stage target menu requested by the UI: "66 1"
    # or "66 1\n台词". It only accepts bare numeric/Chinese-numeric headers, never natural prose.
    match = _BARE_HEADER_RE.match(text)
    if match:
        try:
            option_id = int(match.group("option_id"))
        except (TypeError, ValueError):
            return None
        return ParsedActionPacket(
            option_id=option_id,
            value_text=_clean_header_value(match.group("value") or "-"),
            text=_clean_body_text(match.group("body") or ""),
        )

    return None


def parse_action_choice(raw: str, options: list[ActionOption], *, agent: Agent | None = None) -> ParsedActionResult:
    packet = parse_action_packet(raw)
    if packet is None:
        return ParsedActionResult(None, "Model did not return an AOHP v2 action header, such as [03] or [08:8].")
    by_id = {option.option_id: option for option in options}
    option = by_id.get(packet.option_id)
    if option is None:
        return ParsedActionResult(None, f"Action option {packet.option_id} is not in this turn menu.", packet=packet)

    params = dict(option.params)
    if option.target_choices:
        target_index = _parse_target_index(packet.value_text)
        if target_index is None:
            if len(option.target_choices) == 1:
                target_index = int(option.target_choices[0].get("id") or 1)
            else:
                first = option.target_choices[0].get("id") if option.target_choices else 1
                return ParsedActionResult(None, f"Action {option.option_id:02d} needs a target number in the first line, for example [{option.option_id:02d}:{first}].", packet=packet, option=option)
        target_choice = next((choice for choice in option.target_choices if int(choice.get("id") or -1) == target_index), None)
        if target_choice is None:
            valid_ids = ",".join(str(choice.get("id")) for choice in option.target_choices[:24])
            return ParsedActionResult(None, f"Action {option.option_id:02d} target {target_index} is not in this option's target list. Use one of: {valid_ids}.", packet=packet, option=option)
        choice_params = target_choice.get("params") or {}
        if isinstance(choice_params, dict):
            params.update(choice_params)
    elif option.value_slot:
        value = _parse_numeric_value(packet.value_text, option.default_value)
        if value is None:
            return ParsedActionResult(None, f"Action {option.option_id:02d} needs a numeric value in the first line, for example [{option.option_id:02d}:8].", packet=packet, option=option)
        if option.min_value is not None:
            value = max(option.min_value, float(value))
        if option.max_value is not None:
            value = min(option.max_value, float(value))
        if option.value_slot == "sleep_hours":
            value = round(float(value) * 2) / 2
        elif isinstance(value, float) and float(value).is_integer():
            value = int(value)
        params[option.value_slot] = value

    clean_text = _clean_text(packet.text)
    if option.text_slot:
        if not clean_text:
            if option.text_required:
                return ParsedActionResult(None, f"Action {option.option_id:02d} needs body text from the second line onward.", packet=packet, option=option)
            clean_text = _default_text(option, agent)
        if option.text_slot == "content" and option.tool_name == "write_diary":
            params.setdefault("title", "今天的记录")
        params[option.text_slot] = clean_text
        if option.tone:
            params.setdefault("tone", option.tone)
        elif option.text_slot == "speech":
            params.setdefault("tone", _default_tone(option.tool_name))

    action = ActionChoice(tool_name=option.tool_name, params=params, plan_summary=option.label)
    return ParsedActionResult(action, None, packet=packet, option=option)


def _normalize_raw_packet(raw: str) -> str:
    text = str(raw or "").strip()
    text = text.replace("\ufeff", "")
    text = text.replace("｜", "|").replace("＠", "@")
    # Strip code fences while preserving body newlines.
    text = re.sub(r"^```(?:text)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _clean_header_value(value: str) -> str:
    text = str(value or "-").strip().replace("\u3000", " ")
    if not text:
        return "-"
    return text[:48]


def _clean_body_text(value: str) -> str:
    text = str(value or "")
    # Do not remove punctuation, @, |, commas, ellipses, or quotes from dialogue. The
    # first-line header has already been parsed, so the rest is authentic speech/body.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"^TEXT\s*[:=：]\s*", "", text.strip(), flags=re.IGNORECASE)
    text = _PROTOCOL_NOISE_LINE_RE.sub("", text)
    text = _PROTOCOL_NOISE_INLINE_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_text(value: str) -> str:
    text = str(value or "").strip()
    if text in {"", "-", "无", "不用", "不说", "none", "None", "null", "NULL"}:
        return ""
    # Keep the dialogue natural. Only trim outer whitespace and collapse excessive blank
    # lines that often come from model preambles.
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _parse_target_index(value_text: str) -> int | None:
    text = str(value_text or "").strip()
    if text in {"", "-", "无", "默认", "default", "none"}:
        return None
    if text in _CHINESE_NUMBERS and _CHINESE_NUMBERS[text] > 0:
        return int(_CHINESE_NUMBERS[text])
    if text.startswith("十") and len(text) == 2 and text[1] in _CHINESE_NUMBERS:
        return int(10 + _CHINESE_NUMBERS[text[1]])
    if len(text) >= 2 and text[0] in _CHINESE_NUMBERS and text[1] == "十":
        base = _CHINESE_NUMBERS[text[0]] * 10
        if len(text) == 2:
            return base
        if len(text) == 3 and text[2] in _CHINESE_NUMBERS:
            return base + _CHINESE_NUMBERS[text[2]]
    match = re.search(r"\d{1,3}", text)
    if not match:
        return None
    try:
        value = int(match.group(0))
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_numeric_value(value_text: str, default: float | int | str | None) -> float | None:
    text = str(value_text or "").strip()
    if text in {"", "-", "无", "默认", "default", "none"}:
        if default is None:
            return None
        try:
            return float(default)
        except (TypeError, ValueError):
            return None
    text = text.replace("小时", "").replace("hours", "").replace("hour", "").replace("元", "").replace("块", "").replace("￥", "").replace("amount", "").replace("份", "").strip()
    if text in _CHINESE_NUMBERS:
        return float(_CHINESE_NUMBERS[text])
    if text.startswith("十") and len(text) == 2 and text[1] in _CHINESE_NUMBERS:
        return float(10 + _CHINESE_NUMBERS[text[1]])
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _default_tone(tool_name: str) -> str:
    if "apologize" in tool_name or "decline" in tool_name or "boundary" in tool_name or "protest" in tool_name:
        return "calm"
    if "comfort" in tool_name or "thank" in tool_name or "hug" in tool_name or "mourn" in tool_name:
        return "warm"
    if "crime" in tool_name or "confront" in tool_name or "force" in tool_name:
        return "tense"
    return "neutral"


def _default_text(option: ActionOption, agent: Agent | None) -> str:
    name = agent.chosen_name if agent else "我"
    english = bool(agent and world_language(agent.world) == "en")
    if option.tool_name == "introduce_self" and agent:
        return f"Hi, my name is {name}." if english else f"你好，我叫{name}。"
    if option.tool_name == "refuse_introduction":
        return "Sorry, I don't want to share more right now." if english else "抱歉，我现在还不太想透露更多。"
    if option.tool_name == "mourn_visible_corpse":
        return "I don't know what to say. I just feel heavy inside." if english else "我不知道该说什么，只觉得心里很沉。"
    if option.text_slot == "content":
        return f"{name} carefully wrote this down." if english else f"{name}把这件事认真记了下来。"
    return "I want to do this." if english else "我想这样做。"


def ids_hint(options: list[ActionOption]) -> str:
    return ",".join(f"{option.option_id:02d}" for option in options[:160])


def packet_to_action_choice(packet: ParsedActionPacket, options: list[ActionOption], *, agent: Agent | None = None) -> ActionChoice | None:
    return parse_action_choice(_packet_to_raw_v2(packet), options, agent=agent).action


def _packet_to_raw_v2(packet: ParsedActionPacket) -> str:
    header = f"[{packet.option_id}:{packet.value_text}]" if packet.value_text and packet.value_text != "-" else f"[{packet.option_id}]"
    return f"{header}\n{packet.text}" if packet.text else header
