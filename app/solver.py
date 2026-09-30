"""路口信号周期编排 —— OR-Tools CP-SAT 模型。

决策（联合决定）：
  1. 分组：每条车流分配到哪个相位；
  2. 顺序：启用的相位按 1..K 排列成环；
  3. 整数秒时长：各相位绿灯 g 与随后的全红 r。

目标（字典序）：先最小化周期总秒数 C = Σg + Σr，再最小化相位数 K。
"""

from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

# 字典序目标权重：C 减少 1 秒的收益必须压过 K 的任何差异（K ≤ 10）。
_LEX_W = 1001
# 求解时限（秒）。超时仍有解 -> feasible_candidate；超时无解 -> not_found。
_TIME_LIMIT_SECONDS = 10.0


@dataclass
class Phase:
    order: int
    flows: list[str]
    green: int
    all_red_after: int


@dataclass
class SolveResult:
    status: str  # optimal | infeasible | feasible_candidate | not_found
    cycle: int | None
    phases: list[Phase]
    solver_time_seconds: float

    @property
    def num_phases(self) -> int | None:
        return len(self.phases) if self.phases else None


def solve_plan(
    flows: list,
    conflicts: list[list[str]],
    clearances: dict[str, dict[str, int]],
    cycle_max: int,
) -> SolveResult:
    n = len(flows)
    ids = [f.id for f in flows]
    lo = [f.min_green for f in flows]
    hi = [f.max_green for f in flows]
    idx = {fid: i for i, fid in enumerate(ids)}

    # 有向清空时间矩阵，未列为 0；自环无意义。
    clr = [[0] * n for _ in range(n)]
    for src, dst_map in clearances.items():
        for dst, sec in dst_map.items():
            if src != dst:
                clr[idx[src]][idx[dst]] = sec

    conflict_edges = {
        (idx[u], idx[v]) for u, v in ((p[0], p[1]) for p in conflicts)
    }

    m = cp_model.CpModel()
    N = n  # 相位槽上限：每个相位至少一条车流，最优解相位数不会超过车流数。

    # ---------- 基本变量 ----------
    z = [m.NewBoolVar(f"z_{p}") for p in range(N)]          # 相位 p 是否启用
    x = [[m.NewBoolVar(f"x_{i}_{p}") for p in range(N)]     # 车流 i 在相位 p
         for i in range(n)]
    g = [m.NewIntVar(0, 60, f"g_{p}") for p in range(N)]    # 绿灯秒数
    r = [m.NewIntVar(0, 10, f"r_{p}") for p in range(N)]    # 其后全红秒数

    # 每条车流恰在一个相位。
    for i in range(n):
        m.Add(sum(x[i][p] for p in range(N)) == 1)

    # z[p] 当且仅当相位 p 中至少一条车流。
    for p in range(N):
        for i in range(n):
            m.Add(z[p] >= x[i][p])
        m.Add(sum(x[i][p] for i in range(n)) >= z[p])
        m.Add(sum(x[i][p] for i in range(n)) <= n * z[p])

    # 冲突车流不得同相位。
    for (i, j) in conflict_edges:
        for p in range(N):
            m.Add(x[i][p] + x[j][p] <= 1)

    # 对称性破除：相位槽匿名。固定车流 0 在槽 0；车流 i 只能进入
    # (a) 已含某条编号更小车流的槽，或 (b) 当时编号最小的空槽。
    # 这样每个分组恰好有一种规范表示，不损失任何可行解。
    m.Add(x[0][0] == 1)
    for i in range(1, n):
        # 槽 p 已含编号更小的车流。
        occupied_smaller = []
        for p in range(N):
            osb = m.NewBoolVar(f"osb_{i}_{p}")
            m.Add(sum(x[j][p] for j in range(i)) >= 1).OnlyEnforceIf(osb)
            m.Add(sum(x[j][p] for j in range(i)) == 0).OnlyEnforceIf(osb.Not())
            occupied_smaller.append(osb)
        # first_empty: 第一个（编号最小的）空槽，即 osb[p]=0 且
        # 之前所有槽均非空（osb[0..p-1] 全为 1）。
        first_empty = []
        for p in range(N):
            fe = m.NewBoolVar(f"fe_{i}_{p}")
            m.Add(fe <= occupied_smaller[p].Not())
            for q in range(p):
                m.Add(fe <= occupied_smaller[q])
            first_empty.append(fe)
        for p in range(N):
            m.Add(x[i][p] <= occupied_smaller[p] + first_empty[p])
        m.Add(sum(first_empty) == 1)

    # 绿灯必须同时落在所有成员的区间内；空相位绿灯为 0。
    for p in range(N):
        m.Add(g[p] <= 60 * z[p])
        for i in range(n):
            m.Add(g[p] >= lo[i] * x[i][p])
            m.Add(g[p] <= hi[i] + 60 * (1 - x[i][p]))

    K = sum(z)  # 相位数

    # ---------- 相位排序：启用相位紧凑占据位置 1..K ----------
    # e[k]: 第 k 个位置是否存在（k 从 1 开始），呈前缀形态。
    e = [m.NewBoolVar(f"e_{k}") for k in range(1, N + 1)]
    # pk[p][k]: 相位 p 位于第 k 个位置。
    pk = [[m.NewBoolVar(f"pk_{p}_{k}") for k in range(N)] for p in range(N)]

    for p in range(N):
        m.Add(sum(pk[p]) == z[p])          # 启用相位恰好一个位置
    for k in range(N):
        m.Add(sum(pk[p][k] for p in range(N)) == e[k])  # 每位置至多一个相位
    for k in range(N - 1):
        m.Add(e[k + 1] <= e[k])            # 位置紧凑：1..K

    # last[k]: 第 k 个位置是最后一个位置（用于末->首环绕）。
    last = [m.NewBoolVar(f"last_{k}") for k in range(N)]
    for k in range(N - 1):
        m.Add(last[k] == e[k] - e[k + 1])
    m.Add(last[N - 1] == e[N - 1])

    multi = e[1] if N >= 2 else m.NewConstant(0)  # K >= 2

    # ---------- 相邻相位指示 ----------
    # nxt[p][q]: 非环绕相邻，q 紧跟 p（位置 k -> k+1）。
    nxt = [[m.NewBoolVar(f"nxt_{p}_{q}") for q in range(N)] for p in range(N)]
    # wrap[p][q]: 环绕相邻，p 在末位、q 在首位。
    wrap = [[m.NewBoolVar(f"wrap_{p}_{q}") for q in range(N)] for p in range(N)]

    def link(target, *parts):
        """target = AND(parts)，parts 为 0/1 线性项。"""
        m.Add(target >= sum(parts) - (len(parts) - 1))
        for t in parts:
            m.Add(target <= t)

    for p in range(N):
        for q in range(N):
            if p != q:
                terms = []
                for k in range(N - 1):
                    link_v = m.NewBoolVar(f"L_{p}_{q}_{k}")
                    link(link_v, pk[p][k], pk[q][k + 1])
                    terms.append(link_v)
                m.Add(nxt[p][q] == sum(terms))
            else:
                m.Add(nxt[p][p] == 0)

            wterms = []
            for k in range(N):
                link_v = m.NewBoolVar(f"W_{p}_{q}_{k}")
                link(link_v, pk[p][k], pk[q][0], last[k])
                wterms.append(link_v)
            m.Add(wrap[p][q] == sum(wterms))

    # 每个启用相位恰好一个后继 / 一个前驱（与位置链共同保证单一环）。
    for p in range(N):
        m.Add(sum(nxt[p][q] + wrap[p][q] for q in range(N)) == z[p])
        m.Add(sum(nxt[q][p] + wrap[q][p] for q in range(N)) == z[p])

    # ---------- 全红 ----------
    # 单相位（K=1）时全红为 0；空相位无全红。
    for p in range(N):
        m.Add(r[p] <= 10 * z[p])
        m.Add(r[p] <= 10 * multi)

    # r[p] >= 任意 (前车流 i -> 后车流 j) 的清空时间，取跨相位对的最大值。
    for i in range(n):
        for j in range(n):
            if i == j or clr[i][j] == 0:
                continue
            c = clr[i][j]
            for p in range(N):
                for q in range(N):
                    a = m.NewBoolVar(f"cross_{i}_{p}_{j}_{q}")
                    # i 在 p、j 在 q、q 是 p 的后继，且确实跨相位（K>=2）。
                    link(a, x[i][p], x[j][q], nxt[p][q] + wrap[p][q], multi)
                    m.Add(r[p] >= c * a)

    # ---------- 周期与字典序目标 ----------
    C = m.NewIntVar(0, cycle_max, "C")
    m.Add(C == sum(g) + sum(r))
    m.Minimize(_LEX_W * C + K)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = _TIME_LIMIT_SECONDS
    solver.parameters.num_search_workers = 8
    status = solver.Solve(m)

    wall = solver.WallTime()  # CpSolver.WallTime() 已以秒为单位

    if status == cp_model.INFEASIBLE:
        return SolveResult("infeasible", None, [], wall)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # UNKNOWN（时限内无解）或 MODEL_INVALID（防御）。
        return SolveResult("not_found", None, [], wall)

    # 提取：按位置顺序排列启用相位。
    ordered: list[tuple[int, int]] = []
    for p in range(N):
        if solver.Value(z[p]):
            pos = sum(k * solver.Value(pk[p][k]) for k in range(N))
            ordered.append((pos, p))
    ordered.sort()

    phases: list[Phase] = []
    for order_no, (_, p) in enumerate(ordered, start=1):
        members = [ids[i] for i in range(n) if solver.Value(x[i][p])]
        phases.append(
            Phase(
                order=order_no,
                flows=members,
                green=solver.Value(g[p]),
                all_red_after=solver.Value(r[p]),
            )
        )

    cycle = sum(ph.green + ph.all_red_after for ph in phases)
    assert cycle == solver.Value(C)

    label = "optimal" if status == cp_model.OPTIMAL else "feasible_candidate"
    return SolveResult(label, cycle, phases, wall)
