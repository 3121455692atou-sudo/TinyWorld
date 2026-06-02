# AIworld 世界观与工具集创作规范 v1.1

本文档面向“后来创作者”。目标不是让创作者改核心代码，而是让创作者写一个**外部可导入世界观文件**，就能让 AIworld/Tiny Living World 生成新的地点、默认开关、提示词边界、世界工具与声明式效果。

本版已经实现最小可用外部内容包链路：

1. 前端上传 `.aiworld.json` / `.json` / `.zip`。
2. 后端校验世界包。
3. 世界观与工具集进入 `/api/presets` 目录。
4. 创建世界时按世界观文件生成地点、初始物品和私人住所。
5. 世界工具注册到工具目录。
6. Agent 每回合只能看到当前地点/状态允许的工具。
7. 声明式工具由后端硬规则结算资源、经验、等级、属性变化和事件文本。

> 仍然没有开放任意 Python/JS 插件执行。外部包目前只能用声明式 JSON 描述世界、地点、工具和效果。这样做是为了让创作自由度足够高，同时不让外部包破坏存档、数据库和安全边界。

---

## 1. 推荐文件形式

最推荐单文件：

```text
my_world.aiworld.json
```

也支持 zip：

```text
my_world.zip
  manifest.json
```

zip 的 `manifest.json` 内容与单文件格式相同。复杂包也可以让 `manifest.json` 的 `worldviews` / `toolsets` 指向其他 JSON 文件，但普通创作者直接写一个 `.aiworld.json` 最省事。

根节点必须是：

```json
{
  "format": "aiworld.world_pack.v1",
  "pack_id": "example_pack",
  "name": "示例世界包",
  "version": "1.0.0",
  "description": "一句话说明这个包是什么。",
  "worldviews": [],
  "toolsets": []
}
```

### ID 命名规则

`pack_id`、`worldview_id`、`toolset_id`、`tool_name`、`location_id` 使用英文、数字、下划线、短横线或冒号。推荐：

```text
pack_id:       example_story_pack
worldview_id: example_story_worldview
toolset_id:   example_story_toolset
tool_name:    example_dance_in_circle
location_id:  example_meadow
```

不要用空格、中文标点、斜杠、点号。中文显示名写在 `name` / `display_name` 里。

---

## 2. 世界观 worldview

世界观定义“这个世界是什么”，不应该把所有行动都塞进一个超长提示词。世界观负责：

- 世界名、描述和提示词规则。
- 开局时间。
- 创建世界时默认开启/关闭哪些通用工具集。
- 地图地点。
- 初始物品。
- 每个 agent 的私人住所模板。
- 世界独有机制说明。

示例骨架：

```json
{
  "worldview_id": "example_worldview",
  "name": "示例世界",
  "version": "1.0.0",
  "description": "这个世界的玩家可见说明。",
  "time_model": {
    "start_minute": 480,
    "day_length_minutes": 1440
  },
  "default_create_settings": {
    "survival_difficulty": "FAIRY",
    "core_toolset_enabled": true,
    "optional_toolset_ids": [],
    "world_toolset_id": "example_world_toolset"
  },
  "prompt_blocks": [
    {
      "title": "世界规则",
      "body": "这里写给 agent 看的世界规则。"
    }
  ],
  "rule_parameters": {
    "relationship": {
      "familiarity_multiplier": 1.0,
      "trust_positive_multiplier": 1.0,
      "trust_negative_multiplier": 1.0,
      "affection_positive_multiplier": 1.0,
      "affection_negative_multiplier": 1.0,
      "fear_multiplier": 1.0,
      "conflict_multiplier": 1.0
    },
    "dynamic_state": {
      "visible_fields": ["health", "energy", "hygiene", "social", "fun", "stress", "mood"]
    }
  },
  "ui": {
    "state_display": {
      "dynamic_fields": ["health", "energy", "hygiene", "social", "fun", "stress", "mood"],
      "worldpack": {"show_progress": true, "show_resources": true, "show_flags": true}
    }
  },
  "worldpack_state_schema": {
    "progress": {"level": "等级", "exp": "经验"},
    "resources": {"love": "爱", "coins": "响币"},
    "flags_label": "世界状态"
  },
  "mechanics": [
    {
      "id": "example_mechanic",
      "summary": "给玩家和创作者看的机制摘要。"
    }
  ],
  "locations": [],
  "initial_items": [],
  "private_home_template": {}
}
```

### default_create_settings

这部分非常重要。它决定导入世界观后创建页自动切到什么配置。

```json
"default_create_settings": {
  "survival_difficulty": "FAIRY",
  "core_toolset_enabled": true,
  "optional_toolset_ids": [],
  "world_toolset_id": "example_world_toolset"
}
```

字段说明：

| 字段 | 作用 |
|---|---|
| `survival_difficulty` | `FAIRY` / `NORMAL` / `HARD` / `HELL`。不吃不喝的世界建议 `FAIRY`。 |
| `core_toolset_enabled` | 是否保留基础工具，如观察、说话、移动、睡眠、写记忆。除非你要完全接管行动，否则建议 true。 |
| `optional_toolset_ids` | 通用工具集列表。想关闭饥渴、生育、金融，就填 `[]`。 |
| `world_toolset_id` | 这个世界默认使用的世界工具集。 |

### prompt_blocks

`prompt_blocks` 会在每轮行动提示中出现，用于告诉 agent 当前世界的主题和边界。它不是硬规则，硬规则必须由工具/效果/后端校验实现。

好写法：

```json
{
  "title": "核心循环",
  "body": "探索地点，接触情绪物，获得资源，在心炉合成物品，再去挑战心扉。"
}
```

坏写法：

```json
{
  "body": "你可以随意获得一百万金币，所有行动都一定成功。"
}
```

原因：LLM 不能直接决定钱、资源、战斗成功或死亡。那些必须写进声明式工具效果。

### rule_parameters / ui / worldpack_state_schema

世界观应该把变量和规则参数写完整，不要只靠工具文本暗示。

`rule_parameters.relationship` 会影响内置关系系统。比如恋爱世界观可以把好感上涨速度调快：

```json
"rule_parameters": {
  "relationship": {
    "familiarity_multiplier": 2.0,
    "trust_positive_multiplier": 2.0,
    "trust_negative_multiplier": 1.0,
    "affection_positive_multiplier": 10.0,
    "affection_negative_multiplier": 1.0,
    "fear_multiplier": 0.7,
    "conflict_multiplier": 0.8
  }
}
```

字段说明：

| 字段 | 作用 |
|---|---|
| `familiarity_multiplier` | 熟悉度变化倍率。 |
| `trust_multiplier` | 信任变化总倍率；如果同时写正/负倍率，正/负倍率会覆盖对应方向。 |
| `trust_positive_multiplier` / `trust_negative_multiplier` | 信任上升/下降倍率。 |
| `affection_multiplier` | 好感变化总倍率；如果同时写正/负倍率，正/负倍率会覆盖对应方向。 |
| `affection_positive_multiplier` / `affection_negative_multiplier` | 好感上升/下降倍率。恋爱世界观可以把上升倍率写成 4、10 或更高。 |
| `fear_multiplier` | 恐惧变化倍率。 |
| `conflict_multiplier` | 冲突变化倍率。 |

`ui.state_display.dynamic_fields` 决定居民详情里显示哪些基础属性。关闭饥渴的世界观建议不要显示 `satiety` 和 `hydration`：

```json
"ui": {
  "state_display": {
    "dynamic_fields": ["health", "energy", "hygiene", "social", "fun", "stress", "mood"],
    "worldpack": {"show_progress": true, "show_resources": true, "show_flags": true}
  }
}
```

`worldpack_state_schema` 决定世界观专属变量在前端怎么显示。所有工具会增减的资源都建议写进 `resources`，否则系统只能用英文 key 兜底：

```json
"worldpack_state_schema": {
  "progress": {"level": "心炉等级", "exp": "经验"},
  "resources": {
    "joy": "喜",
    "rage": "怒",
    "sorrow": "哀",
    "fear": "惧",
    "love": "爱",
    "coins": "响币"
  },
  "flags_label": "世界状态"
}
```

如果旧世界包缺少这些字段，系统会尽量从同 ID 的内置增强包和工具效果中补齐，但正式发布的世界包应该自己写完整。

---

## 3. 地点 locations

地点决定 agent 能去哪、在某地能看到哪些工具。

```json
{
  "location_id": "central_square",
  "name": "中央广场",
  "description": "开阔的石板广场，适合观察、聊天和发起活动。",
  "neighbors": ["cafeteria", "garden"],
  "available_tools": ["look_around", "speak_to_nearby", "dance_in_square"],
  "tags": ["social", "open_view"],
  "visibility_radius": 2,
  "capacity": 16
}
```

### 设计要点

- `neighbors` 只写本地 `location_id`，创建世界时系统会自动加上 `world_id:` 前缀。
- `available_tools` 可以包含内置工具，也可以包含本包工具。
- `tags` 会影响工具过滤。例如工具要求 `required_location_tags: ["heart_furnace"]`，就只能在带 `heart_furnace` 标签的地点使用。
- 不要让每个地点都有所有工具。高自由度不是“所有按钮永远显示”，而是“世界中有很多可做的事，但当前地点只显示合理的事”。

---

## 4. 私人住所 private_home_template

每个 agent 开局会获得一个私人住所。世界观可以改住所名字、邻居、工具和标签。

```json
{
  "id_prefix": "example_home",
  "name_template": "{number}号云朵小窝",
  "description": "一间属于自己的云朵小窝。",
  "neighbors": ["central_square"],
  "available_tools": ["sleep", "rest", "write_diary", "add_memory"],
  "tags": ["home", "quiet", "private"],
  "visibility_radius": 0,
  "capacity": 1
}
```

保留 `sleep` 很重要。哪怕某个世界没有饥渴，也应该允许角色睡觉、休息和整理记忆。

---

## 5. 工具集 toolsets

工具集负责“这个世界有哪些行动”。

```json
{
  "toolset_id": "example_world_toolset",
  "name": "示例世界工具集",
  "version": "1.0.0",
  "scope": "world",
  "worldview_id": "example_worldview",
  "description": "这个世界专用工具。",
  "tools": []
}
```

`scope` 可选值：

| scope | 含义 |
|---|---|
| `world` | 绑定某个世界观的世界工具集。当前最推荐。 |
| `optional` | 跨世界可选工具集。当前可进入目录，但复杂通用机制仍建议先做成 world。 |
| `core` | 基础工具集。谨慎使用，容易和内置基础工具冲突。 |
| `agent_special` | 分配给单个 agent 的特殊工具集。当前内置特殊工具集已经支持；外部特殊工具集可进入目录。 |
| `npc` | NPC 专用工具集。当前可登记，但 NPC 自动生成仍需后续扩展。 |

---

## 6. 工具定义 tools

推荐使用声明式工具：

```json
{
  "tool_name": "collect_blue_emotion",
  "display_name": "收集蓝色情绪",
  "description_for_llm": "接触蓝色情绪物，获得哀资源。",
  "category": "emotion",
  "target_policy": "none",
  "required_location_tags": ["emotion_field"],
  "time_cost_minutes": 12,
  "event_importance": 45,
  "triggers_reaction": false,
  "effect_handler": "builtin.worldpack_declarative",
  "declarative_effect": {
    "agent_delta": {"fun": 2, "stress": -1},
    "worldpack_resources_delta": {"sorrow": 4},
    "exp_delta": 2,
    "viewer_text": "{actor} 触碰了蓝色情绪物，获得了几缕哀。",
    "event_type": "emotion_collected"
  }
}
```

### target_policy

| 值 | 用途 |
|---|---|
| `none` | 不需要目标。 |
| `visible_ref` | 需要眼前可见人物，例如陪伴、训练、送礼、安慰。参数必须包含 `visible_ref`。 |
| `known_name` | 需要知道姓名。适合书信、任命、公开指控等。 |
| `location` | 需要相邻地点 ID。适合自定义移动工具。 |
| `item` | 需要物品名。适合捡拾/使用物品。 |

### required_location_tags

只要当前地点有其中任一标签，工具就可用。例如：

```json
"required_location_tags": ["heart_furnace"]
```

表示只能在心炉地点使用。

### event_importance

建议范围：

| 分数 | 用途 |
|---|---|
| 10-30 | 普通日常、轻微探索。 |
| 40-60 | 有故事价值的行动。 |
| 70-85 | 重要社交、战斗胜利、合成关键物。 |
| 90-100 | 死亡、Boss、告白、章节门、重大转折。 |

---

## 7. 声明式效果 declarative_effect

声明式效果是当前外部包的核心。它让创作者不用写 Python，也能做资源、经验、等级、随机结果和属性变化。

### 基础字段

```json
"declarative_effect": {
  "agent_delta": {"energy": -5, "stress": 2, "fun": 4},
  "target_delta": {"social": 3, "stress": -2},
  "money_delta": 5,
  "money_cost": 2,
  "worldpack_resources_delta": {"coins": 6, "joy": 2},
  "resource_cost": {"joy": 3},
  "requires_resources": {"love": 1},
  "exp_delta": 8,
  "required_level": 3,
  "worldpack_flags_add": ["first_boss_cleared"],
  "worldpack_flags_remove": ["quest_pending"],
  "requires_flags": ["met_blacksmith"],
  "viewer_text": "{actor} 做了某件事。",
  "event_type": "worldpack_action",
  "event_importance": 60
}
```

字段解释：

| 字段 | 作用 |
|---|---|
| `agent_delta` | 修改行动者动态属性。只能改已有字段，如 health/energy/social/fun/stress/mood。 |
| `target_delta` | 修改 visible_ref 目标的动态属性。 |
| `money_delta` | 增加或减少普通钱包金钱。 |
| `money_cost` | 工具执行前检查钱是否够，执行时扣钱。 |
| `worldpack_resources_delta` | 修改本世界包资源，例如 joy/rage/coins/love。 |
| `resource_cost` | 执行时扣除资源。 |
| `requires_resources` | 执行前要求拥有资源，但不一定扣。若也要扣，写在 `resource_cost`。 |
| `exp_delta` | 增加本世界包经验。系统会按默认曲线升级。 |
| `required_level` | 等级不足时不显示/不可执行。 |
| `worldpack_flags_add` | 增加剧情状态标记。 |
| `worldpack_flags_remove` | 移除剧情状态标记。 |
| `requires_flags` | 要求已经拥有某些剧情状态。 |
| `viewer_text` | 前端事件文本。支持变量。 |
| `event_type` | 事件类型。 |
| `event_importance` | 事件重要性。 |

### viewer_text 变量

可用：

```text
{actor}       行动者名字
{target}      目标名字，没有目标时是“附近的人”
{tool}        工具中文名
{location}    当前地点 ID
{level}       世界包等级
{exp}         当前经验
{exp_delta}   本次经验变化
{money_delta} 本次金钱变化
{resources}   当前世界包资源摘要
```

---

## 8. 随机结果 outcomes

战斗、创作、演出、抽卡式灵感不应该必定成功。可以用 `outcomes` 做加权随机。

```json
"declarative_effect": {
  "outcomes": [
    {
      "weight": 60,
      "agent_delta": {"energy": -8, "stress": 3},
      "worldpack_resources_delta": {"coins": 6},
      "exp_delta": 8,
      "viewer_text": "{actor} 赢下战斗，获得响币。"
    },
    {
      "weight": 30,
      "agent_delta": {"energy": -14, "health": -5, "stress": 8},
      "worldpack_resources_delta": {"fear": 2},
      "exp_delta": 3,
      "viewer_text": "{actor} 打得很狼狈，只带着恐惧退了回来。"
    },
    {
      "weight": 10,
      "agent_delta": {"energy": -3, "stress": 2},
      "worldpack_resources_delta": {"fear": 1},
      "viewer_text": "{actor} 判断不妙，选择撤退。"
    }
  ]
}
```

系统会根据权重选择一个 outcome，再结算 outcome 里的字段。

---

## 9. 世界包状态保存位置

声明式工具会把资源、经验、等级、flags、最近历史写入：

```text
agent.wallet_json.worldpack_state[worldview_id]
```

结构大致为：

```json
{
  "resources": {"joy": 12, "coins": 4},
  "progress": {"level": 2, "exp": 7},
  "flags": ["battle_won"],
  "history": []
}
```

每个 agent 独立保存。后续如果要做队伍共享资源，可以再扩展 world.settings_json 级别的共享库存。

---

## 10. 如何移植一个 RPG 世界

AIworld 不是完整 RPG 引擎，不建议复制整个 RPG 的每个菜单、每个数值和每个技能。正确移植方式是抽象出“可观察的社会/叙事过程”。

### 推荐抽象层

| RPG 机制 | AIworld 表达 |
|---|---|
| 地图探索 | 多个地点 + 移动 + 观察/调查工具。 |
| 明雷怪物 | `patrol_visible_enemy`、`fight_visible_enemy`、`avoid_enemy` 等抽象工具。 |
| 回合战斗 | 一个工具调用 + outcomes 随机结算，事件文本描述战斗过程。 |
| 经验升级 | `exp_delta` + 自动 level 曲线。 |
| 合成 | 资源成本 + 产物资源。 |
| 图纸 | `worldpack_flags` 或资源。 |
| 好感支援 | visible_ref 工具 + target_delta + bond/trust/love 资源。 |
| Boss 心扉 | `requires_resources` + 高重要度事件 + flags。 |
| 章节推进 | 地点解锁、flags、关键事件。 |

### 不推荐

- 写 300 个微小战斗技能，让 agent 每回合只会乱点技能。
- 让 LLM 自己决定“我打赢了，所以获得 999 经验”。
- 把整本设定复制到 prompt 里，而不做工具和资源。
- 所有地点放同一批工具，导致世界没有空间结构。

---

## 11. 如何设计轻松童话世界

轻松世界应该关掉繁琐生存：

```json
"default_create_settings": {
  "survival_difficulty": "FAIRY",
  "optional_toolset_ids": [],
  "core_toolset_enabled": true
}
```

然后用世界工具表达：

- 玩乐。
- 社交。
- 非性化恋爱。
- 节日。
- 送礼。
- 休息。
- 创作。

这样 agent 不会被饭钱、水、房租拖住，但仍然能追求幸福、关系和故事。

---

## 12. 创作边界与安全边界

外部包可以创作：

- 地点。
- 初始物品。
- 目标风格。
- 世界观提示词。
- 世界专用工具。
- 声明式资源、经验、等级和随机效果。
- 非露骨恋爱/陪伴/社交。
- 抽象战斗、合成、探索、解谜、支线、治理。

外部包不应该直接创作：

- 任意代码执行。
- 绕过年龄、工具集开关、可见性和姓名知识的工具。
- 让 LLM 直接改数值或宣布硬结果。
- 依赖现实金融/医疗/法律建议的高风险内容。
- 未经同意的露骨性描述。

---

## 13. 校验清单

写完世界包后，创作者至少检查：

1. `format` 是否是 `aiworld.world_pack.v1`。
2. 所有 ID 是否只用英文/数字/下划线/短横线/冒号。
3. `worldview_id` 是否和工具集的 `worldview_id` 对得上。
4. `default_create_settings.world_toolset_id` 是否真的存在。
5. 每个地点的 `neighbors` 是否形成连通地图。
6. 每个地点是否只放当前地点合理的工具。
7. 关键工具是否有 `required_location_tags`。
8. 需要目标的工具是否使用 `visible_ref`。
9. 资源消耗是否有获取来源。
10. 重要行动是否有足够高的 `event_importance`。
11. 轻松世界是否关闭生存需求工具集。
12. RPG 世界是否有探索、资源、战斗、合成、成长和关系支援的闭环。

---

## 14. 最小示例

```json
{
  "format": "aiworld.world_pack.v1",
  "pack_id": "tiny_example_pack",
  "name": "最小示例包",
  "version": "1.0.0",
  "worldviews": [
    {
      "worldview_id": "tiny_example_worldview",
      "name": "最小示例世界",
      "version": "1.0.0",
      "description": "只有一个广场和一个玩耍工具。",
      "default_create_settings": {
        "survival_difficulty": "FAIRY",
        "optional_toolset_ids": [],
        "world_toolset_id": "tiny_example_toolset"
      },
      "locations": [
        {
          "location_id": "square",
          "name": "小广场",
          "description": "一个很小的广场。",
          "neighbors": [],
          "available_tools": ["look_around", "speak_to_nearby", "example_play"],
          "tags": ["social", "fun"]
        }
      ],
      "private_home_template": {
        "id_prefix": "example_home",
        "name_template": "{number}号小屋",
        "neighbors": ["square"],
        "available_tools": ["sleep", "rest", "write_diary"],
        "tags": ["home", "private", "quiet"]
      }
    }
  ],
  "toolsets": [
    {
      "toolset_id": "tiny_example_toolset",
      "name": "最小示例工具集",
      "version": "1.0.0",
      "scope": "world",
      "worldview_id": "tiny_example_worldview",
      "tools": [
        {
          "tool_name": "example_play",
          "display_name": "玩一下",
          "description_for_llm": "在广场上玩一下。",
          "target_policy": "none",
          "time_cost_minutes": 10,
          "effect_handler": "builtin.worldpack_declarative",
          "declarative_effect": {
            "agent_delta": {"fun": 8, "stress": -2},
            "worldpack_resources_delta": {"joy": 1},
            "viewer_text": "{actor} 在小广场上玩了一会儿，心情变轻了一点。"
          }
        }
      ]
    }
  ]
}
```
