from __future__ import annotations

import base64
import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Agent, Event, World
from app.storage.audio import audio_path_for_key
from app.storage.images import delete_image_file_if_unreferenced, image_path_for_key, image_url_for_key, parse_image_data_url


router = APIRouter(prefix="/api/storage", tags=["storage"])


class StorageImageDeleteRequest(BaseModel):
    keys: list[str] = Field(default_factory=list, max_length=1000)


@router.get("/images")
def list_stored_images(limit: int = 400, db: Session = Depends(get_db)) -> dict[str, Any]:
    limit = max(1, min(limit, 1000))
    worlds = {world.world_id: world for world in db.execute(select(World)).scalars()}
    grouped: dict[str, dict[str, Any]] = {}

    for event in db.execute(select(Event).where(Event.event_type == "image_generation").order_by(Event.real_created_at.desc())).scalars():
        payload = event.payload if isinstance(event.payload, dict) else {}
        data_url = payload.get("image_data_url")
        image_key = payload.get("image_key")
        image_url = payload.get("image_url")
        if isinstance(image_key, str) and image_key:
            data_url = image_url if isinstance(image_url, str) and image_url else image_url_for_key(image_key)
        if not isinstance(data_url, str) or not (data_url.startswith("data:image/") or data_url.startswith("/api/storage/images/file/")):
            continue
        world = worlds.get(event.world_id)
        _add_image_reference(
            grouped,
            reference_key=f"event:{event.event_id}",
            kind="generated",
            label=str(payload.get("summary_title") or event.viewer_text or "生成图"),
            data_url=data_url,
            image_key=image_key if isinstance(image_key, str) else "",
            world=world,
            owner=f"{event.world_time // 1440 + 1}天 {event.world_time % 1440 // 60:02d}:{event.world_time % 60:02d}",
        )

    for agent in db.execute(select(Agent).order_by(Agent.agent_id.asc())).scalars():
        hint = agent.avatar_hint_json if isinstance(agent.avatar_hint_json, dict) else {}
        world = worlds.get(agent.world_id)
        avatar = hint.get("image_data_url")
        if isinstance(avatar, str) and avatar.startswith("data:image/"):
            _add_image_reference(
                grouped,
                reference_key=f"avatar:{agent.agent_id}",
                kind="avatar",
                label=f"{agent.chosen_name} 头像",
                data_url=avatar,
                world=world,
                owner=agent.chosen_name,
            )
        standing = hint.get("standing_image_data_url")
        if isinstance(standing, str) and standing.startswith("data:image/"):
            _add_image_reference(
                grouped,
                reference_key=f"standing:{agent.agent_id}",
                kind="standing",
                label=f"{agent.chosen_name} 立绘",
                data_url=standing,
                world=world,
                owner=agent.chosen_name,
            )

    items = sorted(
        grouped.values(),
        key=lambda item: (int(item["reference_count"]), int(item["reference_bytes"]), str(item["label"])),
        reverse=True,
    )[:limit]
    totals = {
        "count": len(items),
        "references": sum(int(item["reference_count"]) for item in items),
        "bytes": sum(int(item["size_bytes"]) for item in items),
        "reference_bytes": sum(int(item["reference_bytes"]) for item in items),
        "generated": sum(1 for item in items if "generated" in item["kinds"]),
        "avatar": sum(1 for item in items if "avatar" in item["kinds"]),
        "standing": sum(1 for item in items if "standing" in item["kinds"]),
    }
    return {"items": items, "totals": totals, "limit": limit}


def _add_image_reference(
    grouped: dict[str, dict[str, Any]],
    *,
    reference_key: str,
    kind: str,
    label: str,
    data_url: str,
    image_key: str = "",
    world: World | None = None,
    owner: str | None = None,
) -> None:
    image_hash = _image_hash(data_url, image_key=image_key)
    size_bytes = _data_url_size(data_url)
    preview_url = _preview_url_for_image(data_url, image_hash=image_hash, image_key=image_key)
    item = grouped.get(image_hash)
    reference = {
        "key": reference_key,
        "kind": kind,
        "label": label,
        "world_id": world.world_id if world else "",
        "world_name": world.name if world else "",
        "save_name": _save_name(world),
        "owner": owner or "",
    }
    if not item:
        grouped[image_hash] = {
            "key": f"image:{image_hash}",
            "hash": image_hash,
            "kind": kind,
            "kinds": [kind],
            "label": label,
            "world_id": reference["world_id"],
            "world_name": reference["world_name"],
            "save_name": reference["save_name"],
            "owner": reference["owner"],
            "size_bytes": size_bytes,
            "reference_bytes": size_bytes,
            "reference_count": 1,
            "preview_data_url": "",
            "preview_url": preview_url,
            "image_key": image_key,
            "references": [reference],
        }
        return
    if kind not in item["kinds"]:
        item["kinds"].append(kind)
    item["reference_count"] = int(item["reference_count"]) + 1
    item["reference_bytes"] = int(item["reference_bytes"]) + size_bytes
    item["references"].append(reference)
    if len(item["references"]) <= 3:
        labels = [str(ref["label"]) for ref in item["references"][:3] if ref.get("label")]
        item["label"] = " / ".join(labels)


@router.get("/images/file/{key}")
def get_stored_image_file(key: str) -> FileResponse:
    path = image_path_for_key(key)
    if not path or not path.exists():
        raise HTTPException(404, "image not found")
    return FileResponse(path)


@router.get("/images/preview/{image_hash}")
def get_stored_image_preview(image_hash: str, db: Session = Depends(get_db)) -> Response:
    data_url = _find_data_url_by_hash(db, image_hash)
    if not data_url:
        raise HTTPException(404, "image not found")
    parsed = parse_image_data_url(data_url)
    if not parsed:
        raise HTTPException(404, "image not found")
    mime_type, content = parsed
    return Response(content=content, media_type=mime_type)


@router.get("/audio/file/{key}")
def get_stored_audio_file(key: str) -> FileResponse:
    path = audio_path_for_key(key)
    if not path or not path.exists():
        raise HTTPException(404, "audio not found")
    return FileResponse(path)


@router.post("/images/delete")
def delete_stored_images(payload: StorageImageDeleteRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    keys = [key.strip() for key in payload.keys if key.strip()]
    if not keys:
        return {"ok": True, "deleted": [], "deleted_count": 0}
    deleted: list[str] = []
    for key in keys:
        kind, _, raw_id = key.partition(":")
        if not raw_id:
            continue
        if kind == "image":
            deleted.extend(_delete_image_hash_references(db, raw_id))
            continue
        if kind == "event":
            try:
                event_id = int(raw_id)
            except ValueError:
                continue
            event = db.get(Event, event_id)
            if not event:
                continue
            old_payload = dict(event.payload or {})
            image_key = str(old_payload.get("image_key") or "")
            event.payload = _without_image_fields(old_payload)
            deleted.append(key)
            if image_key:
                delete_image_file_if_unreferenced(image_key, _referenced_image_keys(db, exclude_event_id=event.event_id))
        elif kind in {"avatar", "standing"}:
            agent = db.get(Agent, raw_id)
            if not agent:
                continue
            hint = dict(agent.avatar_hint_json or {})
            field = "image_data_url" if kind == "avatar" else "standing_image_data_url"
            if field in hint:
                hint.pop(field, None)
                if kind == "standing":
                    hint.pop("standing_image_source", None)
                agent.avatar_hint_json = hint
                deleted.append(key)
    db.commit()
    return {"ok": True, "deleted": deleted, "deleted_count": len(deleted)}


def _delete_image_hash_references(db: Session, image_hash: str) -> list[str]:
    deleted: list[str] = []
    for event in db.execute(select(Event).where(Event.event_type == "image_generation")).scalars():
        payload = event.payload if isinstance(event.payload, dict) else {}
        data_url = payload.get("image_data_url")
        image_key = payload.get("image_key")
        if (isinstance(image_key, str) and image_key.split(".", 1)[0] == image_hash) or (isinstance(data_url, str) and _image_hash(data_url) == image_hash):
            event.payload = _without_image_fields(payload)
            deleted.append(f"event:{event.event_id}")
            if isinstance(image_key, str) and image_key:
                delete_image_file_if_unreferenced(image_key, _referenced_image_keys(db, exclude_event_id=event.event_id))
    for agent in db.execute(select(Agent)).scalars():
        hint = dict(agent.avatar_hint_json or {})
        avatar = hint.get("image_data_url")
        standing = hint.get("standing_image_data_url")
        changed = False
        if isinstance(avatar, str) and _image_hash(avatar) == image_hash:
            hint.pop("image_data_url", None)
            deleted.append(f"avatar:{agent.agent_id}")
            changed = True
        if isinstance(standing, str) and _image_hash(standing) == image_hash:
            hint.pop("standing_image_data_url", None)
            hint.pop("standing_image_source", None)
            deleted.append(f"standing:{agent.agent_id}")
            changed = True
        if changed:
            agent.avatar_hint_json = hint
    return deleted


def _without_key(value: Any, key: str) -> dict[str, Any]:
    data = dict(value or {}) if isinstance(value, dict) else {}
    data.pop(key, None)
    return data


def _without_image_fields(value: Any) -> dict[str, Any]:
    data = dict(value or {}) if isinstance(value, dict) else {}
    for key in ("image_data_url", "image_key", "image_url", "image_mime_type", "image_size_bytes", "image_sha256"):
        data.pop(key, None)
    return data


def _referenced_image_keys(db: Session, *, exclude_event_id: int | None = None) -> set[str]:
    keys: set[str] = set()
    for event in db.execute(select(Event).where(Event.event_type == "image_generation")).scalars():
        if exclude_event_id is not None and int(event.event_id) == exclude_event_id:
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        image_key = payload.get("image_key")
        if isinstance(image_key, str) and image_key:
            keys.add(image_key)
    return keys


def _save_name(world: World | None) -> str:
    if not world:
        return ""
    settings = world.settings_json if isinstance(world.settings_json, dict) else {}
    return str(settings.get("save_name") or world.name or world.world_id)


def _preview_url_for_image(data_url: str, *, image_hash: str, image_key: str = "") -> str:
    if image_key:
        return image_url_for_key(image_key)
    if data_url.startswith("/api/storage/images/file/"):
        return data_url
    if data_url.startswith("data:image/"):
        return f"/api/storage/images/preview/{image_hash}"
    return ""


def _find_data_url_by_hash(db: Session, image_hash: str) -> str:
    if not image_hash:
        return ""
    for event in db.execute(select(Event).where(Event.event_type == "image_generation")).scalars():
        payload = event.payload if isinstance(event.payload, dict) else {}
        data_url = payload.get("image_data_url")
        if isinstance(data_url, str) and data_url.startswith("data:image/") and _image_hash(data_url) == image_hash:
            return data_url
    for agent in db.execute(select(Agent)).scalars():
        hint = agent.avatar_hint_json if isinstance(agent.avatar_hint_json, dict) else {}
        for field in ("image_data_url", "standing_image_data_url"):
            data_url = hint.get(field)
            if isinstance(data_url, str) and data_url.startswith("data:image/") and _image_hash(data_url) == image_hash:
                return data_url
    return ""


def _data_url_size(data_url: str) -> int:
    if data_url.startswith("/api/storage/images/file/"):
        key = data_url.rsplit("/", 1)[-1]
        path = image_path_for_key(key)
        return path.stat().st_size if path and path.exists() else 0
    if "," not in data_url:
        return len(data_url.encode("utf-8"))
    header, encoded = data_url.split(",", 1)
    if ";base64" in header:
        padding = encoded.count("=")
        return max(0, int(len(encoded) * 3 / 4) - padding)
    return len(encoded.encode("utf-8"))


def _image_hash(data_url: str, *, image_key: str = "") -> str:
    if image_key:
        return image_key.split(".", 1)[0]
    if data_url.startswith("/api/storage/images/file/"):
        return data_url.rsplit("/", 1)[-1].split(".", 1)[0]
    if "," not in data_url:
        return hashlib.sha256(data_url.encode("utf-8")).hexdigest()
    header, encoded = data_url.split(",", 1)
    if ";base64" in header:
        try:
            return hashlib.sha256(base64.b64decode(encoded, validate=False)).hexdigest()
        except Exception:
            pass
    return hashlib.sha256(data_url.encode("utf-8")).hexdigest()
