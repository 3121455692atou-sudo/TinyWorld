# Security Policy

TinyWorld is a local-first simulation project, but it can load plugins, worldpacks, API keys, local data, and model-provider configuration. Treat it as software that may execute code and process private data.

## Secrets and API Keys

- Do not commit `.env`, `config.yaml`, provider API keys, local databases, logs, exported archives, or private prompts.
- Prefer entering provider keys through the local UI or local environment variables.
- If you accidentally publish an API key, revoke it immediately at the provider.

## Plugin and Worldpack Safety

Worldpacks and plugins can change simulation behavior and may introduce new tools or integrations. Only import packages from sources you trust.

Current safety expectations:

- Plugins should not bundle secrets.
- Plugins should clearly describe external network services they require.
- Tool outcomes should be validated by backend logic, not decided only by agent text.
- Imported packages should be reviewed before use in long-running simulations.

The plugin system is still evolving. Do not treat untrusted plugins as sandboxed.

## Sensitive Simulation Content

TinyWorld may simulate conflict, crime, adult relationship systems, debt, social pressure, and other sensitive scenarios depending on enabled tools and worldpacks.

This is simulation content, not advice or instruction. If you build public worldpacks or plugins, document the intended content level and avoid surprising users.

## Reporting Vulnerabilities

Please report security issues privately when possible.

Include:

- Affected version or commit.
- Steps to reproduce.
- Impact.
- Logs or screenshots with secrets removed.

If GitHub private vulnerability reporting is enabled for the repository, use that. Otherwise contact the maintainer through the repository owner profile or open a minimal issue asking for a private contact path without disclosing exploit details.

## Supported Versions

TinyWorld is currently pre-1.0. Security fixes target the latest `main` branch unless a release branch is explicitly announced.

---

# 安全策略

TinyWorld 是本地优先的模拟项目，但它可以加载插件、世界观包、API Key、本地数据和模型供应商配置。请把它当作可能执行代码并处理私人数据的软件对待。

## 密钥和 API Key

- 不要提交 `.env`、`config.yaml`、供应商 API Key、本地数据库、日志、导出归档或私人提示词。
- 优先通过本地 UI 或本地环境变量输入供应商密钥。
- 如果不小心公开了 API Key，请立即到对应供应商处吊销。

## 插件和世界观包安全

世界观包和插件可以改变模拟行为，并可能引入新工具或集成。只导入可信来源的包。

当前安全预期：

- 插件不应该捆绑密钥。
- 插件应该清楚说明它依赖的外部网络服务。
- 工具结果应该由后端逻辑校验，而不是只由 agent 文本决定。
- 长时间模拟前应该先检查导入包。

插件系统仍在演进。不要把不可信插件视为沙盒内运行。

## 敏感模拟内容

根据启用的工具和世界观包，TinyWorld 可能模拟冲突、犯罪、成人关系系统、债务、社会压力和其他敏感场景。

这些是模拟内容，不是建议或指导。如果你构建公开世界观包或插件，请说明预期内容级别，避免给用户带来意外。

## 报告漏洞

请尽可能私下报告安全问题。

请包含：

- 受影响版本或 commit。
- 复现步骤。
- 影响。
- 已移除密钥的日志或截图。

如果仓库启用了 GitHub 私密漏洞报告，请使用该功能。否则请通过仓库所有者资料联系维护者，或开一个最小化 issue 询问私密联系方式，不要公开漏洞细节。

## 支持版本

TinyWorld 当前仍是 1.0 前版本。除非明确宣布发布分支，安全修复默认面向最新 `main` 分支。
