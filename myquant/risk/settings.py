"""风控设置 DAO（单行配置）。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ..db import session_scope
from ..db.models import RiskSettings


DEFAULTS: dict[str, float] = {
    "account_capital": 100000.0,
    "max_loss_per_trade_pct": 1.0,
    "max_single_position_pct": 10.0,
    "max_industry_exposure_pct": 25.0,
    "cap_strong_market_pct": 80.0,
    "cap_neutral_market_pct": 50.0,
    "cap_weak_market_pct": 20.0,
}


def _serialize(settings: RiskSettings) -> dict[str, Any]:
    return {
        "account_capital": settings.account_capital,
        "max_loss_per_trade_pct": settings.max_loss_per_trade_pct,
        "max_single_position_pct": settings.max_single_position_pct,
        "max_industry_exposure_pct": settings.max_industry_exposure_pct,
        "cap_strong_market_pct": settings.cap_strong_market_pct,
        "cap_neutral_market_pct": settings.cap_neutral_market_pct,
        "cap_weak_market_pct": settings.cap_weak_market_pct,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


def ensure_default() -> None:
    with session_scope() as session:
        existing = session.execute(select(RiskSettings).where(RiskSettings.id == 1)).scalar_one_or_none()
        if existing:
            return
        session.add(RiskSettings(id=1, **DEFAULTS))


def get_settings() -> dict[str, Any]:
    ensure_default()
    with session_scope() as session:
        row = session.execute(select(RiskSettings).where(RiskSettings.id == 1)).scalar_one()
        return _serialize(row)


def update_settings(**fields: Any) -> dict[str, Any]:
    ensure_default()
    with session_scope() as session:
        row = session.execute(select(RiskSettings).where(RiskSettings.id == 1)).scalar_one()
        for key, value in fields.items():
            if value is None or not hasattr(row, key):
                continue
            value_f = float(value)
            if key.endswith("_pct") and not (0.0 <= value_f <= 100.0):
                raise ValueError(f"{key} 必须在 0-100 之间")
            if key == "account_capital" and value_f <= 0:
                raise ValueError("账户资金必须大于 0")
            setattr(row, key, value_f)
        session.flush()
        return _serialize(row)
