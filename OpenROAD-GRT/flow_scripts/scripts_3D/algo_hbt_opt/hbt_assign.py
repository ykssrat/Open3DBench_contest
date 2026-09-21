#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hbt_assign.py -- 阶段 A: HBT 全局最优重布局.

用"最小代价指派 / 最小费用流"替代旧的"逐个螺旋抢最近空格"贪心:
  1. 读 Tcl 导出的拓扑 / 合法格点 / meta;
  2. 构造稠密代价矩阵 C[n_hbt, n_site](纯 numpy 向量化, 秒级);
  3. 全局指派 -> 每个 HBT 一个互不相同的格点, 总代价最小;
  4. 拥塞价格不动点迭代 (拉格朗日松弛), 处理 HBT 之间不可分离的相互干扰;
  5. 输出 best_hbt_locations.csv (沿用原契约 InstName,BestX,BestY).

契约保证:
  - 原位置始终作为候选, 且旧解是可行解 => 模型代价必定 <= 现状;
  - 任何异常都回退到"写原位置", 绝不产出非法/空结果.
"""
import csv
import json
import math
import os
import sys
import time

try:
    import numpy as np
except Exception:                       # 官方容器里没有 numpy, 必须能跑
    np = None

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from hbt_model import (  # noqa: E402
    parse_coords, hpwl, net_slack, timing_weight,
    derive_pitch, density_prices, calibrate_lambda, calibrate_lambda_local,
)
from hbt_mcmf import solve_dense, solve_assignment  # noqa: E402

LOG = []


def log(msg):
    print("[hbt_assign] %s" % msg, flush=True)
    LOG.append(str(msg))


# ---------------------------------------------------------------- 输入
def load_meta(results_dir):
    meta = {}
    p = os.path.join(results_dir, "export_meta.txt")
    if os.path.exists(p):
        for line in open(p, errors="ignore"):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                meta[k.strip()] = v.strip()
    return meta


def load_hbts(results_dir):
    p = os.path.join(results_dir, "export_hbt_topology.csv")
    out = []
    with open(p, newline="", errors="ignore") as f:
        rd = csv.DictReader(f)
        for row in rd:
            name = (row.get("InstName") or "").strip()
            if not name:
                continue
            try:
                cx = int(float(row["CurX"]))
                cy = int(float(row["CurY"]))
            except (KeyError, TypeError, ValueError):
                cx = cy = None
            out.append({
                "name": name,
                "x": cx, "y": cy,
                "bot": parse_coords(row.get("Bot_Coords", "")),
                "top": parse_coords(row.get("Top_Coords", "")),
            })
    return out


def load_current(results_dir):
    """HBT 当前坐标: 优先 export_hbt_current.csv, 退化到已有的 best_hbt_locations.csv."""
    for fn, kx, ky in (("export_hbt_current.csv", "CurX", "CurY"),
                       ("best_hbt_locations.csv", "BestX", "BestY")):
        p = os.path.join(results_dir, fn)
        if not os.path.exists(p):
            continue
        d = {}
        try:
            with open(p, newline="", errors="ignore") as f:
                for row in csv.DictReader(f):
                    try:
                        d[row["InstName"].strip()] = (int(float(row[kx])),
                                                      int(float(row[ky])))
                    except (KeyError, TypeError, ValueError):
                        continue
        except Exception:
            continue
        if d:
            return d, fn
    return {}, None


def load_sites(results_dir):
    p = os.path.join(results_dir, "export_free_sites.csv")
    if not os.path.exists(p):
        return None
    xs, ys = [], []
    with open(p, newline="", errors="ignore") as f:
        for row in csv.DictReader(f):
            try:
                xs.append(int(float(row["X"])))
                ys.append(int(float(row["Y"])))
            except (KeyError, TypeError, ValueError):
                continue
    if not xs:
        return None
    return list(zip(xs, ys))


def synthesize_sites(hbts, bounds, meta, macros):
    """没有 export_free_sites.csv 时的保底: 按 die 边界 + 宏障碍生成格点."""
    ox = int(meta.get("ORIGIN_X", 11990))
    oy = int(meta.get("ORIGIN_Y", 11940))
    pitch = int(meta.get("PITCH", 12800))
    x0, y0, x1, y1 = bounds
    hw = int(meta.get("HBT_W", 0))
    hh = int(meta.get("HBT_H", 0))
    i0 = math.ceil((x0 - ox) / pitch)
    i1 = math.floor((x1 - hw - ox) / pitch)
    j0 = math.ceil((y0 - oy) / pitch)
    j1 = math.floor((y1 - hh - oy) / pitch)
    xs, ys = [], []
    for i in range(i0, i1 + 1):
        gx = ox + i * pitch
        for j in range(j0, j1 + 1):
            gy = oy + j * pitch
            bad = False
            for (mx0, my0, mx1, my1) in macros:
                if gx <= mx1 and gx + hw >= mx0 and gy <= my1 and gy + hh >= my0:
                    bad = True
                    break
            if not bad:
                xs.append(gx)
                ys.append(gy)
    return list(zip(xs, ys))


# ---------------------------------------------------------------- 代价
def build_base_cost(hbts, sites, beta, eps_move):
    n = len(hbts)
    m = sites.shape[0]
    SX = sites[:, 0].astype(np.float64)
    SY = sites[:, 1].astype(np.float64)
    C = np.zeros((n, m), dtype=np.float64)

    slacks = []
    for h in hbts:
        for pts in (h["bot"], h["top"]):
            s = net_slack(pts)
            if s is not None:
                slacks.append(s)
    wns_ref = abs(min(slacks)) if slacks else None
    if wns_ref:
        log("参考 WNS = %.4f ns (有限 slack 引脚 %d 个)" % (wns_ref, len(slacks)))
    else:
        log("无有效 slack (全 INF) -> 时序权重统一为 1.0")

    ndefault = 0
    for i, h in enumerate(hbts):
        for pts in (h["bot"], h["top"]):
            if not pts:
                ndefault += 1
                continue
            w = timing_weight(net_slack(pts), wns_ref, beta)
            base = hpwl(pts)
            x0, y0, x1, y1 = (min(p[0] for p in pts), min(p[1] for p in pts),
                              max(p[0] for p in pts), max(p[1] for p in pts))
            dx = np.maximum(SX, x1) - np.minimum(SX, x0)
            dy = np.maximum(SY, y1) - np.minimum(SY, y0)
            C[i] += w * (dx + dy - base)
        # 最小扰动 tie-break: 代价平台区内优先不搬动
        if h["x"] is not None:
            C[i] += eps_move * (np.abs(SX - h["x"]) + np.abs(SY - h["y"]))
    if ndefault:
        log("空子网(BOT/TOP 无引脚)条目: %d" % ndefault)
    return C, wns_ref


def percentile(vals, q):
    """纯 Python 分位数(线性插值)."""
    vs = sorted(vals)
    if not vs:
        return 0.0
    k = (len(vs) - 1) * (q / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(vs) - 1)
    return vs[lo] + (vs[hi] - vs[lo]) * (k - lo)


def hpwl_delta(bb, x, y):
    """把一个点加进集合后的 HPWL 增量(闭式解, O(1)).

    HPWL(P ∪ {s}) − HPWL(P) = max(0, sx−x1) + max(0, x0−sx) + (y 同理)
    """
    x0, y0, x1, y1 = bb
    d = 0.0
    if x > x1:
        d += x - x1
    elif x < x0:
        d += x0 - x
    if y > y1:
        d += y - y1
    elif y < y0:
        d += y0 - y
    return d


def build_cell_index(sites, pitch, ox, oy):
    """格点 -> 网格单元的倒排表, 供候选格点的环形扩张检索."""
    idx = {}
    for k, (x, y) in enumerate(sites):
        key = ((x - ox) // pitch, (y - oy) // pitch)
        idx.setdefault(key, []).append(k)
    return idx


def select_candidates(cell_index, center, K, max_ring):
    """以 center 单元为中心按环扩张取候选格点, 直到够 K 个(或到 max_ring)."""
    ci, cj = center
    out = []
    for r in range(max_ring + 1):
        if r == 0:
            cells = ((ci, cj),)
        else:
            ring = []
            for i in range(ci - r, ci + r + 1):
                ring.append((i, cj - r))
                ring.append((i, cj + r))
            for j in range(cj - r + 1, cj + r):
                ring.append((ci - r, j))
                ring.append((ci + r, j))
            cells = ring
        for key in cells:
            got = cell_index.get(key)
            if got:
                out.extend(got)
        if len(out) >= K:
            break
    return out


def run_sparse(hbts, sites, meta, results_dir, iters=3, beta=4.0,
               eps_move=0.05, radius=3):
    """零依赖路径: 每个 HBT 只保留 K 个候选格点, 再做全局指派.

    numpy 可用时走稠密矩阵(见 run); 官方容器没有 numpy, 这里必须能跑:
      - 候选由"引脚 bbox 中心向外环扩张"生成, 天然剪掉无意义的远点;
      - 代价用 HPWL 增量的闭式解, O(1) 一对;
      - 指派走拍卖/最小费用流, 拥塞价格迭代照旧.
    """
    t0 = time.time()
    n = len(hbts)
    K = int(os.environ.get("HBT_TOPK", "32"))
    max_ring = int(os.environ.get("HBT_MAX_RING", "80"))

    pitch = int(meta.get("PITCH", 0) or 0) or None
    ox = int(meta.get("ORIGIN_X", 0) or 0) or None
    oy = int(meta.get("ORIGIN_Y", 0) or 0) or None
    have = [h for h in hbts if h["x"] is not None]
    if pitch is None:
        pitch = derive_pitch([h["x"] for h in have]) \
            or derive_pitch([h["y"] for h in have])
    if pitch and have:
        if ox is None:
            ox = min(h["x"] for h in have) % pitch
        if oy is None:
            oy = min(h["y"] for h in have) % pitch
    log("格点: origin=(%s,%s) pitch=%s" % (ox, oy, pitch))

    # 原位置必须可选(否则"不搬"都不成立)
    sites = list(sites)
    pos = {(int(x), int(y)): k for k, (x, y) in enumerate(sites)}
    for h in have:
        key = (h["x"], h["y"])
        if key not in pos:
            pos[key] = len(sites)
            sites.append(key)
    m = len(sites)
    log("候选格点 = %d" % m)
    if m < n:
        log("候选格点 %d < HBT %d -> 回退原位置" % (m, n))
        return None

    use_congestion = bool(pitch and ox is not None and oy is not None)
    if not use_congestion:
        log("无法推断格点参数 -> 关闭拥塞迭代 (iters=1)")
        iters = 1
        cell_index = None
        site_cells = None
    else:
        cell_index = build_cell_index(sites, pitch, ox, oy)
        site_cells = [((x - ox) // pitch, (y - oy) // pitch) for (x, y) in sites]

    slacks = []
    for h in hbts:
        for pts in (h["bot"], h["top"]):
            s = net_slack(pts)
            if s is not None:
                slacks.append(s)
    wns_ref = abs(min(slacks)) if slacks else None
    log("参考 WNS = %s (有限 slack %d 个)" % (wns_ref, len(slacks)))

    # ---- 逐 HBT 生成候选与代价 ----
    cand = []
    origin_idx = []
    origin_cost = 0.0
    for h in hbts:
        subs = []
        allx, ally = [], []
        for pts in (h["bot"], h["top"]):
            if not pts:
                subs.append(None)
                continue
            allx.extend(p[0] for p in pts)
            ally.extend(p[1] for p in pts)
            bb = (min(p[0] for p in pts), min(p[1] for p in pts),
                  max(p[0] for p in pts), max(p[1] for p in pts))
            subs.append((bb, timing_weight(net_slack(pts), wns_ref, beta)))
        if h["x"] is not None:
            ok = pos[(h["x"], h["y"])]
            origin_idx.append(ok)
        else:
            origin_idx.append(None)
        if cell_index is not None and allx:
            cx = (min(allx) + max(allx)) / 2.0
            cy = (min(ally) + max(ally)) / 2.0
            center = (int((cx - ox) // pitch), int((cy - oy) // pitch))
            ks = select_candidates(cell_index, center, K, max_ring)
        elif cell_index is not None and origin_idx[-1] is not None:
            k0 = origin_idx[-1]
            x0, y0 = sites[k0]
            ks = select_candidates(cell_index,
                                   ((x0 - ox) // pitch, (y0 - oy) // pitch),
                                   K, max_ring)
        else:
            ks = []
        if origin_idx[-1] is not None and origin_idx[-1] not in ks:
            ks.append(origin_idx[-1])
        if not ks:
            # 极端退化: 全格点都试(量很小才会走到这)
            ks = range(m)
        row = []
        for k in ks:
            x, y = sites[k]
            c = 0.0
            for sub in subs:
                if sub is None:
                    continue
                bb, w = sub
                c += w * hpwl_delta(bb, x, y)
            if h["x"] is not None:
                c += eps_move * (abs(x - h["x"]) + abs(y - h["y"]))
            row.append((k, c))
        cand.append(row)
        if origin_idx[-1] is not None:
            for (k, c) in row:
                if k == origin_idx[-1]:
                    origin_cost += c
                    break

    avg_k = sum(len(r) for r in cand) / float(n) if n else 0
    log("候选弧 = %d (平均每 HBT %.1f 个候选)" % (sum(len(r) for r in cand), avg_k))

    # ---- 拥塞价格不动点迭代 ----
    best = None
    rho = {}
    lam = 0.0
    peak = 0.0
    for it in range(iters):
        arcs = []
        for i in range(n):
            for (k, c) in cand[i]:
                arcs.append((i, k, c + rho.get(k, 0.0)))
        try:
            pairs, _total = solve_assignment(arcs, n, m, backend="auto", verbose=False)
        except Exception as e:
            log("iter %d 指派失败: %r" % (it, e))
            break
        if len(pairs) != n:
            log("iter %d 指派不完整 (%d/%d)" % (it, len(pairs), n))
            break
        bcost = sum(dict((k, c) for (k, c) in cand[i])[pairs[i]]
                    for i in range(n))
        if use_congestion and it + 1 < iters:
            want = sorted({k for row in cand for (k, _c) in row})
            chosen = [pairs[i] for i in range(n)]
            unit, dens = density_prices(site_cells, chosen, radius, 1.0, want=want)
            # 按"同一 HBT 内部候选之间的离散度"标定, 而不是全局离散度
            umap = {k: u for k, u in zip(want, unit)}
            rows_cost = [[c for (_k, c) in cand[i]] for i in range(n)]
            rows_unit = [[umap.get(k, 0.0) for (k, _c) in cand[i]]
                         for i in range(n)]
            lam = calibrate_lambda_local(rows_cost, rows_unit)
            rho = {k: lam * u for k, u in zip(want, unit)}
            peak = percentile(dens, 95)
        moved = sum(1 for i in range(n) if origin_idx[i] != pairs[i])
        log("iter %d: 模型代价=%.1f 基线=%.1f 拥塞价格=%.3f p95密度=%.3f 搬动=%d 用时=%.1fs"
            % (it, bcost, origin_cost, lam, peak, moved, time.time() - t0))
        cand_best = {"pairs": dict(pairs), "cost": bcost, "peak": peak}
        if best is None or bcost < best["cost"] - 1e-9:
            best = cand_best
        elif peak < best["peak"] * 0.9 and bcost < best["cost"] * 1.002:
            best = cand_best

    if best is None:
        return None

    # 绝不比现状差(模型意义下)
    if origin_cost and best["cost"] > origin_cost + 1e-9:
        log("模型代价高于现状(%.1f > %.1f) -> 采用原位置"
            % (best["cost"], origin_cost))
        best = {"pairs": {i: origin_idx[i] for i in range(n)
                          if origin_idx[i] is not None},
                "cost": origin_cost, "peak": 0.0}
        if len(best["pairs"]) != n:
            return None

    rows = [(hbts[i]["name"], int(sites[best["pairs"][i]][0]),
             int(sites[best["pairs"][i]][1])) for i in range(n)]
    rep = {
        "n_hbt": n, "n_site": m, "mode": "sparse(无 numpy)",
        "avg_candidates": avg_k, "wns_ref": wns_ref, "beta": beta,
        "eps_move": eps_move, "lambda": lam, "iters": iters,
        "cost_before": origin_cost, "cost_after": best["cost"],
        "improve_pct": ((origin_cost - best["cost"]) / origin_cost * 100.0
                        if origin_cost else None),
        "moved": sum(1 for i in range(n) if origin_idx[i] != best["pairs"][i]),
        "seconds": round(time.time() - t0, 2),
        "log": LOG,
    }
    try:
        with open(os.path.join(results_dir, "hbt_assign_report.json"), "w") as f:
            json.dump(rep, f, indent=1, ensure_ascii=False)
    except Exception:
        pass
    log("完成(稀疏): 代价 %.1f -> %.1f (%s%%), 搬动 %d 个, 用时 %.1fs"
        % (origin_cost, best["cost"],
           "n/a" if rep["improve_pct"] is None else "%.2f" % rep["improve_pct"],
           rep["moved"], rep["seconds"]))
    return rows


# ---------------------------------------------------------------- 主流程
def run(results_dir, iters=None, beta=None, eps_move=None, radius=None):
    t0 = time.time()
    if iters is None:
        iters = int(os.environ.get("HBT_ITERS", "3"))
    if beta is None:
        beta = float(os.environ.get("HBT_TIMING_BETA", "4.0"))
    if eps_move is None:
        eps_move = float(os.environ.get("HBT_EPS_MOVE", "0.05"))
    if radius is None:
        radius = int(os.environ.get("HBT_CONGESTION_RADIUS", "3"))

    hbts = load_hbts(results_dir)
    if not hbts:
        log("无 HBT, 退出")
        return None
    if any(h["x"] is None for h in hbts):
        curmap, src = load_current(results_dir)
        if curmap:
            fixed = 0
            for h in hbts:
                if h["x"] is None and h["name"] in curmap:
                    h["x"], h["y"] = curmap[h["name"]]
                    fixed += 1
            log("当前坐标来自 %s (%d 个)" % (src, fixed))
        else:
            log("警告: 拿不到 HBT 当前坐标 -> 无'不搬'基准, 仍会求解")
    log("HBT 数量 = %d" % len(hbts))

    meta = load_meta(results_dir)
    try:
        bx0, by0, bx1, by1 = [int(v) for v in
                              open(os.path.join(results_dir, "die_bounds.txt")).read().strip().split(",")]
    except Exception:
        bx0, by0, bx1, by1 = 0, 0, 0, 0
    macros = []
    mp = os.path.join(results_dir, "export_macro_obstacles.csv")
    if os.path.exists(mp):
        for row in csv.DictReader(open(mp, errors="ignore")):
            try:
                macros.append((int(float(row["X_Min"])), int(float(row["Y_Min"])),
                               int(float(row["X_Max"])), int(float(row["Y_Max"]))))
            except (KeyError, TypeError, ValueError):
                pass

    sites_list = load_sites(results_dir)
    if sites_list is None:
        log("export_free_sites.csv 缺失 -> 按 die+宏 合成格点")
        sites_list = synthesize_sites(hbts, (bx0, by0, bx1, by1), meta, macros)
    if np is None:
        # 官方容器没有 numpy: 走零依赖稀疏路径
        log("numpy 不可用 -> 稀疏路径")
        return run_sparse(hbts, sites_list, meta, results_dir,
                          iters=iters, beta=beta, eps_move=eps_move,
                          radius=radius)
    sites = np.asarray(sites_list, dtype=np.int64)
    log("候选格点 = %d" % sites.shape[0])

    # ---- 网格参数(供密度场使用); 优先 meta, 其次从 HBT 原坐标推断 ----
    ox = int(meta.get("ORIGIN_X", 0)) or None
    oy = int(meta.get("ORIGIN_Y", 0)) or None
    pitch = int(meta.get("PITCH", 0)) or None
    if pitch is None:
        pitch = derive_pitch([h["x"] for h in hbts if h["x"] is not None])
    if pitch is None:
        pitch = derive_pitch([h["y"] for h in hbts if h["y"] is not None])
    have_xy = [h for h in hbts if h["x"] is not None]
    if ox is None and have_xy:
        ox = min(h["x"] for h in have_xy) % (pitch or 1)
    if oy is None and have_xy:
        oy = min(h["y"] for h in have_xy) % (pitch or 1)
    if not pitch or ox is None or oy is None:
        log("无法推断格点参数 -> 关闭拥塞迭代 (iters=1)")
        iters = 1
    log("格点: origin=(%s,%s) pitch=%s" % (ox, oy, pitch))

    # ---- 保证原位置一定在候选里(可行性 + "不搬"永远是选项) ----
    if have_xy:
        cur = set((h["x"], h["y"]) for h in have_xy)
        have = set((int(a), int(b)) for a, b in sites)
        miss = sorted(cur - have)
        if miss:
            log("补入 %d 个 HBT 原坐标格点" % len(miss))
            sites = np.vstack([sites, np.array(miss, dtype=np.int64)])

    n, m = len(hbts), sites.shape[0]
    if n > m:
        log("候选格点 %d < HBT %d -> 回退原位置" % (m, n))
        return None

    C, wns_ref = build_base_cost(hbts, sites, beta, eps_move)

    # ---- 网格索引 ----
    if pitch and ox is not None and oy is not None:
        site_i = ((sites[:, 0] - ox) // pitch).astype(np.int64)
        site_j = ((sites[:, 1] - oy) // pitch).astype(np.int64)
        shape = (int(site_i.max()) + 1, int(site_j.max()) + 1)
    else:
        site_i = site_j = None
        shape = (1, 1)

    # ---- 现状代价(对照) ----
    def cost_of(pairs):
        return float(sum(C[i, j] for i, j in pairs.items()))

    cur_pairs = {}
    if have_xy:
        pos = {(int(a), int(b)): k for k, (a, b) in enumerate(sites)}
        ok = True
        for i, h in enumerate(hbts):
            k = pos.get((h["x"], h["y"]))
            if k is None:
                ok = False
                break
            cur_pairs[i] = k
        if not ok:
            cur_pairs = {}
    base_cost_before = cost_of(cur_pairs) if cur_pairs else None

    # ---- 不动点迭代 ----
    best = None
    rho = np.zeros(m, dtype=np.float64)
    lam = 0.0
    for it in range(iters):
        Ctot = C + rho[None, :]
        pairs, total = solve_dense(Ctot)
        if len(pairs) != n:
            log("iter %d 指派失败 (%d/%d)" % (it, len(pairs), n))
            break
        bcost = cost_of(pairs)
        dens = None
        peak = 0.0
        if site_i is not None and it + 1 < iters:
            chosen = [pairs[i] for i in range(n)]
            site_cells = [(int(site_i[k]), int(site_j[k])) for k in range(m)]
            # lam=1.0 -> unit = 归一化密度, dens = 原始窗口计数
            unit, dens = density_prices(site_cells, chosen, radius, 1.0)
            lam = calibrate_lambda([C[i, chosen[i]] for i in range(n)], unit)
            rho = np.asarray(unit, dtype=np.float64) * lam
            peak = percentile(dens, 95)
        moved = sum(1 for i in range(n)
                    if cur_pairs.get(i) != pairs[i])
        log("iter %d: 模型代价=%.1f 基线=%s 拥塞价格=%.3f p95密度=%.3f 搬动=%d 用时=%.1fs"
            % (it, bcost,
               "n/a" if base_cost_before is None else "%.1f" % base_cost_before,
               lam, peak, moved, time.time() - t0))
        cand = {"pairs": dict(pairs), "cost": bcost, "peak": peak}
        if best is None or bcost < best["cost"] - 1e-9:
            best = cand
        elif (peak < best["peak"] * 0.9
              and bcost < best["cost"] * 1.002):
            best = cand  # 代价几乎相同但拥塞显著更低

    if best is None:
        return None

    # ---- 绝不比现状差 ----
    if base_cost_before is not None and best["cost"] > base_cost_before + 1e-9:
        log("模型代价高于现状(%.1f > %.1f) -> 采用原位置"
            % (best["cost"], base_cost_before))
        best = {"pairs": cur_pairs, "cost": base_cost_before, "peak": 0.0}

    out = []
    for i, h in enumerate(hbts):
        k = best["pairs"][i]
        out.append((h["name"], int(sites[k, 0]), int(sites[k, 1])))

    rep = {
        "n_hbt": n, "n_site": int(m),
        "wns_ref": wns_ref, "beta": beta, "eps_move": eps_move,
        "lambda": lam, "iters": iters,
        "cost_before": base_cost_before, "cost_after": best["cost"],
        "improve_pct": (None if not base_cost_before or base_cost_before == 0
                        else (base_cost_before - best["cost"]) / base_cost_before * 100.0),
        "moved": sum(1 for i in range(n)
                     if cur_pairs.get(i) != best["pairs"][i]),
        "seconds": round(time.time() - t0, 2),
        "log": LOG,
    }
    try:
        with open(os.path.join(results_dir, "hbt_assign_report.json"), "w") as f:
            json.dump(rep, f, indent=1, ensure_ascii=False)
    except Exception:
        pass
    log("完成: 代价 %.1f -> %.1f (%s%%), 搬动 %d 个, 用时 %.1fs"
        % (base_cost_before or 0.0, best["cost"],
           "n/a" if rep["improve_pct"] is None else "%.2f" % rep["improve_pct"],
           rep["moved"], rep["seconds"]))
    return out


def write_csv(results_dir, rows):
    p = os.path.join(results_dir, "best_hbt_locations.csv")
    with open(p, "w", newline="\n") as f:
        f.write("InstName,BestX,BestY\n")
        for name, x, y in rows:
            f.write("%s,%d,%d\n" % (name, x, y))
    return p
