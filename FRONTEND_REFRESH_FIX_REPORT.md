# Frontend refresh / left sidebar repair

This patch addresses the bug where the event feed and selected-agent drawer could update while the top clock and left map stayed frozen.

## Root cause fixed

The old frontend refresh path waited for a single all-in-one request group and used one global sequence guard. Under a fast WebSocket event stream, slow optional endpoints such as narrations/metrics/selected-agent details could delay or discard otherwise valid world/location snapshots. That made the clock and map look stale even while events continued to appear.

There was also a map-specific mistake: once `/locations` returned an `occupants` array, `MapPanel` treated that array as authoritative forever and ignored the fresher `agents` list. If the agent list refreshed before the location occupant snapshot did, the left map could keep showing old counts.

## Changes

- `frontend/src/app/App.tsx`
  - Critical data (`world`, `agents`, `locations`, `events`) now applies as soon as the REST responses return.
  - Slow optional panels (`narrations`, `metrics`, selected-agent details) no longer block the clock, map, residents list, or event feed.
  - Removed the practical effect of the global refresh sequence race for same-world updates; navigation is still guarded.
  - The visible clock also uses the latest loaded event time as a defensive fallback, so it cannot remain behind the event feed.
  - Agent locations get a display-level repair from recent movement and public Werewolf phase events. This is only a UI fallback; the backend remains authoritative after REST catches up.
  - WebSocket scheduling is now throttled with a pending queue instead of debouncing refreshes forever.

- `frontend/src/components/MapPanel.tsx`
  - Live `agents` are now the preferred source for occupant counts/names.
  - Backend `location.occupants` is used as fallback only when no agent list is available.

- `frontend/src/api/client.ts`
  - REST fetches use `cache: "no-store"` to avoid stale browser/proxy snapshots during rapid simulation.

- `backend/app/simulation/turn_runner.py`
  - Per-agent progress WebSocket broadcasts now include `world_summary`, so the header clock can move immediately even before the full REST refresh completes.

## Tests run

```bash
python -m compileall -q backend/app
cd frontend && npm ci && npm run build
PYTHONPATH=backend pytest -q backend/app/tests/test_agent_simulation_repairs.py backend/app/tests/test_event_ui_safety_and_worldviews.py
PYTHONPATH=backend pytest -q backend/app/tests/test_world_create_api.py backend/app/tests/test_aohp_protocol.py backend/app/tests/test_event_sanitization_and_memory.py
```

Results:

- Backend compile: passed
- Frontend production build: passed
- Targeted backend tests: 36 passed, 2 warnings

A full `pytest backend/app/tests` run was attempted, but it timed out in this environment before completion. No failure was observed before timeout.
