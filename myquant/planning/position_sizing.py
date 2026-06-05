"""仓位计算：根据"单笔可承受亏损 / 止损距离"得到目标资金占比和股数。"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PositionResult:
    position_pct: float          # 仓位占总资金 %
    position_shares: int
    capital_used: float
    risk_amount: float           # 实际下单亏损金额（理论）
    risk_per_trade_pct: float    # 输入回显
    single_position_cap_pct: float
    label: str


def compute_position(
    *,
    close: float,
    stop_loss: float,
    account_capital: float,
    max_loss_per_trade_pct: float,
    max_single_position_pct: float,
    lot_size: int = 100,
) -> PositionResult:
    """计算建议仓位。

    - account_capital: 总资金
    - max_loss_per_trade_pct: 单笔最大亏损占总资金 % (例如 1.0 -> 1%)
    - max_single_position_pct: 单一品种仓位上限 % (例如 10.0 -> 10%)
    - 仓位 = min( risk_amount / (close-stop), single_cap / close )
    - 股数按 lot_size (默认 100，对应 A 股一手) 向下取整
    """
    if close <= 0 or stop_loss <= 0:
        raise ValueError("close / stop_loss 必须为正")
    if close <= stop_loss:
        raise ValueError("止损价必须低于收盘价")
    if account_capital <= 0:
        raise ValueError("账户资金必须为正")

    risk_amount = account_capital * (max_loss_per_trade_pct / 100.0)
    stop_distance = close - stop_loss
    shares_by_risk = risk_amount / stop_distance
    single_cap_cash = account_capital * (max_single_position_pct / 100.0)
    shares_by_cap = single_cap_cash / close
    raw_shares = min(shares_by_risk, shares_by_cap)
    shares = int(math.floor(raw_shares / lot_size) * lot_size)
    if shares < lot_size:
        shares = 0
    capital_used = shares * close
    position_pct = (capital_used / account_capital) * 100.0 if account_capital else 0.0
    real_risk_amount = shares * stop_distance

    limited_by = "risk" if shares_by_risk <= shares_by_cap else "single_cap"
    label = (
        f"按单笔最大亏损 {max_loss_per_trade_pct:.1f}% 约束（止损距离 {stop_distance/close:.1%}）"
        if limited_by == "risk"
        else f"按单一品种仓位上限 {max_single_position_pct:.1f}% 约束"
    )

    return PositionResult(
        position_pct=round(position_pct, 2),
        position_shares=shares,
        capital_used=round(capital_used, 2),
        risk_amount=round(real_risk_amount, 2),
        risk_per_trade_pct=max_loss_per_trade_pct,
        single_position_cap_pct=max_single_position_pct,
        label=label,
    )
