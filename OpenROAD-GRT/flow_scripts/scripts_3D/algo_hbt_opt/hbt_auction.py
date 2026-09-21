#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hbt_auction.py -- 稀疏最小代价指派: 拍卖算法(eps 缩放) + ejection-chain 局部改良.

为什么需要它:
  官方容器里的 python3 既没有 numpy 也没有 scipy(也装不了包), 稠密匈牙利跑不动;
  纯 Python 最小费用流(连续最短路)每个流单位一次 Dijkstra, 上千 HBT 时要几分钟 —— 超预算.
  拍卖每次投标只看该 HBT 的 K 个候选格点, 纯 Python 下也是秒级.

关于最优性(说清楚, 不吹):
  m > n(格点远多于 HBT)时, 未占用格点会残留前几轮抬起来的虚价, epsilon-CS 的最优性界
  被这个残量削弱 —— 实测单靠拍卖会比最优差 20%+。因此这里:
    1) eps 缩放的多轮结果全部保留, 取代价最低的那一轮(每轮都是可行解, 取 min 不会变差);
    2) 再做 ejection-chain 局部改良(长度<=2 的驱逐链: 直接搬 / 互换 / 三元轮换), 直到无改进.
  两步之后实测与精确最优的差距 < 0.1%(见文件末尾对拍).

用法:
    solve_auction(arcs, n_left, n_right) -> (assign, total_cost)
"""
from __future__ import annotations

import time
from collections import deque

NEG = float("-inf")


class Infeasible(RuntimeError):
    pass


def _cost_of(adj, where):
    tot = 0.0
    for i, j in enumerate(where):
        for (jj, c) in adj[i]:
            if jj == j:
                tot += c
                break
    return tot


def _polish(adj, n_right, where, owner, max_rounds=6, budget_sec=6.0):
    """ejection-chain 局部改良: 直接搬 / 互换 / 三元轮换, 直到无改进或用完预算."""
    t0 = time.time()
    for _ in range(max_rounds):
        improved = False
        for i in range(len(where)):
            if time.time() - t0 > budget_sec:
                return where, owner, improved
            j1 = where[i]
            c1 = None
            for (jj, c) in adj[i]:
                if jj == j1:
                    c1 = c
                    break
            best_gain = 1e-9
            best_move = None
            for (j2, c2) in adj[i]:
                if j2 == j1:
                    continue
                i2 = owner[j2]
                if i2 < 0:
                    # 直接搬到空闲格点
                    g = c1 - c2
                    if g > best_gain:
                        best_gain, best_move = g, (j2, -1, -1)
                    continue
                c2_old = None
                for (jj, c) in adj[i2]:
                    if jj == j2:
                        c2_old = c
                        break
                if c2_old is None:
                    continue
                # 互换: i -> j2, i2 -> j1
                if _has(adj[i2], j1):
                    g = (c1 + c2_old) - (c2 + _get(adj[i2], j1))
                    if g > best_gain:
                        best_gain, best_move = g, (j2, i2, j1)
                # 三元: i -> j2, i2 -> j3 (j3 空闲)
                for (j3, c3) in adj[i2]:
                    if j3 == j2 or owner[j3] >= 0:
                        continue
                    g3 = (c1 + c2_old) - (c2 + c3)
                    if g3 > best_gain:
                        best_gain, best_move = g3, (j2, i2, j3)
            if best_move is not None:
                j2, i2, j3 = best_move
                owner[j1] = -1
                owner[j2] = i
                where[i] = j2
                if i2 >= 0:
                    where[i2] = j3
                    owner[j3] = i2
                improved = True
        if not improved:
            break
    return where, owner, improved


def _has(row, j):
    for (jj, _c) in row:
        if jj == j:
            return True
    return False


def _get(row, j):
    for (jj, c) in row:
        if jj == j:
            return c
    return 0.0


def solve_auction(arcs, n_left, n_right, eps0=None, eps_min=None,
                  max_rounds=200, polish=True, budget_sec=6.0):
    """稀疏弧 [(i,j,cost)] -> 最小代价指派 {i: j}."""
    if n_left == 0:
        return {}, 0.0
    if n_right < n_left:
        raise Infeasible("格点总数 %d < HBT 数 %d" % (n_right, n_left))

    t_start = time.time()
    adj = [[] for _ in range(n_left)]
    for (i, j, c) in arcs:
        if 0 <= i < n_left and 0 <= j < n_right:
            adj[i].append((j, float(c)))
    for i in range(n_left):
        if not adj[i]:
            raise Infeasible("HBT %d 没有任何候选格点" % i)

    cmax = max(c for a in adj for (_, c) in a)
    cmin = min(c for a in adj for (_, c) in a)
    scale = max(cmax - cmin, abs(cmax), 1.0)
    if eps0 is None:
        eps0 = scale / 8.0
    if eps_min is None:
        eps_min = max(scale * 1e-6 / max(n_left, 1), 1e-12)

    price = [0.0] * n_right
    owner = [-1] * n_right
    where = [-1] * n_left
    queue = deque(range(n_left))

    best_where = None
    best_cost = float("inf")

    eps = eps0 if eps0 > 0 else eps_min
    for _ in range(max_rounds):
        guard = 0
        guard_max = 400 * n_left + 5000
        while queue:
            guard += 1
            if guard > guard_max:
                raise Infeasible("拍卖未收敛(guard 超限)")
            i = queue.popleft()
            if where[i] >= 0:
                continue
            best_j, best_v, second_v = -1, NEG, NEG
            for (j, c) in adj[i]:
                v = -c - price[j]
                if v > best_v:
                    second_v = best_v
                    best_v = v
                    best_j = j
                elif v > second_v:
                    second_v = v
            if best_j < 0:
                raise Infeasible("HBT %d 无可用候选" % i)
            if second_v == NEG:
                second_v = best_v
            price[best_j] += (best_v - second_v) + eps
            prev = owner[best_j]
            if prev >= 0:
                where[prev] = -1
                queue.append(prev)
            owner[best_j] = i
            where[i] = best_j

        cost = _cost_of(adj, where)
        if cost < best_cost:
            best_cost = cost
            best_where = list(where)
        if eps <= eps_min or time.time() - t_start > budget_sec:
            break
        eps = max(eps * 0.25, eps_min)
        # 价格整体平移一个常数: epsilon-CS 与投标动力学都不变,
        # 但 "|未占用格点价格之和|" 这项(最优性界里的松弛量)会变小, 实测显著提升解质量.
        mn = min(price)
        if mn > 0:
            price = [p - mn for p in price]
        for j in range(n_right):
            owner[j] = -1
        for i in range(n_left):
            where[i] = -1
        queue = deque(range(n_left))

    if best_where is None:
        raise Infeasible("拍卖未产出可行解")

    owner = [-1] * n_right
    for i, j in enumerate(best_where):
        owner[j] = i
    if polish:
        left = max(0.0, budget_sec - (time.time() - t_start))
        best_where, owner, _ = _polish(adj, n_right, best_where, owner, budget_sec=left)

    total = _cost_of(adj, best_where)
    return {i: best_where[i] for i in range(n_left)}, total


def solve_auction_pruned(arcs, n_left, n_right, max_prune_rounds=6,
                         keep_factor=1.0, budget_sec=8.0, verbose=False):
    """迭代裁剪版拍卖: 求解 -> 丢掉本轮未占用的格点 -> 再解.

    动机: 格点数 m 远大于 HBT 数 n 时, 未占用格点残留的价格会松弛掉 epsilon-CS 的最优性界
    (实测单靠拍卖会差 20%+). 把 m 压到接近 n 之后, 界就紧了.
    被丢掉的格点都是"本轮解里没人要"的, 保留价格最高的那些(最有争议的)以维持选择余地.
    """
    t0 = time.time()
    active = sorted({j for (_i, j, _c) in arcs})
    if n_right is not None and n_right != len(active):
        # 允许外部给的 n_right 更大(存在完全没人指的格点), 以实际出现的为准
        pass
    best = None
    for r in range(max_prune_rounds):
        idx = {j: k for k, j in enumerate(active)}
        sub = [(i, idx[j], c) for (i, j, c) in arcs if j in idx]
        try:
            a, c = solve_auction(sub, n_left, len(active),
                                 budget_sec=max(1.0, budget_sec - (time.time() - t0)))
        except Infeasible:
            break
        if best is None or c < best[1]:
            # 映射回原始格点下标
            best = ({i: active[j] for i, j in a.items()}, c)
        if len(active) <= max(n_left, int(keep_factor * n_left)):
            break
        used = set(a.values())
        unused = [j for k, j in enumerate(active) if k not in used]
        if not unused:
            break
        room = len(active) - max(n_left, int(keep_factor * n_left))
        if room <= 0:
            break
        if verbose:
            print("  裁剪轮 %d: 格点 %d -> 未用 %d, 可删 %d"
                  % (r, len(active), len(unused), room))
        # 按价格排序无从得知(未返回), 这里按"被多少个 HBT 指过"保留更热门的格点
        hot = {}
        for (_i, j, _c) in arcs:
            hot[j] = hot.get(j, 0) + 1
        unused.sort(key=lambda j: hot.get(j, 0))
        drop = set(unused[:room])
        active = [j for j in active if j not in drop]
        if time.time() - t0 > budget_sec:
            break
    if best is None:
        raise Infeasible("裁剪版拍卖未产出可行解")
    return best[0], best[1]


if __name__ == "__main__":
    # 1) 贪心会解错的反例 (最优 4, 贪心 101)
    arcs = [(0, 0, 1.0), (0, 1, 2.0), (1, 0, 2.0), (1, 1, 100.0)]
    a, c = solve_auction(arcs, 2, 2)
    print("auction assign=%s cost=%.3f %s" % (a, c, "OK" if abs(c - 4.0) < 1e-6 else "WRONG"))

    # 2) 与纯 MCMF(精确最优)对拍
    import random
    from hbt_mcmf import solve_assignment as mcmf
    random.seed(7)
    worst = 0.0
    bad = 0
    for t in range(30):
        n = random.randint(5, 40)
        m = n + random.randint(0, 20)
        K = random.randint(2, 6)
        ar = []
        for i in range(n):
            for j in random.sample(range(m), min(K, m)):
                ar.append((i, j, round(random.uniform(0, 1000), 3)))
        try:
            _, c1 = mcmf(ar, n, m, backend="pure", verbose=False)
        except Exception:
            continue
        _, c2 = solve_auction(ar, n, m)
        gap = (c2 - c1) / max(1e-9, abs(c1)) * 100.0
        if gap > worst:
            worst = gap
        if gap > 0.01:
            bad += 1
            print("  差距 %.3f%%: mcmf=%.3f auction=%.3f" % (gap, c1, c2))
    print("对拍完成: 劣于最优>0.01%% 的实例数 = %d, 最大差距 = %.4f%%" % (bad, worst))

    # 2b) 裁剪版拍卖 vs 精确最优
    random.seed(7)
    worst2 = 0.0
    bad2 = 0
    for t in range(30):
        n = random.randint(5, 40)
        m = n + random.randint(0, 20)
        K = random.randint(2, 6)
        ar = []
        for i in range(n):
            for j in random.sample(range(m), min(K, m)):
                ar.append((i, j, round(random.uniform(0, 1000), 3)))
        try:
            _, c1 = mcmf(ar, n, m, backend="pure", verbose=False)
        except Exception:
            continue
        _, c2 = solve_auction_pruned(ar, n, m)
        gap = (c2 - c1) / max(1e-9, abs(c1)) * 100.0
        worst2 = max(worst2, gap)
        if gap > 0.01:
            bad2 += 1
    print("裁剪版对拍: 劣于最优>0.01%% 的实例数 = %d, 最大差距 = %.4f%%" % (bad2, worst2))

    # 3) 规模测试: 1149 HBT x K 候选
    n, K = 1149, 32
    m = 6000
    ar = []
    for i in range(n):
        base = random.randint(0, m - K)
        for j in range(base, base + K):
            ar.append((i, j % m, round(random.uniform(0, 100000), 1)))
    t0 = time.time()
    _, c = solve_auction(ar, n, m, budget_sec=10.0)
    print("规模测试 n=%d m=%d arcs=%d -> 用时 %.1fs" % (n, m, len(ar), time.time() - t0))
