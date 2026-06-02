# TinyWorld

TinyWorld 是一个本地运行的多 Agent 社会模拟器，包含 FastAPI 后端、SQLite 持久化、Vite React 前端、OpenAI-compatible LLM 适配、模块化世界观/工具集、事件流、导出归档与插件接口。
本项目的操作非常之简单，首页就有详细到每个步骤都用特殊配色标注的新手指引，哪怕您是一窍不通的新人，也能根据指引轻松游玩。
<img width="2555" height="1314" alt="image" src="https://github.com/user-attachments/assets/ba2604de-dcf3-47d4-8e17-994c76cdd691" />
<img width="2555" height="1314" alt="image" src="https://github.com/user-attachments/assets/0ad287a8-d10f-46a9-9da6-0c891ad6ec69" />
可以创建自己的agent，让它们在这个虚拟世界中生活。
<img width="1626" height="830" alt="image" src="https://github.com/user-attachments/assets/c1a0a7f5-df62-4f6d-b3a4-bd01f440668a" />

agent可以普通的生活，恋爱，结婚生子。
<img width="1507" height="977" alt="image" src="https://github.com/user-attachments/assets/59ca08e2-af9c-4a2a-94d3-058cf0161128" />


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
