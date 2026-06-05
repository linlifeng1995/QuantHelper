"""回测绩效指标：从权益曲线 / 收益序列计算年化、夏普、最大回撤、胜率。"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def _to_returns(equity: pd.Series) -> pd.Series:
    eq = pd.to_numeric(equity, errors="coerce").dropna()
    if eq.empty:
        return pd.Series(dtype=float)
    return eq.pct_change().dropna()


def total_return(equity: pd.Series) -> float:
    eq = pd.to_numeric(equity, errors="coerce").dropna()
    if len(eq) < 2:
        return 0.0
    return float(eq.iloc[-1] / eq.iloc[0] - 1.0)


def annualized_return(equity: pd.Series) -> float:
    eq = pd.to_numeric(equity, errors="coerce").dropna()
    if len(eq) < 2:
        return 0.0
    total = eq.iloc[-1] / eq.iloc[0]
    if total <= 0:
        return -1.0
    # 优先按实际日历跨度折年；equity 可能是调仓频率采样，不能用 len(eq) 当交易日。
    n_days: float
    if isinstance(eq.index, pd.DatetimeIndex) and len(eq.index) >= 2:
        delta_days = (eq.index[-1] - eq.index[0]).days
        n_days = float(delta_days) * (TRADING_DAYS_PER_YEAR / 365.25)
        n_days = max(n_days, 1.0)
    else:
        n_days = float(max(1, len(eq) - 1))
    return float(total ** (TRADING_DAYS_PER_YEAR / n_days) - 1.0)


def max_drawdown(equity: pd.Series) -> float:
    eq = pd.to_numeric(equity, errors="coerce").dropna()
    if eq.empty:
        return 0.0
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(dd.min())


def sharpe_ratio(equity: pd.Series, risk_free: float = 0.0, periods_per_year: float = TRADING_DAYS_PER_YEAR) -> float:
    rets = _to_returns(equity)
    if rets.empty:
        return 0.0
    daily_rf = risk_free / periods_per_year
    excess = rets - daily_rf
    std = excess.std(ddof=1)
    if not np.isfinite(std) or std == 0:
        return 0.0
    return float(excess.mean() / std * np.sqrt(periods_per_year))


def win_rate(period_returns: list[float] | pd.Series) -> float:
    arr = pd.Series(period_returns, dtype=float).dropna()
    if arr.empty:
        return 0.0
    return float((arr > 0).sum() / len(arr))


def summarize_equity(
    equity: pd.Series,
    period_returns: list[float] | pd.Series | None = None,
    risk_free: float = 0.0,
    periods_per_year: float = TRADING_DAYS_PER_YEAR,
) -> dict[str, Any]:
    """从权益曲线 + （可选）每期收益数组生成指标字典。"""
    summary = {
        "total_return": total_return(equity),
        "annualized_return": annualized_return(equity),
        "max_drawdown": max_drawdown(equity),
        "sharpe": sharpe_ratio(equity, risk_free=risk_free, periods_per_year=periods_per_year),
        "days": int(len(equity)),
    }
    if period_returns is not None:
        rets = pd.Series(period_returns, dtype=float).dropna()
        summary["win_rate"] = win_rate(rets)
        summary["num_periods"] = int(len(rets))
        summary["avg_period_return"] = float(rets.mean()) if len(rets) else 0.0
    return summary


__all__ = [
    "annualized_return",
    "max_drawdown",
    "sharpe_ratio",
    "summarize_equity",
    "total_return",
    "win_rate",
]
