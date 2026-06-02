# AIworld 世界观导入与创作规范优化报告

本包针对“让后来者更轻松、更自由地创作新世界观”做了一次结构化优化。核心原则是：**世界观必须是外部可导入文件，而不是写死在核心代码里**。

## 1. 本次新增的核心能力

### 1.1 外部世界包加载器

新增文件：

```text
backend/app/content/worldpacks.py
```

能力：

- 支持 `.aiworld.json` / `.json` / `.zip` 世界包。
- 校验 `format = aiworld.world_pack.v1`。
- 自动扫描：
  - `worldpacks/`
  - `docs/worldpacks/`
  - `backend/app/content/worldpacks/`
  - `worldpacks/imported/`
  - 环境变量 `AIWORLD_CONTENT_PACK_DIRS`
- 支持运行时导入并刷新目录。
- 向 preset catalog 合并外部 worldviews / toolsets。

### 1.2 世界观导入 API

修改文件：

```text
backend/app/api/presets.py
pyproject.toml
```

新增接口：

```text
POST /api/presets/worldpacks/import
```

上传字段名：`file`

返回：

- `ok`
- `pack`
- `registered_tool_count`
- `catalog`

### 1.3 前端导入入口

修改文件：

```text
frontend/src/app/App.tsx
frontend/src/api/client.ts
frontend/src/api/types.ts
```

新增：

- 创建世界页可直接上传世界观文件。
- 导入后自动刷新世界观/工具集目录。
- 如果世界包提供 `default_create_settings`，会自动切换生存难度、可选工具集和世界工具集。

### 1.4 创建世界时按外部世界观生成地图

修改文件：

```text
backend/app/world/seed_world.py
backend/app/api/worlds.py
```

外部世界观现在可以声明：

- `locations`
- `initial_items`
- `private_home_template`
- `time_model.start_minute`
- `prompt_blocks`
- `mechanics`
- `default_create_settings`

创建世界时会使用这些内容生成新世界，而不是始终写入默认现代小镇。

### 1.5 声明式世界工具

修改文件：

```text
backend/app/tools/tool_specs.py
backend/app/tools/registry.py
backend/app/tools/validators.py
backend/app/effects/effect_engine.py
backend/app/effects/worldpack_effects.py
```

外部世界包可以定义工具：

- 工具名称、显示名、LLM 描述。
- 当前地点 tag 限制。
- 目标策略：无目标、可见对象、已知姓名、物品、地点。
- 消耗资源、要求资源、获得资源。
- 经验、等级、flag。
- agent / target 属性变化。
- 随机 outcome。
- 事件文本、重要性、颜色、事件类型。

这些工具会进入后端 `TOOL_SPECS`，并参与原本的工具候选过滤。外部包不能绕过核心规则，比如可见性、目标、姓名知识、地点、年龄、工具集开关等。

### 1.6 世界观状态注入 prompt

修改文件：

```text
backend/app/knowledge/perception.py
```

每回合 prompt 现在会加入：

```text
【世界观特有规则】
```

包含：

- 世界观名称。
- 世界包 prompt_blocks。
- 当前 agent 在该世界观下的资源、等级、flags。

这样 agent 不会只看到一堆工具名，而是知道自己正处于什么世界、应该追求什么、资源有什么含义。

## 2. 创作规范文档优化

重写文件：

```text
docs/WORLDVIEW_TOOLSET_PLUGIN_SPEC.md
```

现在它不再只是“未来占位说明”，而是面向创作者的实际规范，包含：

- 单文件 / zip 世界包格式。
- 根字段说明。
- ID 命名规则。
- worldviews 字段说明。
- toolsets 字段说明。
- locations 写法。
- private_home_template 写法。
- default_create_settings 写法。
- prompt_blocks 写法。
- declarative_effect 写法。
- 随机 outcome 写法。
- 资源/经验/等级/flag 设计边界。
- 如何做轻松童话世界。
- 如何做 RPG 抽象世界。
- 如何避免把世界观写死进代码。
- 验收清单。

同时更新：

```text
docs/PLACEHOLDER_INTERFACES.md
```

明确哪些接口已经可用，哪些仍是占位。

## 3. 外部世界包

当前项目不再内置示例外部世界包。外部包应由用户通过前端导入，导入后保存到 `worldpacks/imported/`，不会被视为默认世界观或默认工具集的一部分。

## 4. 本包能测试什么

你现在可以测试：

1. 打开创建世界页。
2. 点击“导入世界观文件”。
3. 上传 `.aiworld.json`。
4. 看它是否进入世界观下拉框。
5. 创建世界。
6. 检查地图是否按外部包生成。
7. 检查 agent prompt 是否出现世界观规则。
8. 检查地点工具是否出现外部工具。
9. 检查工具执行后是否写入事件、资源、经验、等级、flags。

## 5. 验证结果

在这份裁剪代码包上已验证：

```text
python -m compileall -q backend/app
```

通过。

说明：外部世界包不应放进项目默认包目录长期随项目发布；需要测试时通过导入接口安装，测试结束后可以删除 `worldpacks/imported/` 中对应文件。

## 6. 后续建议

下一步可以继续扩展：

- 支持外部包定义系统 NPC。
- 支持外部包定义图标、主题色、前端 UI 标签。
- 支持导入后在前端预览地点图。
- 支持世界包热卸载。
- 支持更复杂的声明式战斗回合状态机。
- 支持世界包自带 prompt 测试用例。
