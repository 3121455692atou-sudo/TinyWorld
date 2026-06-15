from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


ROOT_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT_DIR / "data"
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.yaml"


def _deep_update(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


@dataclass(slots=True)
class ModelConfig:
    provider: str
    model: str


@dataclass(slots=True)
class Settings:
    world_name: str = "微世界"
    seed: int = 20260531
    initial_agent_count: int = 6
    max_reaction_chain: int = 6
    turn_minutes: int = 10
    llm_default_provider: str = "default"
    llm_base_url: str = ""
    llm_api_key_env: str = "TLW_LLM_API_KEY"
    models: dict[str, ModelConfig] = field(
        default_factory=lambda: {
            "world_agent": ModelConfig("default", "model-name"),
            "world_agent_pro": ModelConfig("default", "model-name"),
            "narrator": ModelConfig("default", "model-name"),
        }
    )
    simulation_autostart: bool = False
    simulation_speed: str = "slow"
    frontend_default_view_mode: str = "omniscient"
    narrator_enabled: bool = True
    narrator_events_per_summary: int = 8
    export_include_debug_logs: bool = False
    database_url: str = f"sqlite:///{DATA_DIR / 'world.sqlite3'}"

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.llm_api_key_env) or os.getenv("OPENAI_API_KEY")

    def model_name(self, alias: str) -> str:
        if alias == "world_agent" and os.getenv("TLW_WORLD_MODEL"):
            return os.environ["TLW_WORLD_MODEL"]
        if alias == "narrator" and os.getenv("TLW_NARRATOR_MODEL"):
            return os.environ["TLW_NARRATOR_MODEL"]
        if alias == "world_agent_pro" and os.getenv("TLW_ALLOW_LEGACY_PRO_ALIAS") == "1" and os.getenv("TLW_PRO_MODEL"):
            return os.environ["TLW_PRO_MODEL"]
        return self.models.get(alias, self.models["world_agent"]).model


DEFAULT_RAW_CONFIG: dict[str, Any] = {
    "world": {
        "name": "微世界",
        "seed": 20260531,
        "initial_agent_count": 6,
        "max_reaction_chain": 6,
        "turn_minutes": 10,
    },
    "llm": {
        "default_provider": "default",
        "base_url": "",
        "api_key_env": "TLW_LLM_API_KEY",
        "models": {
            "world_agent": {"provider": "default", "model": "model-name"},
            "world_agent_pro": {"provider": "default", "model": "model-name"},
            "narrator": {"provider": "default", "model": "model-name"},
        },
    },
    "simulation": {"autostart": False, "speed": "slow"},
    "frontend": {"default_view_mode": "omniscient"},
    "narrator": {"enabled": True, "events_per_summary": 8},
    "export": {"include_debug_logs": False},
}


def load_settings(path: Path | None = None) -> Settings:
    raw = DEFAULT_RAW_CONFIG.copy()
    config_path = path or Path(os.getenv("TLW_CONFIG", DEFAULT_CONFIG_PATH))
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        raw = _deep_update(raw, loaded)

    llm = raw["llm"]
    base_url = os.getenv("TLW_LLM_BASE_URL", llm.get("base_url", DEFAULT_RAW_CONFIG["llm"]["base_url"]))
    models = {
        alias: ModelConfig(provider=value.get("provider", "default"), model=value["model"])
        for alias, value in llm.get("models", {}).items()
    }
    return Settings(
        world_name=raw["world"]["name"],
        seed=int(raw["world"]["seed"]),
        initial_agent_count=int(raw["world"]["initial_agent_count"]),
        max_reaction_chain=int(raw["world"]["max_reaction_chain"]),
        turn_minutes=int(raw["world"]["turn_minutes"]),
        llm_default_provider=llm.get("default_provider", "default"),
        llm_base_url=base_url.rstrip("/"),
        llm_api_key_env=llm.get("api_key_env", "TLW_LLM_API_KEY"),
        models=models,
        simulation_autostart=bool(raw["simulation"].get("autostart", False)),
        simulation_speed=raw["simulation"].get("speed", "slow"),
        frontend_default_view_mode=raw["frontend"].get("default_view_mode", "omniscient"),
        narrator_enabled=bool(raw["narrator"].get("enabled", True)),
        narrator_events_per_summary=int(raw["narrator"].get("events_per_summary", 8)),
        export_include_debug_logs=bool(raw["export"].get("include_debug_logs", False)),
        database_url=os.getenv("TLW_DATABASE_URL", f"sqlite:///{DATA_DIR / 'world.sqlite3'}"),
    )


settings = load_settings()
