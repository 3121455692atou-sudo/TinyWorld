# AIworld/TinyWorld optimization report — 2026-06-04

## Main fixes

- Event stream safety/UX: public event text is sanitized at backend event creation, API serialization, and frontend rendering. Mechanical backend phrases such as tool validation errors, reason codes, `llm_feedback`, `payload`, and `state_delta` are not shown in the public event stream.
- Character speech structure: character lines are rendered only from `payload.speech` / `payload.dialogue_lines[].text|speech`. `message`, `content`, `viewer_text`, and `agent_visible_text` are no longer used as dialogue bubble sources.
- Narration separation: public narration removes embedded quoted speech; character speech should appear as avatar + text bubble.
- Location sidebar: `/locations` now returns occupant details and the map panel shows current occupants, with frontend fallback from the agent list.
- Agent drawer refresh: selected agent detail fetches are guarded against stale async responses, avoiding copied cash/LLM/status data when switching residents.
- AOHP compact target selection: action options can now display `目标=编号`, and the model can answer `[66:1]` or `66 1` plus a second-line speech/body when needed. This reduces one-tool-per-character menu explosion.
- Tool failure retry guidance: failure feedback can provide correct format examples; repeated retryable format/target/location failures are hidden for the current turn after the third failure.
- Finance access: market/news/research/chart reading can be used before opening a brokerage account, so agents can naturally discover finance before trading.
- Help requests: food/water/help requests require speech and produce structured dialogue; same and adjacent scenes can hear suitable help events.
- Emergency survival choices: extreme hunger/thirst/health pressure raises priority for help, sharing, emergency/crime-related options without forcing crime.
- Child/baby care: child-care tools are available as reaction tools; newborn/infant/toddler fatal zero-need windows are extended so caregivers have time to react; child need events are escalated earlier; awake guardians can react even if the child is isolated in a private room.
- Medical scene tools: medical checkup, nutrition infusion, free washing, treating visible agents, feeding visible agents, and escorting agents to medical care are available.
- Worldviews: added/verified sweet romance, pure emotion, and werewolf worldviews with distinct scenes; default pregnancy and child growth cycles default to 3 days.
- Werewolf mode: role assignment, phase sync, discussion/vote/night tools, wolf consensus kill, seer/coroner/guard abilities, observer role visibility, and voting history support are wired into the turn runner.
- Memory continuity: memory prompt selection mixes important durable memories with recent facts in chronological order. It favors relationship, child, death, crisis, promise, finance, and werewolf inference facts without dumping raw event logs.
- UI/UX responsive guardrails: portrait mode prioritizes the event stream; panels/drawers are collapsible; text uses overflow wrapping; intervention panel has collapsed/expanded states.

## Tests run

Passed:

- `python -m compileall -q backend/app`
- `cd frontend && npm run build`
- `PYTHONPATH=backend pytest -q backend/app/tests/test_aohp_protocol.py` — 11 passed
- `PYTHONPATH=backend pytest -q backend/app/tests/test_event_sanitization_and_memory.py` — 4 passed
- `PYTHONPATH=backend pytest -q backend/app/tests/test_event_ui_safety_and_worldviews.py` — 3 passed
- `PYTHONPATH=backend pytest -q backend/app/tests/test_world_create_api.py` — 5 passed
- Relevant birth/private-room/child-growth tests in `test_effects_and_knowledge.py` passed individually.
- New child survival/guardian reaction tests in `test_turn_runner_survival.py` passed individually.

Not fully completed in this environment:

- Full all-test-suite runs and some full-file pytest runs timed out or were killed by the execution environment. I therefore validated the changed systems with targeted regression tests instead of claiming full-suite completion.

## Notes

- The implementation intentionally avoids extra reproduction/adult-content safety prompt wording. Reproduction remains an abstract rule/tool system rather than explicit narration.
- Frontend build emits a Vite chunk-size warning only; it does not fail the build.
