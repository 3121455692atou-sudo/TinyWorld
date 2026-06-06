# Werewolf / LLM / UI Refresh Fix Report

本轮基于 `AIworld-core-code-20260605-left-refresh-fix.zip` 继续修复，重点处理狼人杀机制、左侧栏刷新、LLM 模型配置 UI、流式配置和多人台词显示。

## 前端左侧栏刷新

- `world`、`agents`、`locations`、`events` 四类关键快照改成各自返回后立即落地，不再等一个大 `Promise.all` 或全量刷新链路一起完成。
- 世界时钟可以由 `/world` 快照、WebSocket 推送的世界摘要、最新事件时间三层共同兜底。
- 地点人数优先从 live agent `location_id` 计算，避免后端地点快照滞后时把旧人数锁在左侧栏。
- 选中角色详情、叙事、指标等慢数据独立刷新，不再阻塞左侧时钟、地点、事件流。

## 狼人杀机制

- 第 1 天白天只自由交流，不进入圆桌发言，不进入投票。
- 第 1 天夜晚开始后，狼人、预言家、守卫、验尸官等夜间能力才可用。
- 第 2 天开始才进入正式圆桌讨论和公开投票。
- 圆桌发言改为主持式流程：当前发言人至少说一次、最多说十次，可以提前结束。
- 发言后其他存活玩家可以选择反驳或跳过。
- 发生反驳后，双方最多来回回应 5 次，超过后系统自然暂停争论，再继续主持流程。
- 圆桌发言、反驳、回怼不消耗世界分钟；事件时间显示为“第N天 圆桌讨论”，不显示具体钟点。
- 第 2 天起投票不再提供“今天不放逐任何人”的常规选项。
- 观察者可以在角色详情中看到狼人杀身份。

## LLM 模型与生成设置

- 修复“拉取到模型却仍显示尚未拉取模型”的状态覆盖问题。
- 修复“提供商已经改名为哈基米，但下拉仍显示新提供商”的 stale provider 覆盖问题。
- 添加全局和单 Agent 的 LLM 生成设置：流式/非流式、temperature、top_p、max_tokens、presence_penalty、frequency_penalty。
- 生成设置默认折叠，避免模型配置页面继续变得臃肿。
- OpenAI-compatible 客户端支持非流和 SSE 流式响应。

## 事件流显示

- 多人讲话/自我介绍不再强行显示成 `说话者 → 单一目标`。
- 如果事件 payload 带 `addressed_agent_ids` 且人数大于 1，前端会渲染成群体发言，不再误显示单人箭头。
- 角色台词继续走 `payload.speech` / `payload.dialogue_lines`，旁白不夹角色话。

## 测试

已执行：

```bash
python -m compileall -q backend/app
PYTHONPATH=backend pytest -q backend/app/tests
cd frontend && npm run build
```

结果：

- 后端语法编译通过。
- 后端全量测试通过：138 passed, 2 warnings。
- 前端生产构建通过。
- Vite 仍有 chunk size warning，这是体积提示，不是构建失败。
