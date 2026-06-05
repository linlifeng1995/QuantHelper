"""风控设置 API。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from myquant.risk.portfolio_guard import portfolio_summary
from myquant.risk.settings import get_settings, update_settings

from ._utils import sanitize

router = APIRouter(prefix="/api/risk", tags=["risk"])


class RiskSettingsRequest(BaseModel):
    account_capital: float | None = Field(default=None, gt=0)
    max_loss_per_trade_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    max_single_position_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    max_industry_exposure_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    cap_strong_market_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    cap_neutral_market_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    cap_weak_market_pct: float | None = Field(default=None, ge=0.0, le=100.0)


@router.get("/settings")
def get_risk_settings() -> dict[str, Any]:
    return sanitize(get_settings())


@router.put("/settings")
def put_risk_settings(request: RiskSettingsRequest) -> dict[str, Any]:
    try:
        out = update_settings(**request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return sanitize(out)


@router.get("/portfolio")
def get_portfolio_guard() -> dict[str, Any]:
    try:
        from web_app import load_price_cache  # type: ignore

        cache_df = load_price_cache()
    except Exception:
        cache_df = None
    return sanitize(portfolio_summary(cache_df))
