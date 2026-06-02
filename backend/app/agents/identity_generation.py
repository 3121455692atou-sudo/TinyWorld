from __future__ import annotations

import random
import re
import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.state import initial_dynamic_state
from app.agents.traits import normalize_traits, normalize_traits_to_budget, random_traits_with_budget
from app.agents.v5_state import default_desires, default_family, default_law, default_morality, default_tool_learning, default_trauma, default_wallet, default_work
from app.content.toolsets import DEFAULT_AGENT_SPECIAL_TOOLSET_IDS
from app.llm.schemas import TRAIT_NAMES
from app.llm.text_protocols import identity_protocol_system, identity_protocol_user_suffix, parse_identity_draft
from app.core.config import settings
from app.core.models import Agent, AgentLocation, AgentTrait, Inventory, Item, World
from app.llm.openai_compatible import provider
from app.llm.language import identity_language_instruction, normalize_language
from app.llm.runtime import llm_runtime_kwargs, normalize_llm_runtime
from app.llm.schemas import IdentityDraft


FALLBACK_NAMES = [
    "岑安",
    "林栖",
    "沈灯",
    "白砚",
    "顾晴",
    "许澈",
    "南枝",
    "叶微",
    "陶望",
    "温棠",
    "青禾",
    "陆弦",
]

FALLBACK_COLORS = ["#4f7cac", "#b4656f", "#5d8a66", "#c0812d", "#7b68a6", "#2f7f7f"]


def _identity_prompt(seed: int, taken_names: Iterable[str], *, language: str = "zh") -> tuple[str, str]:
    taken_hint = "、".join(taken_names) or "暂无"
    system = identity_protocol_system(child=False, language=language) + "你不知道未来世界里还有谁。不要使用真实公众人物姓名。"
    if normalize_language(language) == "en":
        taken_hint = ", ".join(taken_names) or "none"
        system = identity_protocol_system(child=False, language=language) + " You do not know who else will exist in the future world. Do not use real public figure names."
    user = f"""
世界基调: 温和生存、社交、玩乐、可能死亡。你需要照顾身体需求，也可以认识他人。
随机种子: {seed}
已经不可用的姓名: {taken_hint}
姓名使用中文或中文风格昵称，最多 12 个字符。LOOK_FULL 80 到 800 字。
输出语言: {identity_language_instruction(language)}
TRAITS 必须包含 openness,caution,sociability,empathy,curiosity,discipline,aggression,honesty,creativity,neuroticism，值 0 到 100。
不要默认成为温柔外向的人，请让气质有差异。
{identity_protocol_user_suffix(language)}
"""
    if normalize_language(language) == "en":
        user = f"""
World tone: gentle survival, social life, play, and possible death. You need to care for bodily needs and may meet others.
Random seed: {seed}
Unavailable names: {taken_hint}
Use an English name or nickname, at most 24 characters. LOOK_FULL should be 80 to 800 English words or characters.
Output language: {identity_language_instruction(language)}
TRAITS must include openness,caution,sociability,empathy,curiosity,discipline,aggression,honesty,creativity,neuroticism with values from 0 to 100.
Do not default to a gentle extrovert; make the temperament distinct.
{identity_protocol_user_suffix(language)}
"""
    return system, user


def _fallback_identity(index: int, seed: int, taken_names: set[str]) -> IdentityDraft:
    rng = random.Random(seed)
    name = next((n for n in FALLBACK_NAMES[index:] + FALLBACK_NAMES[:index] if n not in taken_names), f"旅人{index + 1}")
    policy = rng.choice(["open", "selective", "secretive"])
    expression = rng.choice(["中性而清爽", "温柔女性化", "利落男性化", "难以判断", "安静朴素"])
    color = FALLBACK_COLORS[index % len(FALLBACK_COLORS)]
    traits = {
        "openness": rng.randint(30, 85),
        "caution": rng.randint(15, 85),
        "sociability": rng.randint(25, 90),
        "empathy": rng.randint(25, 90),
        "curiosity": rng.randint(25, 90),
        "discipline": rng.randint(20, 90),
        "aggression": rng.randint(0, 55),
        "honesty": rng.randint(35, 95),
        "creativity": rng.randint(25, 95),
        "neuroticism": rng.randint(10, 80),
    }
    short = rng.choice(
        [
            "短发、灰蓝外套、背着旧布包",
            "白发、红围巾、眼神很亮",
            "戴圆眼镜、深色斗篷、动作轻",
            "扎低马尾、棕色围裙、掌心有墨迹",
            "银色短发、旧靴子、袖口别着羽毛",
        ]
    )
    return IdentityDraft(
        chosen_name=name,
        gender_identity=rng.choice(["女", "男", "非二元", "不愿公开"]),
        gender_custom_text="",
        gender_publicity=rng.choice([True, True, False]),
        gender_expression=expression,
        appearance_full=f"{name}看起来{expression}，{short}。这个人站姿不算张扬，却会细细打量周围的路、桌椅和陌生面孔，像是在给每个可记住的细节留位置。衣物实用但有一两个个人化的小装饰。",
        appearance_short=short,
        avatar_hint={"color": color, "tags": short.split("、")[:2]},
        speaking_style=rng.choice(["慢条斯理，句子简短", "坦率直接，偶尔自嘲", "温和谨慎，常先观察", "有点跳跃，喜欢用比喻"]),
        personality_seed="我想在这个小世界里找到稳定的生活节奏，也想确认哪些陌生人值得靠近。",
        initial_goal=rng.choice(["先熟悉地图并找到可靠的水和食物。", "认识几个可信的人，再决定长期计划。", "记录每天发生的事，慢慢理解这个世界。"]),
        intro_policy=policy,
        trait_sliders=traits,
    )


def _fallback_identity_en(index: int, seed: int, taken_names: set[str]) -> IdentityDraft:
    rng = random.Random(seed)
    names = ["Avery", "Rowan", "Mira", "Theo", "Iris", "Noah", "Clara", "Eden", "Morgan", "Lena", "Kai", "June"]
    name = next((n for n in names[index:] + names[:index] if n not in taken_names), f"Resident {index + 1}")
    policy = rng.choice(["open", "selective", "secretive"])
    expression = rng.choice(["androgynous and neat", "softly feminine", "clean-cut masculine", "hard to read", "quiet and plain"])
    color = FALLBACK_COLORS[index % len(FALLBACK_COLORS)]
    short = rng.choice([
        "short hair, a gray-blue jacket, an old cloth bag",
        "pale hair, a red scarf, bright eyes",
        "round glasses, a dark coat, careful movements",
        "a low ponytail, a brown apron, ink on the palms",
        "silver cropped hair, old boots, a feather at the cuff",
    ])
    traits = {
        "openness": rng.randint(30, 85),
        "caution": rng.randint(15, 85),
        "sociability": rng.randint(25, 90),
        "empathy": rng.randint(25, 90),
        "curiosity": rng.randint(25, 90),
        "discipline": rng.randint(20, 90),
        "aggression": rng.randint(0, 55),
        "honesty": rng.randint(35, 95),
        "creativity": rng.randint(25, 95),
        "neuroticism": rng.randint(10, 80),
    }
    return IdentityDraft(
        chosen_name=name,
        gender_identity=rng.choice(["女", "男", "非二元", "不愿公开"]),
        gender_custom_text="",
        gender_publicity=rng.choice([True, True, False]),
        gender_expression=expression,
        appearance_full=f"{name} looks {expression}, with {short}. Their posture is not showy, but they quietly study paths, furniture, and unfamiliar faces, as if saving every useful detail.",
        appearance_short=short,
        avatar_hint={"color": color, "tags": short.split(", ")[:2]},
        speaking_style=rng.choice(["slow and brief", "direct, sometimes self-mocking", "warm but cautious", "slightly wandering and metaphorical"]),
        personality_seed="I want to find a stable rhythm in this small world, and learn which strangers are worth trusting.",
        initial_goal=rng.choice(["Learn the map and find reliable food and water.", "Meet a few trustworthy people before making long-term plans.", "Record what happens each day and slowly understand this world."]),
        intro_policy=policy,
        trait_sliders=traits,
    )


def _configured_identity(
    *,
    preset_name: str,
    preset_appearance: str,
    custom_system_prompt: str | None,
    user_trait_sliders: dict[str, int] | None,
) -> IdentityDraft:
    appearance = _compact_text(preset_appearance)[:4000]
    if len(appearance) < 20:
        appearance = f"{preset_name}的外貌由用户指定: {appearance}"
    short = _appearance_short(appearance)
    prompt_text = custom_system_prompt or ""
    return IdentityDraft(
        chosen_name=preset_name[:12],
        gender_identity=_infer_gender_identity(f"{preset_name}\n{appearance}\n{prompt_text}"),
        gender_custom_text="",
        gender_publicity=True,
        gender_expression=_infer_gender_expression(appearance),
        appearance_full=appearance,
        appearance_short=short,
        avatar_hint={
            "color": "#607d8b",
            "tags": [part.strip() for part in appearance.replace("，", "、").replace("；", "、").split("、") if part.strip()][:3],
            "identity_source": "user_config",
        },
        speaking_style=_extract_speaking_style(prompt_text),
        personality_seed=_personality_seed(prompt_text),
        initial_goal="先照顾自己的生活需求，并按已有身份与他人自然互动。",
        intro_policy="selective",
        trait_sliders=_configured_traits(user_trait_sliders),
    )


def _configured_traits(user_trait_sliders: dict[str, int] | None) -> dict[str, int]:
    return {name: int((user_trait_sliders or {}).get(name, 50)) for name in TRAIT_NAMES}


def _compact_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _appearance_short(appearance: str) -> str:
    text = re.split(r"[。\n]", appearance, maxsplit=1)[0]
    if len(text) < 8:
        text = appearance
    return text[:120] if len(text) >= 8 else f"外貌由用户指定: {text}"[:120]


def _infer_gender_identity(text: str) -> str:
    if re.search(r"她|少女|女子|女性|女学生|女孩", text):
        return "女"
    if re.search(r"少年|男性|男学生|男孩", text):
        return "男"
    return "不愿公开"


def _infer_gender_expression(appearance: str) -> str:
    if "中性" in appearance:
        return "中性"
    if any(word in appearance for word in ["少女", "女性", "女学生", "裙", "双马尾"]):
        return "女性化"
    if any(word in appearance for word in ["少年", "男性", "男学生"]):
        return "男性化"
    return "按用户外貌设定"


def _extract_speaking_style(prompt: str) -> str:
    if not prompt.strip():
        return "遵循用户提供的角色说话习惯。"
    match = re.search(r"(?:说话习惯|语言风格)[：:]\s*(.*?)(?=\n\S{1,24}[：:]|\n【|$)", prompt, re.S)
    if match:
        text = _compact_text(re.sub(r"^\s*[-•]\s*", "", match.group(1), flags=re.M))
        if text:
            return text[:120]
    return "遵循用户提供的角色说话习惯。"


def _personality_seed(prompt: str) -> str:
    text = _compact_text(prompt)
    if not text:
        return "遵循用户给定角色设定，在小世界中自主生活并维持角色一致性。"
    if len(text) < 10:
        return f"{text} 在小世界中自主生活并维持角色一致性。"
    return text[:160]


def validate_unique_name(session: Session, world_id: str, name: str) -> bool:
    existing = session.execute(
        select(Agent).where(Agent.world_id == world_id, Agent.chosen_name == name)
    ).scalar_one_or_none()
    return existing is None


async def prepare_identity_draft(
    *,
    world_id: str,
    world_seed: int,
    index: int,
    taken_names: Iterable[str],
    model_alias: str,
    model_name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    llm_retry_count: int = 2,
    llm_retry_interval_ms: int = 1500,
    llm_rpm: int = 0,
    language: str = "zh",
    custom_system_prompt: str | None = None,
    collective_core_prompt: str | None = None,
    preset_name: str | None = None,
    preset_appearance: str | None = None,
    avatar_data_url: str | None = None,
    user_trait_sliders: dict[str, int] | None = None,
) -> IdentityDraft:
    seed = world_seed + index * 9973
    unavailable_names = {name for name in taken_names if name}
    draft: IdentityDraft | None
    has_configured_identity = bool((preset_name or "").strip() and (preset_appearance or "").strip())
    if has_configured_identity:
        draft = _configured_identity(
            preset_name=(preset_name or "").strip(),
            preset_appearance=(preset_appearance or "").strip(),
            custom_system_prompt=custom_system_prompt,
            user_trait_sliders=user_trait_sliders,
        )
    else:
        draft = None
        system, user = _identity_prompt(seed, unavailable_names, language=language)
        if preset_name:
            user += (f"\nThe user has assigned your name: {preset_name}. NAME must use this exact name.\n" if normalize_language(language) == "en" else f"\n用户已经为你指定姓名: {preset_name}。chosen_name 必须使用这个名字，不要改名。\n")
        if preset_appearance:
            user += (f"\nThe user has assigned your appearance direction: {preset_appearance}. LOOK_FULL and LOOK_SHORT must respect it.\n" if normalize_language(language) == "en" else f"\n用户已经为你指定外貌方向: {preset_appearance}。appearance_full 和 appearance_short 必须尊重这个外貌。\n")
        if custom_system_prompt:
            user += (f"\nLong-term system prompt from the user: {custom_system_prompt}\n" if normalize_language(language) == "en" else f"\n用户给你的长期系统提示词: {custom_system_prompt}\n")
        if collective_core_prompt:
            user += (f"\nCollective core prompt shared by all residents and applied before each action prompt: {collective_core_prompt}\n" if normalize_language(language) == "en" else f"\n所有居民共享的集体核心提示词，会在你的每次行动提示词最前面生效: {collective_core_prompt}\n")
        result = await provider.complete_text(
            model_alias=model_alias,
            system_prompt=system,
            user_prompt=user,
            temperature=0.9,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            **llm_runtime_kwargs(
                normalize_llm_runtime(
                    None,
                    retry_count=llm_retry_count,
                    retry_interval_ms=llm_retry_interval_ms,
                    rpm=llm_rpm,
                )
            ),
        )
        parsed_draft = parse_identity_draft(result.raw_text, forced_name=preset_name.strip() if preset_name else None, child=False)
        if parsed_draft and parsed_draft.chosen_name not in unavailable_names:
            draft = parsed_draft
    if draft is None:
        draft = _fallback_identity_en(index, seed, unavailable_names) if normalize_language(language) == "en" else _fallback_identity(index, seed, unavailable_names)
    if draft.chosen_name in unavailable_names:
        draft = draft.model_copy(update={"chosen_name": _unique_name(draft.chosen_name, index, unavailable_names)})
    if preset_name and not has_configured_identity:
        draft = draft.model_copy(update={"chosen_name": preset_name[:12]})
    if preset_appearance and not has_configured_identity:
        short = preset_appearance[:120]
        full = preset_appearance if len(preset_appearance) >= 20 else f"{preset_name or draft.chosen_name}的外貌由用户指定: {preset_appearance}"
        avatar_hint = {
            **(draft.avatar_hint or {}),
            "tags": [part.strip() for part in preset_appearance.replace("，", "、").split("、") if part.strip()][:3],
        }
        draft = draft.model_copy(update={"appearance_short": short, "appearance_full": full[:4000], "avatar_hint": avatar_hint})
    if avatar_data_url:
        avatar_hint = dict(draft.avatar_hint or {})
        avatar_hint["image_data_url"] = avatar_data_url
        draft = draft.model_copy(update={"avatar_hint": avatar_hint})
    return draft


def _unique_name(name: str, index: int, taken_names: set[str]) -> str:
    base = (name or f"旅人{index + 1}").strip()[:10] or f"旅人{index + 1}"
    for offset in range(0, 1000):
        suffix = str(index + 1 + offset)
        candidate = f"{base}{suffix}"[:12]
        if candidate not in taken_names:
            return candidate
    return f"旅人{uuid.uuid4().hex[:8]}"


async def create_agent_with_identity(
    session: Session,
    world: World,
    *,
    index: int,
    model_alias: str,
    initial_location_id: str,
    provider_name: str | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    llm_retry_count: int = 2,
    llm_retry_interval_ms: int = 1500,
    llm_rpm: int = 0,
    language: str = "zh",
    custom_system_prompt: str | None = None,
    collective_core_prompt: str | None = None,
    preset_name: str | None = None,
    preset_appearance: str | None = None,
    avatar_data_url: str | None = None,
    trait_mode: str = "agent",
    trait_budget: int = 500,
    user_trait_sliders: dict[str, int] | None = None,
    tool_context_mode: str = "dynamic",
    agent_toolset_ids: list[str] | None = None,
    prepared_identity: IdentityDraft | None = None,
) -> Agent:
    agent_id = f"agent_{uuid.uuid4().hex[:12]}"
    seed = world.seed + index * 9973
    taken_names = {
        name
        for (name,) in session.execute(
            select(Agent.chosen_name).where(Agent.world_id == world.world_id, Agent.chosen_name.is_not(None))
        )
        if name
    }
    draft = prepared_identity
    if draft is None:
        draft = await prepare_identity_draft(
            world_id=world.world_id,
            world_seed=world.seed,
            index=index,
            taken_names=taken_names,
            model_alias=model_alias,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            llm_retry_count=llm_retry_count,
            llm_retry_interval_ms=llm_retry_interval_ms,
            llm_rpm=llm_rpm,
            language=language,
            custom_system_prompt=custom_system_prompt,
            collective_core_prompt=collective_core_prompt,
            preset_name=preset_name,
            preset_appearance=preset_appearance,
            avatar_data_url=avatar_data_url,
            user_trait_sliders=user_trait_sliders,
        )
    if draft.chosen_name in taken_names:
        draft = draft.model_copy(update={"chosen_name": _unique_name(draft.chosen_name, index, taken_names)})

    if trait_mode == "player" and user_trait_sliders:
        traits = {name: max(0, int(user_trait_sliders.get(name, 0))) for name in TRAIT_NAMES}
    elif trait_mode == "random":
        traits = random_traits_with_budget(seed, trait_budget)
    elif trait_mode == "agent":
        traits = normalize_traits_to_budget(draft.trait_sliders, seed, trait_budget)
    else:
        traits = normalize_traits(draft.trait_sliders, seed)
    tool_learning = default_tool_learning()
    tool_learning["tool_context_mode"] = tool_context_mode if tool_context_mode in {"dynamic", "all"} else "dynamic"
    tool_learning["agent_toolset_ids"] = list(agent_toolset_ids) if agent_toolset_ids is not None else list(DEFAULT_AGENT_SPECIAL_TOOLSET_IDS)
    tool_learning["llm_runtime"] = normalize_llm_runtime(
        None,
        retry_count=llm_retry_count,
        retry_interval_ms=llm_retry_interval_ms,
        rpm=llm_rpm,
    )
    agent = Agent(
        agent_id=agent_id,
        world_id=world.world_id,
        lifecycle_state="alive",
        model_alias=model_alias,
        model_provider_name=provider_name,
        model_name=model_name,
        llm_base_url=base_url,
        llm_api_key=api_key,
        custom_system_prompt=custom_system_prompt,
        user_configured_name=bool(preset_name),
        chosen_name=draft.chosen_name,
        gender_identity=draft.gender_identity,
        gender_custom_text=draft.gender_custom_text,
        gender_publicity=draft.gender_publicity,
        gender_expression=draft.gender_expression,
        age_stage="adult",
        appearance_full=draft.appearance_full,
        appearance_short=draft.appearance_short,
        avatar_hint_json=draft.avatar_hint,
        speaking_style=draft.speaking_style,
        personality_seed=draft.personality_seed,
        initial_goal=draft.initial_goal,
        intro_policy=draft.intro_policy,
        wallet_json={**default_wallet(), "housing": {"home_location_id": initial_location_id}},
        work_json=default_work(),
        family_json=default_family(),
        law_json=default_law(),
        trauma_json=default_trauma(),
        desires_json=default_desires(),
        morality_json=default_morality(),
        tool_learning_json=tool_learning,
        created_at_world_time=world.current_world_time_minutes,
    )
    session.add(agent)
    session.flush()
    session.add(AgentTrait(agent_id=agent_id, **traits))
    session.add(initial_dynamic_state(agent_id, world.current_world_time_minutes))
    session.add(AgentLocation(agent_id=agent_id, location_id=initial_location_id, arrived_at_world_time=world.current_world_time_minutes))
    for name, description, item_type, quantity in [
        ("便携食物", "开局时准备的一份便携食物。", "food", 1),
        ("瓶装水", "开局时准备的一瓶水。", "water", 1),
    ]:
        item = Item(item_id=f"item_{uuid.uuid4().hex[:12]}", world_id=world.world_id, name=name, description=description, item_type=item_type)
        session.add(item)
        session.flush()
        session.add(Inventory(agent_id=agent_id, item_id=item.item_id, quantity=quantity))
    return agent


def choose_model_alias(index: int) -> str:
    return "world_agent_pro" if index % 4 == 3 else "world_agent"
