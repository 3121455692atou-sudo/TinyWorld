# 左侧时间/地点刷新修复报告（2026-06-05）

这轮不再继续只修 WebSocket 防抖。左侧时间、地点、居民位置改成独立的“左侧实时快照”链路，并保留手动刷新按钮。

## 本轮判断出的关键问题

前端之前把 `world / agents / locations / events` 分成多个请求，并且还会用事件流去推导居民位置。这个兜底逻辑在某些情况下会反过来污染左侧栏：如果事件流或地点快照是旧的，就可能把刚刚从 `/agents` 拉到的新位置又覆盖回旧位置。

所以这轮改动的核心是：

```text
左侧栏不再依赖事件流推导位置。
左侧栏使用后端一次性返回的 live snapshot。
手动刷新按钮直接重拉这个 snapshot。
```

## 新接口

新增：

```text
GET /api/worlds/{world_id}/left-snapshot
```

返回：

```text
world     当前世界时间/状态
agents    当前居民列表和位置
locations 当前地点列表和 occupants
```

这些数据在同一个数据库会话里读取，避免三个接口分别返回不同时间点的快照。

## 前端修复

- `MapPanel` 增加“刷新”按钮。
- 地点面板直接显示当前 `world_time_label`，左侧自己能看到时间。
- 运行中每 1.5 秒自动拉一次 left snapshot；暂停时每 12 秒拉一次。
- WebSocket 收到世界更新时，也会触发 left snapshot。
- 顶部全局刷新仍保留，但左侧刷新不再被叙事、指标、右侧角色详情拖慢。
- `displayAgents` 不再通过事件流强行重算位置，避免旧事件把新位置覆盖回去。

## 同时保留上一轮动态工具修复

这个包也包含动态工具调度修复：目录工具目标推断、v5 全目录上下文评分、场景门控、菜单保底、隐藏候选/调试元工具等。

## 测试

已通过：

```bash
python -m compileall -q backend/app
PYTHONPATH=backend pytest -q backend/app/tests/test_left_snapshot_refresh.py backend/app/tests/test_dynamic_tool_routing.py backend/app/tests/test_aohp_protocol.py
PYTHONPATH=backend pytest -q backend/app/tests/test_agent_simulation_repairs.py backend/app/tests/test_event_ui_safety_and_worldviews.py backend/app/tests/test_event_sanitization_and_memory.py
PYTHONPATH=backend pytest -q backend/app/tests/test_werewolf_full_game_iteration.py backend/app/tests/test_world_create_api.py backend/app/tests/test_llm_models_api.py backend/app/tests/test_plugins_and_english_mode.py backend/app/tests/test_worldpacks.py backend/app/tests/test_repair_regressions.py backend/app/tests/test_turn_runner_survival.py
cd frontend && ./node_modules/.bin/tsc -b --pretty false && ./node_modules/.bin/vite build
```

结果：

```text
左侧快照/动态工具/AOHP：17 passed
事件/照护/安全/记忆回归：20 passed
狼人杀/创建世界/API/插件等：33 passed, 2 warnings
前端 tsc + vite build：passed
```

整目录 pytest 在当前环境里仍然容易超时，所以我拆成多组回归跑。
