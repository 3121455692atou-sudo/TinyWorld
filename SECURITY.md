# Security Policy

TinyWorld is a local-first simulation project, but it can load plugins, worldpacks, API keys, local data, and model-provider configuration. Treat it as software that may execute code and process private data.

## Secrets and API Keys

- Do not commit `.env`, `config.yaml`, provider API keys, local databases, logs, exported archives, or private prompts.
- Prefer entering provider keys through the local UI or local environment variables.
- If you accidentally publish an API key, revoke it immediately at the provider.

## Plugin and Worldpack Safety

Worldpacks and plugins can change simulation behavior and may introduce new tools or integrations. Only import packages from sources you trust.

Current safety expectations:

- Plugins should not bundle secrets.
- Plugins should clearly describe external network services they require.
- Tool outcomes should be validated by backend logic, not decided only by agent text.
- Imported packages should be reviewed before use in long-running simulations.

The plugin system is still evolving. Do not treat untrusted plugins as sandboxed.

## Sensitive Simulation Content

TinyWorld may simulate conflict, crime, adult relationship systems, debt, social pressure, and other sensitive scenarios depending on enabled tools and worldpacks.

This is simulation content, not advice or instruction. If you build public worldpacks or plugins, document the intended content level and avoid surprising users.

## Reporting Vulnerabilities

Please report security issues privately when possible.

Include:

- Affected version or commit.
- Steps to reproduce.
- Impact.
- Logs or screenshots with secrets removed.

If GitHub private vulnerability reporting is enabled for the repository, use that. Otherwise contact the maintainer through the repository owner profile or open a minimal issue asking for a private contact path without disclosing exploit details.

## Supported Versions

TinyWorld is currently pre-1.0. Security fixes target the latest `main` branch unless a release branch is explicitly announced.

