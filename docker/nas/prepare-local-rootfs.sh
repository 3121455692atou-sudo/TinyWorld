#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/../.."

image=${1:-${PYTHON_IMAGE:-python:3.12-slim}}
out="docker/nas/base/python-3.12-slim-rootfs.tar.gz"
mkdir -p docker/nas/base

container_id=$(docker create "$image" true)
cleanup() {
  docker rm "$container_id" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker export "$container_id" | gzip -1 > "$out"
echo "Wrote $out from $image"
