# TinyWorld Roadmap

Chinese version: [ROADMAP.zh-CN.md](ROADMAP.zh-CN.md)

This roadmap describes the intended direction. Details may change as the simulation, UI, and plugin ecosystem evolve.

## v1: Single-Machine Multi-Agent Simulation

- Stable local FastAPI backend and React frontend.
- Persistent SQLite world state.
- AOHP action protocol for agent actions.
- Configurable LLM providers and per-agent models.
- Core world simulation with locations, memory, resources, relationships, tools, and exports.
- Basic mobile and desktop support.

## v1.1: Plugin Ecosystem

- Clear plugin package format.
- Better plugin installation and update UI.
- More examples for toolsets, intervention abilities, and integrations.
- Stronger validation for imported packages.
- Safer handling of plugin metadata and external services.

## v1.2: Worldview Market and Sharing

- Better worldpack authoring documentation.
- Example worldpacks for different genres and simulation styles.
- Import/export flows for sharing worlds, characters, toolsets, and presets.
- Better version compatibility checks for worldpacks.

## v1.3: Evaluation and Visualization

- Multi-agent stability benchmarks.
- Survival, social, relationship, and tool-use metrics.
- Visualization for events, relationships, location flow, economy, and failures.
- Reproducible simulation runs for comparing model behavior.

## v2: Distributed Simulation and Cloud Observation

- Multi-process or distributed simulation workers.
- Long-run cloud/server observation mode.
- Multi-user observer UI.
- Better scheduling, persistence, and replay support for very large worlds.
