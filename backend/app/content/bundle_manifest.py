from __future__ import annotations

from dataclasses import dataclass
import json
import zipfile
from pathlib import Path
from typing import Any


BUNDLE_FORMAT = "aiworld.bundle_manifest.v1"
WORLD_CONFIG_FORMAT = "aiworld.world_config.v1"
MAX_COMPONENTS = 64


class BundleManifestError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BundleComponent:
    component_id: str
    type: str
    format: str
    path: str | None = None
    config: dict[str, Any] | None = None
    required: bool = False


@dataclass(frozen=True, slots=True)
class BundleManifest:
    name: str
    version: str
    components: tuple[BundleComponent, ...]
    raw: dict[str, Any]


def load_bundle_manifest_dict(raw: dict[str, Any]) -> BundleManifest:
    if not isinstance(raw, dict):
        raise BundleManifestError("bundle manifest 根节点必须是 JSON 对象")
    fmt = str(raw.get("format") or "").strip()
    if fmt != BUNDLE_FORMAT:
        raise BundleManifestError(f"format 必须是 {BUNDLE_FORMAT}")
    name = str(raw.get("name") or "AIworld bundle").strip()[:120]
    version = str(raw.get("bundleVersion") or raw.get("version") or "1.0.0").strip()[:40]
    components_raw = raw.get("components")
    if not isinstance(components_raw, list) or not components_raw:
        raise BundleManifestError("components 必须是非空数组")
    if len(components_raw) > MAX_COMPONENTS:
        raise BundleManifestError(f"components 不能超过 {MAX_COMPONENTS} 个")
    components = tuple(_component(item, index) for index, item in enumerate(components_raw))
    return BundleManifest(name=name, version=version, components=components, raw=dict(raw))


def load_bundle_manifest_zip(path: str | Path) -> BundleManifest:
    with zipfile.ZipFile(path) as zf:
        if "manifest.json" not in zf.namelist():
            raise BundleManifestError("bundle zip 缺少 manifest.json")
        raw = json.loads(zf.read("manifest.json").decode("utf-8"))
    return load_bundle_manifest_dict(raw)


def _component(raw: Any, index: int) -> BundleComponent:
    if not isinstance(raw, dict):
        raise BundleManifestError(f"components[{index}] 必须是对象")
    component_id = str(raw.get("component_id") or raw.get("id") or "").strip()
    component_type = str(raw.get("type") or "").strip()
    component_format = str(raw.get("format") or "").strip()
    path = str(raw.get("path") or "").strip() or None
    config = raw.get("config")
    if not component_id:
        raise BundleManifestError(f"components[{index}].component_id 不能为空")
    if not component_type:
        raise BundleManifestError(f"components[{index}].type 不能为空")
    if not component_format:
        raise BundleManifestError(f"components[{index}].format 不能为空")
    if path is None and not isinstance(config, dict):
        raise BundleManifestError(f"components[{index}] 必须提供 path 或内嵌 config")
    return BundleComponent(
        component_id=component_id[:120],
        type=component_type[:80],
        format=component_format[:120],
        path=path,
        config=dict(config) if isinstance(config, dict) else None,
        required=bool(raw.get("required")),
    )
