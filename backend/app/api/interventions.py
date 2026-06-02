from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.content.intervention_abilities import (
    InterventionPackError,
    intervention_pack_errors,
    load_intervention_abilities,
    save_imported_intervention_pack,
    summarize_abilities,
)


router = APIRouter(prefix="/api/interventions", tags=["interventions"])


@router.get("")
def list_intervention_abilities() -> dict:
    return {"abilities": summarize_abilities(load_intervention_abilities()), "errors": intervention_pack_errors()}


@router.post("/import")
async def import_intervention_pack(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "intervention_pack.aiworld.intervention.json"
    content = await file.read()
    if not content:
        raise HTTPException(400, "上传的影响世界能力包为空。")
    try:
        abilities = save_imported_intervention_pack(filename, content)
    except (InterventionPackError, ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, f"影响世界能力包校验失败: {exc}") from exc
    except Exception as exc:
        raise HTTPException(400, f"影响世界能力包导入失败: {exc}") from exc
    return {
        "ok": True,
        "imported": summarize_abilities(abilities),
        "abilities": summarize_abilities(load_intervention_abilities(force=True)),
        "errors": intervention_pack_errors(),
    }
