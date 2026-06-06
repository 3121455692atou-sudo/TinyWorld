# 工具目录瘦身与 LLM 表达能力保留修复报告

本轮基于 `AIworld-core-code-20260605-tool-audit-private-fix.zip` 继续修改，目标是减少“表达情绪/喜好/态度/寒暄/气氛动作”等低价值工具，避免动态工具菜单被这些工具挤占，同时不缩小 agent 的能力边界。

## 核心判断

工具应该用于改变或查询世界状态，例如移动、资源、工作、照护、医疗、金融、法律、犯罪、狼人杀流程、关系确认、生育流程等。

单纯表达情绪、喜好、态度、寒暄、抱怨、玩笑、心情、暧昧暗示等内容，应由 LLM 直接通过台词、群体发言、私人笔记或记忆记录表达，不需要每一种情绪单独占一个工具。

因此，本轮不是削弱 LLM，而是减少对 LLM 的过度工具化。

## 工具数量变化

- 修复前注册工具数：854
- 修复后注册工具数：768
- 直接从 agent-facing 目录中移除的纯表达/重复表达工具：69 个显式 ID + `tool_emotion_*`、`tool_desire_*` 系列
- 额外隐藏但保留兼容的软表达核心工具：14 个

被移除或隐藏的典型工具包括：

- 情绪表达：`tool_emotion_cry`、`tool_emotion_smile`、`tool_emotion_blush` 等
- 喜好/欲望表达：`tool_desire_express_like`、`tool_desire_express_dislike` 等
- 纯寒暄：`tool_social_small_talk`、`tool_social_ask_feeling`、`tool_social_answer_feeling`
- 纯礼貌表达：`tool_social_thank`、`tool_social_apologize`
- 纯浪漫暗示：`tool_romance_hint_affection`、`tool_romance_flirt_light`
- 纯冲突台词：`tool_conflict_disagree`、`tool_conflict_argue`、`tool_conflict_defend_self`
- 纯金融情绪：`v6_feel_envy_of_rich_agent`、`v6_hide_stock_loss`

## 保留的能力边界

这些通用表达/记录能力仍然保留：

- `say_to_visible_agent`
- `speak_to_nearby`
- `write_private_note`
- `add_memory`

这些会改变世界状态或关系状态的能力也保留：

- 约会、牵手、拥抱、告白、确认关系、分手、修复关系
- 成人亲密请求、接受、拒绝、怀孕检测、避孕、出生、生育相关状态变化
- 求助、索要食物/水、分享资源、照顾婴儿、背/扶昏倒者、医疗处理
- 工作、金融、犯罪、法律、狼人杀发言/反驳/投票/夜间能力

也就是说，agent 仍然可以表达“我喜欢你”“我有点嫉妒”“我很害怕”“我想靠近你”，但这些内容应写在台词里；只有当行为会改变世界关系或状态时，才需要工具承接。

## 成人/生育路径说明

按项目要求，本轮没有增加额外安全审查提示词。

为了避免工具瘦身误伤生育路径，`turn_runner` 里补了成人亲密意图对齐：如果 LLM 在台词中表达了明确的成人亲密请求意图，并且世界观允许相关工具，系统可以把它对齐到正式的 `request_adult_intimacy_visible_agent`，而不需要把大量纯暧昧/纯情绪工具塞进菜单。

## 动态菜单压缩

- 成人 agent 动态候选上限从 48 降到 32
- 动态工具最终展示上限从 96 降到 72
- AOHP 普通行动菜单默认上限从 90 降到 72
- reaction 菜单默认上限从 70 降到 55
- 社交/关系/学习/场景工具族配额同步下调

同时加入保底：

- 基础移动工具不会被动态目录挤掉
- 求助/照护/生存/医疗等硬行为仍有优先级
- 关系状态变更和家庭/生育状态变更工具仍可出现

## 软表达工具的兼容处理

部分旧工具没有从 `TOOL_SPECS` 删除，而是隐藏并给出重定向提示，例如：

- `compliment_visible_agent`
- `apologize_to_visible_agent`
- `casual_chat_visible_agent`
- `thank_visible_agent`
- `express_affection_visible_agent`
- `hum_to_self`
- `enjoy_scenery`

这些工具不再进入 agent 菜单。若旧存档或旧输出尝试调用，校验会返回：

```text
这个工具只是表达情绪、喜好、态度或寒暄的旧式细分项。请改用“说一句话 / 向附近说话 / 写私人笔记 / 记录记忆”，把具体情绪和意图直接写在台词或正文里。
```

这能让 LLM 改用通用表达工具，而不是继续依赖细碎工具。

## 测试结果

已通过：

```bash
python -m compileall -q backend/app
```

工具瘦身 / 动态工具：

```bash
PYTHONPATH=backend pytest -q \
  backend/app/tests/test_tool_catalog_audit.py \
  backend/app/tests/test_dynamic_tool_routing.py
```

结果：

```text
16 passed
```

核心回归：

```bash
PYTHONPATH=backend pytest -q \
  backend/app/tests/test_tool_catalog_audit.py \
  backend/app/tests/test_dynamic_tool_routing.py \
  backend/app/tests/test_aohp_protocol.py \
  backend/app/tests/test_agent_simulation_repairs.py \
  backend/app/tests/test_event_ui_safety_and_worldviews.py \
  backend/app/tests/test_event_sanitization_and_memory.py \
  backend/app/tests/test_left_snapshot_refresh.py
```

结果：

```text
48 passed
```

狼人杀 / 世界创建 / LLM 配置 / 插件 / 世界包 / 生存回归：

```bash
PYTHONPATH=backend pytest -q \
  backend/app/tests/test_werewolf_full_game_iteration.py \
  backend/app/tests/test_world_create_api.py \
  backend/app/tests/test_llm_models_api.py \
  backend/app/tests/test_plugins_and_english_mode.py \
  backend/app/tests/test_worldpacks.py \
  backend/app/tests/test_repair_regressions.py \
  backend/app/tests/test_turn_runner_survival.py
```

结果：

```text
33 passed, 2 warnings
```

`test_effects_and_knowledge.py` 单文件在当前环境整文件运行容易超时，因此拆成三段运行，74 个测试均通过：

```text
25 passed
24 passed
25 passed
```

前端构建：

```bash
cd frontend
npm run build
```

结果：

```text
TypeScript 检查通过
Vite build 通过
```

Vite 仍有 chunk size warning，这是体积提示，不是构建失败。

## 未宣称完成的事

本轮完成的是工具目录瘦身、菜单压缩、动态工具可达性回归、表达能力保留。没有宣称每一个剩余工具的真实世界效果都已经逐个完整模拟验证。

后续仍适合继续通过真实模拟日志，继续找“工具存在但效果不真实”“工具出现时机不自然”“工具执行后状态变化不足”的问题。
