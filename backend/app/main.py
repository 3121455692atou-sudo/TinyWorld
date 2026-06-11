from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import agents, identity_library, interventions, llm, plugins, presets, storage, tools, websocket, worlds
from app.core.database import init_db
from app.image_generation.service import resume_pending_image_generations


app = FastAPI(title="微世界", version="0.1.0")


DEFAULT_CORS_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
]

DEFAULT_CORS_ORIGIN_REGEX = (
    r"^https?://("
    r"(localhost|127\.0\.0\.1)"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?$"
)


def csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def cors_origin_regex() -> str | None:
    value = os.getenv("TLW_CORS_ORIGIN_REGEX")
    if value is None or not value.strip():
        return DEFAULT_CORS_ORIGIN_REGEX
    value = value.strip()
    if value.lower() in {"0", "false", "none", "off"}:
        return None
    return value


app.add_middleware(
    CORSMiddleware,
    allow_origins=DEFAULT_CORS_ORIGINS + csv_env("TLW_CORS_ORIGINS"),
    allow_origin_regex=cors_origin_regex(),
    allow_credentials=True,
    allow_private_network=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_private_network_access_header(request, call_next):
    response = await call_next(request)
    if request.headers.get("access-control-request-private-network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


app.include_router(worlds.router)
app.include_router(agents.router)
app.include_router(identity_library.router)
app.include_router(interventions.router)
app.include_router(llm.router)
app.include_router(plugins.router)
app.include_router(presets.router)
app.include_router(storage.router)
app.include_router(tools.router)
app.include_router(websocket.router)


@app.on_event("startup")
async def startup() -> None:
    init_db()
    resume_pending_image_generations()


@app.get("/api/health")
def health() -> dict:
    from app.content.presets import preset_catalog

    catalog = preset_catalog()
    return {
        "ok": True,
        "catalog": {
            "worldviews": len(catalog.get("worldviews") or []),
            "world_toolsets": len(catalog.get("world_toolsets") or []),
            "core_toolsets": len(catalog.get("core_toolsets") or []),
            "optional_toolsets": len(catalog.get("optional_toolsets") or []),
            "agent_special_toolsets": len(catalog.get("agent_special_toolsets") or []),
        },
    }


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
