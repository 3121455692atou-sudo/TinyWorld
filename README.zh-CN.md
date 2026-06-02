# 微世界 TinyWorld

微世界是一个本地运行的多 Agent 社会模拟沙盒，用来观察 LLM agent 在长期生活中会如何行动、互动、记忆、工作、恋爱、应对资源压力和遵守或突破规则。

它会给 agent 一个持续存在的世界，包括地点、事件、记忆、关系、资源、工具、经济、住房、世界观规则和社会压力，并通过 Web 前端记录和展示它们的行为。这个项目既可以作为可玩的模拟器，也可以作为观察和评估 LLM agent 长期行为的小型实验环境。

详细文档请看：https://docs.galbands.com

## 主要功能

- 多 Agent 长期生活模拟：居民、地点、事件、记忆、关系、经济、工作、住房、生育、育儿等。
- Web 前端：创建世界、配置角色、查看事件流、检查状态、导出归档、介入世界。
- 世界观导入：通过 worldpack 定义地点、规则、提示词、变量和世界专属工具集。
- 插件和工具系统：可以扩展工具集、世界能力、介入能力和后续集成。
- AOHP 行动协议：agent 行动输出使用行动编号封包，减少 JSON 输出不稳定的问题。
- 本地部署：支持 macOS、Linux、Windows、Android Termux，也可以部署在服务器上。
- OpenAI 兼容接口：可以在前端配置提供商、Base URL、API Key、模型，并为不同 agent 单独选择模型。

## 这个项目有什么意义

普通聊天只能看到模型在单轮或短对话里的表现。微世界更关注长期行为：agent 是否会照顾自己的生活、是否会工作赚钱、是否会回应关系压力、是否会记住重要事件、是否会在规则和诱惑之间做选择、是否能在很多模拟日之后保持一致性。

它可以用于观察资源匮乏、人际冲突、债务、规则约束、工作压力、记忆压缩、社会拒绝、合作、亲密关系和世界观变化对 LLM agent 的影响。


## 快速启动

macOS / Linux / Android Termux：

```bash
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
./start.sh
```

Windows：

```powershell
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
.\Start.bat
```

打开：

```text
http://127.0.0.1:8010/
```

`start.sh` / `Start.bat` 会安装依赖、构建前端并启动后端。第一次启动会慢一些，后续启动会更快。

## 运行要求

- Python 3.11 或更新版本
- Node.js 20 或更新版本
- Git
- uv，快速启动脚本会在缺失时自动安装

## 配置模型

LLM 提供商、Base URL、API Key、模型、解说 agent、每个居民的模型配置，都可以在网页前端里设置。

也可以复制 `config.example.yaml` 为 `config.yaml`，用作本地默认配置。不要提交 `config.yaml`、`.env`、API Key、数据库、日志或导出的归档。

## 部署模式

微世界常用两种运行方式：

- 单端口模式：构建前端，启动后端，然后打开 `http://127.0.0.1:8010/`。
- 开发模式：后端在 `http://127.0.0.1:8010`，Vite 前端在 `http://127.0.0.1:5174`。

如果 `http://127.0.0.1:8010/` 只返回 JSON 而不是前端页面，运行：

```bash
npm --prefix frontend install
npm --prefix frontend run build
```

然后重启后端。

## 各平台说明

macOS：

```bash
brew install git python node
./start.sh
```

Linux：

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip nodejs npm
./start.sh
```

Windows：

```powershell
winget install Git.Git
winget install Python.Python.3.12
winget install OpenJS.NodeJS.LTS
.\Start.bat
```

Android Termux：

```bash
termux-change-repo
pkg update && pkg upgrade
pkg install git python nodejs-lts clang make rust openssl libffi sqlite termux-api
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
./start.sh
```

安卓可以纯本机运行，但稳定性不如电脑或服务器。长时间模拟时建议插电、关闭电池优化，并尽量使用 64 位设备。

## 常用命令

```bash
uv run pytest
npm --prefix frontend run build
./start.sh
./stop.sh
./scripts/dev.sh
```

Windows：

```powershell
.\Start.bat
.\Stop.bat
```

## 项目结构

- `backend/`：FastAPI 后端、模拟循环、工具执行、AOHP 解析、世界状态、导出和 API。
- `frontend/`：Vite React 前端。
- `worldpacks/`：内置和导入的世界观/工具集包。
- `scripts/`：开发和桌面启动脚本。
- `data/`：本地运行数据，已被 git 忽略。

## 参与贡献

欢迎提交 bug、worldpack、插件、工具、测试、UI 改进和模拟评估想法。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 安全说明

微世界支持导入插件，并会在本地保存 LLM 提供商设置。不要公开 API Key、私有配置、数据库、日志或不可信运行数据。详见 [SECURITY.md](SECURITY.md)。

## 路线图

详见 [ROADMAP.md](ROADMAP.md)。

## 许可证

MIT。详见 [LICENSE](LICENSE)。
