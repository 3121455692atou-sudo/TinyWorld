#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
fi

mkdir -p config data logs debug_exports
if [ ! -f config/config.yaml ]; then
  cp ../../config.example.yaml config/config.yaml
fi

docker compose up -d --build
