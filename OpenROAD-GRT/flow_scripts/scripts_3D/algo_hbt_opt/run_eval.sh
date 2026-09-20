#!/usr/bin/env bash
# run_eval.sh -- 一键复现: GRT -> evaluate -> 官方加权分
#
#   ./run_eval.sh [case] [label] [baseline_label]
#     case          默认 bp_fe
#     label         本次运行标签, 默认 agent_hbt
#     baseline_label对比基线标签, 默认 baseline
#
# 产出:
#   output/<case>/<label>/
#   reports/<case>/<label>/metrics.json
#   reports/<case>/<label>/score.txt
set -euo pipefail

CASE=${1:-bp_fe}
LABEL=${2:-agent_hbt}
BASE_LABEL=${3:-baseline}

ROOT=/workspace/Open3DBench
INPUT="${ROOT}/input/open3dbench_8cases_post_hbt_input_20260724"
ALGO="${ROOT}/OpenROAD-GRT/flow_scripts/scripts_3D/algo_hbt_opt"

cd "${ROOT}"

# baseline 标签 = 官方原流程(不挂 HBT 优化); 其它标签才注入 GRT_PREPARE_TCL
if [ "${LABEL}" = "baseline" ]; then
  unset GRT_PREPARE_TCL
else
  export GRT_PREPARE_TCL="${ALGO}/grt_prepare.tcl"
fi
# 注意: 不要覆盖 RESULTS_DIR —— 它由官方流程自己决定,
# grt_prepare.tcl 会把求解器导出目录强制统一到同一个 results_dir.

echo "=========================================================="
echo "CASE=${CASE}  LABEL=${LABEL}  BASE=${BASE_LABEL}"
echo "GRT_PREPARE_TCL=${GRT_PREPARE_TCL:-<未设置, 官方原流程>}"
echo "=========================================================="

T0=$(date +%s)
./start_contest_docker.sh run-grt "${CASE}" "${INPUT}" "${LABEL}"
T1=$(date +%s)
GRT_SEC=$((T1 - T0))
echo "[run_eval] GRT 用时 ${GRT_SEC}s"

./start_contest_docker.sh evaluate \
    "${CASE}" "${INPUT}" "${ROOT}/output/${CASE}/${LABEL}" "${ROOT}/reports/${CASE}/${LABEL}"
T2=$(date +%s)
echo "[run_eval] evaluate 用时 $((T2 - T1))s"

BASE_M="${ROOT}/reports/${CASE}/${BASE_LABEL}/metrics.json"
NEW_M="${ROOT}/reports/${CASE}/${LABEL}/metrics.json"
SCORE_TXT="${ROOT}/reports/${CASE}/${LABEL}/score.txt"

mkdir -p "$(dirname "${SCORE_TXT}")"
python3 "${ALGO}/score.py" --base "${BASE_M}" --new "${NEW_M}" \
    --json "${ROOT}/reports/${CASE}/${LABEL}/score.json" | tee "${SCORE_TXT}"

echo "[run_eval] DONE  ->  ${SCORE_TXT}"
