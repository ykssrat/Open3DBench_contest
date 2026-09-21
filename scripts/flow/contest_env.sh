#!/usr/bin/env bash
# 与根目录 start_contest_docker.sh 等价, 但额外把 HBT 算法需要的环境变量透传进容器.
#
# 背景: 赛方的 start_contest_docker.sh 只透传 HOME / CONTEST_ROOT,
#       GRT_PREPARE_TCL 之类的变量在宿主机上 export 是无效的 —— 必须显式 -e.
# 用法:
#   GRT_PREPARE_TCL=... scripts/flow/contest_env.sh run-grt bp_fe <input> <label>
#   scripts/flow/contest_env.sh evaluate output/bp_fe/baseline_hbt_opt reports/bp_fe/baseline_hbt_opt
set -euo pipefail

repository=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
image=${OPEN3DBENCH_CONTEST_IMAGE:-gaocr/3dbench-contest:20260914}
docker_bin=${DOCKER_BIN:-docker}

mkdir -p \
  "${repository}/.contest/home" \
  "${repository}/input" \
  "${repository}/output" \
  "${repository}/reports"

# 需要透传进容器的变量(只有非空才传)
PASSTHRU_VARS=(
  GRT_PREPARE_TCL
  GRT_PREPARE_MOVE
  GRT_PREPARE_REUSE
  GRT_PREPARE_MEASURE
  GRT_PREPARE_STANDALONE
  GRT_PREPARE_PLATFORM
  GRT_PREPARE_PY
  GRT_PREPARE_RUNPY
  GRT_PREPARE_DEBUG
  RESULTS_DIR
)

env_args=()
for v in "${PASSTHRU_VARS[@]}"; do
  val="${!v:-}"
  if [ -n "$val" ]; then
    env_args+=(-e "$v=$val")
  fi
done

docker_args=(run --rm)
if [[ -t 0 && -t 1 ]]; then
  docker_args+=(-it)
fi

command_args=("$@")
if [[ ${#command_args[@]} -eq 0 ]]; then
  command_args=(shell)
fi

exec "${docker_bin}" "${docker_args[@]}" \
  --init \
  --user "$(id -u):$(id -g)" \
  --ulimit stack=-1:-1 \
  -e HOME=/workspace/Open3DBench/.contest/home \
  -e CONTEST_ROOT=/workspace/Open3DBench \
  "${env_args[@]}" \
  -v "${repository}:/workspace/Open3DBench" \
  -v "${repository}/OpenROAD-GRT:/workspace/Open3DBench/OpenROAD-GRT-HBT:ro" \
  -w /workspace/Open3DBench \
  "${image}" "${command_args[@]}"
