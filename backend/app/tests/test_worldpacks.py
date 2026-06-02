from __future__ import annotations

import json
from pathlib import Path

from app.content import worldpacks


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
