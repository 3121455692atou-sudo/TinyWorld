#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

if docker compose version >/dev/null 2>&1; then
  compose="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  compose="docker-compose"
else
  echo "docker compose / docker-compose not found" >&2
  exit 1
fi

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

images=${PYTHON_IMAGE_FALLBACKS:-"python:3.12-slim docker.m.daocloud.io/library/python:3.12-slim docker.1panel.live/library/python:3.12-slim docker.1ms.run/library/python:3.12-slim"}
timeout_s=${PYTHON_IMAGE_BUILD_TIMEOUT:-600}

for image in $images; do
  echo "Trying PYTHON_IMAGE=$image"
  if command -v timeout >/dev/null 2>&1; then
    if PYTHON_IMAGE="$image" timeout "$timeout_s" $compose -f docker-compose.yml build tinyworld-backend; then
      PYTHON_IMAGE="$image" $compose -f docker-compose.yml up -d tinyworld-backend
      echo "Started tinyworld-backend with PYTHON_IMAGE=$image"
      exit 0
    fi
  elif PYTHON_IMAGE="$image" $compose -f docker-compose.yml build tinyworld-backend; then
    PYTHON_IMAGE="$image" $compose -f docker-compose.yml up -d tinyworld-backend
    echo "Started tinyworld-backend with PYTHON_IMAGE=$image"
    exit 0
  fi
  echo "Failed or timed out: $image" >&2
done

echo "All PYTHON_IMAGE candidates failed. Use docker-compose.local-rootfs.yml with docker/nas/base/python-3.12-slim-rootfs.tar.gz for an offline base image build." >&2
exit 1
