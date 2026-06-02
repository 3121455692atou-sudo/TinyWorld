from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import agents, identity_library, interventions, llm, plugins, presets, tools, websocket, worlds
from app.core.database import init_db


app = FastAPI(title="微世界", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(worlds.router)
app.include_router(agents.router)
app.include_router(identity_library.router)
app.include_router(interventions.router)
app.include_router(llm.router)
app.include_router(plugins.router)
app.include_router(presets.router)
app.include_router(tools.router)
app.include_router(websocket.router)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


def frontend_dist_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    candidates = [
        project_root / "frontend" / "dist",
        Path.cwd() / "frontend" / "dist",
    ]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    return candidates[0]


frontend_dist = frontend_dist_path()
if (frontend_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
else:
    @app.get("/")
    def root() -> JSONResponse:
        return JSONResponse({
            "ok": True,
            "frontend": "not built",
            "hint": "Run `npm --prefix frontend install && npm --prefix frontend run build`, then restart the backend.",
            "dev_frontend": "http://127.0.0.1:5174/",
            "health": "/api/health",
        })
