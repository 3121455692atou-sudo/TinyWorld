# TinyWorld NAS Docker

这个目录是给 NAS 直接部署当前 TinyWorld 新版本用的 Docker 项目。

## 启动

```bash
cd /mnt/COM/AIworld/docker/nas
./start-nas.sh
```

启动后打开：

```text
http://NAS_IP:5174/
```

如果在 NAS 本机浏览器访问，也可以用：

```text
http://127.0.0.1:5174/
```

## 配置

第一次启动脚本会自动生成：

- `.env`：端口和模型接口环境变量。
- `config/config.yaml`：项目默认配置。
- `data/`：数据库持久化目录。
- `logs/`：日志持久化目录。

账号使用 NAS 上已有的本地用户登录管理界面或 SSH。密码不要写进 `.env`、`docker-compose.yml` 或提交到 Git。

## 镜像源

部分 NAS 会把 Docker Hub 请求改写到自己的镜像源，可能出现 `docker.fnnas.com ... 401 Unauthorized`。本 compose 默认使用镜像代理前缀：

```text
docker.1ms.run/library/node:22-bookworm-slim
docker.1ms.run/library/python:3.12-slim
```

如果这个镜像源不可用，可以在 `.env` 里把 `NODE_IMAGE` / `PYTHON_IMAGE` 改成：

```text
docker.m.daocloud.io/library/node:22-bookworm-slim
docker.m.daocloud.io/library/python:3.12-slim
```

## 常用命令

```bash
docker compose up -d --build
docker compose logs -f
docker compose down
```
