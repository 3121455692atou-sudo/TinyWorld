# Contributing to TinyWorld

Chinese version: [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md)

TinyWorld welcomes contributions from users, worldpack authors, plugin authors, frontend developers, backend developers, and simulation researchers.

## Reporting Bugs

When reporting a bug, include:

- Operating system and version.
- Python, Node.js, and browser versions.
- Whether you used `start.sh`, `Start.bat`, `scripts/dev.sh`, or manual commands.
- Steps to reproduce.
- Expected behavior and actual behavior.
- Relevant backend/frontend logs, with API keys and private data removed.

Please do not include API keys, provider tokens, private prompts, personal data, databases, or exported logs containing private content.

## Writing Worldpacks

Worldpacks can define worldviews, locations, world-specific prompts, variables, rule parameters, and toolsets.

Good worldpacks should:

- Keep IDs stable.
- Clearly document locations, variables, and rule changes.
- Avoid hardcoding private API endpoints or secrets.
- Include a short description of the intended play style.
- Include at least one small test or example config when possible.

## Writing Plugins

Plugins may extend project behavior and install worldpacks, toolsets, or integration metadata.

Good plugins should:

- Use clear package names and versions.
- Avoid broad filesystem or network assumptions.
- Document required services or third-party APIs.
- Avoid storing secrets inside plugin files.
- Fail gracefully when an optional integration is missing.

## Writing Tools

Tools should separate agent intention from system outcome. The LLM can request an action, but backend rules should validate and apply the result.

When adding tools:

- Define clear parameters.
- Add validation for required targets, locations, state, and permissions.
- Keep visible event text human-readable.
- Avoid leaking mechanical state deltas into player-facing text.
- Add tests for success, failure, and edge cases.

## Writing Tests

Useful tests include:

- AOHP parsing and repair behavior.
- Tool validation.
- Tool execution side effects.
- Worldpack import validation.
- Plugin import behavior.
- Simulation stability over multiple turns.
- Frontend build checks for major UI regressions.

Run:

```bash
uv run pytest
npm --prefix frontend run build
```

## Pull Requests

Before opening a pull request:

- Keep changes focused.
- Run tests and frontend build.
- Do not commit `.env`, `config.yaml`, local databases, exported archives, logs, or generated caches.
- Describe what changed and why.
