"""HTTP 层测试：FastAPI TestClient，覆盖 200/422/422 各类非法输入。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

GOOD_REQ = {
    "flows": [
        {"id": "N-S", "min_green": 15, "max_green": 45},
        {"id": "S-N", "min_green": 15, "max_green": 45},
        {"id": "E-W", "min_green": 10, "max_green": 30},
        {"id": "W-E", "min_green": 10, "max_green": 30},
    ],
    "conflicts": [
        ["N-S", "E-W"], ["N-S", "W-E"],
        ["S-N", "E-W"], ["S-N", "W-E"],
    ],
    "clearances": {
        "N-S": {"E-W": 3, "W-E": 3},
        "S-N": {"E-W": 3, "W-E": 3},
        "E-W": {"N-S": 2, "S-N": 2},
        "W-E": {"N-S": 2, "S-N": 2},
    },
    "cycle_max": 120,
}


def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name, extra)
    assert cond, name


r = client.get("/healthz")
check("healthz 200", r.status_code == 200 and r.json()["status"] == "ok")

r = client.post("/plans", json=GOOD_REQ)
check("good 200", r.status_code == 200, str(r.status_code))
body = r.json()
check("good optimal", body["status"] == "optimal", body["status"])
check("good cycle 30", body["cycle"] == 30, str(body["cycle"]))
check("good K=2", body["num_phases"] == 2)
for ph in body["phases"]:
    check("phase keys",
          set(ph.keys()) == {"phase", "flows", "green", "all_red_after"},
          str(ph))
print("  ", body)

# 周期上限过小 => 200 且 infeasible
r = client.post("/plans", json={**GOOD_REQ, "cycle_max": 20})
b = r.json()
check("tight bound 200", r.status_code == 200, str(r.status_code))
check("infeasible status", b["status"] == "infeasible", b["status"])
check("infeasible fields", b["cycle"] is None and b["phases"] == []
      and b["num_phases"] is None)

# ---- 各类 422 ----
def expect_422(name, payload):
    r = client.post("/plans", json=payload)
    check(name, r.status_code == 422, str(r.status_code))

expect_422("flows < 2", {**GOOD_REQ, "flows": GOOD_REQ["flows"][:1]})
expect_422("flows > 10",
           {**GOOD_REQ,
            "flows": [{"id": f"v{i}", "min_green": 1, "max_green": 1}
                      for i in range(11)]})
expect_422("duplicate ids",
           {**GOOD_REQ,
            "flows": [{"id": "A", "min_green": 1, "max_green": 1},
                      {"id": "A", "min_green": 1, "max_green": 1}]})
expect_422("green < 1",
           {**GOOD_REQ,
            "flows": [{"id": "A", "min_green": 0, "max_green": 1},
                      {"id": "B", "min_green": 1, "max_green": 1}]})
expect_422("green > 60",
           {**GOOD_REQ,
            "flows": [{"id": "A", "min_green": 1, "max_green": 61},
                      {"id": "B", "min_green": 1, "max_green": 1}]})
expect_422("min > max",
           {**GOOD_REQ,
            "flows": [{"id": "A", "min_green": 20, "max_green": 10},
                      {"id": "B", "min_green": 1, "max_green": 1}]})
expect_422("green float",
           {**GOOD_REQ,
            "flows": [{"id": "A", "min_green": 1.5, "max_green": 2},
                      {"id": "B", "min_green": 1, "max_green": 1}]})
expect_422("conflict unknown id",
           {**GOOD_REQ, "conflicts": [["N-S", "ZZZ"]]})
expect_422("conflict self pair",
           {**GOOD_REQ, "conflicts": [["N-S", "N-S"]]})
expect_422("conflict arity 3",
           {**GOOD_REQ, "conflicts": [["N-S", "S-N", "E-W"]]})
expect_422("clearance unknown src",
           {**GOOD_REQ, "clearances": {"ZZZ": {"N-S": 1}}})
expect_422("clearance unknown dst",
           {**GOOD_REQ, "clearances": {"N-S": {"ZZZ": 1}}})
expect_422("clearance > 10",
           {**GOOD_REQ, "clearances": {"N-S": {"E-W": 11}}})
expect_422("clearance < 0",
           {**GOOD_REQ, "clearances": {"N-S": {"E-W": -1}}})
expect_422("cycle_max zero", {**GOOD_REQ, "cycle_max": 0})
expect_422("cycle_max negative", {**GOOD_REQ, "cycle_max": -3})
expect_422("cycle_max too big", {**GOOD_REQ, "cycle_max": 701})
expect_422("cycle_max float", {**GOOD_REQ, "cycle_max": 100.5})
expect_422("extra field", {**GOOD_REQ, "bogus": 1})
expect_422("missing flows", {"cycle_max": 100})
expect_422("id empty",
           {**GOOD_REQ,
            "flows": [{"id": "", "min_green": 1, "max_green": 1},
                      {"id": "B", "min_green": 1, "max_green": 1}]})

# 重复冲突对不报错（静默去重）；清空自环忽略（保留跨相位清空时间）
r = client.post("/plans", json={
    **GOOD_REQ,
    "conflicts": GOOD_REQ["conflicts"] + [["E-W", "N-S"]],
    "clearances": {**GOOD_REQ["clearances"], "N-S": {**GOOD_REQ["clearances"]["N-S"], "N-S": 9}},
})
check("dup conflict accepted", r.status_code == 200, str(r.status_code))
check("self clearance ignored", r.json()["cycle"] == 30,
      str(r.json().get("cycle")))

# 清空时间整体缺省为 0：全红为 0
r = client.post("/plans", json={
    "flows": GOOD_REQ["flows"],
    "conflicts": GOOD_REQ["conflicts"],
    "cycle_max": 120,
})
check("default clearance 0", r.json()["cycle"] == 25,
      str(r.json().get("cycle")))

# 无冲突无清空 => 单相位，全红 0
r = client.post("/plans", json={
    "flows": [{"id": "A", "min_green": 3, "max_green": 8},
              {"id": "B", "min_green": 5, "max_green": 9}],
    "cycle_max": 60,
})
b = r.json()
check("single-phase via http",
      b["status"] == "optimal" and b["num_phases"] == 1
      and b["phases"][0]["all_red_after"] == 0
      and b["phases"][0]["green"] == 5
      and b["cycle"] == 5, str(b))

print("\nALL HTTP TESTS PASSED")
