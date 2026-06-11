# TinyWorld NAS Docker

这个目录是给 NAS 直接部署当前 TinyWorld 后端用的 Docker 项目。

NAS 构建包采用 Python-only Dockerfile：只构建 FastAPI 后端，不构建、不打包、不托管前端。NAS 构建时只拉 Python 镜像并安装后端依赖，不会拉 Node 镜像，也不会执行 `npm ci`。

## NAS Docker 项目导入

如果 NAS 不能稳定访问 Docker registry，推荐使用随包携带 Python rootfs 的离线基础镜像构建方式。把整个项目目录上传到 NAS，然后在 NAS 的 Docker/Container Manager 里选择项目根目录的：

```text
docker-compose.local-rootfs.yml
```

这个 compose 会使用 `docker/nas/Dockerfile.local-rootfs`，从 `docker/nas/base/python-3.12-slim-rootfs.tar.gz` 展开 Python 基础系统，不需要拉取 `python:3.12-slim`。数据保存到：

```text
docker/nas/data
docker/nas/logs
docker/nas/debug_exports
docker/nas/config
worldpacks/imported
```

如果 NAS 的项目界面只允许选择 `docker/nas` 子目录，也可以选择本目录里的：

```text
docker-compose.local-rootfs.yml
```

两种方式的容器端口都是 `8010`，默认映射到 NAS 的 `8010`。这是后端 API 端口，不是前端网页端口。

注意：GitHub 仓库不提交 `docker/nas/base/python-3.12-slim-rootfs.tar.gz` 和 `docker/nas/wheelhouse/*.whl` 这些生成文件。使用 GitHub 源码自行部署时，需要先在能联网的电脑上运行 `./prepare-local-rootfs.sh python:3.12-slim` 和 `./prepare-wheelhouse.sh`；使用已经打好的 NAS 离线包时，这些文件已经包含在包内。

## 本机命令启动

```bash
cd /mnt/COM/AIworld/docker/nas
./start-nas.sh
```

启动后检查后端：

```text
http://NAS_IP:8010/api/health
```

前端在电脑本地运行，并连接 NAS 后端：

```bash
VITE_API_BASE=http://NAS_IP:8010 VITE_WS_BASE=ws://NAS_IP:8010 npm --prefix frontend run dev -- --host 127.0.0.1 --port 5174
```

如果需要从局域网内其他设备打开这台电脑上的前端，把 `--host 127.0.0.1` 改成 `--host 0.0.0.0`，然后访问 `http://电脑IP:5174/`。后端默认允许 localhost 和私有局域网来源；需要收紧或扩展时可在 `.env` 里设置 `TLW_CORS_ORIGINS` 或 `TLW_CORS_ORIGIN_REGEX`。

## 配置

第一次启动脚本会自动生成：

- `.env`：端口和模型接口环境变量。
- `config/config.yaml`：项目默认配置。纯 Docker UI 启动时，容器也会在这个文件不存在时自动生成。
- `data/`：数据库持久化目录。
- `logs/`：日志持久化目录。
- `debug_exports/`：调试导出目录。

账号使用 NAS 上已有的本地用户登录管理界面或 SSH。密码不要写进 `.env`、`docker-compose.yml` 或提交到 Git。

## 镜像源与自动换源

`FROM python:3.12-slim` 发生在 Dockerfile 执行前，Dockerfile 内部不能捕获“下载卡住”并自动换源。能自动换源的是外层脚本：

```bash
cd docker/nas
./build-with-mirrors.sh
```

脚本会按 `.env` 里的 `PYTHON_IMAGE_FALLBACKS` 轮流尝试，每个镜像源最多等待 `PYTHON_IMAGE_BUILD_TIMEOUT` 秒。

默认候选：

```text
python:3.12-slim
docker.m.daocloud.io/library/python:3.12-slim
docker.1panel.live/library/python:3.12-slim
docker.1ms.run/library/python:3.12-slim
```

如果使用 NAS 图形界面而不是命令行，图形界面通常不会执行这个脚本。此时直接选择 `docker-compose.local-rootfs.yml`，让构建不拉基础镜像。

要重新生成离线 rootfs 文件，在能拉到 Python 镜像的电脑上运行：

```bash
cd docker/nas
./prepare-local-rootfs.sh python:3.12-slim
```

## 常用命令

```bash
docker compose up -d --build
./build-with-mirrors.sh
docker compose logs -f
docker compose down
```
