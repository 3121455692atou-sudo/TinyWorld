# TinyWorld

TinyWorld is a local multi-agent social simulation sandbox for observing how LLM agents live together over long runs.

It gives agents a persistent world, resources, relationships, rules, tools, memory, and social pressure, then records what they do through a web interface. The project is designed for simulation, experimentation, worldbuilding, and agent-behavior observation.

Detailed documentation: https://docs.galbands.com

## What It Does

- Multi-agent life simulation with persistent residents, locations, events, memories, relationships, economy, work, housing, reproduction, childcare, and optional high-risk social systems.
- Web frontend for creating worlds, configuring agents, watching the event stream, inspecting state, exporting archives, and intervening in the world.
- Worldview import through worldpacks, so creators can define locations, rules, prompts, variables, and world-specific toolsets.
- Plugin and tool system for adding capabilities, toolsets, intervention abilities, and future integrations.
- AOHP action protocol for LLM agent actions, designed to reduce unstable JSON output by using action-number packets.
- Local deployment on desktop, server, and mobile devices, including macOS, Linux, Windows, and Android Termux.
- OpenAI-compatible provider configuration from the UI, with per-agent model selection and runtime controls.

## Why It Matters

TinyWorld is useful when you want to observe how LLM agents behave over time instead of only in one-shot chats. It can expose long-horizon behavior under resource scarcity, relationship conflict, debt, rules, work pressure, memory compression, social rejection, cooperation, and changing world constraints.

The project is not only a game interface. It is also a small research and evaluation environment for studying whether agents can maintain daily life, respond to social consequences, use tools correctly, recover from failures, and remain coherent across many simulated days.

## Screenshots

<img width="1632" height="727" alt="image" src="https://github.com/user-attachments/assets/fb23ed03-d042-4407-b0b2-2c010fd9284e" />
<img width="2560" height="1321" alt="image" src="https://github.com/user-attachments/assets/d91eb459-797f-4df0-a61a-96d53fab6701" />


## Quick Start

macOS / Linux / Android Termux:

```bash
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
./start.sh
```

Windows (first-time users must install Git, Python, and Node.js first; if `git clone` fails immediately, see "Windows From Scratch and Common Errors" below):

First check whether the tools are already installed:

```powershell
git --version
python --version
node -v
npm -v
```

If all commands print version numbers, skip installation and run `git clone` plus `.\Start.bat` below. If a command says it is not recognized or not found, install that tool.

Windows tool downloads:

- Git for Windows: https://git-scm.com/download/win
- Python 3.12: https://www.python.org/downloads/windows/
- Node.js LTS: https://nodejs.org/

```powershell
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
.\Start.bat
```

Open:

```text
http://127.0.0.1:8010/
```

`start.sh` / `Start.bat` installs dependencies, builds the frontend, and starts the backend. The first launch is slower; later launches are faster.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer
- Git
- uv, installed automatically by the quick-start scripts when missing

## Configuration

LLM providers, Base URL, API Key, models, narrator settings, and per-agent model settings can be configured from the web UI.

You can also copy `config.example.yaml` to `config.yaml` for local defaults. Do not commit `config.yaml`, `.env`, API keys, databases, logs, or exported archives.

## Deployment Modes

TinyWorld supports two common modes:

- Single-port mode: build the frontend, start the backend, and open `http://127.0.0.1:8010/`.
- Development mode: backend at `http://127.0.0.1:8010`, Vite frontend at `http://127.0.0.1:5174`.
- Docker Compose mode: use the compose project in `docker/nas/` to build from source on a local machine, server, or NAS.

If `http://127.0.0.1:8010/` returns JSON instead of the frontend, run:

```bash
npm --prefix frontend install
npm --prefix frontend run build
```

Then restart the backend.

## Docker Compose Deployment

The repository includes a Docker Compose project for local source builds in `docker/nas/`. The image builds the frontend and serves the web UI and API from the backend on one exposed port.

```bash
cd TinyWorld/docker/nas
cp .env.example .env
./start-nas.sh
```

You can also run it without the helper script:

```bash
cd TinyWorld/docker/nas
mkdir -p config data logs
cp ../../config.example.yaml config/config.yaml
docker compose up -d --build
```

Open:

```text
http://SERVER_OR_NAS_IP:5174/
```

Use `.env` to set the port and default model endpoint, such as `AIWORLD_PORT`, `TLW_LLM_BASE_URL`, `TLW_LLM_API_KEY`, `TLW_WORLD_MODEL`, and `TLW_PRO_MODEL`. Do not publish `.env`, `config/`, `data/`, or `logs/`.

If a NAS Docker panel supports building from a compose file, select `docker/nas/docker-compose.yml` and keep the build context as the full TinyWorld project directory. Copying only the `docker/nas/` subdirectory is not enough, because the Dockerfile needs `backend/`, `frontend/`, `worldpacks/`, `pyproject.toml`, and `uv.lock`.

If the NAS reports `docker.fnnas.com ... 401 Unauthorized`, the NAS is rewriting Docker Hub pulls to an unavailable mirror. `docker/nas/.env.example` now provides `NODE_IMAGE` and `PYTHON_IMAGE` defaults with a mirror prefix; you can also override them in `.env`.

## Platform Notes

macOS:

```bash
brew install git python node
./start.sh
```

Linux:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip nodejs npm
./start.sh
```

### Windows From Scratch and Common Errors

Most Windows installations do not include Git, Python, or Node.js. Install all three first, then close every PowerShell / CMD window and open a new PowerShell.

Check what is already installed first:

```powershell
git --version
python --version
node -v
npm -v
```

Tools that print version numbers do not need to be installed again. Install only the missing tools; if unsure, install the missing items in this order.

Recommended install commands:

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id OpenJS.NodeJS.LTS -e
```

If `winget` is not available, install them manually:

- Git for Windows: https://git-scm.com/download/win
- Python 3.12: https://www.python.org/downloads/windows/
- Node.js LTS: https://nodejs.org/

Installer notes:

- Keep the default Git for Windows options, and make sure Git is added to PATH.
- On the first Python installer screen, check `Add python.exe to PATH`.
- Keep the default Node.js options; it installs both `node` and `npm`.

Open a new PowerShell and verify the tools:

```powershell
git --version
python --version
node -v
npm -v
```

Then download and start TinyWorld:

```powershell
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
.\Start.bat
```

Common errors:

- `git is not recognized` or `git: command not found`: Git is not installed, or the terminal was opened before PATH was updated. Install Git for Windows and open a new terminal.
- `winget is not recognized`: use the manual download links above.
- `Python was not found`, `python` opens Microsoft Store, or the script says Python is required: reinstall Python with `Add python.exe to PATH` checked. You can also disable the Microsoft Store Python aliases in Windows "App execution aliases".
- `Node.js/npm is required` or `npm is not recognized`: install Node.js LTS, then open a new PowerShell.
- `git clone` is slow or interrupted: confirm that GitHub is reachable. You can also click `Code` -> `Download ZIP` on GitHub, extract the source, and run `.\Start.bat` from the extracted folder.
- `npm install`, `pip install`, or `uv sync` times out: this is usually a network or proxy issue. Retry on a different network or configure the system proxy before running `.\Start.bat` again.
- `address already in use`, `WinError 10048`, or the backend port is occupied: start on another backend port:

```powershell
$env:BACKEND_PORT = "8011"
.\Start.bat
```

After a successful start, open:

```text
http://127.0.0.1:8010/
```

If you used `BACKEND_PORT=8011`, open `http://127.0.0.1:8011/` instead.

Android Termux:

```bash
termux-change-repo
pkg update && pkg upgrade
pkg install git python nodejs-lts clang make rust openssl libffi sqlite termux-api
git clone https://github.com/3121455692atou-sudo/TinyWorld
cd TinyWorld
./start.sh
```

Android runs are possible but less stable than desktop or server runs. Keep the phone powered, avoid battery optimization, and prefer 64-bit devices.

## Common Commands

```bash
uv run pytest
npm --prefix frontend run build
./start.sh
./stop.sh
./scripts/dev.sh
```

Windows:

```powershell
.\Start.bat
.\Stop.bat
```

## Project Structure

- `backend/`: FastAPI backend, simulation loop, tool execution, AOHP parsing, world state, exports, and APIs.
- `frontend/`: Vite React frontend.
- `worldpacks/`: built-in and imported worldview/toolset packages.
- `scripts/`: developer and desktop startup helpers.
- `data/`: local runtime data, ignored by git.

## Contributing

Bug reports, worldpacks, plugins, tools, tests, UI improvements, and simulation-evaluation ideas are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

TinyWorld can import plugins and stores LLM provider settings locally. Do not publish secrets or untrusted runtime data. See [SECURITY.md](SECURITY.md).

## Roadmap

See [ROADMAP.md](ROADMAP.md).

## License

MIT. See [LICENSE](LICENSE).
