#!/usr/bin/env bash

set -euo pipefail

bundle_root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
image=gaocr/3dbench-contest:20260914
expected_image_id=sha256:eb877c5e1f4d94881992b55d474ab189ab3308dac3f38208c5c8b0dd7544bd98
image_archive="${bundle_root}/docker/3dbench-contest_20260915.tar.gz"
docker_bin=${DOCKER_BIN:-docker}

if ! command -v "${docker_bin}" >/dev/null 2>&1; then
  echo "Docker is required but was not found." >&2
  exit 1
fi

local_image_id=$("${docker_bin}" image inspect "${image}" --format '{{.Id}}' 2>/dev/null || true)
if [[ "${local_image_id}" != "${expected_image_id}" ]]; then
  echo "Loading the bundled ${image} image..."
  "${docker_bin}" load --input "${image_archive}"
fi

loaded_image_id=$("${docker_bin}" image inspect "${image}" --format '{{.Id}}')
if [[ "${loaded_image_id}" != "${expected_image_id}" ]]; then
  echo "The loaded image does not match this bundle." >&2
  exit 1
fi

export DOCKER_BIN="${docker_bin}"
export OPEN3DBENCH_CONTEST_IMAGE="${expected_image_id}"
exec "${bundle_root}/Open3DBench/start_contest_docker.sh" "$@"
