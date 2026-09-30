"""暴力枚举交叉验证：n<=7 时穷举所有有序分拆，比对 CP-SAT 的最优值。"""

import itertools
import random
from types import SimpleNamespace

from app.solver import solve_plan


def F(fid, lo, hi):
    return SimpleNamespace(id=fid, min_green=lo, max_green=hi)


def brute(flows, conflicts, clearances, cycle_max):
    n = len(flows)
    ids = [f.id for f in flows]
    lo = {f.id: f.min_green for f in flows}
    hi = {f.id: f.max_green for f in flows}
    cset = {frozenset(p) for p in conflicts}

    def clr(a, b):
        return clearances.get(a, {}).get(b, 0)

    best = None  # (C, K)
    # 用限制增长串（restricted growth string）枚举无序分组。
    def rgs(n):
        a = [0] * n
        def rec(i, mx):
            if i == n:
                yield a[:]
                return
            for v in range(mx + 2):
                a[i] = v
                yield from rec(i + 1, max(mx, v))
                a[i] = 0
        yield from rec(1, 0)

    for code in rgs(n):
        K = max(code) + 1
        groups = [[] for _ in range(K)]
        for i, c in enumerate(code):
            groups[c].append(ids[i])
        # 冲突检查 + 可行绿灯。
        gs = []
        ok = True
        for gr in groups:
            for a, b in itertools.combinations(gr, 2):
                if frozenset((a, b)) in cset:
                    ok = False
            gmin = max(lo[a] for a in gr)
            gmax = min(hi[a] for a in gr)
            if gmin > gmax:
                ok = False
            gs.append(gmin)  # 最小化周期 => 绿灯取下限
        if not ok:
            continue
        # 枚举组的所有排列作为相位顺序。
        for perm in itertools.permutations(range(K)):
            reds = []
            for k in range(K):
                ga = groups[perm[k]]
                gb = groups[perm[(k + 1) % K]]
                if K == 1:
                    reds.append(0)
                else:
                    reds.append(max(clr(a, b) for a in ga for b in gb))
            C = sum(gs[perm[k]] for k in range(K)) + sum(reds)
            if C <= cycle_max and (best is None or (C, K) < best):
                best = (C, K)
    return best


random.seed(42)
ntrial = 0
for t in range(60):
    n = random.randint(2, 7)
    flows = [F(f"v{i}", random.randint(1, 20),
               random.randint(20, 60)) for i in range(n)]
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    cedges = [p for p in pairs if random.random() < 0.35]
    conflicts = [[f"v{i}", f"v{j}"] for i, j in cedges]
    clearances = {}
    for i in range(n):
        d = {}
        for j in range(n):
            if i != j and random.random() < 0.4:
                d[f"v{j}"] = random.randint(0, 10)
        if d:
            clearances[f"v{i}"] = d
    cycle_max = random.choice([30, 60, 120, 300])

    expected = brute(flows, conflicts, clearances, cycle_max)
    got = solve_plan(flows, conflicts, clearances, cycle_max)
    if expected is None:
        assert got.status == "infeasible", (t, got.status, expected)
    else:
        assert got.status == "optimal", (t, got.status, expected)
        assert (got.cycle, len(got.phases)) == expected, \
            (t, (got.cycle, len(got.phases)), expected)
    ntrial += 1

print(f"CROSS-VALIDATED {ntrial} RANDOM CASES OK")
