"""求解器冒烟测试：直接调用 solver，不经过 HTTP。"""

from types import SimpleNamespace

from app.solver import solve_plan


def F(fid, lo, hi):
    return SimpleNamespace(id=fid, min_green=lo, max_green=hi)


def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name, extra)
    assert cond, name


# 1) README 示例：4 车流、2 相位
flows = [F("N-S", 15, 45), F("S-N", 15, 45),
         F("E-W", 10, 30), F("W-E", 10, 30)]
conflicts = [["N-S", "E-W"], ["N-S", "W-E"],
             ["S-N", "E-W"], ["S-N", "W-E"]]
clearances = {
    "N-S": {"E-W": 3, "W-E": 3},
    "S-N": {"E-W": 3, "W-E": 3},
    "E-W": {"N-S": 2, "S-N": 2},
    "W-E": {"N-S": 2, "S-N": 2},
}
res = solve_plan(flows, conflicts, clearances, 120)
check("ex1 status", res.status == "optimal", res.status)
check("ex1 2 phases", len(res.phases) == 2, str(len(res.phases)))
check("ex1 cycle", res.cycle == 30, str(res.cycle))
groups = {tuple(sorted(p.flows)) for p in res.phases}
check("ex1 grouping",
      groups == {("N-S", "S-N"), ("E-W", "W-E")}, str(groups))
reds = sorted(p.all_red_after for p in res.phases)
check("ex1 all-reds", reds == [2, 3], str(reds))
greens = sorted(p.green for p in res.phases)
check("ex1 greens", greens == [10, 15], str(greens))

# 顺序无关：wrap（末->首）全红也必须计入
orders = [(p.flows, p.all_red_after) for p in res.phases]
print("   相位顺序:", orders)

# 2) 单相位（无冲突）=> 全红 0
flows2 = [F("A", 5, 20), F("B", 6, 18)]
res2 = solve_plan(flows2, [], {"A": {"B": 4}}, 60)
check("single-phase status", res2.status == "optimal", res2.status)
check("single-phase K=1", len(res2.phases) == 1, str(len(res2.phases)))
check("single-phase red=0", res2.phases[0].all_red_after == 0)
check("single-phase green=6", res2.phases[0].green == 6,
      str(res2.phases[0].green))
check("single-phase cycle=6", res2.cycle == 6, str(res2.cycle))

# 3) 周期上限过小 => 不可行
res3 = solve_plan(flows, conflicts, clearances, 20)
check("infeasible", res3.status == "infeasible", res3.status)
check("infeasible no cycle", res3.cycle is None)

# 4) 冲突全部成对 => 每条车流一个相位
flows4 = [F(f"v{i}", 1, 1) for i in range(3)]
conf4 = [["v0", "v1"], ["v1", "v2"], ["v0", "v2"]]
clr4 = {"v0": {"v1": 1, "v2": 1},
        "v1": {"v0": 2, "v2": 2},
        "v2": {"v0": 3, "v1": 3}}
res4 = solve_plan(flows4, conf4, clr4, 100)
check("all-conflict K=3", len(res4.phases) == 3, res4.status)
# 3 个相位 + 环上 3 个全红，每个等于对应跨相位对最大值
reds4 = {(tuple(sorted(p.flows))[0], p.all_red_after)
         for p in res4.phases}
print("   三相位全红:", reds4, "cycle:", res4.cycle)
check("all-conflict cycle", res4.cycle == 3 + 1 + 2 + 3, str(res4.cycle))

# 5) 10 车流压力（全冲突 => K=10）
flows5 = [F(f"v{i}", 2, 5) for i in range(10)]
conf5 = [[f"v{i}", f"v{j}"] for i in range(10) for j in range(i + 1, 10)]
clr5 = {f"v{i}": {f"v{j}": (i + j) % 11 for j in range(10) if i != j}
        for i in range(10)}
res5 = solve_plan(flows5, conf5, clr5, 600)
check("n10 solved", res5.status in ("optimal", "feasible_candidate"),
      res5.status)
check("n10 K=10", len(res5.phases) == 10, str(len(res5.phases)))
check("n10 greens=2", all(p.green == 2 for p in res5.phases))
check("n10 cycle>=30", res5.cycle >= 30, str(res5.cycle))
print("   n10 cycle:", res5.cycle, "time:", round(res5.solver_time_seconds, 3))

# 6) 清空时间在合并相位后被绕过：若 i,j 同相位则无红
flows6 = [F("A", 1, 1), F("B", 1, 1), F("C", 1, 1)]
res6 = solve_plan(flows6, [], {"A": {"B": 10}}, 120)
check("merge beats red", len(res6.phases) == 1 and res6.cycle == 1,
      f"{res6.status} K={len(res6.phases)} C={res6.cycle}")

print("\nALL SMOKE TESTS PASSED")
