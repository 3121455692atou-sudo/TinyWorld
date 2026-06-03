FROM node:22-bookworm-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TLW_CONFIG=/app/config.yaml \
    TLW_DATABASE_URL=sqlite:////app/data/world.sqlite3

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN python -c "import pathlib, tomllib; deps = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['dependencies']; pathlib.Path('/tmp/requirements.txt').write_text('\n'.join(deps) + '\n')" \
    && python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend ./backend
COPY worldpacks ./worldpacks
COPY config.example.yaml ./config.example.yaml
COPY README.md README.zh-CN.md README.en.md ./
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

RUN mkdir -p /app/data /app/logs /app/worldpacks/imported

EXPOSE 8010
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8010"]
