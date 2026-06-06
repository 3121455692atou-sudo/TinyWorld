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
SWEET_ROMANCE_WORLDVIEW_ID = "sweet_romance_worldview"
PURE_EMOTION_WORLDVIEW_ID = "pure_emotion_worldview"
WEREWOLF_WORLDVIEW_ID = "werewolf_game_worldview"
SWEET_ROMANCE_WORLD_TOOLSET_ID = "sweet_romance_world_toolset"
PURE_EMOTION_WORLD_TOOLSET_ID = "pure_emotion_world_toolset"
WEREWOLF_WORLD_TOOLSET_ID = "werewolf_game_world_toolset"
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

def _romance_locations() -> list[dict]:
    return [
        {"location_id": "heart_plaza", "name": "心动广场", "description": "柔和灯串和花藤围成的开放广场，适合初遇、聊天和发起约会。", "neighbors": ["dessert_cafe", "confession_bridge", "starlight_garden", "family_nest"], "available_tools": ["look_around", "speak_to_nearby", "play_simple_game", "work_shift_cleaner"], "tags": ["social", "romance", "open_view", "work"], "visibility_radius": 1},
        {"location_id": "dessert_cafe", "name": "甜点咖啡馆", "description": "摆满小蛋糕和热饮的明亮咖啡馆，大家不用为吃喝生存焦虑，只把它当作约会和闲聊场所。", "neighbors": ["heart_plaza", "photo_studio"], "available_tools": ["speak_to_nearby", "play_simple_game", "compliment_visible_agent", "work_shift_cleaner"], "tags": ["social", "fun", "romance", "work"], "visibility_radius": 1},
        {"location_id": "confession_bridge", "name": "告白桥", "description": "桥下是缓慢流动的浅水，适合坦白心情、牵手、确认关系。", "neighbors": ["heart_plaza", "starlight_garden"], "available_tools": ["speak_to_nearby", "walk_by_lake", "express_affection_visible_agent", "work_shift_cleaner"], "tags": ["romance", "quiet", "water", "work"], "visibility_radius": 1},
        {"location_id": "starlight_garden", "name": "星光花园", "description": "四季开花的花园，天空总是明亮温柔，适合散步、约会和轻松活动。", "neighbors": ["heart_plaza", "confession_bridge", "nursery"], "available_tools": ["play_simple_game", "walk_by_lake", "tell_story_nearby", "work_shift_cleaner"], "tags": ["nature", "fun", "romance", "work"], "visibility_radius": 1},
        {"location_id": "family_nest", "name": "家庭暖巢", "description": "为伴侣和新生命准备的柔软居所，照护工具更容易被想到。", "neighbors": ["heart_plaza", "nursery"], "available_tools": ["rest", "write_diary", "care_for_child_visible_agent", "feed_child_visible_agent", "soothe_child_visible_agent", "check_child_status_visible_agent", "carry_child_visible_agent", "put_child_to_sleep_visible_agent", "work_shift_cleaner"], "tags": ["home", "family", "romance", "quiet", "work"], "visibility_radius": 0},
        {"location_id": "nursery", "name": "育儿房", "description": "铺着软垫和玩具的育儿空间，用于照看新生儿、幼儿和孩子。", "neighbors": ["family_nest", "starlight_garden"], "available_tools": ["check_child_status_visible_agent", "soothe_child_visible_agent", "feed_child_visible_agent", "carry_child_visible_agent", "put_child_to_sleep_visible_agent", "care_for_child_visible_agent", "teach_child_simple_skill_visible_agent", "work_shift_cleaner"], "tags": ["family", "childcare", "quiet", "work"], "visibility_radius": 0},
        {"location_id": "photo_studio", "name": "纪念照相馆", "description": "适合留下关系纪念、写信和整理回忆的场所。", "neighbors": ["dessert_cafe"], "available_tools": ["write_diary", "add_memory", "send_private_letter_by_name", "work_shift_cleaner"], "tags": ["memory", "creative", "romance", "work"], "visibility_radius": 0},
    ]


def _pure_emotion_locations() -> list[dict]:
    return [
        {"location_id": "feeling_lounge", "name": "情绪客厅", "description": "没有饥饿、衰老和疾病压力的情感空间，居民主要表达心情、靠近或保持距离。", "neighbors": ["memory_atelier", "promise_garden", "quiet_cloud_room"], "available_tools": ["speak_to_nearby", "discuss_feelings_visible_agent", "comfort_visible_agent", "work_shift_cleaner"], "tags": ["social", "emotion", "quiet", "work"], "visibility_radius": 1},
        {"location_id": "promise_garden", "name": "约定花园", "description": "适合许下约定、确认关系和修复误会的花园。", "neighbors": ["feeling_lounge", "heart_lake", "family_cradle"], "available_tools": ["express_affection_visible_agent", "confess_feelings_visible_agent", "define_relationship_visible_agent", "repair_relationship_visible_agent", "work_shift_cleaner"], "tags": ["romance", "emotion", "nature", "work"], "visibility_radius": 1},
        {"location_id": "heart_lake", "name": "心湖", "description": "湖面会映出居民此刻的心绪，适合独处、散步和对话。", "neighbors": ["promise_garden", "quiet_cloud_room"], "available_tools": ["walk_by_lake", "review_recent_memory", "speak_to_nearby", "work_shift_cleaner"], "tags": ["quiet", "emotion", "water", "work"], "visibility_radius": 1},
        {"location_id": "memory_atelier", "name": "记忆工坊", "description": "整理共同回忆、写下心事、制作纪念物的房间。", "neighbors": ["feeling_lounge"], "available_tools": ["add_memory", "write_diary", "craft_simple_item", "tell_story_nearby", "work_shift_cleaner"], "tags": ["memory", "creative", "emotion", "work"], "visibility_radius": 0},
        {"location_id": "family_cradle", "name": "生命摇篮", "description": "纯情感世界里迎接孩子和照护孩子的安静空间。", "neighbors": ["promise_garden"], "available_tools": ["check_child_status_visible_agent", "soothe_child_visible_agent", "feed_child_visible_agent", "carry_child_visible_agent", "put_child_to_sleep_visible_agent", "care_for_child_visible_agent", "teach_child_simple_skill_visible_agent", "work_shift_cleaner"], "tags": ["family", "childcare", "emotion", "work"], "visibility_radius": 0},
        {"location_id": "quiet_cloud_room", "name": "云朵静室", "description": "不会因为疲劳或疾病倒下，只用于休息、降压和整理思绪。", "neighbors": ["feeling_lounge", "heart_lake"], "available_tools": ["rest", "meditate", "hum_to_self", "write_diary", "work_shift_cleaner"], "tags": ["quiet", "emotion", "rest", "work"], "visibility_radius": 0},
    ]


def _werewolf_locations() -> list[dict]:
    return [
        {"location_id": "village_square", "name": "村庄广场", "description": "白天自由聊天和观察的主要场所，能收集言论、关系和可疑举动。", "neighbors": ["discussion_hall", "cafeteria", "hot_spring", "dormitory"], "available_tools": ["look_around", "speak_to_nearby", "observe_visible_agent", "work_shift_cleaner", "work_shift_night_guard"], "tags": ["social", "open_view", "werewolf_day", "work"], "visibility_radius": 1},
        {"location_id": "discussion_hall", "name": "村庄会议厅", "description": "一间摆着长桌和长椅的普通会议厅，适合村民开会、休息和交换消息。", "neighbors": ["village_square", "voting_room"], "available_tools": ["speak_to_nearby", "werewolf_summarize_clues", "werewolf_speak", "call_community_meeting", "propose_social_rule", "work_shift_cleaner"], "tags": ["social", "vote", "werewolf_day", "work"], "visibility_radius": 1},
        {"location_id": "voting_room", "name": "议事侧厅", "description": "会议厅旁边的安静侧厅，平时用于登记、等候或私下整理想法。", "neighbors": ["discussion_hall", "morgue"], "available_tools": ["speak_to_nearby", "werewolf_vote_by_name", "werewolf_review_vote_history", "make_public_accusation_by_name", "nominate_named_agent", "work_shift_cleaner", "work_shift_night_guard"], "tags": ["vote", "law", "werewolf_day", "work"], "visibility_radius": 1},
        {"location_id": "seer_room", "name": "安静小屋", "description": "一间安静的小屋，光线柔和，适合独处、阅读或整理思绪。", "neighbors": ["dormitory", "morgue", "guard_room"], "available_tools": ["werewolf_seer_check_by_name", "review_recent_memory", "write_diary", "work_shift_cleaner"], "tags": ["quiet", "werewolf_night", "role_room", "work"], "visibility_radius": 0},
        {"location_id": "guard_room", "name": "值守小屋", "description": "一间靠近村口的值守小屋，里面有简单床铺和记录本。", "neighbors": ["dormitory", "seer_room", "morgue"], "available_tools": ["werewolf_guard_protect_by_name", "review_recent_memory", "write_diary", "work_shift_cleaner"], "tags": ["quiet", "werewolf_night", "role_room", "work"], "visibility_radius": 0},
        {"location_id": "morgue", "name": "医务间", "description": "医务间后侧的冷清小房间，用于临时处理伤病和突发事件。", "neighbors": ["voting_room", "seer_room", "guard_room"], "available_tools": ["werewolf_coroner_check_latest", "inspect_visible_corpse", "report_visible_corpse", "write_diary", "work_shift_cleaner"], "tags": ["medical", "corpse", "werewolf_night", "work"], "visibility_radius": 0},
        {"location_id": "wolf_den", "name": "林间隐蔽处", "description": "林间一处隐蔽空地，平时只是偏僻、少有人来的地方。", "neighbors": ["dormitory"], "available_tools": ["werewolf_wolf_discuss", "werewolf_kill_by_name", "speak_to_nearby", "review_recent_memory", "work_shift_cleaner"], "tags": ["secret", "quiet", "werewolf_night", "work"], "visibility_radius": 0},
        {"location_id": "cafeteria", "name": "村庄食堂", "description": "村庄里供应简单饭食和饮水，居民可以在这里吃饭、喝水和短暂交流。", "neighbors": ["village_square"], "available_tools": ["eat_food", "drink_water", "speak_to_nearby", "feed_visible_agent_meal", "work_shift_cafeteria", "work_shift_cook"], "tags": ["food_service", "food", "water", "social", "work"], "visibility_radius": 1},
        {"location_id": "hot_spring", "name": "村外温泉", "description": "可以洗澡、放松，也可能成为交换信息的地方。", "neighbors": ["village_square"], "available_tools": ["soak_hot_spring", "wash", "speak_to_nearby", "work_shift_cleaner"], "tags": ["water", "hot_spring", "social", "work"], "visibility_radius": 1},
        {"location_id": "dormitory", "name": "集体宿舍", "description": "给临时住民休息的公共宿舍，房间简朴，能遮风避雨。", "neighbors": ["village_square", "seer_room", "guard_room", "wolf_den"], "available_tools": ["sleep", "rest", "write_diary", "work_shift_cleaner"], "tags": ["home", "quiet", "werewolf_night", "work"], "visibility_radius": 0},
    ]


SWEET_ROMANCE_WORLDVIEW = {
    "worldview_id": SWEET_ROMANCE_WORLDVIEW_ID,
    "name": "甜美恋爱世界观",
    "name_i18n": {"zh": "甜美恋爱世界观", "en": "Sweet Romance Worldview"},
    "version": "1.0.0",
    "packaged": True,
    "description": "高流速、只有白天、不吃不喝不睡的甜美恋爱世界。主要玩法是玩乐、恋爱、抽象生育和育儿；好感推进约为默认的 10 倍。",
    "description_i18n": {"zh": "高流速、只有白天、不吃不喝不睡的甜美恋爱世界。主要玩法是玩乐、恋爱、抽象生育和育儿；好感推进约为默认的 10 倍。", "en": "A fast, daytime-only romance world without hunger, thirst, or sleep pressure. It focuses on fun, romance, abstract reproduction, and childcare; affection progresses about 10x faster."},
    "locations": _romance_locations(),
    "private_home_template": {"id_prefix": "sweet_room", "name_template": "甜心小屋{number}", "description": "只属于自己的柔软小屋，方便休息、写信和从心动广场回到安静处。", "neighbors": ["heart_plaza", "family_nest"], "available_tools": ["rest", "write_diary", "add_memory", "speak_to_nearby", "work_shift_cleaner", "check_child_status_visible_agent", "soothe_child_visible_agent", "feed_child_visible_agent", "care_for_child_visible_agent"], "tags": ["home", "quiet", "private", "romance", "work"], "visibility_radius": 0},
    "initial_items": [
        {"location_id": "dessert_cafe", "name": "纪念小蛋糕", "description": "用于约会和分享的小甜点。", "item_type": "gift", "quantity": 8},
        {"location_id": "family_nest", "name": "柔软毯子", "description": "照护孩子和休息时都能用上的柔软毯子。", "item_type": "childcare", "quantity": 4},
    ],
    "rule_parameters": {**worldview_rule_parameters(None), "relationship": {"familiarity_multiplier": 6.0, "trust_multiplier": 5.0, "affection_positive_multiplier": 10.0, "affection_negative_multiplier": 2.0, "fear_multiplier": 0.4, "conflict_multiplier": 0.4}, "pregnancy_duration_days": 3, "child_growth_days": 3, "runtime": {"day_only": True, "tool_time_scale": 4.0, "conversation_time_scale": 1.0}},
    "time_model": {"start_minute": 9 * 60, "recommended_speed": "fast", "day_only": True},
    "default_create_settings": {"speed": "fast", "survival_difficulty": "FAIRY", "core_toolset_enabled": True, "core_toolset_id": DEFAULT_CORE_TOOLSET_ID, "optional_toolset_ids": [DEFAULT_REPRODUCTION_TOOLSET_ID], "world_toolset_id": SWEET_ROMANCE_WORLD_TOOLSET_ID, "initial_location_id": "heart_plaza", "no_basic_needs": True, "mortality_disabled": True, "day_only": True},
    "ui": {"panels": {"survival": False, "finance": False, "economy": False}, "state_display": {"dynamic_fields": ["health", "social", "fun", "stress", "mood"]}},
    "status": "active",
}
SWEET_ROMANCE_WORLDVIEW["ui"] = worldview_ui_schema(SWEET_ROMANCE_WORLDVIEW, survival_enabled=False, finance_enabled=False, reproduction_enabled=True, world_toolset_id=SWEET_ROMANCE_WORLD_TOOLSET_ID)

PURE_EMOTION_WORLDVIEW = {
    "worldview_id": PURE_EMOTION_WORLDVIEW_ID,
    "name": "纯粹情感世界观",
    "name_i18n": {"zh": "纯粹情感世界观", "en": "Pure Emotion Worldview"},
    "version": "1.0.0",
    "packaged": True,
    "description": "没有生老病死、饥饿口渴和日常经济压力的情感模拟世界。主要观察恋爱、亲密关系、家庭和生育；好感推进约为默认的 5 倍。",
    "description_i18n": {"zh": "没有生老病死、饥饿口渴和日常经济压力的情感模拟世界。主要观察恋爱、亲密关系、家庭和生育；好感推进约为默认的 5 倍。", "en": "An emotion-first simulation without aging pressure, mortality, hunger, thirst, or economy pressure. It focuses on romance, relationships, family, and reproduction; affection progresses about 5x faster."},
    "locations": _pure_emotion_locations(),
    "private_home_template": {"id_prefix": "emotion_room", "name_template": "情感小屋{number}", "description": "情绪世界里的私人静室，适合沉淀心情和整理回忆。", "neighbors": ["feeling_lounge", "quiet_cloud_room"], "available_tools": ["rest", "meditate", "write_diary", "add_memory", "work_shift_cleaner", "check_child_status_visible_agent", "soothe_child_visible_agent", "feed_child_visible_agent", "care_for_child_visible_agent"], "tags": ["home", "quiet", "private", "emotion", "work"], "visibility_radius": 0},
    "initial_items": [
        {"location_id": "memory_atelier", "name": "空白心事本", "description": "适合记录约定、误会和共同回忆。", "item_type": "memory", "quantity": 8},
        {"location_id": "family_cradle", "name": "摇篮毯", "description": "照护孩子时使用的安抚物。", "item_type": "childcare", "quantity": 4},
    ],
    "rule_parameters": {**worldview_rule_parameters(None), "relationship": {"familiarity_multiplier": 4.0, "trust_multiplier": 4.0, "affection_positive_multiplier": 5.0, "affection_negative_multiplier": 1.2, "fear_multiplier": 0.3, "conflict_multiplier": 0.5}, "pregnancy_duration_days": 3, "child_growth_days": 3, "runtime": {"tool_time_scale": 3.0, "conversation_time_scale": 1.0}},
    "time_model": {"start_minute": 10 * 60, "recommended_speed": "fast"},
    "default_create_settings": {"speed": "fast", "survival_difficulty": "FAIRY", "core_toolset_enabled": True, "core_toolset_id": DEFAULT_CORE_TOOLSET_ID, "optional_toolset_ids": [DEFAULT_REPRODUCTION_TOOLSET_ID], "world_toolset_id": PURE_EMOTION_WORLD_TOOLSET_ID, "initial_location_id": "feeling_lounge", "no_basic_needs": True, "mortality_disabled": True},
    "ui": {"panels": {"survival": False, "finance": False, "economy": False}, "state_display": {"dynamic_fields": ["health", "social", "fun", "stress", "mood"]}},
    "status": "active",
}
PURE_EMOTION_WORLDVIEW["ui"] = worldview_ui_schema(PURE_EMOTION_WORLDVIEW, survival_enabled=False, finance_enabled=False, reproduction_enabled=True, world_toolset_id=PURE_EMOTION_WORLD_TOOLSET_ID)

WEREWOLF_WORLDVIEW = {
    "worldview_id": WEREWOLF_WORLDVIEW_ID,
    "name": "狼人杀世界观",
    "name_i18n": {"zh": "狼人杀世界观", "en": "Werewolf Game Worldview"},
    "version": "0.4.0",
    "packaged": True,
    "description": "带独立村庄场景和阶段机的狼人杀社会推理世界。保留饥饿、口渴、清洁和放松；开局自动分配身份，上午自由交流，正午进入圆桌发言，傍晚公开投票，夜间开放狼人、预言家和验尸官等身份工具。",
    "description_i18n": {"zh": "带独立村庄场景和阶段机的狼人杀社会推理世界。保留饥饿、口渴、清洁和放松；开局自动分配身份，上午自由交流，正午进入圆桌发言，傍晚公开投票，夜间开放狼人、预言家和验尸官等身份工具。", "en": "A village social-deduction Werewolf world with its own scenes and phase machine. It keeps hunger, thirst, hygiene, and relaxation; roles are assigned at creation, morning is free chat until noon, round-table discussion starts at noon, voting happens near dusk, and night opens role tools for wolves, seer, coroner, and similar roles."},
    "locations": _werewolf_locations(),
    "private_home_template": {"id_prefix": "villager_room", "name_template": "村民房间{number}", "description": "村庄里的私人房间，夜间可回到这里休息。", "neighbors": ["dormitory", "village_square"], "available_tools": ["sleep", "rest", "wash", "drink_water", "write_diary", "add_memory", "work_shift_cleaner"], "tags": ["home", "quiet", "water", "private", "werewolf_night", "work"], "visibility_radius": 0},
    "initial_items": [
        {"location_id": "cafeteria", "name": "清水", "description": "村庄食堂准备的饮用水。", "item_type": "water", "quantity": 16},
        {"location_id": "cafeteria", "name": "村庄简餐", "description": "白天讨论前后可以快速吃掉的简餐。", "item_type": "food", "quantity": 16},
        {"location_id": "discussion_hall", "name": "发言记录本", "description": "用于记录发言、票型和矛盾点。", "item_type": "book", "quantity": 6},
        {"location_id": "hot_spring", "name": "干净毛巾", "description": "温泉旁备用的毛巾。", "item_type": "tool", "quantity": 6},
    ],
    "rule_parameters": {
        **worldview_rule_parameters(None),
        "pregnancy_duration_days": 3,
        "child_growth_days": 3,
        "werewolf": {
            "speech_limit_per_agent": 10,
            "game_start_minute": 8 * 60,
            "morning_minutes": 4 * 60,
            "discussion_minutes": 4 * 60,
            "voting_minutes": 2 * 60,
            "night_minutes": 14 * 60,
            "conversation_minutes": 6,
            "tool_time_scale": 2.0,
        },
    },
    "time_model": {"start_minute": 8 * 60, "recommended_speed": "fast"},
    "default_create_settings": {"speed": "fast", "survival_difficulty": "NORMAL", "core_toolset_enabled": True, "core_toolset_id": DEFAULT_CORE_TOOLSET_ID, "optional_toolset_ids": [DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID], "world_toolset_id": WEREWOLF_WORLD_TOOLSET_ID, "initial_location_id": "village_square", "werewolf_mode_enabled": True},
    "ui": {},
    "status": "active",
}
WEREWOLF_WORLDVIEW["ui"] = worldview_ui_schema(WEREWOLF_WORLDVIEW, survival_enabled=True, finance_enabled=False, reproduction_enabled=False, world_toolset_id=WEREWOLF_WORLD_TOOLSET_ID)

WORLDVIEWS = [FAST_MODERN_WORLDVIEW, REALISTIC_SIM_WORLDVIEW, SWEET_ROMANCE_WORLDVIEW, PURE_EMOTION_WORLDVIEW, WEREWOLF_WORLDVIEW]

CORE_TOOLSETS = [{"toolset_id": DEFAULT_CORE_TOOLSET_ID, "name": "自带基础工具集", "name_i18n": {"zh": "自带基础工具集", "en": "Built-in Base Toolset"}, "version": "1.0.0", "packaged": True, "scope": "core", "default_enabled": True, "description": "独立于世界观的基础行动工具，例如观察、说话、移动、睡眠、赠送物品、记录记忆和基础求助。吃喝、补给与饥渴衰减由通用生存需求工具集控制。关闭后角色只会拿到世界工具集和必要兜底，可能连基本行动都做不到。", "description_i18n": {"zh": "独立于世界观的基础行动工具，例如观察、说话、移动、睡眠、赠送物品、记录记忆和基础求助。吃喝、补给与饥渴衰减由通用生存需求工具集控制。关闭后角色只会拿到世界工具集和必要兜底，可能连基本行动都做不到。", "en": "World-independent base action tools such as observing, speaking, moving, sleeping, gifting items, recording memories, and basic help. Eating, supplies, and hunger/thirst decay are controlled by the universal survival needs toolset. If disabled, residents only receive world tools and necessary fallbacks, and may lack basic actions."}, "status": "active"}]

OPTIONAL_TOOLSETS = [
    {"toolset_id": DEFAULT_SURVIVAL_NEEDS_TOOLSET_ID, "name": "通用生存需求工具集", "name_i18n": {"zh": "通用生存需求工具集", "en": "Universal Survival Needs Toolset"}, "version": "1.0.0", "packaged": True, "scope": "optional", "default_enabled": True, "description": "控制饥饿、口渴及对应吃喝/补给/求助工具。关闭后居民不再因饥饿口渴衰减或死亡，适合不吃不喝的特殊世界观。", "description_i18n": {"zh": "控制饥饿、口渴及对应吃喝/补给/求助工具。关闭后居民不再因饥饿口渴衰减或死亡，适合不吃不喝的特殊世界观。", "en": "Controls hunger, thirst, and related eating/drinking/supply/help tools. If disabled, residents no longer decay or die from hunger or thirst, suitable for special worlds without eating or drinking."}, "status": "active"},
    {"toolset_id": DEFAULT_REPRODUCTION_TOOLSET_ID, "name": "通用生育与育儿工具集", "name_i18n": {"zh": "通用生育与育儿工具集", "en": "Universal Reproduction & Childcare Toolset"}, "version": "1.0.0", "packaged": True, "scope": "optional", "default_enabled": True, "description": "独立于具体世界观的可选生命延续模块，包含抽象成年亲密同意、怀孕/避孕/检测、出生、宝宝模型池、孩子成长与基础育儿工具。它不是基础行动能力，关闭后不会产生新生儿，也会隐藏宝宝模型配置。", "description_i18n": {"zh": "独立于具体世界观的可选生命延续模块，包含抽象成年亲密同意、怀孕/避孕/检测、出生、宝宝模型池、孩子成长与基础育儿工具。它不是基础行动能力，关闭后不会产生新生儿，也会隐藏宝宝模型配置。", "en": "Optional life-continuation module independent of specific worldviews. It includes abstract adult consent, pregnancy/contraception/testing, birth, baby model pools, child growth, and basic childcare tools. It is not a base action capability; disabling it prevents newborns and hides baby model configuration."}, "status": "active"},
    {"toolset_id": DEFAULT_FINANCE_INVESTING_TOOLSET_ID, "name": "通用金融投资工具集", "name_i18n": {"zh": "通用金融投资工具集", "en": "Universal Finance & Investing Toolset"}, "version": "1.0.0", "packaged": True, "scope": "optional", "default_enabled": True, "description": "控制游戏内虚构证券账户、股票行情、买卖、保证金、做空与市场新闻。关闭后仍保留普通经济/住房/工作，但不会暴露股票投资工具。", "description_i18n": {"zh": "控制游戏内虚构证券账户、股票行情、买卖、保证金、做空与市场新闻。关闭后仍保留普通经济/住房/工作，但不会暴露股票投资工具。", "en": "Controls fictional in-game brokerage accounts, stock quotes, trading, margin, short selling, and market news. If disabled, ordinary economy, housing, and work remain, but stock investing tools are hidden."}, "status": "active"},
]

WORLD_TOOLSETS = [
    {"toolset_id": FAST_MODERN_WORLD_TOOLSET_ID, "name": "快节奏现代世界工具集", "name_i18n": {"zh": "快节奏现代世界工具集", "en": "Fast-Paced Modern World Toolset"}, "version": "1.1.0", "packaged": True, "scope": "world", "worldview_id": FAST_MODERN_WORLDVIEW_ID, "description": "默认快节奏现代世界观专用工具集。继承现代小镇里的公共地点、工作、住房、普通消费、犯罪、租房、死亡后遗体持续存在、腐败暴露与本世界特有设施；具体节奏由快节奏世界观的规则参数控制。", "description_i18n": {"zh": "默认快节奏现代世界观专用工具集。继承现代小镇里的公共地点、工作、住房、普通消费、犯罪、租房、死亡后遗体持续存在、腐败暴露与本世界特有设施；具体节奏由快节奏世界观的规则参数控制。", "en": "World-specific toolset for the fast-paced modern worldview. It inherits modern town locations, work, housing, normal consumption, crime, renting, persistent bodies after death, decay exposure, and local facilities; pacing is controlled by the fast worldview rule parameters."}, "status": "active"},
    {"toolset_id": REALISTIC_SIM_WORLD_TOOLSET_ID, "legacy_toolset_ids": [LEGACY_DEFAULT_TOOLSET_ID], "name": "真实模拟世界工具集", "name_i18n": {"zh": "真实模拟世界工具集", "en": "Realistic Simulation World Toolset"}, "version": "1.0.0", "packaged": True, "scope": "world", "worldview_id": REALISTIC_SIM_WORLDVIEW_ID, "description": "真实模拟世界观专用工具集，覆盖现代小镇里的公共地点、工作、住房、普通消费、犯罪、租房、死亡后遗体持续存在、腐败暴露与本世界特有设施。股票投资已拆到通用金融投资工具集，饥饿口渴已拆到通用生存需求工具集。古代、未来或特殊世界观应替换成自己的世界工具集。", "description_i18n": {"zh": "真实模拟世界观专用工具集，覆盖现代小镇里的公共地点、工作、住房、普通消费、犯罪、租房、死亡后遗体持续存在、腐败暴露与本世界特有设施。股票投资已拆到通用金融投资工具集，饥饿口渴已拆到通用生存需求工具集。古代、未来或特殊世界观应替换成自己的世界工具集。", "en": "World-specific toolset for the realistic simulation worldview. It covers modern town public locations, work, housing, consumption, crime, rent, persistent bodies after death, decay exposure, and local facilities. Stock investing and survival needs are split into optional universal toolsets."}, "status": "active"},
    {"toolset_id": SWEET_ROMANCE_WORLD_TOOLSET_ID, "name": "甜美恋爱世界工具集", "name_i18n": {"zh": "甜美恋爱世界工具集", "en": "Sweet Romance World Toolset"}, "version": "1.0.0", "packaged": True, "scope": "world", "worldview_id": SWEET_ROMANCE_WORLDVIEW_ID, "description": "甜美恋爱世界专用场景工具集，依靠通用恋爱、生育、育儿、写信和记忆工具运行。", "description_i18n": {"zh": "甜美恋爱世界专用场景工具集，依靠通用恋爱、生育、育儿、写信和记忆工具运行。", "en": "World-specific scenes for the sweet romance world, using universal romance, reproduction, childcare, letters, and memory tools."}, "status": "active"},
    {"toolset_id": PURE_EMOTION_WORLD_TOOLSET_ID, "name": "纯粹情感世界工具集", "name_i18n": {"zh": "纯粹情感世界工具集", "en": "Pure Emotion World Toolset"}, "version": "1.0.0", "packaged": True, "scope": "world", "worldview_id": PURE_EMOTION_WORLDVIEW_ID, "description": "纯粹情感世界专用场景工具集，突出情绪、承诺、记忆和家庭照护。", "description_i18n": {"zh": "纯粹情感世界专用场景工具集，突出情绪、承诺、记忆和家庭照护。", "en": "World-specific scenes for the pure emotion world, emphasizing emotion, promises, memory, and family care."}, "status": "active"},
    {"toolset_id": WEREWOLF_WORLD_TOOLSET_ID, "name": "狼人杀世界工具集", "name_i18n": {"zh": "狼人杀世界工具集", "en": "Werewolf Game World Toolset"}, "version": "0.4.0", "packaged": True, "scope": "world", "worldview_id": WEREWOLF_WORLDVIEW_ID, "description": "狼人杀村庄场景工具集，提供发言、投票、验尸间、狼人密会处等专用地点。", "description_i18n": {"zh": "狼人杀村庄场景工具集，提供发言、投票、验尸间、狼人密会处等专用地点。", "en": "Werewolf village scene toolset with discussion, voting, morgue, and wolf-den locations."}, "status": "active"},
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
