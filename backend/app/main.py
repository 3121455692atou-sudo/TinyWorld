from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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


@app.get("/")
def root() -> dict:
    return {"ok": True, "frontend": "http://127.0.0.1:5174/", "health": "/api/health"}


frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
