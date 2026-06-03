from __future__ import annotations

import json
from pathlib import Path

from app.content import worldpacks
from app.content.bundle_manifest import BUNDLE_FORMAT, load_bundle_manifest_dict


def _write_pack(path: Path, *, pack_id: str, name: str, worldview_name: str) -> None:
    payload = {
        "format": worldpacks.PACK_FORMAT,
        "pack_id": pack_id,
        "name": name,
        "version": "1.0.0",
        "worldviews": [
            {
                "worldview_id": "duplicate_test_worldview",
                "name": worldview_name,
                "version": "1.0.0",
            }
        ],
        "toolsets": [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_imported_worldpack_overrides_bundled_duplicate_without_error(tmp_path, monkeypatch):
    bundled_dir = tmp_path / "bundled"
    imported_dir = tmp_path / "imported"
    bundled_dir.mkdir()
    imported_dir.mkdir()
    _write_pack(
        bundled_dir / "sample_external_world.aiworld.json",
        pack_id="duplicate_pack",
        name="内置版本",
        worldview_name="内置世界观",
    )
    _write_pack(
        imported_dir / "sample_external_world.aiworld.json",
        pack_id="duplicate_pack",
        name="导入版本",
        worldview_name="导入世界观",
    )
    monkeypatch.setattr(worldpacks, "default_worldpack_dirs", lambda: [bundled_dir])
    monkeypatch.setattr(worldpacks, "imported_worldpack_dir", lambda: imported_dir)

    try:
        loaded = worldpacks.load_all_worldpacks(force=True)

        assert len(loaded) == 1
        assert loaded[0].name == "导入版本"
        assert loaded[0].data["worldviews"][0]["name"] == "导入世界观"
        assert worldpacks.content_pack_errors() == []
    finally:
        worldpacks._CACHE = None
        worldpacks._ERRORS = []


def test_bundle_manifest_accepts_multiple_config_components():
    manifest = load_bundle_manifest_dict(
        {
            "format": BUNDLE_FORMAT,
            "name": "Full Config Bundle",
            "bundleVersion": "1.0.0",
            "components": [
                {"component_id": "agents", "type": "agent_config", "format": "tiny-living-world-agent-config-v2", "path": "configs/agents.json", "required": True},
                {"component_id": "world", "type": "world_pack", "format": worldpacks.PACK_FORMAT, "path": "worldpacks/world.json"},
            ],
        }
    )

    assert manifest.name == "Full Config Bundle"
    assert [component.type for component in manifest.components] == ["agent_config", "world_pack"]
