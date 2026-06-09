# TinyWorld / 微世界

TinyWorld is a local multi-agent social simulation sandbox.

微世界是一个本地运行的多 Agent 社会模拟沙盒，用来观察 LLM agent 在长期生活、资源压力、人际关系和世界规则下会如何行动。

![TinyWorld setup screen](https://github.com/user-attachments/assets/ba2604de-dcf3-47d4-8e17-994c76cdd691)

![TinyWorld simulation screen](https://github.com/user-attachments/assets/0ad287a8-d10f-46a9-9da6-0c891ad6ec69)

## Choose Language / 选择语言

- [English documentation](README.en.md)
- [中文文档](README.zh-CN.md)

## Quick Start / 快速开始

macOS / Linux / Android Termux:

```bash
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
./start.sh
```

Windows:

First install Git for Windows, Python 3.12, and Node.js LTS. See [中文 Windows 从零安装](README.zh-CN.md#windows-从零安装与常见报错) or [English Windows setup](README.en.md#windows-from-scratch-and-common-errors) if `git clone`, `python`, or `npm` is not recognized.

Check first; if these commands print version numbers, you do not need to install them again:

```powershell
git --version
python --version
node -v
npm -v
```

- Git for Windows: https://git-scm.com/download/win
- Python 3.12: https://www.python.org/downloads/windows/
- Node.js LTS: https://nodejs.org/

```powershell
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
.\Start.bat
```

Open / 打开：

```text
http://127.0.0.1:8010/
```

Detailed documentation / 详细文档：

https://docs.galbands.com

## Docker Compose / Docker Compose 部署

This repository includes a local source-build Docker Compose project in `docker/nas/`.

本仓库内置了一个本地源码构建用的 Docker Compose 项目，位置是 `docker/nas/`。

```bash
cd TinyWorld/docker/nas
cp .env.example .env
./start-nas.sh
```

Open / 打开：

```text
http://SERVER_OR_NAS_IP:5174/
```

For NAS Docker panels, select `docker/nas/docker-compose.yml` and keep the complete TinyWorld project as the build context. Do not copy only `docker/nas/`.

如果使用 NAS 的 Docker 面板，请选择 `docker/nas/docker-compose.yml`，并保留完整 TinyWorld 项目作为构建上下文。不要只复制 `docker/nas/` 子目录。
