"""财务/估值快照采集 API（C4）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import web_app
from myquant.data.snapshots import (
    snapshot_status,
    sync_daily_basic,
    sync_fina_indicator,
)
from myquant.pools.dao import get_pool
from myquant.tushare_client import DEFAULT_TUSHARE_HTTP_URL

from ._utils import sanitize


router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])


# ---------------------------------------------------------------------------
# Request 模型
# ---------------------------------------------------------------------------
class _BaseSyncRequest(BaseModel):
    token: str = Field(default="", description="Tushare token；留空使用缓存中的 token")
    http_url: str = Field(default=DEFAULT_TUSHARE_HTTP_URL)


class DailyBasicSyncRequest(_BaseSyncRequest):
    trade_dates: list[str] = Field(default_factory=list, description="目标交易日列表")
    pool_id: int | None = Field(default=None, description="可选：仅同步指定池中的 ts_code")


class FinaSyncRequest(_BaseSyncRequest):
    ts_codes: list[str] = Field(default_factory=list, description="ts_code 列表，例如 000001.SZ")
    pool_id: int | None = Field(default=None, description="可选：使用指定股票池的成员")
    start_date: str | None = None
    end_date: str | None = None
    limit: int | None = Field(default=None, description="最多同步多少只股票（防止超时）")


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _resolve_token(req: _BaseSyncRequest) -> str:
    token = (req.token or "").strip() or (web_app.load_token_cache() or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="请提供 Tushare Token，或先在缓存中保存 token")
    return token


def _build_client(req: _BaseSyncRequest):
    token = _resolve_token(req)
    http_url = (req.http_url or "").strip() or DEFAULT_TUSHARE_HTTP_URL
    return web_app.init_tushare_client(token, http_url)


def _ts_codes_from_pool(pool_id: int) -> list[str]:
    pool = get_pool(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail=f"股票池 {pool_id} 不存在")
    tickers = [item.get("ticker") for item in pool.get("items", []) if item.get("ticker")]
    return [web_app.to_ts_code(t) for t in tickers if t]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/status")
def get_status() -> dict[str, Any]:
    return sanitize(snapshot_status())


@router.post("/sync/daily_basic")
def post_sync_daily_basic(req: DailyBasicSyncRequest) -> dict[str, Any]:
    trade_dates = [d for d in (req.trade_dates or []) if str(d).strip()]
    if not trade_dates:
        raise HTTPException(status_code=400, detail="trade_dates 不能为空")
    if len(trade_dates) > 60:
        raise HTTPException(status_code=400, detail="单次同步最多支持 60 个交易日，请分批")
    ts_codes: list[str] | None = None
    if req.pool_id is not None:
        ts_codes = _ts_codes_from_pool(req.pool_id)
        if not ts_codes:
            raise HTTPException(status_code=400, detail="指定股票池为空")
    pro = _build_client(req)
    try:
        result = sync_daily_basic(pro, trade_dates, ts_codes=ts_codes)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"daily_basic 同步失败：{exc!r}") from exc
    return sanitize({"result": result.as_dict(), "status": snapshot_status()})


@router.post("/sync/fina")
def post_sync_fina(req: FinaSyncRequest) -> dict[str, Any]:
    codes: list[str] = []
    if req.ts_codes:
        codes = [str(c).strip() for c in req.ts_codes if str(c).strip()]
    elif req.pool_id is not None:
        codes = _ts_codes_from_pool(req.pool_id)
    if not codes:
        raise HTTPException(status_code=400, detail="ts_codes 或 pool_id 必须提供其一")
    if req.limit is not None and req.limit > 0:
        codes = codes[: int(req.limit)]
    if len(codes) > 200:
        raise HTTPException(
            status_code=400,
            detail=f"单次最多支持 200 只股票（当前 {len(codes)}），请通过 limit 或 pool_id 分批",
        )
    pro = _build_client(req)
    try:
        result = sync_fina_indicator(
            pro,
            codes,
            start_date=req.start_date,
            end_date=req.end_date,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"fina 同步失败：{exc!r}") from exc
    return sanitize({"result": result.as_dict(), "status": snapshot_status()})
