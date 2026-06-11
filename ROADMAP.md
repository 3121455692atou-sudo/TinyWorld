# TinyWorld Roadmap

This roadmap describes the intended direction. Details may change as the simulation, UI, and plugin ecosystem evolve.

## v1: Single-Machine Multi-Agent Simulation

- Stable local FastAPI backend and React frontend.
- Persistent SQLite world state.
- AOHP action protocol for agent actions.
- Configurable LLM providers and per-agent models.
- Core world simulation with locations, memory, resources, relationships, tools, and exports.
- Basic mobile and desktop support.

## v1.1: Plugin Ecosystem

- Clear plugin package format.
- Better plugin installation and update UI.
- More examples for toolsets, intervention abilities, and integrations.
- Stronger validation for imported packages.
- Safer handling of plugin metadata and external services.

## v1.2: Worldview Market and Sharing

- Better worldpack authoring documentation.
- Example worldpacks for different genres and simulation styles.
- Import/export flows for sharing worlds, characters, toolsets, and presets.
- Better version compatibility checks for worldpacks.

## v1.3: Evaluation and Visualization

- Multi-agent stability benchmarks.
- Survival, social, relationship, and tool-use metrics.
- Visualization for events, relationships, location flow, economy, and failures.
- Reproducible simulation runs for comparing model behavior.

## v2: Distributed Simulation and Cloud Observation

- Multi-process or distributed simulation workers.
- Long-run cloud/server observation mode.
- Multi-user observer UI.
- Better scheduling, persistence, and replay support for very large worlds.

---

# TinyWorld 路线图

这份路线图描述项目的大致方向。随着模拟系统、UI 和插件生态演进，具体细节可能调整。

## v1：单机多 Agent 模拟

- 稳定的本地 FastAPI 后端和 React 前端。
- 持久化 SQLite 世界状态。
- 用于 agent 行动的 AOHP 行动协议。
- 可配置 LLM 提供商和每个 agent 的模型。
- 包含地点、记忆、资源、关系、工具和导出的核心世界模拟。
- 基础移动端和桌面端支持。

## v1.1：插件生态

- 清晰的插件包格式。
- 更好的插件安装和更新 UI。
- 为工具集、介入能力和集成提供更多示例。
- 更强的导入包校验。
- 更安全地处理插件元数据和外部服务。

## v1.2：世界观市场和分享

- 更好的世界观包作者文档。
- 面向不同题材和模拟风格的示例世界观包。
- 用于分享世界、角色、工具集和预设的导入/导出流程。
- 更好的世界观包版本兼容性检查。

## v1.3：评估和可视化

- 多 Agent 稳定性基准。
- 生存、社交、关系和工具使用指标。
- 事件、关系、地点流动、经济和失败情况的可视化。
- 可复现实验运行，用于比较模型行为。

## v2：分布式模拟和云端观察

- 多进程或分布式模拟 worker。
- 长时间云端/服务器观察模式。
- 多用户观察者 UI。
- 面向大型世界的更好调度、持久化和回放支持。
