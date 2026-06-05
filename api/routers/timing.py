"""择时（Trading State）API。

端点：
  GET /api/timing/states        -> 返回 6 种状态的元数据（label/color/description）
  GET /api/timing/ticker/{tk}   -> 单标的择时
  GET /api/timing/pool/{pool_id} -> 整池批量择时
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

import web_app
from myquant.timing import (
    STATE_COLORS,
    STATE_DESCRIPTIONS,
    STATE_LABELS,
    evaluate_pool,
    evaluate_ticker,
)

from ._utils import sanitize

router = APIRouter(prefix="/api/timing", tags=["timing"])


@router.get("/states")
def get_states() -> dict[str, Any]:
    """返回 6 种择时状态的展示元数据，便于前端图例。"""
    states = [
        {
            "state": key,
            "label": STATE_LABELS[key],
            "color": STATE_COLORS[key],
            "description": STATE_DESCRIPTIONS[key],
        }
        for key in STATE_LABELS
    ]
    return sanitize({"states": states})


@router.get("/ticker/{ticker}")
def get_ticker_timing(
    ticker: str,
    end_date: str | None = Query(default=None, description="YYYY-MM-DD；缺省取 price_cache 最后一天"),
) -> dict[str, Any]:
    price_cache = web_app.load_price_cache()
    if price_cache is None or price_cache.empty:
        raise HTTPException(status_code=503, detail="price_cache 为空，请先在「数据更新」中拉取行情")
    result = evaluate_ticker(price_cache, ticker, end_date)
    return sanitize(result)


@router.get("/pool/{pool_id}")
def get_pool_timing(
    pool_id: int,
    end_date: str | None = Query(default=None),
) -> dict[str, Any]:
    price_cache = web_app.load_price_cache()
    if price_cache is None or price_cache.empty:
        raise HTTPException(status_code=503, detail="price_cache 为空，请先在「数据更新」中拉取行情")
    try:
        result = evaluate_pool(price_cache, pool_id, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return sanitize(result)
