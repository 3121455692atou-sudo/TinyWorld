# Change Log

## 2026-06-09

- One-click setup, agent archive import/export, and archived setup reuse now preserve initial acquaintance and affection settings.
- Simulation steps for the same world are serialized to avoid duplicate events from concurrent auto-run and manual continue calls.
- Werewolf morning announcements are deduplicated so the same notice and body-discovery event are not written repeatedly for one day.
- Werewolf notice-board text is standardized as "狼人存在于村中" for the public indication that wolves remain.
- Werewolf vending-machine scenes can query, recommend, buy, and consume inventory supplies through the shared item flow.
- Market and vending-machine item query text uses neutral wording instead of fixed vendor narration.
- Food and drinks use the same inventory-supply action path; item attributes decide whether the result is eating or drinking.
- Manual start/continue after consecutive LLM failures resets the failure counter and retries the same agent.
- The identity archive UI has improved search and filtering.
- Runtime settings, one-click setup overview, import/export, and reuse controls are shown consistently in the frontend.

Verification:

- `uv run pytest backend/app/tests -q` passed.
- `npm --prefix frontend run build` passed.

## 2026-06-07

- Added an independent market catalog and inventory item service for search, recommendations, purchase, consumption, placement, pickup, transfer, and gift-affection checks.
- Normal simulation no longer forces urgent survival tools before the LLM chooses an action; hunger, thirst, and fatigue only affect prompt context and menu priority.
- Removed fixed normal-mode fallback actions after LLM or repair failure.
- Provider/API failures are the only failures counted toward consecutive LLM-failure auto-pause; parse/protocol errors are recorded separately.
- Tool format, target, and location failures give corrective feedback and can hide the failing tool for the rest of the turn after repeated failures.
- Normal speech, help, introduction, social, and confrontation actions no longer receive default backend-written character dialogue.
- Werewolf exiles are written into public memory and removed from future speech, vote, attack, inspection, and guard targets.
- Werewolf night-kill wins preserve `winner` and final-speech state; phase sync no longer advances into a new morning after the game is already decided.
- Werewolf final speeches no longer use fixed fallback text; empty, failed, or truncated outputs are not written or advanced.
- Werewolf final speeches support longer endgame text and detect provider truncation reasons.
- Werewolf day 1 is daytime free talk only, night abilities begin on night 1, and formal roundtable/voting starts on day 2.
- Werewolf roundtable, voting, and night phases use stricter host-flow tools so normal actions do not steal phase turns.
- The Windows start script reuses an existing PATH `uv` before trying to install it.

Verification:

- Relevant backend regression tests passed.
- Frontend build passed.

## 2026-06-06

- `/api/worlds` no longer writes runtime state or returns full world settings for the list view.
- SQLite parallel mode no longer opens separate sessions for same-turn concurrent submissions; action selection is sequential before batched execution.
- The left snapshot reads latest event time so the sidebar clock does not lag behind the event stream.
- High-frequency left snapshots omit full settings and avatar base64; the frontend preserves settings and hydrates avatars once per world.
- Frontend GET requests no longer send `Content-Type: application/json`, avoiding unnecessary CORS preflights in dev mode.
- Sidebar agent, location, avatar, and clock merging was strengthened to avoid wiping existing data with lightweight snapshots.
- Relationship-stage routing now filters and orders relationship, breakup, repair, intimacy, contraception, pregnancy-test, and birth-preparation tools per target.
- `validate_tool` enforces relationship-stage gates so the LLM cannot call unavailable relationship tools directly.
- Adult-intimacy semantic alignment now requires both menu availability and target relationship-stage permission.
- Werewolf locations and prompts avoid revealing hidden identity mechanics before the rules are discovered.
- Wolves receive private pack memory; night attacks require aligned wolf targets and can force wolf discussion first.
- Secret, wolf-only, target-parameter, and known-name tool routing is stricter.
- Low-information public events such as `do_nothing`, tool-failure placeholders, and candidate-tool debug events are hidden from normal event feeds.
- Werewolf default schedule changed to 08:00 free talk, 12:00 roundtable, 18:00 vote, and 22:00 night actions.
- Multiple wolves must hold a wolf discussion before night attack becomes available.
- Werewolf victory writes a decided event and enters final speeches before the game-end event.
- Frontend world-list loading has a timeout fallback instead of staying on the loading screen forever.

Verification:

- Backend compile passed.
- Relevant backend regression tests passed.
- Frontend build passed.

## 2026-06-05

- Public event text is sanitized at creation, API serialization, and frontend rendering so internal validation errors and payload details are not shown to players.
- Character speech is rendered only from structured speech/dialogue payload fields.
- Narration and character speech are separated to avoid duplicated quoted dialogue.
- AOHP menus support compact target selection to reduce one-tool-per-target menu expansion.
- Tool failure feedback includes correct format examples, and repeated retryable failures can hide the tool for the current turn.
- Dynamic tool routing scans the full catalog with context scoring instead of only using the first few catalog entries.
- Tool target inference no longer misuses visibility conditions as parameter rules.
- Scene gates and guaranteed essentials keep food, medical, library, finance, care, rescue, movement, and survival tools available in the right contexts.
- Private-room validation failures are system-only; other agents' private rooms are no longer normal movement targets.
- Meta, debug, and legacy abstract catalog tools no longer enter agent menus or execute through free calls.
- The tool catalog was pruned so pure emotion, preference, attitude, greeting, and atmosphere actions are expressed through speech, nearby speech, private notes, or memory instead of separate tools.
- State-changing tools remain available for movement, survival, care, medicine, work, finance, law, crime, relationship confirmation, reproduction flow, and Werewolf flow.
- Added a live left-snapshot path that reads world, agents, and locations in one snapshot and supports manual refresh.
- Critical frontend snapshots land independently so slow narration, metrics, or selected-agent detail calls do not block world, agent, location, and event updates.
- WebSocket refresh uses throttling plus a pending queue.
- The world-intervention panel expanded/collapsed state was fixed.
- LLM provider settings support streaming, temperature, top_p, max_tokens, presence_penalty, and frequency_penalty globally and per agent.
- The OpenAI-compatible client supports SSE streaming.
- OpenAI-compatible request timeout is configurable instead of hardcoded to 60 seconds.
- Werewolf role assignment, phase sync, discussion, voting, night abilities, wolf consensus kill, seer/coroner/guard abilities, observer visibility, and voting history are wired into the scheduler.
- Werewolf discussion, vote, and night menus are narrowed to phase-required tools.
- Werewolf roundtable uses a host-style current-speaker flow.
- Werewolf voting supports day-1 no-exile and forced exile from day 2 onward.
- Werewolf night recovery stabilizes surviving or critical players so morning roundtables are not swallowed by hunger, dehydration, fatigue, or unconsciousness.
- Agent archive import detects zip content and files with extra `.zip.` suffixes instead of parsing zip files as JSON.
- Memory prompt selection mixes important durable memories with recent facts in chronological order.
- Baby/child care, medical scenes, food/water help, and finance-information access were made more reachable.

Verification:

- Backend compile passed.
- Backend targeted and grouped regression tests passed.
- Frontend build passed.

## 2026-06-04

- Core worldviews, toolsets, plugins, AOHP protocol, event safety, Werewolf base flow, memory continuity, and responsive UI were consolidated for the public version.
- Mobile portrait layout prioritizes the event stream, collapses side panels, and adds text wrapping and overflow guardrails.

Verification:

- Backend core tests passed.
- Frontend build passed.
