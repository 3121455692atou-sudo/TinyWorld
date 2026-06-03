from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings


router = APIRouter(prefix="/api/llm", tags=["llm"])


class PullModelsRequest(BaseModel):
    base_url: str = Field(default=settings.llm_base_url, max_length=300)
    api_key: str | None = Field(default=None, max_length=4000)


def _model_id_from_item(item: object) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if not isinstance(item, dict):
        return None
    for key in ("id", "name", "model"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_model_ids(data: object) -> list[str]:
    if isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        candidates = []
        for key in ("models", "data"):
            value = data.get(key)
            if isinstance(value, list):
                candidates = value
                break
        if not candidates:
            single = _model_id_from_item(data.get("model")) or _model_id_from_item(data.get("id"))
            return [single] if single else []
    else:
        return []

    seen: set[str] = set()
    models: list[str] = []
    for item in candidates:
        model_id = _model_id_from_item(item)
        if model_id and model_id not in seen:
            seen.add(model_id)
            models.append(model_id)
    return models


@router.post("/models")
async def pull_models(payload: PullModelsRequest) -> dict:
    api_key = payload.api_key or settings.api_key
    if not api_key:
        raise HTTPException(400, "API key is required")
    base_url = payload.base_url.rstrip("/")
    if not base_url:
        raise HTTPException(400, "Base URL is required")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(400, f"Failed to pull models: {exc}") from exc
    return {"models": extract_model_ids(data)}
