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

## 截图
<img width="1632" height="727" alt="image" src="https://github.com/user-attachments/assets/f95035d5-6d7b-4dec-82ed-f647eedda2c4" />

<img width="1507" height="977" alt="image" src="https://github.com/user-attachments/assets/3002098f-be51-4349-a3be-ca1d496bc31e" />


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

Windows（第一次使用请先安装 Git、Python、Node.js；如果 `git clone` 直接报错，先看下方“Windows 从零安装与常见报错”）：

先在 PowerShell 里检查电脑是否已经装好这些工具：

```powershell
git --version
python --version
node -v
npm -v
```

这些命令都能显示版本号的话，可以直接运行下面的 `git clone` 和 `.\Start.bat`，不用重复安装。哪个命令提示“不是内部或外部命令”或“command not found”，就安装对应工具。

Windows 工具下载：

- Git for Windows：https://git-scm.com/download/win
- Python 3.12：https://www.python.org/downloads/windows/
- Node.js LTS：https://nodejs.org/

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
- Docker Compose 模式：使用 `docker/nas/` 目录里的 compose 文件在本机、服务器或 NAS 上构建并运行后端镜像；前端不进入 Docker。

如果 `http://127.0.0.1:8010/` 只返回 JSON 而不是前端页面，运行：

```bash
npm --prefix frontend install
npm --prefix frontend run build
```

然后重启后端。

## Docker Compose 部署

仓库内置了一个 Docker Compose 项目，位置是 `docker/nas/`。这个 compose **只构建和运行后端**：不会构建前端，不会拉 Node 镜像，不会执行 `npm ci`，也不会在容器里托管网页。

有网络、可以拉 Docker 基础镜像的机器可以直接在项目根目录运行：

```bash
cd TinyWorld
docker compose up -d --build
```

```bash
cd TinyWorld/docker/nas
cp .env.example .env
./start-nas.sh
```

也可以不用脚本，直接执行：

```bash
cd TinyWorld/docker/nas
mkdir -p config data logs
cp ../../config.example.yaml config/config.yaml
docker compose up -d --build
```

启动后打开：

```text
http://服务器或NAS的IP:8010/api/health
```

前端请在电脑本地运行，并连接 Docker/NAS 后端：

```bash
VITE_API_BASE=http://服务器或NAS的IP:8010 VITE_WS_BASE=ws://服务器或NAS的IP:8010 npm --prefix frontend run dev -- --host 127.0.0.1 --port 5174
```

如果只在运行前端的这台电脑上打开网页，保留 `--host 127.0.0.1` 即可。如果要让局域网里的手机、平板或另一台电脑打开前端，把命令里的 `--host 127.0.0.1` 改成 `--host 0.0.0.0`，然后在其他设备上访问：

```text
http://前端电脑IP:5174/
```

`.env` 里可以改后端端口和默认模型接口，例如 `AIWORLD_BACKEND_PORT`、`TLW_LLM_BASE_URL`、`TLW_LLM_API_KEY`、`TLW_WORLD_MODEL`、`TLW_PRO_MODEL`。不要把 `.env`、`config/`、`data/`、`logs/` 提交或公开。

如果 NAS 的 Docker 面板支持“从 compose 构建”，请选择 `docker/nas/docker-compose.yml`，并把构建上下文保持为完整 TinyWorld 项目目录。只复制 `docker/nas/` 这个子目录是不够的，因为 Dockerfile 需要读取 `backend/`、`worldpacks/`、`pyproject.toml` 和 `uv.lock`。

如果 NAS 拉取 `python:3.12-slim` 卡住，说明卡在 Dockerfile 执行前的基础镜像下载阶段，Dockerfile 内部不能自动换源。命令行部署可以运行 `docker/nas/build-with-mirrors.sh` 轮流尝试 `PYTHON_IMAGE_FALLBACKS`。

封闭 NAS 或无法访问 Docker Hub 的 NAS 请使用离线 rootfs 方式：先在一台能联网、能拉镜像的电脑上生成离线构建材料，再把完整项目目录上传到 NAS。

```bash
cd TinyWorld/docker/nas
./prepare-local-rootfs.sh python:3.12-slim
./prepare-wheelhouse.sh
```

生成后应存在：

```text
docker/nas/base/python-3.12-slim-rootfs.tar.gz
docker/nas/wheelhouse/*.whl
```

然后在 NAS Docker 面板里选择 `docker-compose.local-rootfs.yml`。GitHub 仓库不会提交这些大文件；如果你拿到的是已经打好的 NAS 离线包，包内会直接包含这些文件。

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

### Windows 从零安装与常见报错

Windows 电脑通常没有预装 Git、Python 和 Node.js。第一次部署时请先安装这三个工具，安装完成后关闭所有 PowerShell / CMD 窗口，再重新打开一个新的 PowerShell。

先检查电脑上是否已经安装：

```powershell
git --version
python --version
node -v
npm -v
```

能显示版本号的工具不用重复安装。缺哪个装哪个；如果不确定，就按下面顺序安装缺失项。

推荐安装方式：

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id OpenJS.NodeJS.LTS -e
```

如果 `winget` 不存在，手动下载安装：

- Git for Windows：https://git-scm.com/download/win
- Python 3.12：https://www.python.org/downloads/windows/
- Node.js LTS：https://nodejs.org/

安装时注意：

- Git 安装器里保留默认选项即可，确保 Git 会加入 PATH。
- Python 安装器第一页勾选 `Add python.exe to PATH`。
- Node.js 安装器保留默认选项即可，它会同时安装 `node` 和 `npm`。

安装完成后重新打开 PowerShell，检查工具是否可用：

```powershell
git --version
python --version
node -v
npm -v
```

然后下载并启动项目：

```powershell
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
.\Start.bat
```

常见报错：

- `git` 不是内部或外部命令 / `git: command not found`：没有安装 Git，或安装后没有重新打开 PowerShell。安装 Git for Windows 后重新打开终端再试。
- `winget` 不是内部或外部命令：系统没有 winget，请改用上面的手动下载链接。
- `Python was not found`、`python` 打开 Microsoft Store，或脚本提示需要 Python：重新安装 Python，并勾选 `Add python.exe to PATH`；也可以在 Windows“应用执行别名”里关闭 Python 的 Microsoft Store 别名。
- `Node.js/npm is required` 或 `npm` 不是内部或外部命令：安装 Node.js LTS，安装后重新打开 PowerShell。
- `git clone` 下载很慢或中断：先确认网络能访问 GitHub；也可以在 GitHub 页面点 `Code` -> `Download ZIP` 下载源码，解压后在解压目录运行 `.\Start.bat`。
- `npm install`、`pip install` 或 `uv sync` 超时：通常是网络或代理问题。换网络、配置系统代理后重试；中国大陆网络可以临时执行 `npm config set registry https://registry.npmmirror.com` 后再运行 `.\Start.bat`。
- `address already in use`、`WinError 10048` 或端口被占用：换一个后端端口再启动：

```powershell
$env:BACKEND_PORT = "8011"
.\Start.bat
```

启动成功后浏览器打开：

```text
http://127.0.0.1:8010/
```

如果改用了 `BACKEND_PORT=8011`，就打开 `http://127.0.0.1:8011/`。

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

欢迎提交 bug、worldpack、插件、工具、测试、UI 改进和模拟评估想法。详见 [贡献指南](CONTRIBUTING.zh-CN.md)。

## 安全说明

微世界支持导入插件，并会在本地保存 LLM 提供商设置。不要公开 API Key、私有配置、数据库、日志或不可信运行数据。详见 [安全策略](SECURITY.zh-CN.md)。

## 路线图

详见 [路线图](ROADMAP.zh-CN.md)。

## 许可证

MIT。详见 [LICENSE](LICENSE)。
