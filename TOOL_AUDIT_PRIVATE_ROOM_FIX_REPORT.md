# 工具审计与“私人空间”刷屏修复报告

本轮基于动态工具修复版继续迭代，并合入左侧 live snapshot 刷新链路。

## 聊天记录定位

上传的 `world_a84fdae04286_events_start_end.zip` 中共有 239 条事件，其中 45 条为同类 `tool_failed`：

- `若叶睦想去某个私人空间，但没有直接进去。`
- `八幡海铃想去某个私人空间，但没有直接进去。`

这些事件集中出现在第 2 天 18:24 - 22:09 的夜间阶段，地点多为 `集体宿舍`。这说明问题不是地图里真的有一个叫“私人空间”的场景，而是后端把 `private_room_blocked` 一类校验失败自然化成了过于抽象的公开文本。

## 根因

“私人空间”不是一个真实 Location。它是普通移动/地点工具试图进入他人私人房间、角色房间或未授权特殊房间时的失败文本。旧逻辑把这类失败当作 public event 写入事件流，于是 LLM 反复尝试、前端反复显示，形成刷屏。

## 修复

1. `private_room_blocked` / `not_private_room` / `own_private_room` 等验证失败改为 system-only 事件，给 LLM 纠错，但不进入公开事件流。
2. 保留自然化失败文本，但不再使用“私人空间”这种让玩家误以为有隐藏地点的说法；如需要内部文本，会描述为“在某某房间门前停了停，但没有直接进去”。
3. `ToolValidation` 在私人房间失败时携带 `destination`，便于内部反馈准确说明是哪间房。
4. 普通 `move_to_location` / `wander` 菜单不再把他人私人房间作为普通目标；他人房间只能通过 `knock_private_room`、入室盗窃/抢劫等明确工具进入。
5. 元工具、调试工具、旧目录占位工具不再 agent-facing，也不能被 free-call 执行：
   - `request_more_candidate_tools`
   - `explain_available_tools`
   - `tool_meta_*`
   - `system_*`
   - `tool_move_to_location`
   - `tool_location_enter_room` 等旧抽象目录移动/门控工具
6. 保留已有左侧 live snapshot + 手动刷新链路，防止左侧时间/地点继续被大刷新链路拖住。

## 工具逐项审计

新增/扩展 `backend/app/tests/test_tool_catalog_audit.py`：

- 静态逐项审计所有注册工具是否是 agent-facing、是否有合法 target_policy、是否缺少描述。
- 构造“万能测试大厅”，逐个对所有注册工具注入代表性参数并调用 `validate_tool()`。
- 本轮结果：注册工具 854 个，其中 798 个代表性参数直接通过，56 个被预期的上下文门控拦截，非预期绑定失败 0 个。
- 对典型菜单场景解析 target_choices / text_slot 后重新验证，三组场景各 97 个菜单项均可通过校验。

## 说明

本轮不是“让所有工具强制出现”，而是让工具在合适场景出现，并减少没实际效果、容易误导 LLM 或污染菜单的旧抽象工具。真正需要逐项行为效果测试的工具仍应继续用模拟日志迭代，但这轮已经修掉了一批导致 900+ 工具大面积不可达/误调用的结构性问题。

## 已跑测试

```bash
python -m compileall -q backend/app
PYTHONPATH=backend pytest -vv backend/app/tests/test_tool_catalog_audit.py -q
PYTHONPATH=backend pytest -vv backend/app/tests/test_aohp_protocol.py -q
PYTHONPATH=backend pytest -vv backend/app/tests/test_event_sanitization_and_memory.py -q
PYTHONPATH=backend pytest -vv backend/app/tests/test_left_snapshot_refresh.py -s
PYTHONPATH=backend pytest -q backend/app/tests/test_werewolf_full_game_iteration.py
cd frontend && NODE_OPTIONS=--max-old-space-size=1536 ./node_modules/.bin/tsc -b --pretty false --incremental false
cd frontend && NODE_OPTIONS=--max-old-space-size=1536 ./node_modules/.bin/vite build
```

结果：后端语法编译通过；工具审计 8 passed；AOHP 11 passed；事件清洗/记忆 4 passed；左侧快照 1 passed；狼人杀整局迭代测试 3 passed；前端 TypeScript 检查通过；Vite build 通过。Vite 仍有 chunk size warning，不影响构建。
