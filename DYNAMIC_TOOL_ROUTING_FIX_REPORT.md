# 动态工具调度修复报告（2026-06-05）

本轮修复重点不是给某几个工具单独打补丁，而是修动态工具链路：目录工具注册 → 场景/状态过滤 → 候选工具排序 → AOHP 菜单展开 → 最终菜单 cap。

## 主要根因

1. 目录工具目标类型推断错误。旧逻辑把 `visible_when_zh` 当成参数绑定规则使用，导致很多“只是在某地点可用”的工具被误判为需要地点参数；同时把“无需姓名”误判为“需要已知姓名”。结果是大量工具要么进不了菜单，要么进了菜单也被校验层拒绝。

2. v5 目录工具只从前几十个工具里抽候选，900+ 工具中绝大多数永远没有进入候选集。

3. 后端动态工具 cap 和前端 AOHP action cap 双重截断，先截断一次、展开后再截断一次，很多场景专属/照护/工作/学习/金融/医疗工具被普通社交工具挤掉。

4. 元工具/调试工具仍可能进入行动菜单，导致“当前工具可能不足、申请更多候选”这类机械语言泄漏到用户可见事件里。

## 本轮修复

- 重写目录工具目标推断：只使用明确 target_rule 或非常明确的工具 id 后缀判断 `visible_ref / known_name / location / item`，不再用可见条件推断参数。
- v5 目录工具改成全目录扫描 + 上下文评分，不再只取前 32 个。
- 增加场景门控：食堂工具主要在食堂/食物场景，医疗身体工具在医务室更靠前，图书馆学习/记忆工具更靠前，警察/法院/受害者工具只有真实案件上下文才出现。
- 增加成人/生育相关工具的上下文门控：不加额外安全提示词，只根据关系、待处理亲密请求、亲密会话、地点等游戏状态决定是否进入菜单，避免初次见面广场被成人工具挤占。
- 增加菜单保底：移动、生存、金融探索、医疗照护、婴儿照护、昏倒救助等关键工具不会被目录工具挤掉。
- 隐藏 `request_more_candidate_tools` / `explain_available_tools` 等调试/候选说明工具，避免公开事件流显示机械语言。
- 新增 `test_dynamic_tool_routing.py`，覆盖目标推断、广场社交、食堂饥饿、医务室治疗、图书馆学习、可见目标绑定、成人工具关系上下文恢复等场景。

## 实测场景

手动审计过这些场景的菜单：

- 中央广场普通状态：社交、群聊、观察、移动、公共发言可见；元工具和成人目录工具不再挤占初见菜单。
- 食堂饥饿状态：吃饭、求食物、饮水、食堂/食物工具可见。
- 医务室低健康状态：体检、清洗、身体治疗、休息类工具可见；食堂/集市/客服/警务噪声被过滤。
- 图书馆高好奇状态：阅读、写日记、记忆总结、学习/创作类工具可见；警务/受害者/法院噪声被过滤。
- 昏倒救助回归：`help_visible_agent` / `escort_visible_agent_to_medical` 不会被动态目录工具挤掉。

## 测试命令

已通过：

```bash
python -m compileall -q backend/app
PYTHONPATH=backend pytest -q backend/app/tests/test_dynamic_tool_routing.py
PYTHONPATH=backend pytest -q backend/app/tests/test_aohp_protocol.py backend/app/tests/test_dynamic_tool_routing.py backend/app/tests/test_agent_simulation_repairs.py backend/app/tests/test_event_ui_safety_and_worldviews.py backend/app/tests/test_event_sanitization_and_memory.py
PYTHONPATH=backend pytest -q backend/app/tests/test_werewolf_full_game_iteration.py backend/app/tests/test_world_create_api.py backend/app/tests/test_llm_models_api.py backend/app/tests/test_plugins_and_english_mode.py backend/app/tests/test_worldpacks.py backend/app/tests/test_repair_regressions.py backend/app/tests/test_turn_runner_survival.py
```

测试结果：

- 动态工具专项：7 passed
- 第一组定向回归：38 passed
- 第二组定向回归：33 passed, 2 warnings
- 后端编译：passed

尝试过整目录 `pytest backend/app/tests`，执行环境超时；超时前没有看到失败。对超时前后拆分的关键文件做了定向回归。

## 仍建议后续继续迭代的方向

这轮是大面积结构性修复，不是逐个手工验证全部 900+ 工具。后续最有效的迭代方式是：继续用真实游玩日志抽样，统计“进入菜单但校验失败”“长期从不进入菜单”“进入了但不合场景”的工具，再按工具族补场景标签和评分规则。
