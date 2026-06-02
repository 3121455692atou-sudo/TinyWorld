# TinyWorld

TinyWorld 是一个本地运行的多 Agent 社会模拟器，包含 FastAPI 后端、SQLite 持久化、Vite React 前端、OpenAI-compatible LLM 适配、模块化世界观/工具集、事件流、导出归档与插件接口。

首页有带颜色标注的新手指引；创建世界后，角色会在本地世界里生活、聊天、工作、恋爱、结婚生子，也可以通过插件扩展世界观和工具集。

详细文档请看：https://docs.galbands.com

## 运行方式

TinyWorld 有两种常用运行方式：

- 开发模式：后端 `http://127.0.0.1:8010`，前端 `http://127.0.0.1:5174`。
- 单端口模式：先构建前端，再只启动后端，浏览器打开 `http://127.0.0.1:8010/`。

如果 `8010/` 只返回 JSON，通常说明还没有执行 `npm --prefix frontend run build`，或需要重启后端。

## 通用依赖

- Python 3.11 或更新版本
- Node.js 20 或更新版本
- Git
- uv

安装 uv：

```bash
python -m pip install -U uv
```

## macOS 部署

推荐用 Homebrew 安装依赖：

```bash
brew install git python node
python3 -m pip install -U uv
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
uv sync
npm --prefix frontend install
npm --prefix frontend run build
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010
```

打开：

```text
http://127.0.0.1:8010/
```

开发模式可改用：

```bash
./scripts/dev.sh
```

也可以用桌面启动脚本：

```bash
./scripts/start-desktop.sh
```

它会同时启动后端和前端开发服务器，并在 Linux、macOS、Termux、Git Bash/MSYS 环境下尽量自动打开浏览器。

## Linux 部署

Debian / Ubuntu 示例：

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip nodejs npm
python3 -m pip install -U uv
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
uv sync
npm --prefix frontend install
npm --prefix frontend run build
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010
```

打开：

```text
http://127.0.0.1:8010/
```

如果发行版自带 Node.js 版本太旧，请改用 NodeSource、nvm 或发行版的新版 Node.js 包。

## Windows 部署

在 PowerShell 中执行：

```powershell
winget install Git.Git
winget install Python.Python.3.12
winget install OpenJS.NodeJS.LTS
py -m pip install -U uv
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
uv sync
npm --prefix frontend install
npm --prefix frontend run build
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010
```

打开：

```text
http://127.0.0.1:8010/
```

如果 `uv` 命令找不到，关闭并重新打开 PowerShell，或使用：

```powershell
py -m uv sync
py -m uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010
```

## Android / Termux 部署

安卓纯本机部署适合实验和轻量游玩。长时间模拟会受电量、散热、内存和后台限制影响，建议插电、关闭电池优化，并尽量保持 Termux 在前台或使用唤醒锁。

请从 F-Droid 或 GitHub Releases 安装 Termux，不建议使用 Google Play 中不再维护的旧版本。

在 Termux 中执行：

```bash
termux-change-repo
pkg update && pkg upgrade
pkg install git python nodejs-lts clang make rust openssl libffi sqlite termux-api
```

拉取项目并安装依赖：

```bash
cd ~
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
python -m pip install -U pip wheel setuptools uv
uv sync
npm --prefix frontend install
npm --prefix frontend run build
```

启动：

```bash
export TLW_DATABASE_URL="sqlite:////data/data/com.termux/files/home/TinyWorld/data/world.sqlite3"
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010
```

然后在安卓浏览器打开：

```text
http://127.0.0.1:8010/
```

如果某些 Python 包在 Termux 上安装失败，先确认 `clang`、`rust`、`openssl`、`libffi`、`sqlite` 已安装。32 位安卓设备不建议作为长期运行环境，64 位 Android 设备更适合。

## 模型配置

模型供应商、Base URL 和 API Key 可以在前端填写，也可以复制 `config.example.yaml` 为 `config.yaml` 后自行配置。

请不要把 `config.yaml`、`.env`、数据库、日志或导出归档提交到仓库。

## 常用命令

```bash
uv run pytest
npm --prefix frontend run build
./scripts/start-desktop.sh
./scripts/backend.sh
./scripts/frontend.sh
./scripts/stop.sh
```
