#!/usr/bin/env bash
# ==============================================================================
#  run_grt_measure.sh
#    HBT 重布局 前/后 线长 & 拥塞 对比测量
#
#  依赖文件（默认与本脚本同目录；找不到会按常见流程路径自动探测，也可用 -t / -y 指定）：
#      grt_prepare.tcl      —— HBT 搬运 + 测量（本脚本自动传 GRT_STANDALONE=1）
#      optimize_hbts.py     —— HBT 位置求解器【可选】
#                              没有它也能跑：after 会跳过 HBT 搬运，
#                              若有现成的 best_hbt_locations.csv 则直接复用
#
#  用法：
#      ./run_grt_measure.sh -c bp_fe -i <输入包> -o <输出目录> -r <openroad>
#
#  参数：
#      -c  CASE        设计名，默认 bp_fe
#      -i  INPUT       输入包根目录（其下应有 cases/<CASE>/grt_input、platforms/）
#      -o  OUT         输出目录，默认 ./measure_run_<CASE>
#      -r  OPENROAD    openroad 可执行文件路径（不给则自动探测）
#      -t  TCL         grt_prepare.tcl 路径（不给则自动探测）
#      -y  PYOPT       optimize_hbts.py 路径（不给则自动探测，找不到就跳过求解）
#      -p  PLATFORM    平台目录名，默认 nangate45_3D
#      -P  PYTHON      python 解释器，默认自动探测 python3/python
#      -b              只跑 before（基线），跳过优化与对比
#      -h              帮助
#
#  也可全部用环境变量：CASE / OPEN3D_INPUT / OPENROAD_BIN / PLATFORM / PYTHON
#                      GRT_TCL / GRT_PYOPT
# ==============================================================================
set -uo pipefail

die() { echo "[FATAL] $*" >&2; exit 1; }
log() { echo "[$(date +%H:%M:%S)] $*"; }

# ----------------------------- 参数解析 -----------------------------
CASE="${CASE:-bp_fe}"
PLATFORM="${PLATFORM:-nangate45_3D}"
INPUT="${OPEN3D_INPUT:-}"
OUT=""
OR="${OPENROAD_BIN:-}"
PY="${PYTHON:-}"
TCL="${GRT_TCL:-}"
PYOPT="${GRT_PYOPT:-}"
BASELINE_ONLY=0

while getopts ":c:i:o:r:p:P:t:y:bh" opt; do
  case "$opt" in
    c) CASE="$OPTARG" ;;
    i) INPUT="$OPTARG" ;;
    o) OUT="$OPTARG" ;;
    r) OR="$OPTARG" ;;
    p) PLATFORM="$OPTARG" ;;
    P) PY="$OPTARG" ;;
    t) TCL="$OPTARG" ;;
    y) PYOPT="$OPTARG" ;;
    b) BASELINE_ONLY=1 ;;
    h) sed -n '2,42p' "${BASH_SOURCE[0]}"; exit 0 ;;
    :) die "选项 -$OPTARG 缺少参数" ;;
    *) die "未知选项 -$OPTARG（用 -h 查看帮助）" ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # 仓库根
# 官方流程里 tcl 的常见落点
FLOW_TCL="OpenROAD-GRT/flow_scripts/scripts_3D/algo_hbt_opt/grt_prepare.tcl"

# ---- grt_prepare.tcl：必须 ----
if [ -z "$TCL" ]; then
  for p in \
    "$SCRIPT_DIR/grt_prepare.tcl" \
    "$PWD/grt_prepare.tcl" \
    "$SCRIPT_DIR/$FLOW_TCL" \
    "$PWD/$FLOW_TCL" \
    "$PWD/../$FLOW_TCL"; do
    [ -f "$p" ] && { TCL="$p"; break; }
  done
fi
{ [ -n "$TCL" ] && [ -f "$TCL" ]; } || die "找不到 grt_prepare.tcl，请用 -t /path/to/grt_prepare.tcl 指定"

# ---- optimize_hbts.py：可选，缺了就关闭求解 ----
RUNPY=1
if [ -z "$PYOPT" ]; then
  for p in \
    "$SCRIPT_DIR/optimize_hbts.py" \
    "$PWD/optimize_hbts.py" \
    "$SCRIPT_DIR/OpenROAD-GRT/flow_scripts/scripts_3D/algo_hbt_opt/optimize_hbts.py" \
    "$PWD/OpenROAD-GRT/flow_scripts/scripts_3D/algo_hbt_opt/optimize_hbts.py"; do
    [ -f "$p" ] && { PYOPT="$p"; break; }
  done
fi
if [ -z "$PYOPT" ] || [ ! -f "$PYOPT" ]; then
  PYOPT=""; RUNPY=0
  echo "[WARN] 未找到 optimize_hbts.py —— 不调用求解器；" \
       "after 将复用已有 best_hbt_locations.csv，若也没有则等同于 before"
fi

# ----------------------------- 探测 python -----------------------------
resolve_py() {
  [ -n "$PY" ] && command -v "$PY" >/dev/null 2>&1 && { echo "$PY"; return 0; }
  local p
  for p in python3 python; do
    if command -v "$p" >/dev/null 2>&1; then echo "$p"; return 0; fi
  done
  return 1
}
PY="$(resolve_py)" || die "找不到 python3 / python"

# ----------------------------- 探测 openroad -----------------------------
resolve_openroad() {
  if [ -n "$OR" ]; then
    [ -x "$OR" ] || die "-r 指定的 openroad 不可执行：$OR"
    echo "$OR"; return 0
  fi
  local p
  p="$(command -v openroad 2>/dev/null)"; [ -n "$p" ] && { echo "$p"; return 0; }
  for p in \
    "$HOME/eda/open3Dbench/Open3DBench/.contest/openroad-src/build/src/openroad" \
    "$HOME/Open3DBench/.contest/openroad-src/build/src/openroad" \
    "/workspace/Open3DBench/OpenROAD-GRT/build/src/openroad" \
    "/workspace/Open3DBench/OpenROAD-3D/build/src/openroad" \
    "/workspace/OpenROAD/build/src/openroad" \
    "/workspace/OpenROAD-GRT/build/src/openroad" \
    "/usr/local/bin/openroad" \
    "/opt/openroad/bin/openroad" \
    "$HOME/.local/bin/openroad"
  do
    [ -x "$p" ] && { echo "$p"; return 0; }
  done
  # 最后在常见工程目录下扫一遍（限定深度，避免全盘）
  for p in $(find /workspace /opt /usr/local "$HOME" -maxdepth 6 \
               -type f -name openroad -perm -u+x 2>/dev/null | head -n5); do
    [ -x "$p" ] && { echo "$p"; return 0; }
  done
  return 1
}
OR="$(resolve_openroad)" || die "找不到 openroad，请用 -r /path/to/openroad 指定，或设置 OPENROAD_BIN"

# ----------------------------- 探测输入包 -----------------------------
# 判定标准：存在 <dir>/cases/<CASE>/grt_input
looks_like_input() {
  [ -n "${1:-}" ] && [ -d "$1/cases/$CASE/grt_input" ] && [ -d "$1/platforms/$PLATFORM" ]
}
resolve_input() {
  if [ -n "$INPUT" ]; then
    looks_like_input "$INPUT" || die "-i 指定的目录不是合法输入包（缺 cases/$CASE/grt_input 或 platforms/$PLATFORM）：$INPUT"
    echo "$INPUT"; return 0
  fi
  local d
  for d in \
    "$PWD/input/open3dbench_8cases_post_hbt_input_20260724" \
    "$SCRIPT_DIR/input/open3dbench_8cases_post_hbt_input_20260724" \
    "$PWD/../input/open3dbench_8cases_post_hbt_input_20260724" \
    "/workspace/Open3DBench/input/open3dbench_8cases_post_hbt_input_20260724" \
    "$HOME/Open3DBench/input/open3dbench_8cases_post_hbt_input_20260724" \
    "$PWD" "$SCRIPT_DIR" "$PWD/.."
  do
    looks_like_input "$d" && { echo "$d"; return 0; }
  done
  for d in "$PWD"/input/* "$SCRIPT_DIR"/input/*; do
    looks_like_input "$d" && { echo "$d"; return 0; }
  done
  return 1
}
INPUT="$(resolve_input)" || die "找不到输入包，请用 -i <输入包> 指定（其下应有 cases/$CASE/grt_input 与 platforms/$PLATFORM）"

OUT="${OUT:-$SCRIPT_DIR/measure_run_$CASE}"
mkdir -p "$OUT"

# ----------------------------- 环境回显 -----------------------------
echo "=============================================================="
echo " CASE      : $CASE"
echo " PLATFORM  : $PLATFORM"
echo " INPUT     : $INPUT"
echo " OUTPUT    : $OUT"
echo " OPENROAD  : $OR   ($("$OR" -version 2>&1 | head -n1))"
echo " PYTHON    : $PY   ($("$PY" -V 2>&1))"
echo " TCL       : $TCL"
if [ "$RUNPY" -eq 1 ]; then
  echo " SOLVER    : $PYOPT"
else
  echo " SOLVER    : （未找到 optimize_hbts.py，跳过 HBT 求解）"
fi
echo "=============================================================="

# ----------------------------- 跑一次 openroad -----------------------------
run_once() {
  local tag="$1" move="$2"
  mkdir -p "$OUT/measure/$tag"
  log "运行 [$tag]（GRT_PREPARE_MOVE=$move）..."
  if ! env \
      GRT_STANDALONE=1 \
      GRT_PREPARE_MEASURE=1 \
      GRT_MEASURE_TAG="$tag" \
      GRT_PREPARE_MOVE="$move" \
      GRT_INPUT_DIR="$INPUT" \
      GRT_PREPARE_PLATFORM="$PLATFORM" \
      CASE="$CASE" \
      RESULTS_DIR="$OUT" \
      GRT_PREPARE_PY="$PYOPT" \
      GRT_PREPARE_RUNPY="$RUNPY" \
      "$OR" -exit "$TCL" > "$OUT/$tag.log" 2>&1
  then
    echo "[ERROR] openroad 失败（tag=$tag）。日志尾部 50 行：" >&2
    tail -n 50 "$OUT/$tag.log" >&2
    exit 1
  fi
  for f in export_hbt_topology.csv export_macro_obstacles.csv die_bounds.txt best_hbt_locations.csv; do
    [ -f "$OUT/$f" ] && cp -f "$OUT/$f" "$OUT/measure/$tag/" 2>/dev/null
  done
  log "[$tag] 完成 -> $OUT/measure/$tag"
}

run_once before 0
if [ "$BASELINE_ONLY" -eq 0 ]; then
  run_once after 1
fi

# ----------------------------- 汇总对比 -----------------------------
summarize() {
  TAGS=(before)
  [ "$BASELINE_ONLY" -eq 0 ] && TAGS=(before after)
  "$PY" - "$OUT" "${TAGS[@]}" <<'PYEOF'
import os, re, sys

out  = sys.argv[1]
tags = sys.argv[2:]
N = r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)"

def read(p):
    return open(p, errors="ignore").read() if os.path.exists(p) else ""

def txt(tag, name):
    # 优先 rpt，其次该次运行的 openroad 日志
    return read(os.path.join(out, "measure", tag, name)) + "\n" + read(os.path.join(out, tag + ".log"))

def grab(s, pats):
    for p in pats:
        m = re.search(p, s, re.I)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None

# ---- GRT-0096 拥塞表解析 ------------------------------------------------
# global_route -verbose 把拥塞表打到 stdout（rpt 里抓不到，因为 report 命令没有返回值），
# 所以直接从本次运行的 openroad 日志里解析：
#   [INFO GRT-0096] Final congestion report:
#   Layer   Resource   Demand   Usage (%)   Max H / Max V / Total Overflow
#   metal1  ...        ...      ...         h / v / tot
#   Total   3801286    453564   11.93%      0 /  0 /  0
ROW = re.compile(r"^(\S+)\s+(\d+)\s+(\d+)\s+([\d.]+)%\s+(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*$")

_cg_cache = {}

def grt_congestion(tag):
    if tag in _cg_cache:
        return _cg_cache[tag]
    d = None
    s = read(os.path.join(out, tag + ".log"))
    i = s.find("GRT-0096")
    if i >= 0:
        rows, total = [], None
        for ln in s[i:].splitlines()[1:]:
            ln = ln.strip()
            m = ROW.match(ln)
            if not m:
                if rows or total:
                    break
                continue
            r = {"name": m.group(1), "resource": int(m.group(2)),
                 "demand": int(m.group(3)), "usage": float(m.group(4)),
                 "h": int(m.group(5)), "v": int(m.group(6)), "tot": int(m.group(7))}
            if m.group(1).lower() == "total":
                total = r
                break
            rows.append(r)
        if rows or total:
            if total is None:
                total = {"resource": sum(x["resource"] for x in rows),
                         "demand": sum(x["demand"] for x in rows),
                         "h": sum(x["h"] for x in rows),
                         "v": sum(x["v"] for x in rows),
                         "tot": sum(x["tot"] for x in rows),
                         "usage": max(x["usage"] for x in rows) if rows else 0.0}
            d = {"h": total["h"], "v": total["v"], "tot": total["tot"],
                 "usage": total["usage"],
                 "worst": max([x["tot"] for x in rows], default=0),
                 "worst_layer": max(rows, key=lambda x: x["tot"])["name"] if rows else "",
                 "rows": rows, "total": total}
            try:
                with open(os.path.join(out, "congestion_%s.txt" % tag), "w") as f:
                    f.write("Layer         Resource        Demand        Usage (%)"
                            "    Max H / Max V / Total Overflow\n")
                    for x in rows:
                        f.write("%-12s %12d %13d %13.2f%%   %6d / %5d / %6d\n" % (
                            x["name"], x["resource"], x["demand"], x["usage"],
                            x["h"], x["v"], x["tot"]))
                    f.write("%-12s %12d %13d %13.2f%%   %6d / %5d / %6d\n" % (
                        "Total", total.get("resource", 0), total.get("demand", 0),
                        total["usage"], total["h"], total["v"], total["tot"]))
            except Exception:
                pass
    _cg_cache[tag] = d
    return d

def cgv(tag, key):
    d = grt_congestion(tag)
    return None if d is None else d.get(key)

# ---- 指标定义：(显示名, 来源文件名, 正则候选 或 取值回调) ----
WL = [
    ("HPWL(um, 自算)", "00_hpwl_selfcheck.rpt", [r"HPWL_UM\s*=\s*" + N]),
    ("report_wirelength(um)", "02_wirelength.rpt",
        [r"GRT-0018\]\s*Total\s+wirelength\s*:\s*" + N,
         r"(?:total\s+)?wire\s*length\s*[:=]?\s*" + N,
         r"(?:total\s+)?wirelength\s*[:=]?\s*" + N,
         r"^\s*Total\s+" + N]),
]
CG = [
    ("Total H overflow(GR)",   "", lambda t: cgv(t, "h")),
    ("Total V overflow(GR)",   "", lambda t: cgv(t, "v")),
    ("Total overflow(GR)",     "", lambda t: cgv(t, "tot")),
    ("Max/Worst overflow(GR)", "", lambda t: cgv(t, "worst")),
    ("GR Usage(%)",            "", lambda t: cgv(t, "usage")),
]

def section(title, items):
    lines, rows = [], []
    W = 26
    lines.append("")
    lines.append("---- %s ----" % title)
    lines.append("%-*s %16s %16s %14s %9s" % (W, "metric", tags[0],
                 tags[1] if len(tags) > 1 else "-",
                 "delta", "delta%"))
    for name, fn, pats in items:
        if callable(pats):
            vals = [pats(t) for t in tags]
        else:
            vals = [grab(txt(t, fn), pats) for t in tags]
        rows.append((name, vals))
        a = vals[0]
        b = vals[1] if len(vals) > 1 else None
        fa = "%16s" % ("n/a" if a is None else "%.2f" % a)
        fb = "%16s" % ("n/a" if b is None else "%.2f" % b)
        if a is None or b is None:
            d, dp = "n/a", "n/a"
        else:
            d  = "%.2f" % (b - a)
            dp = ("n/a" if a == 0 else "%+.2f%%" % ((b - a) / abs(a) * 100.0))
        lines.append("%-*s %s %s %14s %9s" % (W, name, fa, fb, d, dp))
    return lines, rows

all_lines, all_rows = [], []
l, r = section("线长 Wirelength", WL); all_lines += l; all_rows += r
l, r = section("拥塞 Congestion (global_route)", CG); all_lines += l; all_rows += r

hdr = "=" * 78
hdr += "\n HBT 重布局 前/后 对比   (out=%s)" % out
hdr += "\n 报告目录: %s/measure/{%s}/   日志: %s/{%s}.log" % (out, ",".join(tags), out, ",".join(tags))
hdr += "\n" + "=" * 78
body = "\n".join(all_lines)
report = hdr + body + "\n\n注：n/a 表示该指标在日志/rpt 里都没抓到。\n" \
         "    线长取自 [INFO GRT-0018] Total wirelength；\n" \
         "    拥塞取自 global_route -verbose 打印的 GRT-0096 表（原件: congestion_<tag>.txt，\n" \
         "    逐层差异: diff_congestion_table.txt）；\n" \
         "    HPWL(um, 自算) 不依赖任何 report 命令，由 ITerm/BTerm bbox 聚合得到。\n"
print(report)

with open(os.path.join(out, "SUMMARY.txt"), "w") as f:
    f.write(report + "\n")
with open(os.path.join(out, "summary.csv"), "w") as f:
    f.write("type,metric," + ",".join(tags) + ",delta,delta_pct\n")
    for name, vals in all_rows:
        a = vals[0]; b = vals[1] if len(vals) > 1 else None
        d  = "" if (a is None or b is None) else "%.6f" % (b - a)
        dp = "" if (a is None or b is None or a == 0) else "%.4f" % ((b - a) / abs(a) * 100.0)
        f.write("metric,%s,%s,%s,%s,%s\n" % (
            name,
            "" if a is None else "%.6f" % a,
            "" if b is None else "%.6f" % b, d, dp))
print("已写出: %s/SUMMARY.txt, %s/summary.csv" % (out, out))
PYEOF
}

summarize

# 顺手留一份 rpt 差异，便于人工核对
if [ "$BASELINE_ONLY" -eq 0 ]; then
  for r in 00_hpwl_selfcheck 02_wirelength 06_congestion; do
    b="$OUT/measure/before/$r.rpt"; a="$OUT/measure/after/$r.rpt"
    if [ -f "$b" ] && [ -f "$a" ]; then
      diff -u "$b" "$a" > "$OUT/diff_$r.txt" 2>/dev/null || true
    fi
  done
  if [ -f "$OUT/congestion_before.txt" ] && [ -f "$OUT/congestion_after.txt" ]; then
    diff -u "$OUT/congestion_before.txt" "$OUT/congestion_after.txt" \
      > "$OUT/diff_congestion_table.txt" 2>/dev/null || true
  fi
fi

log "全部完成。输出目录：$OUT"
