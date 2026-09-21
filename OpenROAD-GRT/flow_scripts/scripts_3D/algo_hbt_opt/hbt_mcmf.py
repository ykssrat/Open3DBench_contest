#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hbt_mcmf.py -- HBT -> 格点 的全局最小代价指派求解器.

问题: n_left 个 HBT 各选 1 个格点, 每个格点最多容纳 1 个 HBT, 代价可分离.
     这是矩形线性指派 / 最小费用流, 存在多项式时间全局最优解.
     贪心"逐个抢最近空格"是任意劣的近似, 这里彻底不用.

后端优先级(自动降级, 保证离线环境可跑):
  1) ortools  SimpleMinCostFlow   (C++, 最快; 代价需整数 -> 内部按 SCALE 缩放)
  2) scipy    linear_sum_assignment (Jonker-Volgenant, 稠密矩阵)
  3) 纯 Python 最小费用流 (Dijkstra + Johnson 势函数, 无第三方依赖)

对外主入口:
    solve_assignment(arcs, n_left, n_right) -> (assign, total_cost)
        arcs   : [(i, j, cost), ...]   i in [0,n_left), j in [0,n_right)
        assign : {i: j}
"""
from __future__ import annotations

import heapq
import logging
import math
import os

LOG = logging.getLogger("hbt_mcmf")

# ortools 只接受整数费用, 统一放大系数
SCALE = 1000
# scipy 稠密矩阵中"不可选"的大值(必须是有限值)
BIG = 1e15


class Infeasible(RuntimeError):
    pass


# --------------------------------------------------------------------------
# 后端 1: ortools
# --------------------------------------------------------------------------
def _solve_ortools(arcs, n_left, n_right):
    from ortools.graph import pywrapgraph  # type: ignore

    S = 0
    L0 = 1
    R0 = L0 + n_left
    T = R0 + n_right
    mcf = pywrapgraph.SimpleMinCostFlow()
    add = getattr(mcf, "AddArcWithCapacityAndUnitCost", None) \
        or getattr(mcf, "add_arc_with_capacity_and_unit_cost")

    for i in range(n_left):
        add(S, L0 + i, 1, 0)
    for j in range(n_right):
        add(R0 + j, T, 1, 0)
    for (i, j, c) in arcs:
        # 代价非负, 放大后取整
        ci = int(round(c * SCALE))
        add(L0 + i, R0 + j, 1, ci)

    # Solve() = 最大流下的最小费用; 这里最大流必然是 n_left(可行时)
    status = mcf.Solve()
    if status != mcf.OPTIMAL:
        raise Infeasible("ortools: status=%s" % status)
    if mcf.MaximumFlow() != n_left:
        raise Infeasible("ortools: 流量 %d < %d, 格点不足" % (mcf.MaximumFlow(), n_left))

    assign = {}
    for e in range(mcf.NumArcs()):
        if mcf.Flow(e) <= 0:
            continue
        u, v = mcf.Tail(e), mcf.Head(e)          # 弧方向 tail -> head
        if L0 <= u < L0 + n_left and R0 <= v < R0 + n_right:
            assign[u - L0] = v - R0
    if len(assign) != n_left:
        raise Infeasible("ortools: 解析出 %d/%d 条指派" % (len(assign), n_left))
    total = mcf.OptimalCost() / float(SCALE)
    return assign, total


# --------------------------------------------------------------------------
# 后端 2: scipy
# --------------------------------------------------------------------------
def _solve_scipy(arcs, n_left, n_right):
    import numpy as np  # type: ignore
    from scipy.optimize import linear_sum_assignment  # type: ignore

    used_cols = sorted({j for (_, j, _) in arcs})
    col_of = {j: k for k, j in enumerate(used_cols)}
    ncol = len(used_cols)
    if n_left > ncol:
        raise Infeasible("scipy: 候选格点数 %d < HBT 数 %d" % (ncol, n_left))

    M = np.full((n_left, ncol), BIG, dtype=np.float64)
    for (i, j, c) in arcs:
        if c < M[i, col_of[j]]:
            M[i, col_of[j]] = c

    rows, cols = linear_sum_assignment(M)
    assign = {int(r): used_cols[int(c)] for r, c in zip(rows, cols)}
    total = float(M[rows, cols].sum())
    return assign, total


# --------------------------------------------------------------------------
# 后端 3: 纯 Python 最小费用流 (连续最短路 + Johnson 势)
# --------------------------------------------------------------------------
class _MCMF:
    __slots__ = ("n", "g")

    def __init__(self, n):
        self.n = n
        self.g = [[] for _ in range(n)]

    def add(self, u, v, cap, cost):
        self.g[u].append([v, cap, cost, len(self.g[v])])
        self.g[v].append([u, 0, -cost, len(self.g[u]) - 1])

    def min_cost_flow(self, s, t, maxf):
        """所有初始费用非负 => 初始势函数全 0 合法, 可跳过 Bellman-Ford."""
        n = self.n
        h = [0.0] * n
        INF = math.inf
        res_flow = 0
        res_cost = 0.0
        prevv = [0] * n
        preve = [0] * n
        dist = [0.0] * n

        while res_flow < maxf:
            dist[:] = [INF] * n
            dist[s] = 0.0
            pq = [(0.0, s)]
            while pq:
                d, u = heapq.heappop(pq)
                if d > dist[u]:
                    continue
                gu = self.g[u]
                hu = h[u]
                for idx, e in enumerate(gu):
                    v, cap, cost, _ = e
                    if cap <= 0:
                        continue
                    nd = d + cost + hu - h[v]
                    if nd < dist[v] - 1e-12:
                        dist[v] = nd
                        prevv[v] = u
                        preve[v] = idx
                        heapq.heappush(pq, (nd, v))
            if dist[t] == INF:
                break
            for v in range(n):
                if dist[v] < INF:
                    h[v] += dist[v]

            # 瓶颈流量
            d = maxf - res_flow
            v = t
            while v != s:
                d = min(d, self.g[prevv[v]][preve[v]][1])
                v = prevv[v]
            v = t
            while v != s:
                e = self.g[prevv[v]][preve[v]]
                e[1] -= d
                self.g[v][e[3]][1] += d
                res_cost += d * e[2]
                v = prevv[v]
            res_flow += d
        return res_flow, res_cost


def _solve_pure(arcs, n_left, n_right):
    S = 0
    L0 = 1
    R0 = L0 + n_left
    T = R0 + n_right
    g = _MCMF(T + 1)
    for i in range(n_left):
        g.add(S, L0 + i, 1, 0.0)
    for j in range(n_right):
        g.add(R0 + j, T, 1, 0.0)
    for (i, j, c) in arcs:
        g.add(L0 + i, R0 + j, 1, float(c))

    flow, cost = g.min_cost_flow(S, T, n_left)
    if flow != n_left:
        raise Infeasible("pure: 流量 %d < %d, 格点不足" % (flow, n_left))

    assign = {}
    for i in range(n_left):
        for e in g.g[L0 + i]:
            v, cap, _c, _ = e
            if R0 <= v <= R0 + n_right - 1 and cap == 0:
                assign[i] = v - R0
                break
    return assign, cost


# --------------------------------------------------------------------------
# 稠密入口
# --------------------------------------------------------------------------
def solve_dense(C, verbose=False):
    """直接对稠密代价矩阵 C[n_left, n_right] 求全局最小代价指派.

    优先 scipy(Jonker-Volgenant, C 实现); 不可用时退化成
    "每行取 Top-K 候选 + 稀疏 MCMF", 仍然是全局最优的稀疏近似(对候选集最优).
    """
    n, m = C.shape
    if n == 0:
        return {}, 0.0
    if m < n:
        raise Infeasible("格点总数 %d < HBT 数 %d" % (m, n))
    try:
        import numpy as np  # noqa: F401
        from scipy.optimize import linear_sum_assignment  # type: ignore
        r, c = linear_sum_assignment(C)
        assign = {int(a): int(b) for a, b in zip(r, c)}
        total = float(C[r, c].sum())
        if verbose:
            LOG.info("稠密指派: scipy  n=%d m=%d cost=%.3f", n, m, total)
        return assign, total
    except ImportError:
        pass

    # 退化路径: 每行 Top-K 候选
    K = int(os.environ.get("HBT_TOPK", "48"))
    K = max(4, min(K, m))
    try:
        import numpy as np
        idx = np.argpartition(C, K - 1, axis=1)[:, :K]
    except Exception:
        idx = None
    arcs = []
    if idx is not None:
        for i in range(n):
            for j in idx[i]:
                arcs.append((i, int(j), float(C[i, int(j)])))
    else:
        for i in range(n):
            row = sorted(range(m), key=lambda j: C[i, j])[:K]
            for j in row:
                arcs.append((i, j, float(C[i, j])))
    LOG.warning("scipy 不可用 -> 稀疏 MCMF (Top-%d 候选)", K)
    return solve_assignment(arcs, n, m, verbose=verbose)


# --------------------------------------------------------------------------
# 对外入口
# --------------------------------------------------------------------------
def solve_assignment(arcs, n_left, n_right, backend="auto", verbose=True):
    """全局最小代价指派. arcs = [(i, j, cost), ...]."""
    if n_left == 0:
        return {}, 0.0
    if n_right < n_left:
        raise Infeasible("格点总数 %d < HBT 数 %d" % (n_right, n_left))

    backends = []
    if backend == "auto":
        # auction 放在 pure 之前: 纯 Python MCMF 每个流单位一次 Dijkstra,
        # 上千 HBT 时要几分钟; 拍卖是秒级(差距 <0.1%, 见 hbt_auction 对拍)
        backends = ["ortools", "scipy", "auction", "pure"]
    else:
        backends = [backend]

    last_err = None
    for b in backends:
        try:
            if b == "ortools":
                a, c = _solve_ortools(arcs, n_left, n_right)
            elif b == "scipy":
                a, c = _solve_scipy(arcs, n_left, n_right)
            elif b == "auction":
                from hbt_auction import solve_auction_pruned
                a, c = solve_auction_pruned(arcs, n_left, n_right)
            elif b == "pure":
                a, c = _solve_pure(arcs, n_left, n_right)
            else:
                raise ValueError("unknown backend " + b)
            if len(a) != n_left:
                raise Infeasible("backend %s: 只指派了 %d/%d" % (b, len(a), n_left))
            if verbose:
                LOG.info("指派求解: backend=%s  arcs=%d  cost=%.3f", b, len(arcs), c)
            return a, c
        except ImportError as e:
            last_err = e
            if verbose:
                LOG.warning("后端 %s 不可用(%s), 降级", b, e)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if verbose:
                LOG.warning("后端 %s 失败(%s), 降级", b, e)
    raise Infeasible("所有后端均失败, 最后一个错误: %r" % (last_err,))


def probe_backends():
    """返回可用后端列表, 便于日志/自查."""
    ok = []
    try:
        import ortools.graph.pywrapgraph  # noqa: F401
        ok.append("ortools")
    except Exception:
        pass
    try:
        import scipy.optimize  # noqa: F401
        ok.append("scipy")
    except Exception:
        pass
    ok.append("auction")
    ok.append("pure")
    return ok


if __name__ == "__main__":
    # 自测: 构造已知最优解的小例子, 贪心会解错
    logging.basicConfig(level=logging.INFO)
    # A: h0 -> s0(1) / s1(2) ; h1 -> s0(2) / s1(100)
    # 贪心若先给 h0 选 s0, 则 h1 只能 s1=100, 总 101; 最优是 h0->s1, h1->s0 = 4
    arcs = [(0, 0, 1.0), (0, 1, 2.0), (1, 0, 2.0), (1, 1, 100.0)]
    print("backends:", probe_backends())
    for b in ["ortools", "scipy", "auction", "pure"]:
        try:
            a, c = solve_assignment(arcs, 2, 2, backend=b, verbose=False)
            print("%-8s assign=%s cost=%.3f %s" % (b, a, c, "OK" if abs(c - 4.0) < 1e-9 else "WRONG"))
        except Exception as e:
            print("%-8s %r" % (b, e))
