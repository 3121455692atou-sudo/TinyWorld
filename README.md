# TinyWorld

TinyWorld 是一个本地运行的多 Agent 社会模拟器，包含 FastAPI 后端、SQLite 持久化、Vite React 前端、OpenAI-compatible LLM 适配、模块化世界观/工具集、事件流、导出归档与插件接口。

详细文档请看：https://docs.galbands.com

## 快速运行

```bash
uv sync
npm --prefix frontend install
./scripts/dev.sh
```

前端默认在 `http://127.0.0.1:5174`，后端默认在 `http://127.0.0.1:8010`。

## 配置

模型供应商和 API Key 可以在前端填写，也可以复制 `config.example.yaml` 为 `config.yaml` 后自行配置。请不要把 `config.yaml`、`.env`、数据库、日志或导出归档提交到仓库。

## 常用命令

```bash
uv run pytest
npm --prefix frontend run build
./scripts/stop.sh
```
