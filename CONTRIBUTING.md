# Contributing to TinyWorld

TinyWorld welcomes contributions from users, worldpack authors, plugin authors, frontend developers, backend developers, and simulation researchers.

## Reporting Bugs

When reporting a bug, include:

- Operating system and version.
- Python, Node.js, and browser versions.
- Whether you used `start.sh`, `Start.bat`, `scripts/dev.sh`, or manual commands.
- Steps to reproduce.
- Expected behavior and actual behavior.
- Relevant backend/frontend logs, with API keys and private data removed.

Please do not include API keys, provider tokens, private prompts, personal data, databases, or exported logs containing private content.

## Writing Worldpacks

Worldpacks can define worldviews, locations, world-specific prompts, variables, rule parameters, and toolsets.

Good worldpacks should:

- Keep IDs stable.
- Clearly document locations, variables, and rule changes.
- Avoid hardcoding private API endpoints or secrets.
- Include a short description of the intended play style.
- Include at least one small test or example config when possible.

## Writing Plugins

Plugins may extend project behavior and install worldpacks, toolsets, or integration metadata.

Good plugins should:

- Use clear package names and versions.
- Avoid broad filesystem or network assumptions.
- Document required services or third-party APIs.
- Avoid storing secrets inside plugin files.
- Fail gracefully when an optional integration is missing.

## Writing Tools

Tools should separate agent intention from system outcome. The LLM can request an action, but backend rules should validate and apply the result.

When adding tools:

- Define clear parameters.
- Add validation for required targets, locations, state, and permissions.
- Keep visible event text human-readable.
- Avoid leaking mechanical state deltas into player-facing text.
- Add tests for success, failure, and edge cases.

## Writing Tests

Useful tests include:

- AOHP parsing and repair behavior.
- Tool validation.
- Tool execution side effects.
- Worldpack import validation.
- Plugin import behavior.
- Simulation stability over multiple turns.
- Frontend build checks for major UI regressions.

Run:

```bash
uv run pytest
npm --prefix frontend run build
```

## Pull Requests

Before opening a pull request:

- Keep changes focused.
- Run tests and frontend build.
- Do not commit `.env`, `config.yaml`, local databases, exported archives, logs, or generated caches.
- Describe what changed and why.

---

# TinyWorld 贡献指南

TinyWorld 欢迎用户、世界观包作者、插件作者、前端开发者、后端开发者和模拟研究者参与贡献。

## 报告 Bug

报告 bug 时请包含：

- 操作系统和版本。
- Python、Node.js 和浏览器版本。
- 使用的是 `start.sh`、`Start.bat`、`scripts/dev.sh`，还是手动命令。
- 复现步骤。
- 预期行为和实际行为。
- 相关后端/前端日志，并移除 API Key 和私人数据。

请不要提交 API Key、供应商 token、私人提示词、个人数据、数据库，或包含私人内容的导出日志。

## 编写世界观包

世界观包可以定义世界观、地点、世界专属提示词、变量、规则参数和工具集。

好的世界观包应该：

- 保持 ID 稳定。
- 清楚说明地点、变量和规则变化。
- 避免硬编码私人 API 地址或密钥。
- 简短说明预期玩法风格。
- 尽可能提供一个小测试或示例配置。

## 编写插件

插件可以扩展项目行为，并安装世界观包、工具集或集成元数据。

好的插件应该：

- 使用清晰的包名和版本。
- 避免宽泛假设文件系统或网络环境。
- 说明依赖的服务或第三方 API。
- 避免把密钥存进插件文件。
- 在可选集成缺失时优雅失败。

## 编写工具

工具应该区分 agent 意图和系统结果。LLM 可以请求行动，但后端规则必须验证并应用结果。

添加工具时：

- 定义清晰的参数。
- 校验必要目标、地点、状态和权限。
- 保持可见事件文本适合人阅读。
- 避免把机械状态变化泄露进玩家可见文本。
- 为成功、失败和边界情况添加测试。

## 编写测试

有价值的测试包括：

- AOHP 解析和修复行为。
- 工具校验。
- 工具执行副作用。
- 世界观包导入校验。
- 插件导入行为。
- 多轮模拟稳定性。
- 主要 UI 变更后的前端构建检查。

运行：

```bash
uv run pytest
npm --prefix frontend run build
```

## Pull Request

提交 PR 前：

- 保持修改聚焦。
- 运行测试和前端构建。
- 不要提交 `.env`、`config.yaml`、本地数据库、导出归档、日志或生成缓存。
- 说明改了什么，以及为什么改。
