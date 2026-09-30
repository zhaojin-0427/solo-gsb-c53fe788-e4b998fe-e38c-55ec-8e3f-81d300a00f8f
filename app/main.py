"""FastAPI 应用：路口信号周期编排服务。"""

from __future__ import annotations

from fastapi import FastAPI

from .schemas import PhaseOut, PlanRequest, PlanResponse
from .solver import solve_plan

app = FastAPI(
    title="路口信号周期编排服务",
    description=(
        "给定车流绿灯区间、无向冲突对与有向清空时间，"
        "联合决定相位分组、顺序与整数秒时长，在周期上限内先最小化周期、"
        "再最小化相位数。"
    ),
    version="1.0.0",
)


@app.get("/healthz", tags=["meta"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/plans", response_model=PlanResponse, tags=["plans"])
def create_plan(req: PlanRequest) -> PlanResponse:
    result = solve_plan(req.flows, req.conflicts, req.clearances, req.cycle_max)
    return PlanResponse(
        status=result.status,
        cycle=result.cycle,
        num_phases=result.num_phases,
        phases=[
            PhaseOut(
                phase=ph.order,
                flows=ph.flows,
                green=ph.green,
                all_red_after=ph.all_red_after,
            )
            for ph in result.phases
        ],
        solver_time_seconds=round(result.solver_time_seconds, 4),
    )
