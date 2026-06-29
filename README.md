# TinyWorld / 微世界

TinyWorld is a local multi-agent social simulation sandbox.

微世界是一个本地运行的多 Agent 社会模拟沙盒，用来观察 LLM agent 在长期生活、资源压力、人际关系和世界规则下会如何行动。

![TinyWorld setup screen](https://github.com/user-attachments/assets/ba2604de-dcf3-47d4-8e17-994c76cdd691)

![TinyWorld simulation screen](https://github.com/user-attachments/assets/0ad287a8-d10f-46a9-9da6-0c891ad6ec69)

## Choose Language / 选择语言

- [English documentation](README.en.md)
- [中文文档](README.zh-CN.md)
- Contributing: [English](CONTRIBUTING.md) / [中文](CONTRIBUTING.zh-CN.md)
- Roadmap: [English](ROADMAP.md) / [中文](ROADMAP.zh-CN.md)
- Security: [English](SECURITY.md) / [中文](SECURITY.zh-CN.md)

## Quick Start / 快速开始

macOS / Linux / Android Termux:

```bash
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
./start.sh
```

Windows:

先检查 Git、Python、Node.js 和 npm 是否已经安装；能显示版本号的工具不用重复安装，缺哪个装哪个。

First check whether Git, Python, Node.js, and npm are already installed; if a command prints a version, do not reinstall that tool.



```powershell
git --version
python --version
node -v
npm -v
```

下载缺失的工具：Git for Windows、Python 3.12、Node.js LTS。

Download the missing tools: Git for Windows, Python 3.12, and Node.js LTS.

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
 [中文 Windows 从零安装](README.zh-CN.md#windows-从零安装与常见报错)。

 [English Windows setup](README.en.md#windows-from-scratch-and-common-errors).


Detailed documentation / 详细文档：

https://docs.galbands.com

## Docker Compose / Docker Compose 部署

This repository includes a backend-only Docker Compose project in `docker/nas/`.

本仓库内置了一个只构建后端的 Docker Compose 项目，位置是 `docker/nas/`。

Docker Compose does not build or serve the frontend. It runs the FastAPI backend on port `8010`; run the Vite frontend on your computer and point it at the Docker/NAS backend.

Docker Compose 不构建、不托管前端。它只在 `8010` 端口运行 FastAPI 后端；前端请在电脑本地运行，并连接 Docker/NAS 后端。

Backend health check / 后端健康检查：

```text
http://SERVER_OR_NAS_IP:8010/api/health
```

Normal backend build with internet access / 有网络时构建后端：

```bash
cd TinyWorld
docker compose up -d --build
```

NAS or offline backend build / NAS 或离线后端构建：

Use `docker-compose.local-rootfs.yml` only when the package contains `docker/nas/base/python-3.12-slim-rootfs.tar.gz` and `docker/nas/wheelhouse/*.whl`. The GitHub repository does not commit those large generated files.

只有包里带有 `docker/nas/base/python-3.12-slim-rootfs.tar.gz` 和 `docker/nas/wheelhouse/*.whl` 时，才使用 `docker-compose.local-rootfs.yml`。GitHub 仓库不会提交这些生成的大文件。

```bash
cd TinyWorld/docker/nas
./prepare-local-rootfs.sh python:3.12-slim
./prepare-wheelhouse.sh
```

Then upload the whole project directory to the NAS and select `docker-compose.local-rootfs.yml` in the NAS Docker panel.

然后把完整项目目录上传到 NAS，在 NAS Docker 面板里选择 `docker-compose.local-rootfs.yml`。

Run frontend locally / 本地运行前端：

```bash
VITE_API_BASE=http://SERVER_OR_NAS_IP:8010 VITE_WS_BASE=ws://SERVER_OR_NAS_IP:8010 npm --prefix frontend run dev -- --host 127.0.0.1 --port 5174
```

If another device needs to open the frontend, use `--host 0.0.0.0` and open `http://FRONTEND_PC_IP:5174/`.

如果要让局域网里的其他设备打开前端，把 `--host 127.0.0.1` 改成 `--host 0.0.0.0`，然后打开 `http://前端电脑IP:5174/`。

For NAS Docker panels, keep the complete TinyWorld project as the build context. Do not copy only `docker/nas/`.

如果使用 NAS 的 Docker 面板，请保留完整 TinyWorld 项目作为构建上下文。不要只复制 `docker/nas/` 子目录。





## 🤝 Friends / Links

<table border="0">
  <tbody>
    <tr>
      <td width="200" align="center">
        <a href="https://linux.do" target="_blank" style="text-decoration:none;">
          <img src="https://img.shields.io/badge/LINUX.DO-Community-000000?style=for-the-badge&logo=linux&logoColor=white" alt="LINUX.DO" />
        </a>
      </td>
      <td align="left">
        <strong><a href="https://linux.do" target="_blank">LINUX.DO</a></strong><br/>
        真诚、友善、团结、专业，共建你我引以为荣之社区。
      </td>
    
