#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/../.."

image=${1:-${PYTHON_IMAGE:-python:3.12-slim}}
mkdir -p docker/nas/wheelhouse
rm -f docker/nas/wheelhouse/*.whl

user_flag=""
if command -v id >/dev/null 2>&1; then
  user_flag="--user $(id -u):$(id -g)"
fi

docker run --rm $user_flag -v "$PWD:/work" -w /work "$image" sh -c "python -c \"import pathlib, tomllib; deps = tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['dependencies']; pathlib.Path('/tmp/tinyworld-requirements.txt').write_text('\\\\n'.join(deps) + '\\\\n')\" && python -m pip download -i https://pypi.tuna.tsinghua.edu.cn/simple -r /tmp/tinyworld-requirements.txt -d docker/nas/wheelhouse"
echo "Wrote wheels to docker/nas/wheelhouse"
