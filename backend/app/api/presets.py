from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.content.presets import preset_catalog
from app.content.worldpacks import WorldPackError, save_imported_worldpack, summarize_pack


router = APIRouter(prefix="/api/presets", tags=["presets"])


@router.get("")
def get_presets() -> dict:
    return preset_catalog()


@router.post("/worldpacks/import")
async def import_worldpack(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "worldpack.aiworld.json"
    content = await file.read()
    if not content:
        raise HTTPException(400, "上传的世界观文件为空。")
    try:
        pack = save_imported_worldpack(filename, content)
    except (WorldPackError, ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, f"世界观包校验失败: {exc}") from exc
    except Exception as exc:
        raise HTTPException(400, f"世界观包导入失败: {exc}") from exc
    registered = 0
    try:
        from app.tools.tool_specs import refresh_external_worldpack_tools

        registered = refresh_external_worldpack_tools()
    except Exception:
        registered = 0
    return {"ok": True, "pack": summarize_pack(pack), "registered_tool_count": registered, "catalog": preset_catalog()}
