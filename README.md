# 路口信号周期编排服务

给定一个路口 2～10 条有向车流的绿灯可行区间、车流间的无向冲突关系、
以及切换相位时的有向清空时间，服务联合决定：

1. **分组**：每条车流恰好放入一个相位（同相位同时放行）；
2. **顺序**：各相位的放行先后顺序（首尾相接成环）；
3. **整数秒时长**：每个相位的绿灯时长与随后的全红时长。

在给定周期上限内，**先最小化周期总秒数，再最小化相位数**（字典序优化）。
求解器为 [Google OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver)。

## 约束与规则（与实现一致）

- 每条车流**恰好**在一个相位放行。
- 同一相位内不得出现任何冲突车流；冲突对是**无向**的（`[A, B]` 等价于 `[B, A]`，重复对自动去重）。
- 相位绿灯为整数秒，必须同时落在该相位所有成员的 `[min_green, max_green]` 区间内
  （因此合流后绿灯取“各下限最大值”，它必须不大于“各上限最小值”）。
- 相邻两个相位之间（**含末相位回到首相位**）插入全红时长，不少于所有
  “前车流 → 后车流”有向清空时间的**最大值**；未列出的有向对清空时间按 **0** 计。
- 只有一个相位时，全红为 **0**（相位放行自身，不需要清空）。
- 周期 `cycle = Σ 绿灯 + Σ 全红 ≤ cycle_max`。
- 优化目标为字典序：先最小化 `cycle`，再最小化相位数。

## 求解状态 `status`

| 状态 | 含义 |
| --- | --- |
| `optimal` | 求解器**已证明**周期与相位数均为最优 |
| `infeasible` | 求解器**已证明无解**（任何分组/顺序/时长都无法满足周期上限） |
| `feasible_candidate` | 找到了**可行候选**但在 10 秒时限内未证明最优，可直接使用 |
| `not_found` | 时限内**未找到**任何可行解（不代表无解，不等同于 `infeasible`） |

## 启动方式

### 方式一：Docker Compose（推荐，一键启动）

```bash
docker compose up --build
```

服务监听 `http://localhost:8000`。

### 方式二：本地 Python 运行

需要 Python 3.11+。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 访问方式

- 编排接口（POST）：`http://localhost:8000/plans`
- 健康检查（GET）：`http://localhost:8000/healthz` → `{"status":"ok"}`
- 交互式 API 文档（Swagger UI）：`http://localhost:8000/docs`
- OpenAPI 描述：`http://localhost:8000/openapi.json`

## 请求字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `flows` | 数组（2～10 项） | 车流列表 |
| `flows[].id` | 非空字符串 | 车流唯一 ID，不允许重复 |
| `flows[].min_green` | 整数 1～60 | 绿灯下限（秒） |
| `flows[].max_green` | 整数 1～60 | 绿灯上限（秒），须 ≥ `min_green` |
| `conflicts` | 字符串二元组数组，可省略 | 无向冲突对；两项须不同且为已声明 ID |
| `clearances` | 对象，可省略 | 有向清空时间：`{前车流: {后车流: 秒数}}`，值为整数 0～10，未列为 0 |
| `cycle_max` | 正整数，≤ 700 | 周期上限（秒） |

> 非法 ID、非法区间（超出 1～60 或下限大于上限）、非法冲突对、
> 清空时间越界、周期上限非正整数等均返回 **HTTP 422**。
> 请求中出现未声明字段也返回 422。

## 请求与响应示例（实际运行输出）

### 示例 1：正常编排（已证明最优）

请求 `POST /plans`：

```json
{
  "flows": [
    {"id": "N-S", "min_green": 15, "max_green": 45},
    {"id": "S-N", "min_green": 15, "max_green": 45},
    {"id": "E-W", "min_green": 10, "max_green": 30},
    {"id": "W-E", "min_green": 10, "max_green": 30}
  ],
  "conflicts": [
    ["N-S", "E-W"], ["N-S", "W-E"],
    ["S-N", "E-W"], ["S-N", "W-E"]
  ],
  "clearances": {
    "N-S": {"E-W": 3, "W-E": 3},
    "S-N": {"E-W": 3, "W-E": 3},
    "E-W": {"N-S": 2, "S-N": 2},
    "W-E": {"N-S": 2, "S-N": 2}
  },
  "cycle_max": 120
}
```

`curl` 调用：

```bash
curl -X POST http://localhost:8000/plans \
  -H 'Content-Type: application/json' \
  -d @request.json
```

响应 `200 OK`：

```json
{
    "status": "optimal",
    "cycle": 30,
    "num_phases": 2,
    "phases": [
        {
            "phase": 1,
            "flows": ["E-W", "W-E"],
            "green": 10,
            "all_red_after": 2
        },
        {
            "phase": 2,
            "flows": ["N-S", "S-N"],
            "green": 15,
            "all_red_after": 3
        }
    ],
    "solver_time_seconds": 0.04
}
```

读法：

- 相位 1 放行 `E-W`、`W-E`（东西向不冲突，合流），绿灯 10 秒（两区间下限最大值）；
  之后全红 2 秒（东西 → 南北两组有向清空时间的最大值）；
- 相位 2 放行 `N-S`、`S-N`，绿灯 15 秒；之后全红 3 秒（**末相位回到首相位**，
  南北 → 东西清空时间的最大值）；
- 周期 = 10 + 2 + 15 + 3 = **30 秒**，且已证明在周期最小化、相位数最小化意义下最优。

### 示例 2：周期上限过小，已证明无解

把上例的 `cycle_max` 改为 `20`，响应 `200 OK`：

```json
{
    "status": "infeasible",
    "cycle": null,
    "num_phases": null,
    "phases": [],
    "solver_time_seconds": 0.009
}
```

### 示例 3：无冲突、无清空时间 —— 单相位

```bash
curl -X POST http://localhost:8000/plans \
  -H 'Content-Type: application/json' \
  -d '{"flows":[{"id":"A","min_green":3,"max_green":8},{"id":"B","min_green":5,"max_green":9}],"cycle_max":60}'
```

响应：

```json
{
    "status": "optimal",
    "cycle": 5,
    "num_phases": 1,
    "phases": [
        {
            "phase": 1,
            "flows": ["A", "B"],
            "green": 5,
            "all_red_after": 0
        }
    ],
    "solver_time_seconds": 0.01
}
```

（`solver_time_seconds` 为该次求解的墙钟耗时，每次运行会有小幅波动。）

唯一相位的全红为 0；绿灯 5 秒同时落在 `[3,8]` 与 `[5,9]` 内。

### 示例 4：非法输入返回 422

下限大于上限（`N-S` 的 `min_green=40 > max_green=15`）：

```json
{"detail":[{"type":"value_error","loc":["body","flows",0],
"msg":"Value error, 车流 N-S 的 min_green(40) 不得大于 max_green(15)",
"input":{"id":"N-S","min_green":40,"max_green":15},"ctx":{"error":{}}}]}
```

冲突对引用未声明的 ID（`ZZZ`）：

```json
{"detail":[{"type":"value_error","loc":["body"],
"msg":"Value error, 冲突对引用了未声明的车流 ID: ['ZZZ']", ...}]}
```

清空时间超出 0～10 秒（`N-S -> E-W = 11`）：

```json
{"detail":[{"type":"value_error","loc":["body"],
"msg":"Value error, 清空时间 'N-S' -> 'E-W' = 11 超出 0~10 秒", ...}]}
```

## 项目结构

```
.
├── app/
│   ├── __init__.py
│   ├── main.py       # FastAPI 应用与路由
│   ├── schemas.py    # 请求/响应模型与 422 校验
│   └── solver.py     # OR-Tools CP-SAT 编排模型
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── smoke_test.py     # 求解器行为测试
├── http_test.py      # HTTP / 422 测试
└── brute_test.py     # 小规模暴力枚举交叉验证
```

本地运行测试：

```bash
.venv/bin/python smoke_test.py
.venv/bin/python http_test.py
.venv/bin/python brute_test.py
```
