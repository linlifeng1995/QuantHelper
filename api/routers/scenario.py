"""情景模拟 API（C3）。

``POST /api/scenario/simulate`` 输入计划集合 + 情景集合，输出每个情景下的
组合 P&L、止损触发数与 ticker 明细。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from myquant.scenario.simulator import (
    DEFAULT_SCENARIOS,
    ScenarioInput,
    simulate_plan_sensitivity,
    simulate_portfolio,
)

from ._utils import sanitize


router = APIRouter(prefix="/api/scenario", tags=["scenario"])


class ScenarioSpec(BaseModel):
    name: str = Field(..., description="情景名称")
    shock_pct: float = Field(default=0.0, ge=-0.5, le=0.5, description="统一冲击百分比，-0.5~0.5")
    overrides: dict[str, float] = Field(default_factory=dict, description="按 ticker 覆盖冲击百分比")


class SimulateRequest(BaseModel):
    plan_ids: list[int] | None = Field(default=None, description="可选：限定 plan_id 集合")
    include_drafts: bool = Field(default=True, description="是否纳入 status=draft 的计划")
    apply_stop_loss: bool = Field(default=True, description="跌破止损是否按止损价结算")
    scenarios: list[ScenarioSpec] | None = Field(default=None, description="为空使用默认 6 档")


@router.get("/defaults")
def get_defaults() -> dict[str, Any]:
    return sanitize({"scenarios": DEFAULT_SCENARIOS})


@router.post("/simulate")
def post_simulate(req: SimulateRequest) -> dict[str, Any]:
    if req.scenarios is not None and len(req.scenarios) == 0:
        raise HTTPException(status_code=400, detail="scenarios 不能为空列表；省略则使用默认情景")
    if req.scenarios is not None and len(req.scenarios) > 20:
        raise HTTPException(status_code=400, detail="scenarios 数量上限 20")

    sc_inputs: list[ScenarioInput] | None = None
    if req.scenarios is not None:
        sc_inputs = [
            ScenarioInput(name=s.name, shock_pct=float(s.shock_pct), overrides=dict(s.overrides))
            for s in req.scenarios
        ]

    try:
        result = simulate_portfolio(
            scenarios=sc_inputs,
            plan_ids=req.plan_ids,
            include_drafts=req.include_drafts,
            apply_stop_loss=req.apply_stop_loss,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"情景模拟失败：{exc!r}") from exc

    return sanitize(result)


@router.get("/plan/{plan_id}/sensitivity")
def get_plan_sensitivity(
    plan_id: int,
    shock_start: float = -0.20,
    shock_end: float = 0.20,
    shock_step: float = 0.01,
    apply_stop_loss: bool = True,
) -> dict[str, Any]:
    """单标的价格灵敏度曲线。"""
    if not (-0.5 <= shock_start < shock_end <= 0.5):
        raise HTTPException(status_code=400, detail="shock_start/end 需在 [-0.5, 0.5] 且 start<end")
    if not (0.001 <= shock_step <= 0.1):
        raise HTTPException(status_code=400, detail="shock_step 需在 [0.001, 0.1]")
    try:
        result = simulate_plan_sensitivity(
            plan_id,
            shock_start=shock_start,
            shock_end=shock_end,
            shock_step=shock_step,
            apply_stop_loss=apply_stop_loss,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "不存在" in msg else 400
        raise HTTPException(status_code=code, detail=msg) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"灵敏度计算失败：{exc!r}") from exc

    return sanitize(result)
