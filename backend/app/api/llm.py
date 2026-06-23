from __future__ import annotations

import asyncio
from urllib.parse import urlparse, urlunparse

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
            if isinstance(value, list) and value:
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


def _normalize_base_url(value: str) -> str:
    """Accept provider base URLs copied from either root, /v1, /models, or chat endpoints."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        # Keep the user's value intact; httpx will return a clear InvalidURL error.
        return raw.rstrip("/")
    parts = [part for part in parsed.path.split("/") if part]
    while parts and parts[-1] in {"models", "chat", "completions"}:
        parts.pop()
    normalized_path = "/" + "/".join(parts) if parts else ""
    return urlunparse((parsed.scheme, parsed.netloc, normalized_path.rstrip("/"), "", "", "")).rstrip("/")


def _model_url_candidates(base_url: str) -> list[str]:
    base = _normalize_base_url(base_url)
    if not base:
        return []
    candidates = [f"{base}/models"]
    path = urlparse(base).path.rstrip("/")
    if not path.endswith("/v1") and path != "/v1":
        candidates.append(f"{base}/v1/models")
    seen: set[str] = set()
    ordered: list[str] = []
    for url in candidates:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = response.text
    text = str(payload)
    if len(text) > 500:
        text = f"{text[:500]}..."
    return f"HTTP {response.status_code}: {text}"


@router.post("/models")
async def pull_models(payload: PullModelsRequest) -> dict:
    api_key = (payload.api_key or settings.api_key or "").strip()
    urls = _model_url_candidates(payload.base_url)
    if not urls:
        raise HTTPException(400, "Base URL is required")

    headers = {"Accept": "application/json", "User-Agent": "aiworld-model-pull/1.0"}
    # Local OpenAI-compatible providers such as Ollama or LM Studio often do not
    # require a key.  Do not reject those before the request reaches /models.
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    last_error = "no request attempted"
    async with httpx.AsyncClient(timeout=30) as client:
        for url in urls:
            response = None
            # Model pulls often run over a flaky proxy/VPN; a single transient
            # connection error should not make the whole pull fail and leave the
            # provider showing "no models fetched". Retry a few times before moving on.
            for attempt in range(3):
                try:
                    response = await client.get(url, headers=headers)
                    break
                except httpx.HTTPError as exc:
                    # Some transport errors (proxy resets, read timeouts) stringify to
                    # an empty message; fall back to the exception type so the surfaced
                    # error is never blank.
                    detail = str(exc) or exc.__class__.__name__
                    last_error = f"{url}: {detail}"
                    if attempt < 2:
                        await asyncio.sleep(0.6 * (attempt + 1))
            if response is None:
                continue
            if response.status_code in {404, 405} and url != urls[-1]:
                last_error = f"{url}: {_error_detail(response)}"
                continue
            if response.status_code >= 400:
                last_error = f"{url}: {_error_detail(response)}"
                continue
            try:
                data = response.json()
            except ValueError as exc:
                last_error = f"{url}: response is not JSON ({exc})"
                continue
            models = extract_model_ids(data)
            if models:
                return {"models": models, "source_url": url}
            last_error = f"{url}: response contained no recognizable model ids"

    raise HTTPException(400, f"Failed to pull models: {last_error}")
