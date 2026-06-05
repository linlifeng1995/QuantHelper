"""市场宽度/状态分类：依据 price_cache 计算 MA60 以上比例。

由于本地缓存不含基准指数，使用宽度作为代理：
- strong : %above_MA60 ≥ 60%
- neutral: 30% ≤ %above_MA60 < 60%
- weak   : %above_MA60 < 30%
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

RegimeKey = Literal["strong", "neutral", "weak", "unknown"]

REGIME_LABELS: dict[str, str] = {
    "strong": "强势市场",
    "neutral": "震荡市场",
    "weak": "弱势市场",
    "unknown": "未知",
}

REGIME_COLORS: dict[str, str] = {
    "strong": "green",
    "neutral": "blue",
    "weak": "red",
    "unknown": "default",
}


@dataclass
class RegimeResult:
    regime: RegimeKey
    label: str
    color: str
    breadth_pct: float
    sample_size: int
    end_date: str | None

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "label": self.label,
            "color": self.color,
            "breadth_pct": self.breadth_pct,
            "sample_size": self.sample_size,
            "end_date": self.end_date,
        }


def resolve_effective_end_date(
    price_cache_df: pd.DataFrame,
    end_date: str | None = None,
) -> str | None:
    """挑选 breadth-aware 的有效末日（最后一行 notna 数量 ≥ max(50% 历史峰值, 100) 的交易日）。

    用于让 recommend()、classify_regime() 等口径统一，避免增量更新时半截最新行污染评估。
    返回 'YYYY-MM-DD' 字符串，若无法识别则原样返回入参 end_date。
    """
    if price_cache_df is None or price_cache_df.empty:
        return end_date
    df = price_cache_df
    if end_date is not None:
        df = df.loc[df.index <= pd.Timestamp(end_date)]
        if df.empty:
            return end_date
    row_counts = df.notna().sum(axis=1)
    if row_counts.empty:
        return end_date
    max_count = int(row_counts.max())
    threshold = max(int(max_count * 0.5), 100)
    valid_idx = row_counts[row_counts >= threshold].index
    if len(valid_idx) == 0:
        return end_date
    return pd.Timestamp(valid_idx.max()).strftime("%Y-%m-%d")


def classify_regime(price_cache_df: pd.DataFrame, end_date: str | None = None) -> RegimeResult:
    if price_cache_df is None or price_cache_df.empty:
        return RegimeResult("unknown", REGIME_LABELS["unknown"], REGIME_COLORS["unknown"], 0.0, 0, end_date)

    df = price_cache_df
    if end_date is not None:
        df = df.loc[df.index <= pd.Timestamp(end_date)]
        if df.empty:
            return RegimeResult("unknown", REGIME_LABELS["unknown"], REGIME_COLORS["unknown"], 0.0, 0, end_date)

    # 选取"最后一行 notna 数量充足"的交易日作为有效末日，避免增量更新时半截行污染
    end_str = resolve_effective_end_date(df, None)
    if end_str is None:
        return RegimeResult("unknown", REGIME_LABELS["unknown"], REGIME_COLORS["unknown"], 0.0, 0, end_date)
    last_idx = pd.Timestamp(end_str)
    df = df.loc[df.index <= last_idx]
    window = df.tail(60)
    if len(window) < 20:
        return RegimeResult("unknown", REGIME_LABELS["unknown"], REGIME_COLORS["unknown"], 0.0, 0, end_str)

    ma60 = window.mean(axis=0, skipna=True)
    last = df.loc[last_idx]
    pair = pd.DataFrame({"last": last, "ma60": ma60}).dropna()
    if pair.empty:
        return RegimeResult("unknown", REGIME_LABELS["unknown"], REGIME_COLORS["unknown"], 0.0, 0, end_str)

    above = (pair["last"] > pair["ma60"]).sum()
    total = len(pair)
    pct = round(float(above) / float(total) * 100.0, 2)

    if pct >= 60.0:
        key: RegimeKey = "strong"
    elif pct >= 30.0:
        key = "neutral"
    else:
        key = "weak"
    return RegimeResult(key, REGIME_LABELS[key], REGIME_COLORS[key], pct, total, end_str)
