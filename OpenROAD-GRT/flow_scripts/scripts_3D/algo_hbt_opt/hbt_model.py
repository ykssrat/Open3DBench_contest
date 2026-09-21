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
def density_prices(site_cells, chosen, radius, lam, want=None):
    """给定本轮被占用的格点, 返回每个格点的拥塞价格 rho.

    纯 Python 实现(官方容器无 numpy/scipy): 稀疏地把每个被占用格点的
    (2r+1)^2 邻域计数摊到哈希表里, 复杂度 O(被占用数 * (2r+1)^2),
    比"建全网格再做盒式滤波"小一个量级。

    site_cells : [(i, j), ...] 每个格点的网格坐标
    chosen     : 本轮被占用的格点下标
    radius     : 统计窗口半径(格点数)
    lam        : 价格强度(自标定)
    want       : 只在这些下标上返回(候选格点), 默认全部
    """
    r = int(radius)
    dens = {}
    for k in chosen:
        ci, cj = site_cells[k]
        for di in range(-r, r + 1):
            a = ci + di
            for dj in range(-r, r + 1):
                key = (a, cj + dj)
                dens[key] = dens.get(key, 0) + 1
    if want is None:
        want = range(len(site_cells))
    vals = [float(dens.get(site_cells[k], 0)) for k in want]
    mx = max(vals) if vals else 0.0
    if mx <= 0:
        return [0.0] * len(vals), vals
    return [lam * (v / mx) for v in vals], vals


def stdev(vals):
    """样本标准差(纯 Python, 避免依赖 numpy)."""
    n = len(vals)
    if n == 0:
        return 0.0
    mu = sum(vals) / n
    return (sum((v - mu) ** 2 for v in vals) / n) ** 0.5


def median(vals):
    vs = sorted(vals)
    n = len(vs)
    if n == 0:
        return 0.0
    return vs[n // 2] if n % 2 else 0.5 * (vs[n // 2 - 1] + vs[n // 2])


def calibrate_lambda_local(rows_cost, rows_unit, alpha=None):
    """按"同一 HBT 内部"的候选离散度标定价格强度(推荐用法).

    为什么不用全局离散度: 跨 HBT 的基础代价差异主要来自网的大小(差几个量级),
    而决定是否搬动的是"同一 HBT 的各个候选之间"的代价差 —— 用全局 std 标定
    会把价格放大几十倍, 反过来压死线长项. 这里取每个 HBT 内部 std 的中位数.

    rows_cost : 每个 HBT 在其候选格点上的基础代价列表
    rows_unit : 同上, 但为归一化密度(0~1)
    """
    if alpha is None:
        alpha = float(os.environ.get("HBT_CONGESTION_ALPHA", "0.35"))
    sb = median([stdev(r) for r in rows_cost if len(r) > 1])
    su = median([stdev(r) for r in rows_unit if len(r) > 1])
    if sb <= 0:
        return 0.0
    su = max(su, 0.02)          # 密度几乎均匀时防止价格炸掉
    return alpha * sb / su


def calibrate_lambda(base_costs, dens_samples):
    """自标定价格强度: 让价格项的离散度约为基础代价离散度的 alpha 倍.

    不写死任何绝对值, 因此对不同规模/不同 die 的隐藏用例都成立.
    """
    # 注意: 传入的必须是"价格项本身"的样本(即归一化密度 unit, 取值 0~1),
    # 不能传原始窗口计数 —— 两者差一个 max(dens) 因子, 传错会让 lambda 放大几十倍.
    alpha = float(os.environ.get("HBT_CONGESTION_ALPHA", "0.35"))
    sb = stdev(list(base_costs)) if len(base_costs) else 0.0
    sd = stdev(list(dens_samples)) if len(dens_samples) else 0.0
    if sb <= 0:
        return 0.0
    # 密度几乎均匀时 sd 会趋于 0, 不设下限会让价格炸掉
    sd = max(sd, 0.02)
    return alpha * sb / sd
