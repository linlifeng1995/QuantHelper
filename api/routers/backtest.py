"""回测 API（C2）：滚动价格回测。

新路由 ``POST /api/backtest/rolling/price`` 使用 ``myquant.backtest.rolling_price``
实现真实回测，与遗留的 ``POST /api/backtest/rolling`` 占位接口共存。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import web_app
from myquant.backtest.rolling_price import STRATEGY_LABELS, run_rolling_backtest
from myquant.backtest.runs import delete_run, get_run, list_runs, save_run
from myquant.pools.dao import get_pool

from ._utils import sanitize


router = APIRouter(prefix="/api/backtest", tags=["backtest"])


class RollingPriceRequest(BaseModel):
    pool_id: int | None = Field(default=None, description="可选：使用指定股票池的成员")
    tickers: list[str] = Field(default_factory=list, description="可选：自定义 ticker 列表（与 pool_id 二选一）")
    start_date: str | None = None
    end_date: str | None = None
    strategy: str = Field(default="momentum_60d")
    rebalance: str = Field(default="month", description="month / week / quarter")
    top_n: int = Field(default=10, ge=1, le=200)
    save: bool = Field(default=False, description="是否持久化为 BacktestRun")
    label: str | None = Field(default=None, description="保存时的可选标签")


@router.get("/rolling/strategies")
def get_strategies() -> dict[str, Any]:
    return sanitize(
        {
            "strategies": [
                {"value": key, "label": label}
                for key, label in STRATEGY_LABELS.items()
            ],
            "rebalance_options": [
                {"value": "week", "label": "每周"},
                {"value": "month", "label": "每月"},
                {"value": "quarter", "label": "每季"},
            ],
        }
    )


@router.post("/rolling/price")
def post_rolling_price(req: RollingPriceRequest) -> dict[str, Any]:
    tickers: list[str] = []
    if req.tickers:
        tickers = [str(t).strip() for t in req.tickers if str(t).strip()]
    elif req.pool_id is not None:
        pool = get_pool(req.pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail=f"股票池 {req.pool_id} 不存在")
        tickers = [str(it.get("ticker")).strip() for it in pool.get("items", []) if it.get("ticker")]
    if not tickers:
        raise HTTPException(status_code=400, detail="tickers 或 pool_id 必须提供其一")

    try:
        price_cache = web_app.load_price_cache()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"加载价格缓存失败：{exc!r}") from exc
    if price_cache is None or price_cache.empty:
        raise HTTPException(status_code=503, detail="价格缓存为空，请先到数据更新页同步行情")

    try:
        result = run_rolling_backtest(
            price_cache,
            tickers=tickers,
            start_date=req.start_date,
            end_date=req.end_date,
            strategy=req.strategy,
            rebalance=req.rebalance,
            top_n=req.top_n,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"回测失败：{exc!r}") from exc

    payload = result.as_dict()
    if req.save:
        try:
            run_id = save_run(
                payload,
                label=req.label,
                pool_id=req.pool_id,
                params={
                    "pool_id": req.pool_id,
                    "tickers": req.tickers if not req.pool_id else None,
                    "start_date": req.start_date,
                    "end_date": req.end_date,
                    "strategy": req.strategy,
                    "rebalance": req.rebalance,
                    "top_n": req.top_n,
                },
            )
            payload["run_id"] = run_id
        except Exception as exc:  # noqa: BLE001
            payload.setdefault("warnings", []).append(f"持久化失败：{exc!r}")

    return sanitize(payload)


@router.get("/runs")
def get_runs(limit: int = 50) -> dict[str, Any]:
    if limit <= 0 or limit > 200:
        raise HTTPException(status_code=400, detail="limit 需在 1..200")
    return sanitize({"runs": list_runs(limit=limit)})


@router.get("/runs/{run_id}")
def get_run_detail(run_id: int) -> dict[str, Any]:
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"回测 {run_id} 不存在")
    return sanitize(run)


@router.delete("/runs/{run_id}")
def delete_run_route(run_id: int) -> dict[str, Any]:
    if not delete_run(run_id):
        raise HTTPException(status_code=404, detail=f"回测 {run_id} 不存在")
    return {"ok": True}
