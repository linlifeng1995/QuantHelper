"""TradingPlan DAO。"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from sqlalchemy import select

from myquant.db import session_scope
from myquant.db.models import TradingPlan

PLAN_STATUSES = ("draft", "active", "executed", "cancelled", "expired")
PLAN_ACTIONS = ("buy", "add", "hold", "reduce", "exit", "avoid")
_ALIAS_NAME_RE = re.compile(r"^t\d+$", re.IGNORECASE)


def _pool_cache_name_map() -> dict[str, str]:
    try:
        import web_app  # type: ignore

        df = web_app.load_pool_cache()
    except Exception:
        return {}
    if df is None or df.empty or "ticker" not in df.columns:
        return {}
    name_col = "名称" if "名称" in df.columns else ("name" if "name" in df.columns else None)
    if not name_col:
        return {}
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        ticker = str(row.get("ticker") or "").strip()
        name = str(row.get(name_col) or "").strip()
        if ticker and name:
            out[ticker] = name
    return out


def _fill_name(plan: dict[str, Any], name_map: dict[str, str]) -> dict[str, Any]:
    ticker = str(plan.get("ticker") or "").strip()
    name = str(plan.get("name") or "").strip()
    if ticker and (not name or _ALIAS_NAME_RE.match(name)):
        fallback = name_map.get(ticker)
        if fallback:
            plan["name"] = fallback
    return plan


def _serialize(plan: TradingPlan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "ticker": plan.ticker,
        "name": plan.name,
        "pool_id": plan.pool_id,
        "action": plan.action,
        "trading_state": plan.trading_state,
        "confidence": plan.confidence,
        "entry_zone_low": plan.entry_zone_low,
        "entry_zone_high": plan.entry_zone_high,
        "stop_loss": plan.stop_loss,
        "stop_loss_method": plan.stop_loss_method,
        "take_profits": plan.take_profits or [],
        "risk_reward": plan.risk_reward,
        "position_pct": plan.position_pct,
        "position_shares": plan.position_shares,
        "risk_per_trade_pct": plan.risk_per_trade_pct,
        "account_capital": plan.account_capital,
        "reasons": plan.reasons or [],
        "risks": plan.risks or [],
        "note": plan.note,
        "features_snapshot": plan.features_snapshot or {},
        "valid_until": plan.valid_until.isoformat() if plan.valid_until else None,
        "status": plan.status,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }


_FIELDS = {
    "ticker", "name", "pool_id", "action", "trading_state", "confidence",
    "entry_zone_low", "entry_zone_high", "stop_loss", "stop_loss_method",
    "take_profits", "risk_reward", "position_pct", "position_shares",
    "risk_per_trade_pct", "account_capital", "reasons", "risks", "note",
    "features_snapshot", "valid_until", "status",
}


def _parse_valid_until(v: Any) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def list_plans(
    *,
    status: str | None = None,
    ticker: str | None = None,
    pool_id: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with session_scope() as session:
        stmt = select(TradingPlan).order_by(TradingPlan.created_at.desc()).limit(int(limit))
        if status:
            stmt = stmt.where(TradingPlan.status == status)
        if ticker:
            stmt = stmt.where(TradingPlan.ticker == ticker)
        if pool_id is not None:
            stmt = stmt.where(TradingPlan.pool_id == pool_id)
        rows = session.execute(stmt).scalars().all()
        name_map = _pool_cache_name_map()
        return [_fill_name(_serialize(p), name_map) for p in rows]


def get_plan(plan_id: int) -> dict[str, Any] | None:
    with session_scope() as session:
        plan = session.get(TradingPlan, plan_id)
        if not plan:
            return None
        return _fill_name(_serialize(plan), _pool_cache_name_map())


def create_plan(data: dict[str, Any]) -> dict[str, Any]:
    payload = {k: v for k, v in data.items() if k in _FIELDS}
    if "valid_until" in payload:
        payload["valid_until"] = _parse_valid_until(payload["valid_until"])
    if not payload.get("ticker"):
        raise ValueError("ticker 必填")
    payload.setdefault("status", "draft")
    payload.setdefault("action", "buy")
    payload.setdefault("confidence", "medium")
    with session_scope() as session:
        plan = TradingPlan(**payload)
        session.add(plan)
        session.flush()
        return _fill_name(_serialize(plan), _pool_cache_name_map())


def update_plan(plan_id: int, data: dict[str, Any]) -> dict[str, Any]:
    payload = {k: v for k, v in data.items() if k in _FIELDS}
    if "valid_until" in payload:
        payload["valid_until"] = _parse_valid_until(payload["valid_until"])
    with session_scope() as session:
        plan = session.get(TradingPlan, plan_id)
        if not plan:
            raise ValueError(f"plan_id={plan_id} 不存在")
        for k, v in payload.items():
            setattr(plan, k, v)
        session.flush()
        return _fill_name(_serialize(plan), _pool_cache_name_map())


def delete_plan(plan_id: int) -> None:
    with session_scope() as session:
        plan = session.get(TradingPlan, plan_id)
        if plan:
            session.delete(plan)
