from __future__ import annotations

from copy import deepcopy

from app.content.worldview_runtime import worldview_locations, worldview_rule_parameters, worldview_ui_schema
from app.content.worldpacks import content_pack_errors, external_catalog, find_external_toolset, find_external_worldview
from app.content.toolsets import (
    AGENT_SPECIAL_TOOLSETS,
    FINANCE_INVESTING_TOOLSET_ID,
    REPRODUCTION_TOOLSET_ID,
    SURVIVAL_NEEDS_TOOLSET_ID,
)

FAST_MODERN_WORLDVIEW_ID = "fast_modern_worldview"
REALISTIC_SIM_WORLDVIEW_ID = "default_modern_worldview"
DEFAULT_WORLDVIEW_ID = FAST_MODERN_WORLDVIEW_ID
DEFAULT_CORE_TOOLSET_ID = "core_basic_toolset"
DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID = SURVIVAL_NEEDS_TOOLSET_ID
DEFAULT_REPRODUCTION_TOOLSET_ID = REPRODUCTION_TOOLSET_ID
DEFAULT_FINANCE_INVESTING_TOOLSET_ID = FINANCE_INVESTING_TOOLSET_ID
FAST_MODERN_WORLD_TOOLSET_ID = "fast_modern_world_toolset"
REALISTIC_SIM_WORLD_TOOLSET_ID = "default_modern_world_toolset"
LEGACY_DEFAULT_TOOLSET_ID = "default_modern_toolset"
DEFAULT_WORLD_TOOLSET_ID = FAST_MODERN_WORLD_TOOLSET_ID
DEFAULT_TOOLSET_ID = DEFAULT_WORLD_TOOLSET_ID
DEFAULT_OPTIONAL_TOOLSET_IDS = [DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID, DEFAULT_REPRODUCTION_TOOLSET_ID, DEFAULT_FINANCE_INVESTING_TOOLSET_ID]


def _modern_ui(worldview: dict, *, world_toolset_id: str) -> dict:
    return worldview_ui_schema(worldview, survival_enabled=True, finance_enabled=True, reproduction_enabled=False, world_toolset_id=world_toolset_id)


FAST_MODERN_WORLDVIEW = {
    "worldview_id": FAST_MODERN_WORLDVIEW_ID,
    "name": "快节奏现代世界观",
    "name_i18n": {"zh": "快节奏现代世界观", "en": "Fast-Paced Modern Worldview"},
    "version": "1.1.0",
    "packaged": True,
    "description": "默认推荐世界观。地点、关系、经济、住房和现代日常与真实模拟世界相同，但现实等待时间里的日期推进更快：非对话行动会推进更多世界时间，对话仍保持短耗时，工作被压缩到可玩的长度，关系变化更快；饥饿和口渴调成一天大致吃一次饭、喝一次水即可维持。适合实际游玩和观察互动，不会被一日三餐频繁打断。",
    "description_i18n": {"zh": "默认推荐世界观。地点、关系、经济、住房和现代日常与真实模拟世界相同，但现实等待时间里的日期推进更快：非对话行动会推进更多世界时间，对话仍保持短耗时，工作被压缩到可玩的长度，关系变化更快；饥饿和口渴调成一天大致吃一次饭、喝一次水即可维持。适合实际游玩和观察互动，不会被一日三餐频繁打断。", "en": "Recommended default worldview. It uses the same modern town, relationships, economy, housing, and daily life as the realistic simulation, but world days advance faster in real waiting time: non-dialogue actions advance more world time, dialogue remains short, work is compressed to a playable length, relationships progress faster, and hunger/thirst are tuned around roughly one meal and one drink per day."},
    "locations": worldview_locations(None),
    "rule_parameters": {
        **worldview_rule_parameters(None),
        "relationship": {
            "familiarity_multiplier": 2.0,
            "trust_multiplier": 1.6,
            "affection_positive_multiplier": 2.0,
            "affection_negative_multiplier": 1.5,
            "fear_multiplier": 1.2,
            "conflict_multiplier": 1.3,
        },
        "runtime": {"tool_time_scale": 2.0, "conversation_time_scale": 1.0, "dynamic_effect_scale": 1.5, "survival_cadence": "one_meal_one_drink_per_day"},
    },
    "time_model": {"start_minute": 8 * 60, "recommended_speed": "fast", "tool_time_scale": 2.0, "conversation_time_scale": 1.0},
    "default_create_settings": {"speed": "fast", "survival_difficulty": "NORMAL", "core_toolset_enabled": True, "core_toolset_id": DEFAULT_CORE_TOOLSET_ID, "optional_toolset_ids": DEFAULT_OPTIONAL_TOOLSET_IDS, "world_toolset_id": FAST_MODERN_WORLD_TOOLSET_ID},
    "ui": {},
    "status": "active",
}
FAST_MODERN_WORLDVIEW["ui"] = _modern_ui(FAST_MODERN_WORLDVIEW, world_toolset_id=FAST_MODERN_WORLD_TOOLSET_ID)

REALISTIC_SIM_WORLDVIEW = {
    "worldview_id": REALISTIC_SIM_WORLDVIEW_ID,
    "name": "真实模拟世界观",
    "name_i18n": {"zh": "真实模拟世界观", "en": "Realistic Simulation Worldview"},
    "version": "1.0.0",
    "packaged": True,
    "description": "原来的现代小镇社会模拟世界观，保留更真实、更琐碎的生存节奏：居民需要更频繁地吃饭、喝水、睡觉、清洁、赚钱和处理住房压力。它不再是默认选项，需要在创建世界时主动选择。",
    "description_i18n": {"zh": "原来的现代小镇社会模拟世界观，保留更真实、更琐碎的生存节奏：居民需要更频繁地吃饭、喝水、睡觉、清洁、赚钱和处理住房压力。它不再是默认选项，需要在创建世界时主动选择。", "en": "The original modern town social simulation worldview. It keeps a more realistic and more detailed survival rhythm: residents need to eat, drink, sleep, wash, earn money, and handle housing pressure more often. It is no longer the default option and must be selected explicitly when creating a world."},
    "locations": worldview_locations(None),
    "rule_parameters": worldview_rule_parameters(None),
    "time_model": {"start_minute": 8 * 60, "recommended_speed": "slow"},
    "default_create_settings": {"speed": "slow", "survival_difficulty": "NORMAL", "core_toolset_enabled": True, "core_toolset_id": DEFAULT_CORE_TOOLSET_ID, "optional_toolset_ids": DEFAULT_OPTIONAL_TOOLSET_IDS, "world_toolset_id": REALISTIC_SIM_WORLD_TOOLSET_ID},
    "ui": {},
    "status": "active",
}
REALISTIC_SIM_WORLDVIEW["ui"] = _modern_ui(REALISTIC_SIM_WORLDVIEW, world_toolset_id=REALISTIC_SIM_WORLD_TOOLSET_ID)
WORLDVIEWS = [FAST_MODERN_WORLDVIEW, REALISTIC_SIM_WORLDVIEW]

CORE_TOOLSETS = [{"toolset_id": DEFAULT_CORE_TOOLSET_ID, "name": "自带基础工具集", "name_i18n": {"zh": "自带基础工具集", "en": "Built-in Base Toolset"}, "version": "1.0.0", "packaged": True, "scope": "core", "default_enabled": True, "description": "独立于世界观的基础行动工具，例如观察、说话、移动、睡眠、赠送物品、记录记忆和基础求助。吃喝、补给与饥渴衰减由通用生存需求工具集控制。关闭后角色只会拿到世界工具集和必要兜底，可能连基本行动都做不到。", "description_i18n": {"zh": "独立于世界观的基础行动工具，例如观察、说话、移动、睡眠、赠送物品、记录记忆和基础求助。吃喝、补给与饥渴衰减由通用生存需求工具集控制。关闭后角色只会拿到世界工具集和必要兜底，可能连基本行动都做不到。", "en": "World-independent base action tools such as observing, speaking, moving, sleeping, gifting items, recording memories, and basic help. Eating, supplies, and hunger/thirst decay are controlled by the universal survival needs toolset. If disabled, residents only receive world tools and necessary fallbacks, and may lack basic actions."}, "status": "active"}]

OPTIONAL_TOOLSETS = [
    {"toolset_id": DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID, "name": "通用生存需求工具集", "name_i18n": {"zh": "通用生存需求工具集", "en": "Universal Survival Needs Toolset"}, "version": "1.0.0", "packaged": True, "scope": "optional", "default_enabled": True, "description": "控制饥饿、口渴及对应吃喝/补给/求助工具。关闭后居民不再因饥饿口渴衰减或死亡，适合不吃不喝的特殊世界观。", "description_i18n": {"zh": "控制饥饿、口渴及对应吃喝/补给/求助工具。关闭后居民不再因饥饿口渴衰减或死亡，适合不吃不喝的特殊世界观。", "en": "Controls hunger, thirst, and related eating/drinking/supply/help tools. If disabled, residents no longer decay or die from hunger or thirst, suitable for special worlds without eating or drinking."}, "status": "active"},
    {"toolset_id": DEFAULT_REPRODUCTION_TOOLSET_ID, "name": "通用生育与育儿工具集", "name_i18n": {"zh": "通用生育与育儿工具集", "en": "Universal Reproduction & Childcare Toolset"}, "version": "1.0.0", "packaged": True, "scope": "optional", "default_enabled": True, "description": "独立于具体世界观的可选生命延续模块，包含抽象成年亲密同意、怀孕/避孕/检测、出生、宝宝模型池、孩子成长与基础育儿工具。它不是基础行动能力，关闭后不会产生新生儿，也会隐藏宝宝模型配置。", "description_i18n": {"zh": "独立于具体世界观的可选生命延续模块，包含抽象成年亲密同意、怀孕/避孕/检测、出生、宝宝模型池、孩子成长与基础育儿工具。它不是基础行动能力，关闭后不会产生新生儿，也会隐藏宝宝模型配置。", "en": "Optional life-continuation module independent of specific worldviews. It includes abstract adult consent, pregnancy/contraception/testing, birth, baby model pools, child growth, and basic childcare tools. It is not a base action capability; disabling it prevents newborns and hides baby model configuration."}, "status": "active"},
    {"toolset_id": DEFAULT_FINANCE_INVESTING_TOOLSET_ID, "name": "通用金融投资工具集", "name_i18n": {"zh": "通用金融投资工具集", "en": "Universal Finance & Investing Toolset"}, "version": "1.0.0", "packaged": True, "scope": "optional", "default_enabled": True, "description": "控制游戏内虚构证券账户、股票行情、买卖、保证金、做空与市场新闻。关闭后仍保留普通经济/住房/工作，但不会暴露股票投资工具。", "description_i18n": {"zh": "控制游戏内虚构证券账户、股票行情、买卖、保证金、做空与市场新闻。关闭后仍保留普通经济/住房/工作，但不会暴露股票投资工具。", "en": "Controls fictional in-game brokerage accounts, stock quotes, trading, margin, short selling, and market news. If disabled, ordinary economy, housing, and work remain, but stock investing tools are hidden."}, "status": "active"},
]

WORLD_TOOLSETS = [
    {"toolset_id": FAST_MODERN_WORLD_TOOLSET_ID, "name": "快节奏现代世界工具集", "name_i18n": {"zh": "快节奏现代世界工具集", "en": "Fast-Paced Modern World Toolset"}, "version": "1.1.0", "packaged": True, "scope": "world", "worldview_id": FAST_MODERN_WORLDVIEW_ID, "description": "默认快节奏现代世界观专用工具集。继承现代小镇里的公共地点、工作、住房、普通消费、犯罪、租房、死亡后遗体持续存在、腐败暴露与本世界特有设施；具体节奏由快节奏世界观的规则参数控制。", "description_i18n": {"zh": "默认快节奏现代世界观专用工具集。继承现代小镇里的公共地点、工作、住房、普通消费、犯罪、租房、死亡后遗体持续存在、腐败暴露与本世界特有设施；具体节奏由快节奏世界观的规则参数控制。", "en": "World-specific toolset for the fast-paced modern worldview. It inherits modern town locations, work, housing, normal consumption, crime, renting, persistent bodies after death, decay exposure, and local facilities; pacing is controlled by the fast worldview rule parameters."}, "status": "active"},
    {"toolset_id": REALISTIC_SIM_WORLD_TOOLSET_ID, "legacy_toolset_ids": [LEGACY_DEFAULT_TOOLSET_ID], "name": "真实模拟世界工具集", "name_i18n": {"zh": "真实模拟世界工具集", "en": "Realistic Simulation World Toolset"}, "version": "1.0.0", "packaged": True, "scope": "world", "worldview_id": REALISTIC_SIM_WORLDVIEW_ID, "description": "真实模拟世界观专用工具集，覆盖现代小镇里的公共地点、工作、住房、普通消费、犯罪、租房、死亡后遗体持续存在、腐败暴露与本世界特有设施。股票投资已拆到通用金融投资工具集，饥饿口渴已拆到通用生存需求工具集。古代、未来或特殊世界观应替换成自己的世界工具集。", "description_i18n": {"zh": "真实模拟世界观专用工具集，覆盖现代小镇里的公共地点、工作、住房、普通消费、犯罪、租房、死亡后遗体持续存在、腐败暴露与本世界特有设施。股票投资已拆到通用金融投资工具集，饥饿口渴已拆到通用生存需求工具集。古代、未来或特殊世界观应替换成自己的世界工具集。", "en": "World-specific toolset for the realistic simulation worldview. It covers modern town public locations, work, housing, consumption, crime, rent, persistent bodies after death, decay exposure, and local facilities. Stock investing and survival needs are split into optional universal toolsets."}, "status": "active"},
]

PLACEHOLDER_INTERFACES = [
    {"interface_id": "worldview_import", "name": "世界观导入", "status": "active", "description": "已支持导入 .aiworld.json/.json/.zip 世界包，导入后会进入世界观下拉列表，并可把默认开关、地点、物品、私宅模板写入新世界。"},
    {"interface_id": "toolset_import", "name": "声明式工具集导入", "status": "active", "description": "已支持世界包内的声明式工具集，工具会注册到后端工具表，并通过地点、目标、资源、等级、flag 等条件过滤。"},
    {"interface_id": "optional_toolset_import", "name": "通用工具集导入", "status": "partial", "description": "世界包格式已支持 scope=optional/core/agent_special/npc；当前最完整的是 world scope。可选/特殊工具集会进入目录，但复杂运行时仍建议先用声明式效果。"},
    {"interface_id": "agent_special_toolset_import", "name": "特殊工具集导入", "status": "placeholder", "description": "后续用于导入可分配给单个 agent 的特殊工具集，让不同居民拥有不同可用工具，目前内置若干特殊工具集可勾选。"},
    {"interface_id": "plugin_import", "name": "插件导入", "status": "active", "description": "已支持从本地文件或 GitHub/URL 安装插件包到本地 worldpacks/imported，并刷新世界观、工具集和工具目录。"},
    {"interface_id": "agent_tts", "name": "Agent TTS 接口", "status": "active", "description": "已支持给单个 agent 保存本地或云端 TTS 配置，事件流播放，并可在聊天归档中可选导出已缓存音频。"},
    {"interface_id": "identity_model_history", "name": "历史身份与模型库", "status": "active", "description": "已支持从本地存档提取历史 agent 身份、头像、提示词、模型、工具与 TTS 配置，并应用到新世界的 agent 槽位。"},
]


def _catalog_sections() -> dict:
    external = external_catalog()
    agent_special_toolsets = [{"version": "1.0.0", "packaged": True, "scope": "agent_special", "default_enabled": True, "status": "active", **deepcopy(toolset)} for toolset in AGENT_SPECIAL_TOOLSETS]
    world_toolsets = deepcopy(WORLD_TOOLSETS) + deepcopy(external["world_toolsets"])
    return {"worldviews": deepcopy(WORLDVIEWS) + deepcopy(external["worldviews"]), "core_toolsets": deepcopy(CORE_TOOLSETS) + deepcopy(external["core_toolsets"]), "optional_toolsets": deepcopy(OPTIONAL_TOOLSETS) + deepcopy(external["optional_toolsets"]), "agent_special_toolsets": agent_special_toolsets + deepcopy(external["agent_special_toolsets"]), "world_toolsets": world_toolsets, "toolsets": world_toolsets, "placeholder_interfaces": deepcopy(PLACEHOLDER_INTERFACES), "content_pack_errors": content_pack_errors()}


def preset_catalog() -> dict:
    return _catalog_sections()


def worldview_by_id(worldview_id: str | None) -> dict:
    for worldview in WORLDVIEWS:
        if worldview["worldview_id"] == worldview_id:
            return deepcopy(worldview)
    external = find_external_worldview(worldview_id)
    if external:
        return deepcopy(external)
    return deepcopy(WORLDVIEWS[0])


def core_toolset_by_id(toolset_id: str | None) -> dict:
    for toolset in CORE_TOOLSETS:
        if toolset["toolset_id"] == toolset_id:
            return deepcopy(toolset)
    external = find_external_toolset(toolset_id)
    if external and external.get("scope") == "core":
        return deepcopy(external)
    return deepcopy(CORE_TOOLSETS[0])


def optional_toolsets_by_ids(toolset_ids: list[str] | None) -> list[dict]:
    requested = set(toolset_ids or [])
    builtins = [deepcopy(toolset) for toolset in OPTIONAL_TOOLSETS if toolset["toolset_id"] in requested]
    external = external_catalog()
    builtins.extend(deepcopy(toolset) for toolset in external["optional_toolsets"] if toolset["toolset_id"] in requested)
    return builtins


def world_toolset_by_id(toolset_id: str | None) -> dict:
    for toolset in WORLD_TOOLSETS:
        aliases = set(toolset.get("legacy_toolset_ids") or [])
        if toolset["toolset_id"] == toolset_id or toolset_id in aliases:
            return deepcopy(toolset)
    external = find_external_toolset(toolset_id)
    if external and external.get("scope", "world") in {"world", "npc"}:
        return deepcopy(external)
    return deepcopy(WORLD_TOOLSETS[0])


def toolset_by_id(toolset_id: str | None) -> dict:
    return world_toolset_by_id(toolset_id)
