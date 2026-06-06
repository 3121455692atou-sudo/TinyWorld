# 2026-06-05 前端刷新与狼人杀阶段修复报告

## 本轮重点修复

1. 影响世界面板展开/收起状态
   - `WorldInterventionPanel` 使用明确的 `expanded` 状态、`data-expanded` 和 `toggleLabel`。
   - 展开时按钮显示“收起”，收起时按钮显示“展开”。
   - CSS 增加硬兜底，确保 expanded/collapsed 两种状态不会同时显示错误内容。

2. 顶部时间、地点人数与居民位置刷新
   - WebSocket 刷新从“反复 debounce 清掉旧刷新”改成“节流 + pending 队列”。
   - 连续事件推送不会再导致刷新一直被推迟，时间、地点、居民列表会持续重拉。
   - WebSocket 推送的 world 时间不会覆盖成更旧时间。
   - 地点人数在有后端 occupants 明细时严格使用 occupants.length，不再用 stale occupant_count 取最大值。

3. 事件流机械语言防漏
   - `request_more_candidate_tools` / `explain_available_tools` 产生的候选工具调试事件改为 `visibility_scope="system"`。
   - 列表和导出接口隐藏旧的 `candidate_request` 事件。
   - 后端与前端 sanitizer 增加：当前工具可能不足、隐藏候选、候选工具、解释过滤原因、向系统申请、agent_requested_more_candidates。

4. 狼人杀时间表
   - 默认从旧的 20/45/25/90 分钟调试循环改成真实一天节奏：
     - 08:00-12:00 自由交流
     - 12:00-16:00 圆桌发言
     - 16:00-18:00 公开投票
     - 18:00-次日 08:00 夜间行动
   - 已创建的旧世界如果保存了 20/45/25/90 或总周期过短，也会在读取阶段按新节奏迁移，避免 08:38 就进入圆桌。

5. 狼人杀圆桌发言
   - 圆桌阶段只让当前发言人行动，不再让其他人轮流 do_nothing。
   - 当前发言人走主持式强制提问：要么发言，要么在至少发言一次后结束。
   - 不是强制十次；最多十次，可以提前结束，但至少必须说一次。
   - LLM 没有正确输出时，会兜底生成一条自然发言，避免空场直接投票。
   - `werewolf_end_speech` 在 0 次发言时被后端硬规则拒绝。

6. UI/UX 响应式兜底
   - 增加文本换行/不溢出硬规则。
   - 竖屏下事件流最少占据主要可视区域，侧栏与影响世界面板通过滚动/折叠减少喧宾夺主。
   - 地点居民名单限制高度并自动换行，避免撑爆地点卡片。

## 已执行测试

```bash
python -m compileall -q backend/app
PYTHONPATH=backend pytest -q backend/app/tests
cd frontend && npm ci && npm run build
```

结果：

- 后端语法编译通过。
- 后端全量测试：135 passed，2 warnings。
- 前端生产构建通过。
