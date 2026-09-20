#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
score.py -- 按赛题五官方口径计算加权得分.

赛题原文(第五节):
  "对于每个用例, 计算各项关键指标相对于基线的提升比例, 经加权求和后作为最终得分."
    TNS 25% | WNS 20% | Runtime 25% | 绕线线长 10% | DRC 10% | HBT 数量 10%
  HBT 数量: "统计 HBT 数量超过全局 HBT 总容量 30% 的部分" (评估器已给 hbt_free_limit)

用法:
  python3 score.py --base reports/bp_fe/baseline/metrics.json \
                   --new  reports/bp_fe/candidate/metrics.json \
                   [--grt-base 123.4] [--grt-new 100.2]
  --grt-* 为可选: 把 GRT 环节耗时并入 Runtime.
"""
import argparse
import json
import math
import os
import sys

W = {"tns": 0.25, "wns": 0.20, "runtime": 0.25,
     "wirelength": 0.10, "drc": 0.10, "hbt": 0.10}


def _get(m, *keys, default=None):
    for k in keys:
        if k in m and m[k] is not None:
            return m[k]
    return default


def extract(m, grt_seconds=None):
    cap = _get(m, "hbt_capacity", default=0) or 0
    cnt = _get(m, "hbt_count", default=0) or 0
    limit = _get(m, "hbt_free_limit", default=int(0.3 * cap)) or int(0.3 * cap)
    rt = _get(m, "evaluator_runtime_seconds", default=0.0) or 0.0
    if grt_seconds:
        rt += float(grt_seconds)
    excess = _get(m, "hbt_excess_count")
    if excess is None:
        excess = max(0, cnt - limit)
    return {
        "tns": float(_get(m, "tns_ns", "sta_setup_tns", "setup_tns", default=0.0)),
        "wns": float(_get(m, "wns_ns", "sta_setup_wns", "setup_wns", default=0.0)),
        "runtime": float(rt),
        "wirelength": float(_get(m, "drt_wirelength_um", "wirelength_um", default=0.0)),
        "drc": float(_get(m, "drc", "drc_violation_count", default=0.0)),
        "hbt_excess": float(excess),
        "hbt_count": cnt,
        "hbt_limit": limit,
    }


def ratio(key, b, n):
    """相对基线的提升比例: 越大越好, 正=改善."""
    if key in ("tns", "wns"):
        # 负值指标: 越接近 0 越好; 以 |baseline| 归一化
        den = abs(b) if abs(b) > 1e-12 else 1.0
        return (n - b) / den
    den = b if abs(b) > 1e-12 else 0.0
    if den == 0.0:
        return 0.0 if n == 0 else -1.0
    return (b - n) / den


def score(base_m, new_m, grt_base=None, grt_new=None):
    b = extract(base_m, grt_base)
    n = extract(new_m, grt_new)
    rows = []
    total = 0.0
    for k in ("tns", "wns", "runtime", "wirelength", "drc", "hbt"):
        bk = b["hbt_excess"] if k == "hbt" else b[k]
        nk = n["hbt_excess"] if k == "hbt" else n[k]
        r = ratio(k, bk, nk)
        total += W[k] * r
        rows.append((k, bk, nk, r, W[k], W[k] * r))
    return total, rows, b, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--grt-base", type=float, default=None)
    ap.add_argument("--grt-new", type=float, default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    bm = json.load(open(a.base))
    nm = json.load(open(a.new))
    total, rows, b, n = score(bm, nm, a.grt_base, a.grt_new)

    print("=" * 78)
    print("基线 : %s" % a.base)
    print("候选 : %s" % a.new)
    print("=" * 78)
    print("%-12s %14s %14s %10s %6s %10s" % ("指标", "基线", "候选", "提升比例", "权重", "加权贡献"))
    for k, bk, nk, r, w, c in rows:
        print("%-12s %14.4f %14.4f %9.4f%% %6.2f %10.5f"
              % (k, bk, nk, r * 100.0, w, c))
    print("-" * 78)
    print("HBT: count %s -> %s (limit %s, excess %s -> %s)"
          % (b["hbt_count"], n["hbt_count"], n["hbt_limit"],
             b["hbt_excess"], n["hbt_excess"]))
    print("加权总分 = %+.6f   (%+.4f%%)" % (total, total * 100.0))
    print("=" * 78)

    if a.json:
        json.dump({"score": total,
                   "rows": [{"k": k, "base": bk, "new": nk, "ratio": r,
                             "weight": w, "contrib": c} for k, bk, nk, r, w, c in rows]},
                  open(a.json, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
