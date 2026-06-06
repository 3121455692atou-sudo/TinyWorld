# 工具关系阶段动态路由修复记录

## 目标

- 保持行动菜单显示上限为 60，不通过降低显示数量掩盖问题。
- 继续删除/屏蔽没有硬状态意义、可以直接用普通台词表达的工具。
- 让关系推进类工具按具体目标的关系阶段显示和排序：陌生/好感为 0 时不显示确认交往；高好感、高信任、高熟悉时确认交往靠前；已经交往/伴侣后，成年亲密、避孕、验孕、生产准备等真正改变世界状态的工具更靠前。

## 核心改动

1. 新增 `app.social.relationship_stage`：集中计算目标关系快照、阶段门槛、菜单上下文和排序权重。
2. 动态工具注册层继续剪掉 `tool_romance_*` / `tool_adult_*` 这类 v5/v6 表达型目录工具，保留核心状态转移工具。
3. `build_action_options` 在展开 visible_ref 工具时，会按目标逐个过滤关系阶段，并按好感/信任/关系状态排序目标。
4. 行动菜单最终 60 项 cap 保留不变，但给高关系阶段工具预留靠前位置。
5. `validate_tool` 增加关系阶段硬校验，避免 LLM 绕过菜单直接调用不该出现的确认交往/成年亲密等工具。
6. 成年亲密语义自动对齐不再因为“世界开启生育系统”就无条件转成成年亲密请求；必须当前菜单真的开放该工具，并且目标关系阶段允许。

## 测试

通过：

```bash
PYTHONPATH=backend uv run python -m compileall -q backend/app
PYTHONPATH=backend uv run pytest -q backend/app/tests/test_dynamic_tool_routing.py backend/app/tests/test_tool_catalog_audit.py backend/app/tests/test_effects_and_knowledge.py
PYTHONPATH=backend uv run pytest -q backend/app/tests/test_agent_simulation_repairs.py backend/app/tests/test_event_ui_safety_and_worldviews.py backend/app/tests/test_werewolf_full_game_iteration.py
```

结果：113 个相关测试通过。
