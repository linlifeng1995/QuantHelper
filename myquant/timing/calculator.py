"""择时计算入口：单标的 / 多标的 / 整池。

调用方负责传入 price_cache_df；router 层会通过 ``web_app.load_price_cache()``
预先加载。同一池子内批量计算时复用一次 compute_price_factors 调用以提速。
"""
from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from myquant.factors.buckets import compute_price_factors
from myquant.pools.dao import get_pool

from .rules import TimingResult, evaluate_features


def _resolve_end_date(price_cache_df: pd.DataFrame, end_date: str | None) -> str:
    if end_date:
        return end_date
    if price_cache_df is None or price_cache_df.empty:
        raise ValueError("price_cache 为空，无法推断 end_date")
    return pd.Timestamp(price_cache_df.index.max()).strftime("%Y-%m-%d")


def evaluate_tickers(
    price_cache_df: pd.DataFrame,
    tickers: Iterable[str],
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """批量计算择时。返回 list[{ticker, ...TimingResult}]。"""
    ticker_list = [str(t) for t in tickers if t]
    if not ticker_list:
        return []
    eff_end = _resolve_end_date(price_cache_df, end_date)
    factor_table = compute_price_factors(price_cache_df, ticker_list, eff_end)
    df = factor_table.df if factor_table is not None else pd.DataFrame()
    by_ticker: dict[str, dict[str, Any]] = {}
    if df is not None and not df.empty and "ticker" in df.columns:
        for row in df.to_dict(orient="records"):
            by_ticker[str(row["ticker"])] = row
    results: list[dict[str, Any]] = []
    for tk in ticker_list:
        feats = by_ticker.get(tk, {"ticker": tk})
        timing: TimingResult = evaluate_features(feats)
        out = {"ticker": tk, "end_date": eff_end, **timing.to_dict()}
        results.append(out)
    return results


def evaluate_ticker(
    price_cache_df: pd.DataFrame,
    ticker: str,
    end_date: str | None = None,
) -> dict[str, Any]:
    """单标的择时。"""
    items = evaluate_tickers(price_cache_df, [ticker], end_date)
    if not items:
        return {
            "ticker": ticker,
            "end_date": end_date,
            "state": "do_not_trade",
            "label": "暂不交易",
            "color": "default",
            "description": "无数据",
            "reasons": ["price_cache 为空"],
            "risks": [],
            "features": {},
        }
    return items[0]


def evaluate_pool(
    price_cache_df: pd.DataFrame,
    pool_id: int,
    end_date: str | None = None,
) -> dict[str, Any]:
    """对整个 pool 计算择时。返回 {pool_id, pool_name, end_date, items:[...]}。"""
    pool = get_pool(pool_id)
    if pool is None:
        raise ValueError(f"pool_id={pool_id} 不存在")
    items = pool.get("items") or []
    tickers = [it.get("ticker") for it in items if it.get("ticker")]
    timing_rows = evaluate_tickers(price_cache_df, tickers, end_date)
    by_ticker = {row["ticker"]: row for row in timing_rows}
    enriched: list[dict[str, Any]] = []
    for it in items:
        tk = it.get("ticker")
        row = by_ticker.get(tk, {})
        enriched.append(
            {
                "ticker": tk,
                "name": it.get("name"),
                "industry": it.get("industry"),
                **{k: v for k, v in row.items() if k != "ticker"},
            }
        )
    return {
        "pool_id": pool["id"],
        "pool_name": pool.get("name"),
        "end_date": timing_rows[0]["end_date"] if timing_rows else end_date,
        "count": len(enriched),
        "items": enriched,
    }
