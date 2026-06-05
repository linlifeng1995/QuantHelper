"""PlanFill DAO + 计划执行汇总（已实现盈亏 / 剩余持仓）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from myquant.db import session_scope
from myquant.db.models import PlanFill, TradingPlan

FILL_SIDES = ("buy", "sell")


def _serialize(fill: PlanFill) -> dict[str, Any]:
    return {
        "id": fill.id,
        "plan_id": fill.plan_id,
        "side": fill.side,
        "trade_date": fill.trade_date.isoformat() if fill.trade_date else None,
        "price": fill.price,
        "quantity": fill.quantity,
        "fee": fill.fee or 0.0,
        "note": fill.note,
        "created_at": fill.created_at.isoformat() if fill.created_at else None,
    }


def _parse_trade_date(v: Any) -> datetime:
    if v is None or v == "":
        return datetime.utcnow()
    if isinstance(v, datetime):
        return v
    s = str(v).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"无法解析 trade_date={v!r}") from exc


def list_fills(plan_id: int) -> list[dict[str, Any]]:
    with session_scope() as session:
        stmt = (
            select(PlanFill)
            .where(PlanFill.plan_id == int(plan_id))
            .order_by(PlanFill.trade_date.asc(), PlanFill.id.asc())
        )
        rows = session.execute(stmt).scalars().all()
        return [_serialize(r) for r in rows]


def create_fill(plan_id: int, data: dict[str, Any]) -> dict[str, Any]:
    side = str(data.get("side") or "").strip().lower()
    if side not in FILL_SIDES:
        raise ValueError(f"side 必须为 {FILL_SIDES} 之一，实际：{data.get('side')!r}")
    price = float(data.get("price") or 0.0)
    if price <= 0:
        raise ValueError("price 必须 > 0")
    quantity = int(data.get("quantity") or 0)
    if quantity <= 0:
        raise ValueError("quantity 必须 > 0")
    fee = float(data.get("fee") or 0.0)
    trade_date = _parse_trade_date(data.get("trade_date"))
    note = data.get("note")
    with session_scope() as session:
        plan = session.get(TradingPlan, int(plan_id))
        if plan is None:
            raise ValueError(f"plan_id={plan_id} 不存在")
        if side == "sell":
            owned = _net_quantity(session, plan_id)
            if quantity > owned:
                raise ValueError(f"卖出 {quantity} 超过当前持仓 {owned}")
        fill = PlanFill(
            plan_id=int(plan_id),
            side=side,
            trade_date=trade_date,
            price=price,
            quantity=quantity,
            fee=fee,
            note=note,
        )
        session.add(fill)
        session.flush()
        return _serialize(fill)


def delete_fill(fill_id: int) -> None:
    with session_scope() as session:
        fill = session.get(PlanFill, int(fill_id))
        if fill is not None:
            session.delete(fill)


def _net_quantity(session, plan_id: int) -> int:
    rows = session.execute(
        select(PlanFill).where(PlanFill.plan_id == int(plan_id))
    ).scalars().all()
    buy = sum(r.quantity for r in rows if r.side == "buy")
    sell = sum(r.quantity for r in rows if r.side == "sell")
    return buy - sell


def summarize_plan(plan_id: int) -> dict[str, Any]:
    """计算单条 plan 的已实现 PnL、剩余持仓、平均成本（FIFO）。"""
    with session_scope() as session:
        rows = session.execute(
            select(PlanFill)
            .where(PlanFill.plan_id == int(plan_id))
            .order_by(PlanFill.trade_date.asc(), PlanFill.id.asc())
        ).scalars().all()
    # FIFO 配对
    lots: list[list[float]] = []  # [qty, price]
    realized_pnl = 0.0
    total_fee = 0.0
    total_buy_cost = 0.0
    total_buy_qty = 0
    total_sell_qty = 0
    total_sell_value = 0.0
    for f in rows:
        total_fee += float(f.fee or 0.0)
        if f.side == "buy":
            lots.append([float(f.quantity), float(f.price)])
            total_buy_qty += int(f.quantity)
            total_buy_cost += float(f.quantity) * float(f.price)
        else:
            remaining = float(f.quantity)
            sell_price = float(f.price)
            total_sell_qty += int(f.quantity)
            total_sell_value += float(f.quantity) * sell_price
            while remaining > 0 and lots:
                lot_qty, lot_price = lots[0]
                take = min(lot_qty, remaining)
                realized_pnl += take * (sell_price - lot_price)
                lot_qty -= take
                remaining -= take
                if lot_qty <= 1e-9:
                    lots.pop(0)
                else:
                    lots[0][0] = lot_qty
    open_quantity = int(round(sum(q for q, _ in lots)))
    open_cost = sum(q * p for q, p in lots)
    avg_cost = (open_cost / open_quantity) if open_quantity > 0 else None
    realized_pnl_net = realized_pnl - total_fee
    return {
        "plan_id": int(plan_id),
        "fills_count": len(rows),
        "total_buy_qty": total_buy_qty,
        "total_sell_qty": total_sell_qty,
        "open_quantity": open_quantity,
        "avg_cost": avg_cost,
        "open_cost": open_cost if open_quantity > 0 else 0.0,
        "realized_pnl": realized_pnl,
        "total_fee": total_fee,
        "realized_pnl_net": realized_pnl_net,
        "total_buy_cost": total_buy_cost,
        "total_sell_value": total_sell_value,
    }
