# 影响世界能力插件规范

文件可以是 `.json` 或 `.zip`。ZIP 内需要有 `manifest.json`，内容同 JSON。

```json
{
  "format": "aiworld.intervention_pack.v1",
  "abilities": [
    {
      "ability_id": "example_blessing",
      "name": "温柔祝福",
      "description": "让某个居民忽然感觉轻松一些。",
      "requires_actor": true,
      "requires_target": false,
      "requires_location": false,
      "event_type": "player_intervention_plugin",
      "importance": 55,
      "color_class": "important",
      "viewer_text_template": "{actor} 忽然觉得心里轻了一点。{note}",
      "actor_delta": {
        "stress": -8,
        "mood": 4
      }
    }
  ]
}
```

可用字段：

- `ability_id`: 必填，能力 ID，会作为前端提交的 `action`。
- `name`: 前端显示名。
- `description`: 前端说明。
- `requires_actor`: 是否需要选择居民。
- `requires_target`: 是否需要选择对象。
- `requires_location`: 是否需要选择地点。
- `viewer_text_template`: 玩家看到的事件文本，可用 `{actor}`、`{target}`、`{location}`、`{note}`。
- `actor_delta` / `target_delta`: 修改基础状态，字段包括 `health`、`energy`、`satiety`、`hydration`、`hygiene`、`social`、`fun`、`stress`、`mood`。
- `relationship_delta_actor_to_target` / `relationship_delta_target_to_actor`: 修改关系数值，如 `affection`、`trust`、`familiarity`、`conflict`、`fear`。
- `move_actor_to_selected_location` / `move_target_to_selected_location`: 为 `true` 时把对应居民移动到所选地点。

导入接口：

- 前端：游戏内“影响世界”面板右上角“导入能力”。
- 后端：`POST /api/interventions/import`。
- 能力目录：`GET /api/interventions`。
