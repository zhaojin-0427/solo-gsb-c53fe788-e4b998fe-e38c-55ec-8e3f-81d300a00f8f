"""请求 / 响应 Pydantic 模型与输入校验。

校验失败由 FastAPI 统一返回 HTTP 422。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 严格整数：JSON 中的 10 与 "10" 字符串不混淆，浮点数一律拒绝。
IntSec = Annotated[int, Field(strict=True)]


class FlowIn(BaseModel):
    """一条有向车流及其可接受的绿灯整数秒区间。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="车流唯一 ID")
    min_green: IntSec = Field(ge=1, le=60, description="绿灯下限（秒）")
    max_green: IntSec = Field(ge=1, le=60, description="绿灯上限（秒）")

    @model_validator(mode="after")
    def _check_bounds(self) -> "FlowIn":
        if self.min_green > self.max_green:
            raise ValueError(
                f"车流 {self.id} 的 min_green({self.min_green}) "
                f"不得大于 max_green({self.max_green})"
            )
        return self


class PlanRequest(BaseModel):
    """POST /plans 的请求体。"""

    model_config = ConfigDict(extra="forbid")

    flows: list[FlowIn] = Field(
        min_length=2,
        max_length=10,
        description="2~10 条车流，ID 必须唯一",
    )
    conflicts: list[list[str]] = Field(
        default_factory=list,
        description="无向冲突对，每对为两个不同且已声明的车流 ID",
    )
    clearances: dict[str, dict[str, IntSec]] = Field(
        default_factory=dict,
        description="有向清空时间 {前车流: {后车流: 0~10 秒}}，未列为 0",
    )
    cycle_max: IntSec = Field(
        gt=0,
        le=700,
        description="周期上限（正整数秒，最大 700：10 相位 ×（60 绿灯 + 10 全红））",
    )

    @model_validator(mode="after")
    def _check_cross_fields(self) -> "PlanRequest":
        ids = [f.id for f in self.flows]
        id_set = set(ids)
        if len(id_set) != len(ids):
            dup = sorted({x for x in ids if ids.count(x) > 1})
            raise ValueError(f"车流 ID 必须唯一，重复: {dup}")

        # 冲突对：元素必须恰好 2 个、非自环、引用已知 ID；无向重复对静默去重。
        seen_pairs: set[frozenset[str]] = set()
        for pair in self.conflicts:
            if len(pair) != 2:
                raise ValueError(f"冲突对必须恰好包含 2 个车流 ID: {pair!r}")
            u, v = pair
            if u == v:
                raise ValueError(f"冲突对不能是同一车流: {u}")
            unknown = [x for x in (u, v) if x not in id_set]
            if unknown:
                raise ValueError(f"冲突对引用了未声明的车流 ID: {unknown}")
            seen_pairs.add(frozenset((u, v)))
        # 原地写回去重后的结果，供求解器直接使用。
        self.conflicts = [sorted(p) for p in seen_pairs]

        # 清空时间：内层键必须已知；值 0~10；自环无意义，忽略。
        for src, dst_map in self.clearances.items():
            if src not in id_set:
                raise ValueError(f"清空时间引用了未声明的车流 ID: {src!r}")
            if not isinstance(dst_map, dict):
                raise ValueError(f"车流 {src} 的清空时间必须是对象映射")
            for dst, seconds in dst_map.items():
                if dst not in id_set:
                    raise ValueError(
                        f"清空时间 {src!r} -> {dst!r} 引用了未声明的车流 ID"
                    )
                if src == dst:
                    continue
                if not isinstance(seconds, int) or isinstance(seconds, bool):
                    raise ValueError(
                        f"清空时间 {src!r} -> {dst!r} 必须是 0~10 的整数秒"
                    )
                if not 0 <= seconds <= 10:
                    raise ValueError(
                        f"清空时间 {src!r} -> {dst!r} = {seconds} 超出 0~10 秒"
                    )
        return self


class PhaseOut(BaseModel):
    phase: int = Field(description="相位序号，按放行顺序从 1 开始")
    flows: list[str] = Field(description="本相位放行的车流 ID")
    green: int = Field(description="本相位绿灯时长（秒）")
    all_red_after: int = Field(
        description="本相位之后到下一相位（末相位则回到首相位）的全红时长（秒）"
    )


class PlanResponse(BaseModel):
    status: str = Field(
        description=(
            "求解状态：optimal=已证明最优；infeasible=已证明无解；"
            "feasible_candidate=找到可行候选但未证明最优；"
            "not_found=时限内未找到可行解（不代表无解）"
        )
    )
    cycle: int | None = Field(default=None, description="周期总时长（秒）")
    num_phases: int | None = Field(default=None, description="相位数")
    phases: list[PhaseOut] = Field(default_factory=list)
    solver_time_seconds: float = Field(description="求解器墙钟耗时（秒）")
