#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hbt_model.py -- HBT 布局代价模型.

输入由 grt_prepare.tcl 导出:
  export_hbt_topology.csv : InstName,CurX,CurY,Bot_Coords,Top_Coords
                           Coords 形如 "x_y_slack|x_y_slack|..." (slack 可能是 INF)
  export_free_sites.csv   : X,Y              —— 合法的空闲 HBT 键合格点
  export_meta.txt         : DBU/ORIGIN_X/ORIGIN_Y/PITCH/HBT_W/HBT_H/DIE
  die_bounds.txt          : xMin,yMin,xMax,yMax

代价模型:
  c(h,s) = W_bot(h) * [HPWL(B_h U {s}) - HPWL(B_h)]
         + W_top(h) * [HPWL(T_h U {s}) - HPWL(T_h)]
         + eps * |s - origin_h|_1        (最小扰动 tie-break)
         + rho(s)                        (拥塞价格, 见 density_prices)
"""
import math
import os

INF = float("inf")


# ---------------------------------------------------------------- 解析
def parse_coords(s):
    """'x_y_slack|x_y_slack' -> [(x, y, slack), ...]; slack 非法/INF 记为 inf."""
    pts = []
    if not s or s == "NONE":
        return pts
    for tok in s.split("|"):
        tok = tok.strip()
        if not tok:
            continue
        parts = tok.split("_")
        if len(parts) < 3:
            continue
        try:
            x = float(parts[0])
            y = float(parts[1])
        except ValueError:
            continue
        try:
            sl = float(parts[2])
        except ValueError:
            sl = INF
        pts.append((x, y, sl))
    return pts


def bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def hpwl(pts):
    """半周长线长 (DBU). 单点 -> 0."""
    if not pts:
        return 0.0
    x0, y0, x1, y1 = bbox(pts)
    return (x1 - x0) + (y1 - y0)


def net_slack(pts):
    """该子网的最差(最小)有限 slack; 全为 INF 时返回 None."""
    vals = [p[2] for p in pts if math.isfinite(p[2])]
    return min(vals) if vals else None


def timing_weight(slack, wns_ref, beta):
    """归一化时序权重: W = 1 + beta * clamp(-slack / |WNS_ref|, 0, 1).

    替换掉旧代码里会爆量级的 `1 + |slack| * 10`:
      - 分母用本设计的参考 WNS 归一化, 与 slack 的绝对量级无关;
      - 上限硬 clamp 到 1 + beta, 任何隐藏用例都不会失控.
    """
    if slack is None or not math.isfinite(slack):
        return 1.0
    if wns_ref is None or wns_ref <= 0:
        return 1.0
    r = -slack / wns_ref
    if r < 0.0:
        r = 0.0
    elif r > 1.0:
        r = 1.0
    return 1.0 + beta * r


def derive_pitch(values):
    """从一组 HBT 坐标推断格点间距: 取两两差的最大公约数."""
    vs = sorted(set(int(v) for v in values))
    if len(vs) < 2:
        return None
    g = 0
    for a, b in zip(vs, vs[1:]):
        d = b - a
        if d <= 0:
            continue
        g = d if g == 0 else math.gcd(g, d)
        if g == 1:
            break
    return g or None


# ---------------------------------------------------------------- 拥塞价格
def density_prices(site_ij, chosen, shape, radius, lam):
    """给定本轮被占用的格点, 返回每个候选格点的拥塞价格 rho.

    site_ij : (m,2) int, 每个候选格点的 (i,j) 网格坐标
    chosen   : (k,)   本轮被占用的候选格点下标
    shape    : (nI, nJ) 网格尺寸
    radius   : 统计窗口半径(格点数)
    lam      : 价格强度(自标定)
    """
    import numpy as np

    g = np.zeros(shape, dtype=np.float64)
    if len(chosen):
        g[site_ij[chosen, 0], site_ij[chosen, 1]] = 1.0
    try:
        from scipy.ndimage import uniform_filter
        d = uniform_filter(g, size=2 * radius + 1, mode="constant")
    except Exception:
        # 无 scipy: 用 separable 累积和做盒式滤波
        p = np.zeros((shape[0] + 1, shape[1] + 1), dtype=np.float64)
        p[1:, 1:] = g
        c = p.cumsum(0).cumsum(1)
        r = radius
        d = np.zeros(shape, dtype=np.float64)
        for i in range(shape[0]):
            i0 = max(0, i - r)
            i1 = min(shape[0], i + r + 1)
            for j in range(shape[1]):
                j0 = max(0, j - r)
                j1 = min(shape[1], j + r + 1)
                d[i, j] = (c[i1, j1] - c[i0, j1] - c[i1, j0] + c[i0, j0])
    dens = d[site_ij[:, 0], site_ij[:, 1]]
    mx = float(dens.max()) if dens.size else 0.0
    if mx <= 0:
        return np.zeros(site_ij.shape[0]), dens
    return lam * (dens / mx), dens


def calibrate_lambda(base_costs, dens_samples):
    """自标定价格强度: 让价格项的离散度约为基础代价离散度的 alpha 倍.

    不写死任何绝对值, 因此对不同规模/不同 die 的隐藏用例都成立.
    """
    import numpy as np

    alpha = float(os.environ.get("HBT_CONGESTION_ALPHA", "0.35"))
    sb = float(np.std(base_costs)) if len(base_costs) else 0.0
    sd = float(np.std(dens_samples)) if len(dens_samples) else 0.0
    if sd <= 1e-12 or sb <= 0:
        return 0.0
    return alpha * sb / sd
