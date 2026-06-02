from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings


router = APIRouter(prefix="/api/llm", tags=["llm"])


class PullModelsRequest(BaseModel):
    base_url: str = Field(default=settings.llm_base_url, max_length=300)
    api_key: str | None = Field(default=None, max_length=4000)


@router.post("/models")
async def pull_models(payload: PullModelsRequest) -> dict:
    api_key = payload.api_key or settings.api_key
    if not api_key:
        raise HTTPException(400, "API key is required")
    base_url = payload.base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(400, f"Failed to pull models: {exc}") from exc
    models = [item["id"] for item in data.get("data", []) if isinstance(item, dict) and item.get("id")]
    return {"models": models}

