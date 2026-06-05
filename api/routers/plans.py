"""交易计划 API（B2）。

端点：
  POST /api/plans/generate            -> 仅生成不保存
  GET  /api/plans                     -> 列表（status/ticker/pool_id 过滤）
  POST /api/plans                     -> 保存计划
  GET  /api/plans/{id}                -> 详情
  PATCH /api/plans/{id}               -> 更新（含 status 切换）
  DELETE /api/plans/{id}              -> 删除
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import web_app
from myquant.planning import generate_plan
from myquant.planning.dao import (
    PLAN_ACTIONS,
    PLAN_STATUSES,
    create_plan,
    delete_plan,
    get_plan,
    list_plans,
    update_plan,
)
from myquant.planning.fills import (
    FILL_SIDES,
    create_fill,
    delete_fill,
    list_fills,
    summarize_plan,
)
from myquant.risk.portfolio_guard import evaluate_new_plan

from ._utils import sanitize

router = APIRouter(prefix="/api/plans", tags=["plans"])


class GenerateRequest(BaseModel):
    ticker: str = Field(..., description="标的代码，例如 600000.SH")
    pool_id: int | None = None
    name: str | None = None
    end_date: str | None = None
    valid_days: int = Field(default=5, ge=1, le=60)
    risk_override: dict[str, float] | None = None


class SavePlanRequest(BaseModel):
    ticker: str
    name: str | None = None
    pool_id: int | None = None
    action: str = "buy"
    trading_state: str | None = None
    confidence: str = "medium"
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    stop_loss: float | None = None
    stop_loss_method: str | None = None
    take_profits: list[dict[str, Any]] | None = None
    risk_reward: float | None = None
    position_pct: float | None = None
    position_shares: int | None = None
    risk_per_trade_pct: float | None = None
    account_capital: float | None = None
    reasons: list[str] | None = None
    risks: list[str] | None = None
    note: str | None = None
    features_snapshot: dict[str, Any] | None = None
    valid_until: str | None = None
    status: str = "draft"


class UpdatePlanRequest(BaseModel):
    action: str | None = None
    status: str | None = None
    confidence: str | None = None
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    stop_loss: float | None = None
    take_profits: list[dict[str, Any]] | None = None
    position_pct: float | None = None
    position_shares: int | None = None
    note: str | None = None
    valid_until: str | None = None


@router.post("/generate")
def post_generate(req: GenerateRequest) -> dict[str, Any]:
    price_cache = web_app.load_price_cache()
    if price_cache is None or price_cache.empty:
        raise HTTPException(status_code=503, detail="price_cache 为空，请先在「数据更新」中拉取行情")
    try:
        plan = generate_plan(
            ticker=req.ticker,
            price_cache_df=price_cache,
            end_date=req.end_date,
            pool_id=req.pool_id,
            name=req.name,
            risk_override=req.risk_override,
            valid_days=req.valid_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return sanitize({"plan": plan.to_dict()})


@router.get("")
def get_plans(
    status: str | None = Query(default=None),
    ticker: str | None = Query(default=None),
    pool_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    if status and status not in PLAN_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 仅支持 {PLAN_STATUSES}")
    return sanitize({"plans": list_plans(status=status, ticker=ticker, pool_id=pool_id, limit=limit)})


@router.post("")
def post_plan(req: SavePlanRequest, force: bool = Query(default=False, description="跳过风控硬拦")) -> dict[str, Any]:
    if req.action not in PLAN_ACTIONS:
        raise HTTPException(status_code=400, detail=f"action 仅支持 {PLAN_ACTIONS}")
    if req.status not in PLAN_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 仅支持 {PLAN_STATUSES}")
    # 输入合理性：仓位百分比单位 = 百分比（0-100），不是小数
    if req.position_pct is not None:
        if not (0 < req.position_pct <= 100):
            raise HTTPException(
                status_code=400,
                detail=f"position_pct={req.position_pct} 不合法（需在 (0, 100] 范围内，单位是百分比）",
            )
    # 风控硬拦：仅当落库为可执行状态（draft/active）且 action 不是 exit/avoid 时
    guard_warnings: list[str] = []
    if (
        not force
        and req.position_pct is not None
        and req.action not in ("exit", "avoid")
        and req.status in ("draft", "active")
    ):
        try:
            price_cache = web_app.load_price_cache()
        except Exception:
            price_cache = None
        guard = evaluate_new_plan(
            candidate_position_pct=float(req.position_pct),
            ticker=req.ticker,
            price_cache_df=price_cache,
        )
        if not guard.get("ok", True):
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "风控限制：计划保存被拒绝",
                    "breaches": guard.get("breaches", []),
                    "guard": guard,
                    "hint": "若确认要落库，可加查询参数 ?force=true 绕过",
                },
            )
        guard_warnings = guard.get("breaches", [])
    try:
        plan = create_plan(req.model_dump(exclude_none=False))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return sanitize({"plan": plan, "guard_warnings": guard_warnings})


@router.get("/{plan_id}")
def get_plan_detail(plan_id: int) -> dict[str, Any]:
    plan = get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"plan_id={plan_id} 不存在")
    return sanitize({"plan": plan})


@router.patch("/{plan_id}")
def patch_plan(plan_id: int, req: UpdatePlanRequest, force: bool = Query(default=False)) -> dict[str, Any]:
    if req.status is not None and req.status not in PLAN_STATUSES:
        raise HTTPException(status_code=400, detail=f"status 仅支持 {PLAN_STATUSES}")
    if req.action is not None and req.action not in PLAN_ACTIONS:
        raise HTTPException(status_code=400, detail=f"action 仅支持 {PLAN_ACTIONS}")
    if req.position_pct is not None and not (0 < req.position_pct <= 100):
        raise HTTPException(
            status_code=400,
            detail=f"position_pct={req.position_pct} 不合法（需在 (0, 100] 范围内）",
        )
    # 仅当更新 position_pct 且目标 status 落到 draft/active 时做风控
    if not force and req.position_pct is not None:
        existing = get_plan(plan_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"plan_id={plan_id} 不存在")
        target_status = req.status if req.status is not None else existing.get("status")
        target_action = req.action if req.action is not None else existing.get("action")
        if target_status in ("draft", "active") and target_action not in ("exit", "avoid"):
            try:
                price_cache = web_app.load_price_cache()
            except Exception:
                price_cache = None
            guard = evaluate_new_plan(
                candidate_position_pct=float(req.position_pct),
                ticker=existing.get("ticker", ""),
                price_cache_df=price_cache,
            )
            if not guard.get("ok", True):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "风控限制：计划更新被拒绝",
                        "breaches": guard.get("breaches", []),
                        "guard": guard,
                        "hint": "若确认要更新，可加查询参数 ?force=true 绕过",
                    },
                )
    try:
        plan = update_plan(plan_id, req.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return sanitize({"plan": plan})


@router.delete("/{plan_id}")
def delete_plan_route(plan_id: int) -> dict[str, Any]:
    delete_plan(plan_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# D2 计划执行追踪：成交记录 + 已实现盈亏
# ---------------------------------------------------------------------------
class FillRequest(BaseModel):
    side: str = Field(..., description=f"成交方向 ({'/'.join(FILL_SIDES)})")
    price: float = Field(..., gt=0, description="成交价 (元)")
    quantity: int = Field(..., gt=0, description="成交股数")
    trade_date: str | None = Field(default=None, description="成交时间 ISO 字符串；空则取当前")
    fee: float | None = Field(default=0.0, ge=0, description="手续费 (元)")
    note: str | None = None


@router.get("/{plan_id}/fills")
def list_fills_route(plan_id: int) -> dict[str, Any]:
    if get_plan(plan_id) is None:
        raise HTTPException(404, f"plan_id={plan_id} 不存在")
    fills = list_fills(plan_id)
    summary = summarize_plan(plan_id)
    return sanitize({"fills": fills, "summary": summary})


@router.post("/{plan_id}/fills")
def create_fill_route(plan_id: int, payload: FillRequest) -> dict[str, Any]:
    if get_plan(plan_id) is None:
        raise HTTPException(404, f"plan_id={plan_id} 不存在")
    try:
        fill = create_fill(plan_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    summary = summarize_plan(plan_id)
    return sanitize({"fill": fill, "summary": summary})


@router.delete("/{plan_id}/fills/{fill_id}")
def delete_fill_route(plan_id: int, fill_id: int) -> dict[str, Any]:
    delete_fill(fill_id)
    summary = summarize_plan(plan_id)
    return sanitize({"ok": True, "summary": summary})
