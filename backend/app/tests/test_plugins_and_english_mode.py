from __future__ import annotations

import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.content import worldpacks
from app.core import database
from app.llm.language import cjk_count
from app.main import app
from app.knowledge.perception import build_turn_context_with_options
from app.tests.conftest import make_world


def test_plugin_import_endpoint_accepts_legacy_plugin_zip_and_lists_it(tmp_path, monkeypatch):
    bundled_dir = tmp_path / "bundled"
    imported_dir = tmp_path / "imported"
    bundled_dir.mkdir()
    imported_dir.mkdir()
    monkeypatch.setattr(worldpacks, "default_worldpack_dirs", lambda: [bundled_dir])
    monkeypatch.setattr(worldpacks, "imported_worldpack_dir", lambda: imported_dir)
    worldpacks._CACHE = None
    worldpacks._ERRORS = []

    manifest = {
        "format": worldpacks.LEGACY_PLUGIN_FORMAT,
        "pack_id": "plugin_smoke_test",
        "name": "Plugin Smoke Test",
        "version": "1.0.0",
        "worldviews": [],
        "toolsets": [
            {
                "toolset_id": "plugin_smoke_toolset",
                "name": "Plugin Smoke Toolset",
                "version": "1.0.0",
                "scope": "world",
                "tools": [
                    {
                        "tool_name": "plugin_smoke_wave",
                        "display_name": "Wave from plugin",
                        "description_for_llm": "A tiny plugin-defined greeting action.",
                        "target_policy": "none",
                    }
                ],
            }
        ],
    }
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))

    client = TestClient(app)
    response = client.post(
        "/api/plugins/import",
        files={"file": ("plugin_smoke_test.zip", data.getvalue(), "application/zip")},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["plugin"]["pack_id"] == "plugin_smoke_test"
    assert (imported_dir / "plugin_smoke_test.zip").exists()

    listed = client.get("/api/plugins")
    assert listed.status_code == 200
    assert any(item["pack_id"] == "plugin_smoke_test" for item in listed.json()["plugins"])

    worldpacks._CACHE = None
    worldpacks._ERRORS = []


def test_plugin_import_accepts_common_plugin_format_alias(tmp_path, monkeypatch):
    bundled_dir = tmp_path / "bundled"
    imported_dir = tmp_path / "imported"
    bundled_dir.mkdir()
    imported_dir.mkdir()
    monkeypatch.setattr(worldpacks, "default_worldpack_dirs", lambda: [bundled_dir])
    monkeypatch.setattr(worldpacks, "imported_worldpack_dir", lambda: imported_dir)
    worldpacks._CACHE = None
    worldpacks._ERRORS = []

    manifest = {
        "format": "aiworld.plugin.v1",
        "pack_id": "plugin_alias_test",
        "name": "Plugin Alias Test",
        "version": "1.0.0",
        "worldviews": [],
        "toolsets": [],
    }
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))

    client = TestClient(app)
    response = client.post(
        "/api/plugins/import",
        files={"file": ("plugin_alias_test.zip", data.getvalue(), "application/zip")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["plugin"]["format"] == worldpacks.LEGACY_PLUGIN_FORMAT
    assert (imported_dir / "plugin_alias_test.zip").exists()

    worldpacks._CACHE = None
    worldpacks._ERRORS = []


def test_plugin_import_error_mentions_plugin_format():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": "aiworld.plugin_pack.v0",
                    "pack_id": "bad_plugin_format",
                    "name": "Bad Plugin Format",
                    "version": "1.0.0",
                    "worldviews": [],
                    "toolsets": [],
                }
            ),
        )

    client = TestClient(app)
    response = client.post(
        "/api/plugins/import",
        files={"file": ("bad_plugin_format.zip", data.getvalue(), "application/zip")},
    )

    assert response.status_code == 400
    assert worldpacks.PACK_FORMAT in response.text
    assert worldpacks.LEGACY_PLUGIN_FORMAT in response.text


def test_english_action_prompt_has_no_chinese_residue_even_with_chinese_seed_data(db):
    world, agents = make_world(db, 2)
    world.settings_json = {"language": "en"}

    context = build_turn_context_with_options(db, world, agents[0])

    assert cjk_count(context.prompt) == 0
    assert "Action options:" in context.prompt
    assert "Person A" in context.prompt
    assert "[speech]" in context.prompt or "[body]" in context.prompt
    assert "行动编号协议" not in context.prompt
    assert "附近人物" not in context.prompt
    assert "台词" not in context.prompt
