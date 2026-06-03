from __future__ import annotations

import io
import json
import zipfile

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.content.bundle_manifest import BUNDLE_FORMAT, BundleManifestError, load_bundle_manifest_dict
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
        filename, content = _extract_worldpack_component(filename, content)
        pack = save_imported_worldpack(filename, content)
    except (WorldPackError, BundleManifestError, ValueError, UnicodeDecodeError) as exc:
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


def _extract_worldpack_component(filename: str, content: bytes) -> tuple[str, bytes]:
    lowered = filename.lower()
    if lowered.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            if "manifest.json" not in zf.namelist():
                return filename, content
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            if str(manifest.get("format") or "") != BUNDLE_FORMAT:
                return filename, content
            bundle = load_bundle_manifest_dict(manifest)
            component = next((item for item in bundle.components if item.type == "world_pack"), None)
            if not component:
                raise BundleManifestError("bundle manifest 缺少 world_pack 组件")
            if component.path:
                if component.path not in zf.namelist():
                    raise BundleManifestError(f"world_pack 组件文件不存在: {component.path}")
                return component.path.rsplit("/", 1)[-1] or "worldpack.aiworld.json", zf.read(component.path)
            if component.config is not None:
                return f"{component.component_id}.aiworld.json", json.dumps(component.config, ensure_ascii=False).encode("utf-8")
            raise BundleManifestError("world_pack 组件必须提供 path 或 config")
    try:
        manifest = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return filename, content
    if str(manifest.get("format") or "") != BUNDLE_FORMAT:
        return filename, content
    bundle = load_bundle_manifest_dict(manifest)
    component = next((item for item in bundle.components if item.type == "world_pack"), None)
    if not component or component.config is None:
        raise BundleManifestError("JSON bundle 必须提供内嵌 world_pack config")
    return f"{component.component_id}.aiworld.json", json.dumps(component.config, ensure_ascii=False).encode("utf-8")
