# 接口实现状态

本文件只记录“外部内容/插件相关接口”的当前状态。世界观与工具集创作规范见 `docs/WORLDVIEW_TOOLSET_PLUGIN_SPEC.md`。

## 已实现：外部世界观文件导入

- 状态: 已实现最小可用版。
- API: `POST /api/presets/worldpacks/import`
- 前端: 创建页“世界观与工具集”面板里的“导入世界观文件”。
- 支持文件: `.aiworld.json`、`.json`、`.zip`。
- 已实现能力:
  - 校验 `aiworld.world_pack.v1` 世界包。
  - 世界观/工具集进入 `/api/presets` 目录。
  - 创建世界时按外部世界观生成地点、初始物品、私人住所。
  - 外部世界工具注册为工具候选。
  - `builtin.worldpack_declarative` 声明式效果结算资源、经验、等级、flags、属性和事件。

## 部分实现：外部工具集导入

- 状态: 声明式工具已可用；任意代码工具未开放。
- 当前实现:
  - 外部工具集可随世界包导入。
  - `scope=world` 的世界工具集最稳定。
  - `scope=optional`、`agent_special`、`npc` 可进入目录，但复杂分配/自动 NPC 创建仍需后续扩展。
- 当前限制:
  - 不能执行外部 Python/JS。
  - 不能绕过核心可见性、姓名知识、年龄、工具集开关和地点校验。

## 未实现：前端/后端插件代码挂载

- 状态: 未开放。
- 原因: 任意插件代码会带来安全、存档兼容和崩溃恢复问题。
- 推荐替代: 先用 `.aiworld.json` 的 locations/tools/declarative_effect 表达世界观玩法。

## 未实现：Agent TTS

- 状态: 占位。
- 目标: 给单个 agent 绑定本地或云端 TTS，并在事件流或导出 HTML 中播放语音。

## 未实现：历史身份与模型库

- 状态: 占位。
- 当前替代: 人员配置导入导出 zip 已经能保存姓名、外貌、头像、模型、工具模式、特殊工具集和属性。
