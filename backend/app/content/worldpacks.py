from __future__ import annotations

import json
import os
import re
import zipfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PACK_FORMAT = "aiworld.world_pack.v1"
LEGACY_PLUGIN_FORMAT = "aiworld.plugin_pack.v1"
PACK_FORMAT_V2 = "aiworld.world_pack.v2"
PLUGIN_FORMAT_V2 = "aiworld.plugin_pack.v2"
FORMAT_ALIASES = {
    "aiworld.worldpack.v1": PACK_FORMAT,
    "aiworld.worldpack.v2": PACK_FORMAT_V2,
    "aiworld.plugin.v1": LEGACY_PLUGIN_FORMAT,
    "aiworld.plugin.v2": PLUGIN_FORMAT_V2,
}
ACCEPTED_FORMATS = {PACK_FORMAT, LEGACY_PLUGIN_FORMAT, PACK_FORMAT_V2, PLUGIN_FORMAT_V2, *FORMAT_ALIASES}
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_:\-]{1,119}$")


class WorldPackError(ValueError):
    """Raised when an external world/content pack is malformed."""


@dataclass(frozen=True, slots=True)
class LoadedWorldPack:
    pack_id: str
    name: str
    version: str
    source_path: str
    data: dict[str, Any]
    warnings: tuple[str, ...] = ()


_CACHE: list[LoadedWorldPack] | None = None
_ERRORS: list[dict[str, str]] = []


def project_root() -> Path:
    # backend/app/content/worldpacks.py -> project root
    return Path(__file__).resolve().parents[3]


def default_worldpack_dirs() -> list[Path]:
    root = project_root()
    dirs = [
        root / "worldpacks",
        root / "docs" / "worldpacks",
        Path(__file__).resolve().parent / "worldpacks",
    ]
    env_dirs = os.getenv("AIWORLD_CONTENT_PACK_DIRS")
    if env_dirs:
        dirs = [Path(item).expanduser() for item in env_dirs.split(os.pathsep) if item.strip()] + dirs
    return dirs


def imported_worldpack_dir() -> Path:
    return Path(os.getenv("AIWORLD_IMPORTED_WORLD_PACK_DIR", str(project_root() / "worldpacks" / "imported"))).expanduser()


def _worldpack_source_priority(pack: LoadedWorldPack) -> int:
    """Higher priority packs override lower priority packs with the same pack_id."""
    try:
        source = Path(pack.source_path).expanduser().resolve()
        imported_dir = imported_worldpack_dir().resolve()
        if source == imported_dir or imported_dir in source.parents:
            return 30
        env_dirs = os.getenv("AIWORLD_CONTENT_PACK_DIRS")
        if env_dirs:
            for item in env_dirs.split(os.pathsep):
                if not item.strip():
                    continue
                env_dir = Path(item).expanduser().resolve()
                if source == env_dir or env_dir in source.parents:
                    return 20
    except OSError:
        return 10
    return 10


def _dedupe_worldpacks(packs: list[LoadedWorldPack]) -> list[LoadedWorldPack]:
    by_pack_id: dict[str, LoadedWorldPack] = {}
    order: list[str] = []
    for pack in packs:
        current = by_pack_id.get(pack.pack_id)
        if current is None:
            by_pack_id[pack.pack_id] = pack
            order.append(pack.pack_id)
            continue
        if _worldpack_source_priority(pack) > _worldpack_source_priority(current):
            by_pack_id[pack.pack_id] = _merge_duplicate_pack(fallback=current, preferred=pack)
        else:
            by_pack_id[pack.pack_id] = _merge_duplicate_pack(fallback=pack, preferred=current)
    return [by_pack_id[pack_id] for pack_id in order]


def _merge_duplicate_pack(*, fallback: LoadedWorldPack, preferred: LoadedWorldPack) -> LoadedWorldPack:
    """Keep the higher-priority pack, but fill missing entry fields from the lower one.

    This lets a user re-import an older copy of a packaged world pack without losing
    newer runtime metadata such as UI state schemas and rule multipliers.
    """
    data = deepcopy(preferred.data)
    for collection, id_key in [("worldviews", "worldview_id"), ("toolsets", "toolset_id")]:
        fallback_items = {
            str(item.get(id_key)): item
            for item in fallback.data.get(collection) or []
            if isinstance(item, dict) and item.get(id_key)
        }
        merged_items: list[Any] = []
        seen: set[str] = set()
        for item in data.get(collection) or []:
            if not isinstance(item, dict):
                merged_items.append(item)
                continue
            item_id = str(item.get(id_key) or "")
            seen.add(item_id)
            base = fallback_items.get(item_id)
            merged_items.append(_fill_missing_deep(base, item) if base else item)
        for item_id, item in fallback_items.items():
            if item_id not in seen:
                merged_items.append(deepcopy(item))
        data[collection] = merged_items
    data["source_path"] = preferred.source_path
    return LoadedWorldPack(
        pack_id=preferred.pack_id,
        name=preferred.name,
        version=preferred.version,
        source_path=preferred.source_path,
        data=data,
        warnings=tuple([*fallback.warnings, *preferred.warnings]),
    )


def _fill_missing_deep(fallback: dict[str, Any] | None, preferred: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(fallback, dict):
        return deepcopy(preferred)
    merged = deepcopy(fallback)
    for key, value in preferred.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _fill_missing_deep(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_all_worldpacks(*, force: bool = False) -> list[LoadedWorldPack]:
    global _CACHE, _ERRORS
    if _CACHE is not None and not force:
        return _CACHE
    packs: list[LoadedWorldPack] = []
    errors: list[dict[str, str]] = []
    seen_sources: set[Path] = set()
    for directory in default_worldpack_dirs() + [imported_worldpack_dir()]:
        if not directory.exists() or not directory.is_dir():
            continue
        for path in sorted(directory.glob("*")):
            if path in seen_sources or path.suffix.lower() not in {".json", ".aiworld", ".zip"} and not path.name.endswith(".aiworld.json"):
                continue
            seen_sources.add(path)
            try:
                packs.append(load_worldpack_file(path))
            except Exception as exc:  # keep the app usable if one external pack is bad
                errors.append({"source_path": str(path), "error": str(exc)})
    _CACHE = _dedupe_worldpacks(packs)
    _ERRORS = errors
    return _CACHE


def content_pack_errors() -> list[dict[str, str]]:
    load_all_worldpacks()
    return list(_ERRORS)


def load_worldpack_file(path: Path) -> LoadedWorldPack:
    if path.suffix.lower() == ".zip":
        return _load_worldpack_zip(path)
    return load_worldpack_dict(json.loads(path.read_text(encoding="utf-8")), source_path=str(path))


def load_worldpack_bytes(filename: str, content: bytes) -> LoadedWorldPack:
    suffix = Path(filename).suffix.lower()
    if suffix == ".zip":
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            return _load_worldpack_zip(tmp_path, source_path=filename)
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
    return load_worldpack_dict(json.loads(content.decode("utf-8")), source_path=filename)


def save_imported_worldpack(filename: str, content: bytes) -> LoadedWorldPack:
    pack = load_worldpack_bytes(filename, content)
    target_dir = imported_worldpack_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(filename, default=f"{pack.pack_id}.aiworld.json")
    if Path(safe_name).suffix.lower() not in {".json", ".zip", ".aiworld"} and not safe_name.endswith(".aiworld.json"):
        safe_name = f"{pack.pack_id}.aiworld.json"
    target = target_dir / safe_name
    if target.exists():
        stem = target.stem
        suffix = "".join(target.suffixes) or ".json"
        target = target_dir / f"{stem}_{pack.version.replace('.', '_')}{suffix}"
    target.write_bytes(content)
    load_all_worldpacks(force=True)
    # Return the persisted version so source_path is useful.
    return load_worldpack_file(target)


def _load_worldpack_zip(path: Path, *, source_path: str | None = None) -> LoadedWorldPack:
    with zipfile.ZipFile(path) as zf:
        if "manifest.json" not in zf.namelist():
            raise WorldPackError("zip 世界包缺少 manifest.json")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        data = dict(manifest)
        data.setdefault("worldviews", [])
        data.setdefault("toolsets", [])
        for field in ["worldviews", "toolsets", "system_agents"]:
            raw_entries = manifest.get(field)
            if not raw_entries:
                continue
            if all(isinstance(item, str) for item in raw_entries):
                merged: list[Any] = []
                for entry_path in raw_entries:
                    if entry_path not in zf.namelist():
                        raise WorldPackError(f"manifest 声明的 {field} 文件不存在: {entry_path}")
                    payload = json.loads(zf.read(entry_path).decode("utf-8"))
                    if isinstance(payload, list):
                        merged.extend(payload)
                    elif isinstance(payload, dict) and isinstance(payload.get(field), list):
                        merged.extend(payload[field])
                    elif isinstance(payload, dict):
                        merged.append(payload)
                    else:
                        raise WorldPackError(f"{entry_path} 不是合法 JSON 对象或数组")
                data[field] = merged
        return load_worldpack_dict(data, source_path=source_path or str(path))


def load_worldpack_dict(raw: dict[str, Any], *, source_path: str) -> LoadedWorldPack:
    if not isinstance(raw, dict):
        raise WorldPackError("世界包根节点必须是 JSON 对象")
    fmt = str(raw.get("format") or "").strip()
    if fmt not in ACCEPTED_FORMATS:
        raise WorldPackError(f"format 必须是 {PACK_FORMAT} / {LEGACY_PLUGIN_FORMAT} / {PACK_FORMAT_V2} / {PLUGIN_FORMAT_V2}")
    pack_id = _require_id(raw, "pack_id")
    name = _require_str(raw, "name")
    version = _require_str(raw, "version")
    warnings: list[str] = []
    data = deepcopy(raw)
    data["format"] = FORMAT_ALIASES.get(fmt, fmt)
    data["pack_id"] = pack_id
    data["name"] = name
    data["version"] = version
    data["source_path"] = source_path
    data.setdefault("worldviews", [])
    data.setdefault("toolsets", [])
    if not isinstance(data["worldviews"], list):
        warnings.append("worldviews 不是数组，已忽略。")
        data["worldviews"] = []
    if not isinstance(data["toolsets"], list):
        warnings.append("toolsets 不是数组，已忽略。")
        data["toolsets"] = []
    data["worldviews"], worldview_warnings = _sanitize_worldviews(data["worldviews"], pack_id=pack_id, source_path=source_path)
    data["toolsets"], toolset_warnings = _sanitize_toolsets(data["toolsets"], pack_id=pack_id, source_path=source_path)
    warnings.extend(worldview_warnings)
    warnings.extend(toolset_warnings)
    duplicate_warnings = _dedupe_pack_entries(data)
    warnings.extend(duplicate_warnings)
    data["import_warnings"] = warnings
    return LoadedWorldPack(pack_id=pack_id, name=name, version=version, source_path=source_path, data=data, warnings=tuple(warnings))


def external_catalog() -> dict[str, list[dict[str, Any]]]:
    catalog = {
        "worldviews": [],
        "core_toolsets": [],
        "optional_toolsets": [],
        "agent_special_toolsets": [],
        "world_toolsets": [],
        "toolsets": [],
    }
    for pack in load_all_worldpacks():
        for worldview in pack.data.get("worldviews") or []:
            item = _external_entry(worldview, pack)
            catalog["worldviews"].append(item)
        for toolset in pack.data.get("toolsets") or []:
            item = _external_entry(toolset, pack)
            scope = item.get("scope") or "world"
            if scope == "core":
                catalog["core_toolsets"].append(item)
            elif scope == "optional":
                catalog["optional_toolsets"].append(item)
            elif scope == "agent_special":
                catalog["agent_special_toolsets"].append(item)
            else:
                catalog["world_toolsets"].append(item)
                catalog["toolsets"].append(item)
    return catalog


def find_external_worldview(worldview_id: str | None) -> dict[str, Any] | None:
    if not worldview_id:
        return None
    for pack in load_all_worldpacks():
        for worldview in pack.data.get("worldviews") or []:
            if worldview.get("worldview_id") == worldview_id:
                return _external_entry(worldview, pack)
    return None


def find_external_toolset(toolset_id: str | None) -> dict[str, Any] | None:
    if not toolset_id:
        return None
    for pack in load_all_worldpacks():
        for toolset in pack.data.get("toolsets") or []:
            aliases = set(toolset.get("legacy_toolset_ids") or [])
            if toolset.get("toolset_id") == toolset_id or toolset_id in aliases:
                return _external_entry(toolset, pack)
    return None


def iter_external_tool_definitions() -> Iterable[dict[str, Any]]:
    for pack in load_all_worldpacks():
        for toolset in pack.data.get("toolsets") or []:
            toolset_id = str(toolset.get("toolset_id") or "")
            worldview_id = str(toolset.get("worldview_id") or "")
            for tool in toolset.get("tools") or []:
                if not isinstance(tool, dict):
                    continue
                item = deepcopy(tool)
                item.setdefault("pack_id", pack.pack_id)
                item.setdefault("pack_name", pack.name)
                item.setdefault("source_path", pack.source_path)
                item.setdefault("toolset_id", toolset_id)
                item.setdefault("worldview_id", worldview_id)
                yield item


def external_tool_names_for_toolset(toolset_id: str | None) -> set[str]:
    toolset = find_external_toolset(toolset_id)
    if not toolset:
        return set()
    return {str(tool.get("tool_name") or tool.get("id") or "") for tool in toolset.get("tools") or [] if isinstance(tool, dict)} - {""}


def worldview_start_minute(worldview: dict[str, Any] | None, fallback: int = 8 * 60) -> int:
    time_model = (worldview or {}).get("time_model") or {}
    if not isinstance(time_model, dict):
        return fallback
    try:
        return int(time_model.get("start_minute", fallback))
    except (TypeError, ValueError):
        return fallback


def worldview_default_create_settings(worldview: dict[str, Any] | None) -> dict[str, Any]:
    raw = (worldview or {}).get("default_create_settings") or {}
    return deepcopy(raw) if isinstance(raw, dict) else {}


def summarize_pack(pack: LoadedWorldPack) -> dict[str, Any]:
    return {
        "pack_id": pack.pack_id,
        "format": pack.data.get("format"),
        "name": pack.name,
        "version": pack.version,
        "source_path": pack.source_path,
        "import_warnings": list(pack.warnings or pack.data.get("import_warnings") or []),
        "worldviews": [
            {"worldview_id": item.get("worldview_id"), "name": item.get("name"), "version": item.get("version")}
            for item in pack.data.get("worldviews") or []
        ],
        "toolsets": [
            {"toolset_id": item.get("toolset_id"), "name": item.get("name"), "scope": item.get("scope", "world")}
            for item in pack.data.get("toolsets") or []
        ],
    }


def _external_entry(raw: dict[str, Any], pack: LoadedWorldPack) -> dict[str, Any]:
    item = deepcopy(raw)
    item.setdefault("packaged", False)
    item.setdefault("status", "external")
    item.setdefault("entry_status", "external")
    item.setdefault("pack_id", pack.pack_id)
    item.setdefault("pack_name", pack.name)
    item.setdefault("pack_version", pack.version)
    item.setdefault("source_path", pack.source_path)
    return item


def _sanitize_worldviews(worldviews: list[Any], *, pack_id: str, source_path: str) -> tuple[list[dict[str, Any]], list[str]]:
    result: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, raw in enumerate(worldviews):
        if not isinstance(raw, dict):
            warnings.append(f"worldviews[{index}] 不是对象，已跳过。")
            continue
        item = deepcopy(raw)
        try:
            worldview_id = _require_id(item, "worldview_id")
            _require_str(item, "name")
            _require_str(item, "version")
        except WorldPackError as exc:
            warnings.append(f"worldviews[{index}] 无法识别: {exc}，已跳过。")
            continue
        item.setdefault("description", "")
        if "locations" in item and not isinstance(item["locations"], list):
            warnings.append(f"{worldview_id}.locations 不是数组，已忽略。")
            item["locations"] = []
        locations: list[dict[str, Any]] = []
        for loc_index, location in enumerate(item.get("locations") or []):
            normalized = _sanitize_location(location, worldview_id, loc_index, warnings)
            if normalized is not None:
                locations.append(normalized)
        if "locations" in item:
            item["locations"] = locations
        result.append(item)
    return result, warnings


def _sanitize_toolsets(toolsets: list[Any], *, pack_id: str, source_path: str) -> tuple[list[dict[str, Any]], list[str]]:
    result: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, raw in enumerate(toolsets):
        if not isinstance(raw, dict):
            warnings.append(f"toolsets[{index}] 不是对象，已跳过。")
            continue
        item = deepcopy(raw)
        try:
            toolset_id = _require_id(item, "toolset_id")
            _require_str(item, "name")
            _require_str(item, "version")
        except WorldPackError as exc:
            warnings.append(f"toolsets[{index}] 无法识别: {exc}，已跳过。")
            continue
        item.setdefault("scope", "world")
        if item["scope"] not in {"core", "optional", "world", "agent_special", "npc"}:
            warnings.append(f"{toolset_id}.scope 不合法，已按 world 处理。")
            item["scope"] = "world"
        if "tools" in item and not isinstance(item["tools"], list):
            warnings.append(f"{toolset_id}.tools 不是数组，已忽略。")
            item["tools"] = []
        tools: list[dict[str, Any]] = []
        for tool_index, tool in enumerate(item.get("tools") or []):
            normalized = _sanitize_tool(tool, toolset_id, tool_index, warnings)
            if normalized is not None:
                tools.append(normalized)
        if "tools" in item:
            item["tools"] = tools
        result.append(item)
    return result, warnings


def _sanitize_location(raw: Any, worldview_id: str, index: int, warnings: list[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        warnings.append(f"{worldview_id}.locations[{index}] 不是对象，已跳过。")
        return None
    item = deepcopy(raw)
    try:
        location_id = _require_id(item, "location_id")
        _require_str(item, "name")
    except WorldPackError as exc:
        warnings.append(f"{worldview_id}.locations[{index}] 无法识别: {exc}，已跳过。")
        return None
    item.setdefault("description", "")
    for key in ["neighbors", "available_tools", "tags"]:
        if key in item and not isinstance(item[key], list):
            warnings.append(f"地点 {location_id}.{key} 不是数组，已按空数组处理。")
            item[key] = []
    return item


def _sanitize_tool(raw: Any, toolset_id: str, index: int, warnings: list[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        warnings.append(f"{toolset_id}.tools[{index}] 不是对象，已跳过。")
        return None
    item = deepcopy(raw)
    tool_id = item.get("tool_name") or item.get("id")
    if not tool_id:
        warnings.append(f"{toolset_id}.tools[{index}] 缺少 tool_name，已跳过。")
        return None
    if not ID_RE.match(str(tool_id)):
        warnings.append(f"{toolset_id}.tools[{index}] 工具 ID 不合法: {tool_id}，已跳过。")
        return None
    item["tool_name"] = str(tool_id)
    item.setdefault("display_name", item.get("name") or item.get("name_zh") or str(tool_id))
    item.setdefault("description_for_llm", item.get("description") or item.get("effect_summary") or str(item["display_name"]))
    target_policy = item.get("target_policy", "none")
    if target_policy not in {"none", "visible_ref", "known_name", "item", "location"}:
        warnings.append(f"{tool_id}.target_policy 不合法，已按 none 处理。")
        item["target_policy"] = "none"
    return item


def _dedupe_pack_entries(data: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for key, id_key in [("worldviews", "worldview_id"), ("toolsets", "toolset_id")]:
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for item in data.get(key) or []:
            item_id = str(item.get(id_key))
            if item_id in seen:
                warnings.append(f"{key} 内重复 ID {item_id} 已跳过后续条目。")
                continue
            seen.add(item_id)
            deduped.append(item)
        data[key] = deduped
    seen_tools: set[str] = set()
    for toolset in data.get("toolsets") or []:
        deduped_tools: list[dict[str, Any]] = []
        for tool in toolset.get("tools") or []:
            tool_id = str(tool.get("tool_name") or tool.get("id"))
            if tool_id in seen_tools:
                warnings.append(f"tools 内重复 tool_name {tool_id} 已跳过后续条目。")
                continue
            seen_tools.add(tool_id)
            deduped_tools.append(tool)
        if "tools" in toolset:
            toolset["tools"] = deduped_tools
    return warnings


def iter_tools_in_data(data: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for toolset in data.get("toolsets") or []:
        for tool in toolset.get("tools") or []:
            if isinstance(tool, dict):
                yield tool


def _require_id(raw: dict[str, Any], key: str) -> str:
    value = str(raw.get(key) or "").strip()
    if not value or not ID_RE.match(value):
        raise WorldPackError(f"缺少或非法 ID 字段: {key}")
    raw[key] = value
    return value


def _require_str(raw: dict[str, Any], key: str) -> str:
    value = str(raw.get(key) or "").strip()
    if not value:
        raise WorldPackError(f"缺少必填字段: {key}")
    raw[key] = value
    return value


def _safe_filename(filename: str, *, default: str) -> str:
    name = Path(filename or default).name
    name = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "_", name).strip("._")
    return name or default
