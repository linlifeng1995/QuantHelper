"""滚动价格回测：按时间窗口重复"打分→选 top N→等权持有"，仅依赖价格缓存。

不使用财务数据，因此不会触发 ``assert_fina_snapshots_available``。Phase 4 之后
扩展到基本面回测时会换到带 ``ann_date`` 防未来函数的查询接口。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .metrics import summarize_equity


# ---------------------------------------------------------------------------
# 策略：在 (price_window: rows×tickers) 上为每只 ticker 计算一个分数
# 越大越偏好。NaN 表示当前没有足够数据，会被剔除。
# ---------------------------------------------------------------------------
def _strategy_momentum(window: pd.DataFrame, lookback: int) -> pd.Series:
    if len(window) <= lookback:
        return pd.Series(np.nan, index=window.columns)
    return window.iloc[-1] / window.iloc[-1 - lookback] - 1.0


def _strategy_trend_slope(window: pd.DataFrame, lookback: int = 60) -> pd.Series:
    if len(window) < lookback:
        return pd.Series(np.nan, index=window.columns)
    recent = window.tail(lookback)
    t_axis = np.arange(len(recent), dtype=float)
    out: dict[str, float] = {}
    for ticker in recent.columns:
        series = recent[ticker].astype(float).to_numpy()
        if np.isnan(series).any() or series.mean() == 0:
            out[ticker] = np.nan
            continue
        slope = float(np.polyfit(t_axis, series, 1)[0])
        out[ticker] = slope / float(series.mean())
    return pd.Series(out)


def _strategy_low_volatility(window: pd.DataFrame, lookback: int = 60) -> pd.Series:
    if len(window) < lookback + 1:
        return pd.Series(np.nan, index=window.columns)
    pct = window.tail(lookback + 1).pct_change().tail(lookback)
    vol = pct.std()
    # 越低越好 → 取负
    return -vol


STRATEGIES: dict[str, Any] = {
    "momentum_20d": lambda w: _strategy_momentum(w, 20),
    "momentum_60d": lambda w: _strategy_momentum(w, 60),
    "momentum_120d": lambda w: _strategy_momentum(w, 120),
    "trend_slope_60d": lambda w: _strategy_trend_slope(w, 60),
    "low_volatility_60d": lambda w: _strategy_low_volatility(w, 60),
}

STRATEGY_LABELS: dict[str, str] = {
    "momentum_20d": "20 日动量",
    "momentum_60d": "60 日动量",
    "momentum_120d": "120 日动量",
    "trend_slope_60d": "60 日趋势斜率",
    "low_volatility_60d": "低波动 60 日",
}


# ---------------------------------------------------------------------------
# 调仓日期生成
# ---------------------------------------------------------------------------
def _build_rebalance_dates(index: pd.DatetimeIndex, freq: str) -> list[pd.Timestamp]:
    if len(index) == 0:
        return []
    freq = (freq or "month").lower()
    if freq in {"week", "weekly", "w"}:
        # 每周最后一个出现的交易日
        grouper = index.to_series().groupby(pd.Grouper(freq="W"))
    elif freq in {"quarter", "quarterly", "q"}:
        grouper = index.to_series().groupby(pd.Grouper(freq="QE"))
    else:
        grouper = index.to_series().groupby(pd.Grouper(freq="ME"))
    dates: list[pd.Timestamp] = []
    for _, sub in grouper:
        if len(sub) == 0:
            continue
        dates.append(pd.Timestamp(sub.iloc[-1]))
    return dates


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------
@dataclass
class RollingBacktestResult:
    start_date: str
    end_date: str
    strategy: str
    rebalance: str
    top_n: int
    universe_size: int
    rebalance_dates: list[str]
    equity_curve: list[dict[str, Any]]  # [{date, portfolio, benchmark}]
    holdings: list[dict[str, Any]]  # [{date, tickers, scores}]
    period_returns: list[dict[str, Any]]  # 每段 holding period 收益
    metrics: dict[str, Any]
    benchmark_metrics: dict[str, Any]
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "strategy": self.strategy,
            "strategy_label": STRATEGY_LABELS.get(self.strategy, self.strategy),
            "rebalance": self.rebalance,
            "top_n": self.top_n,
            "universe_size": self.universe_size,
            "rebalance_dates": self.rebalance_dates,
            "equity_curve": self.equity_curve,
            "holdings": self.holdings,
            "period_returns": self.period_returns,
            "metrics": self.metrics,
            "benchmark_metrics": self.benchmark_metrics,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def run_rolling_backtest(
    price_cache_df: pd.DataFrame,
    tickers: Iterable[str],
    start_date: str | None,
    end_date: str | None,
    strategy: str = "momentum_60d",
    rebalance: str = "month",
    top_n: int = 10,
) -> RollingBacktestResult:
    if price_cache_df is None or price_cache_df.empty:
        raise ValueError("price_cache 为空，无法回测")
    if strategy not in STRATEGIES:
        raise ValueError(
            f"未知策略 '{strategy}'，可选：{', '.join(sorted(STRATEGIES.keys()))}"
        )
    if top_n <= 0:
        raise ValueError("top_n 必须为正整数")

    px = price_cache_df.copy()
    px.index = pd.to_datetime(px.index)
    px = px.sort_index()

    ticker_list = [str(t) for t in tickers if t]
    available_tickers = [t for t in ticker_list if t in px.columns]
    universe = px[available_tickers] if available_tickers else px

    warnings: list[str] = []
    if available_tickers and len(available_tickers) < len(ticker_list):
        warnings.append(
            f"价格缓存缺失 {len(ticker_list) - len(available_tickers)} 只标的，已自动剔除"
        )
    if not available_tickers:
        warnings.append("未指定标的列表，回测使用价格缓存中所有 ticker（可能很大）")

    # 解析时间范围
    start_ts = pd.Timestamp(start_date) if start_date else px.index.min()
    end_ts = pd.Timestamp(end_date) if end_date else px.index.max()
    if start_ts >= end_ts:
        raise ValueError(f"start_date ({start_date}) 必须早于 end_date ({end_date})")

    # 调仓日期：必须在 [start_ts, end_ts] 范围内，且至少 2 个
    in_range = px.index[(px.index >= start_ts) & (px.index <= end_ts)]
    if len(in_range) < 5:
        raise ValueError(f"回测区间数据点过少（{len(in_range)} 行），请扩大范围")
    rebalance_dates = _build_rebalance_dates(in_range, rebalance)
    if len(rebalance_dates) < 2:
        raise ValueError(
            f"调仓频率 '{rebalance}' 在区间内仅产生 {len(rebalance_dates)} 个调仓日，至少需要 2 个"
        )

    strategy_fn = STRATEGIES[strategy]

    holdings_records: list[dict[str, Any]] = []
    period_records: list[dict[str, Any]] = []
    equity_dates: list[pd.Timestamp] = []
    equity_port: list[float] = []
    equity_bench: list[float] = []

    cur_eq_port = 1.0
    cur_eq_bench = 1.0

    # equity 曲线起点：第一个调仓日
    equity_dates.append(rebalance_dates[0])
    equity_port.append(cur_eq_port)
    equity_bench.append(cur_eq_bench)

    for i in range(len(rebalance_dates) - 1):
        d_start = rebalance_dates[i]
        d_end = rebalance_dates[i + 1]

        # 用 d_start 及之前的数据打分（防未来函数）
        window = universe.loc[:d_start].ffill()
        if window.empty:
            continue
        scores = strategy_fn(window)
        scores = scores.replace([np.inf, -np.inf], np.nan).dropna()

        if scores.empty:
            warnings.append(f"{d_start.date()}: 策略返回空分数，跳过该期")
            equity_dates.append(d_end)
            equity_port.append(cur_eq_port)
            equity_bench.append(cur_eq_bench)
            continue

        top = scores.sort_values(ascending=False).head(top_n)
        selected = list(top.index)

        # 计算 [d_start, d_end] 期间每只 ticker 的收益
        seg = universe.loc[d_start:d_end]
        if len(seg) < 2:
            equity_dates.append(d_end)
            equity_port.append(cur_eq_port)
            equity_bench.append(cur_eq_bench)
            continue

        ticker_rets: dict[str, float] = {}
        for tk in selected:
            series = seg[tk].dropna()
            if len(series) < 2:
                ticker_rets[tk] = np.nan
                continue
            ticker_rets[tk] = float(series.iloc[-1] / series.iloc[0] - 1.0)

        valid_rets = [r for r in ticker_rets.values() if not pd.isna(r)]
        if not valid_rets:
            port_ret = 0.0
        else:
            port_ret = float(np.mean(valid_rets))

        # benchmark = 全集等权
        bench_rets: list[float] = []
        for tk in seg.columns:
            series = seg[tk].dropna()
            if len(series) < 2:
                continue
            bench_rets.append(float(series.iloc[-1] / series.iloc[0] - 1.0))
        bench_ret = float(np.mean(bench_rets)) if bench_rets else 0.0

        cur_eq_port *= 1.0 + port_ret
        cur_eq_bench *= 1.0 + bench_ret

        equity_dates.append(d_end)
        equity_port.append(cur_eq_port)
        equity_bench.append(cur_eq_bench)

        holdings_records.append(
            {
                "date": d_start.strftime("%Y-%m-%d"),
                "tickers": selected,
                "scores": {tk: round(float(top[tk]), 6) for tk in selected},
            }
        )
        period_records.append(
            {
                "start": d_start.strftime("%Y-%m-%d"),
                "end": d_end.strftime("%Y-%m-%d"),
                "portfolio_return": round(port_ret, 6),
                "benchmark_return": round(bench_ret, 6),
                "excess": round(port_ret - bench_ret, 6),
                "n_holdings": int(len(selected)),
                "n_valid": int(len(valid_rets)),
            }
        )

    equity_index = pd.DatetimeIndex(equity_dates)
    equity_port_series = pd.Series(equity_port, index=equity_index)
    equity_bench_series = pd.Series(equity_bench, index=equity_index)

    periods_per_year = {"week": 52.0, "weekly": 52.0, "w": 52.0,
                        "month": 12.0, "monthly": 12.0, "m": 12.0,
                        "quarter": 4.0, "quarterly": 4.0, "q": 4.0}.get(rebalance.lower(), 12.0)

    metrics = summarize_equity(
        equity_port_series,
        period_returns=[p["portfolio_return"] for p in period_records],
        periods_per_year=periods_per_year,
    )
    benchmark_metrics = summarize_equity(
        equity_bench_series,
        period_returns=[p["benchmark_return"] for p in period_records],
        periods_per_year=periods_per_year,
    )

    equity_curve = [
        {
            "date": d.strftime("%Y-%m-%d"),
            "portfolio": round(p, 6),
            "benchmark": round(b, 6),
        }
        for d, p, b in zip(equity_index, equity_port, equity_bench)
    ]

    return RollingBacktestResult(
        start_date=start_ts.strftime("%Y-%m-%d"),
        end_date=end_ts.strftime("%Y-%m-%d"),
        strategy=strategy,
        rebalance=rebalance,
        top_n=top_n,
        universe_size=len(universe.columns),
        rebalance_dates=[d.strftime("%Y-%m-%d") for d in rebalance_dates],
        equity_curve=equity_curve,
        holdings=holdings_records,
        period_returns=period_records,
        metrics=metrics,
        benchmark_metrics=benchmark_metrics,
        warnings=warnings,
    )


__all__ = [
    "run_rolling_backtest",
    "RollingBacktestResult",
    "STRATEGIES",
    "STRATEGY_LABELS",
]
