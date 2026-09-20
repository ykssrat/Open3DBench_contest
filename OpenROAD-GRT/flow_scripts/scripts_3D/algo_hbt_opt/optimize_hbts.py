#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
optimize_hbts.py -- HBT 布局求解入口 (保持原有调用契约).

  环境变量 RESULTS_DIR : 与 grt_prepare.tcl 共用的结果目录
  输出   $RESULTS_DIR/best_hbt_locations.csv : InstName,BestX,BestY

内部调用 hbt_assign(全局最小代价指派 + 拥塞价格不动点迭代).
任何异常都回退到"写出 HBT 原坐标", 保证下游 GRT 永远拿得到合法输入.
"""
import csv
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

RESULTS_DIR = os.environ.get("RESULTS_DIR") or "/workspace/Open3DBench/measure_run_bp_fe"


def fallback_original(results_dir):
    """回退: 直接把 HBT 原坐标写回 best_hbt_locations.csv."""
    p = os.path.join(results_dir, "export_hbt_topology.csv")
    rows = []
    if os.path.exists(p):
        with open(p, newline="", errors="ignore") as f:
            for row in csv.DictReader(f):
                try:
                    rows.append((row["InstName"].strip(),
                                 int(float(row["CurX"])), int(float(row["CurY"]))))
                except (KeyError, TypeError, ValueError):
                    continue
    out = os.path.join(results_dir, "best_hbt_locations.csv")
    with open(out, "w", newline="\n") as f:
        f.write("InstName,BestX,BestY\n")
        for n, x, y in rows:
            f.write("%s,%d,%d\n" % (n, x, y))
    print("[optimize_hbts] FALLBACK 写出原坐标 %d 个 -> %s" % (len(rows), out), flush=True)
    return out


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    try:
        import hbt_assign
    except Exception:
        traceback.print_exc()
        print("[optimize_hbts] hbt_assign 不可用 -> 回退", flush=True)
        fallback_original(RESULTS_DIR)
        return 0
    try:
        rows = hbt_assign.run(RESULTS_DIR)
    except Exception:
        traceback.print_exc()
        rows = None
    if not rows:
        fallback_original(RESULTS_DIR)
        return 0
    p = hbt_assign.write_csv(RESULTS_DIR, rows)
    print("[optimize_hbts] 写出 %d 个 HBT -> %s" % (len(rows), p), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
