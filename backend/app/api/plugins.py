from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.content.presets import preset_catalog
from app.content.worldpacks import LEGACY_PLUGIN_FORMAT, PLUGIN_FORMAT_V2, WorldPackError, load_all_worldpacks, save_imported_worldpack, summarize_pack


router = APIRouter(prefix="/api/plugins", tags=["plugins"])
MAX_PLUGIN_DOWNLOAD_BYTES = 50 * 1024 * 1024


class PluginInstallUrlRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


@router.get("")
def list_plugins() -> dict:
    plugins = [
        summarize_pack(pack)
        for pack in load_all_worldpacks(force=True)
        if str(pack.data.get("format") or "") in {LEGACY_PLUGIN_FORMAT, PLUGIN_FORMAT_V2} or "plugin" in str(pack.pack_id).lower()
    ]
    return {"plugins": plugins}


@router.post("/import")
async def import_plugin(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "aiworld-plugin.zip"
    content = await file.read()
    if not content:
        raise HTTPException(400, "上传的插件包为空。")
    return _install_plugin_bytes(filename, content)


@router.post("/install-url")
async def install_plugin_from_url(payload: PluginInstallUrlRequest) -> dict:
    urls = _download_candidates(payload.url.strip())
    last_error = ""
    for url in urls:
        try:
            content = await _download(url)
            filename = Path(urlparse(url).path).name or "aiworld-plugin.zip"
            return _install_plugin_bytes(filename, content)
        except Exception as exc:
            last_error = str(exc)
    raise HTTPException(400, f"插件下载或安装失败: {last_error or '未知错误'}")


async def _download(url: str) -> bytes:
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        content = response.content
    if not content:
        raise ValueError("下载内容为空。")
    if len(content) > MAX_PLUGIN_DOWNLOAD_BYTES:
        raise ValueError("插件包超过 50MB 限制。")
    return content


def _install_plugin_bytes(filename: str, content: bytes) -> dict:
    try:
        pack = save_imported_worldpack(filename, content)
    except (WorldPackError, ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, f"插件包校验失败: {exc}") from exc
    except Exception as exc:
        raise HTTPException(400, f"插件包导入失败: {exc}") from exc
    registered = 0
    try:
        from app.tools.tool_specs import refresh_external_worldpack_tools

        registered = refresh_external_worldpack_tools()
    except Exception:
        registered = 0
    return {"ok": True, "plugin": summarize_pack(pack), "registered_tool_count": registered, "catalog": preset_catalog()}


def _download_candidates(raw_url: str) -> list[str]:
    parsed = urlparse(raw_url)
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return [raw_url]
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return [raw_url]
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if len(parts) >= 4 and parts[2] in {"archive", "releases"}:
        return [raw_url]
    return [
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/main",
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/master",
        raw_url,
    ]
