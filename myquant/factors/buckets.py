"""因子桶计算器：在保留 web_app.build_factor_screen 算法等价基础上拆成桶。

输入：price_cache_df (index=date, columns=ticker), pool_df (含 ticker/行业/PE/PB/ROE/GROWTH/成交额)
输出：scored_df，每只股票一行，包含各因子原始值 + 各桶分数 (0-100)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from .registry import BUCKETS, BUCKET_DISPLAY_NAMES


# ---------------------------------------------------------------------------
# 工具函数：与 web_app 保持等价（拷贝避免循环依赖）
# ---------------------------------------------------------------------------
def _industry_series(df: pd.DataFrame) -> pd.Series:
    if "行业" in df.columns:
        return df["行业"].fillna("未分类").astype(str)
    return pd.Series("未分类", index=df.index)


def group_percentile_score(df: pd.DataFrame, value_col: str, higher_is_better: bool = True) -> pd.Series:
    if value_col not in df.columns:
        return pd.Series(0.5, index=df.index)
    values = pd.to_numeric(df[value_col], errors="coerce")
    industry = _industry_series(df)
    ranked = values.groupby(industry).rank(pct=True, ascending=higher_is_better)
    global_ranked = values.rank(pct=True, ascending=higher_is_better)
    group_size = values.groupby(industry).transform("count")
    out = ranked.where(group_size >= 5, global_ranked)
    out = (out * 0.7 + global_ranked * 0.3).fillna(global_ranked).fillna(0.5)
    return out.clip(0.0, 1.0)


def minmax_score(values: pd.Series, higher_is_better: bool = True) -> pd.Series:
    values = pd.to_numeric(values, errors="coerce")
    finite = values.replace([np.inf, -np.inf], np.nan)
    min_val = finite.min(skipna=True)
    max_val = finite.max(skipna=True)
    if pd.isna(min_val) or pd.isna(max_val) or min_val == max_val:
        score = pd.Series(0.5, index=values.index)
    else:
        score = (finite - min_val) / (max_val - min_val)
    if not higher_is_better:
        score = 1.0 - score
    return score.fillna(0.5).clip(0.0, 1.0)


def normalize_price_discontinuities(price_df: pd.DataFrame, threshold: float = 0.45) -> pd.DataFrame:
    """Back-adjust obvious split/ex-right discontinuities before factor math."""
    if price_df is None or price_df.empty:
        return price_df

    out = price_df.copy()
    for col in out.columns:
        original = pd.to_numeric(out[col], errors="coerce")
        valid = original.dropna()
        if len(valid) < 2:
            continue

        adjusted = original.copy()
        changes = original.pct_change()
        jump_dates = changes[(changes <= -threshold) | (changes >= threshold / (1.0 - threshold))].index
        for jump_date in jump_dates:
            pos = original.index.get_loc(jump_date)
            if not isinstance(pos, int) or pos <= 0:
                continue
            prev_price = original.iloc[pos - 1]
            curr_price = original.iloc[pos]
            if not (np.isfinite(prev_price) and np.isfinite(curr_price)) or prev_price <= 0 or curr_price <= 0:
                continue
            ratio = float(curr_price / prev_price)
            if 0.05 <= ratio <= 20.0:
                adjusted.iloc[:pos] = adjusted.iloc[:pos] * ratio
        out[col] = adjusted
    return out


# ---------------------------------------------------------------------------
# 价格派生因子（趋势 + 动量 + 风险 + 部分成交量）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PriceFactorTable:
    df: pd.DataFrame  # 含 ticker + ret_*/ma_*/breakout/vol_*/max_dd 等列


def compute_price_factors(price_cache_df: pd.DataFrame, tickers: list[str], end_date: str) -> PriceFactorTable:
    out_cols = pd.DataFrame({"ticker": list(dict.fromkeys([str(t) for t in tickers]))})
    if price_cache_df is None or price_cache_df.empty or out_cols.empty:
        return PriceFactorTable(out_cols)

    px = price_cache_df.copy()
    px.index = pd.to_datetime(px.index)
    px = px.sort_index().loc[: pd.Timestamp(end_date)]
    available = [t for t in out_cols["ticker"].tolist() if t in px.columns]
    if not available or px.empty:
        return PriceFactorTable(out_cols)

    px = normalize_price_discontinuities(px[available]).ffill()
    last = px.iloc[-1]
    factor_map: dict[str, pd.Series] = {}

    # 动量 / 趋势收益
    for window in [5, 20, 60, 120]:
        if len(px) > window:
            factor_map[f"ret_{window}d"] = last / px.shift(window).iloc[-1] - 1.0
        else:
            factor_map[f"ret_{window}d"] = pd.Series(np.nan, index=available)

    # 均线
    for window in [20, 60, 120]:
        if len(px) >= window:
            factor_map[f"ma_{window}"] = px.tail(window).mean()
        else:
            factor_map[f"ma_{window}"] = pd.Series(np.nan, index=available)
    factor_map["close"] = last

    # 多头排列：MA20 > MA60 > MA120
    ma20 = factor_map["ma_20"]
    ma60 = factor_map["ma_60"]
    ma120 = factor_map["ma_120"]
    factor_map["ma_alignment"] = ((last > ma20) & (ma20 > ma60) & (ma60 > ma120)).astype(int)

    # 52 周高点距离
    high_window = min(252, len(px))
    if high_window > 1:
        high_52w = px.tail(high_window).max()
        factor_map["dist_52w_high"] = last / high_52w - 1.0

    # 突破因子：是否突破前 20/60 日最高（不含今天）
    if len(px) > 20:
        high_20 = px.iloc[-21:-1].max()
        factor_map["breakout_20d"] = (last > high_20).astype(int)
    if len(px) > 60:
        high_60 = px.iloc[-61:-1].max()
        factor_map["breakout_60d"] = (last > high_60).astype(int)

    # 60 日斜率（线性回归 close ~ t，归一化为均价的比例）
    if len(px) >= 60:
        recent = px.tail(60)
        t_axis = np.arange(len(recent), dtype=float)
        slopes: dict[str, float] = {}
        for ticker in available:
            series = recent[ticker].astype(float).values
            if np.isnan(series).any() or series.mean() == 0:
                slopes[ticker] = np.nan
                continue
            slope = np.polyfit(t_axis, series, 1)[0]
            slopes[ticker] = float(slope / series.mean())
        factor_map["trend_slope_60d"] = pd.Series(slopes)

    # 动量加速 = ret_120 - ret_20
    factor_map["momentum_accel"] = factor_map.get("ret_120d", pd.Series(np.nan, index=available)) - factor_map.get(
        "ret_20d", pd.Series(np.nan, index=available)
    )

    # 波动率 + 回撤
    pct = px.pct_change()
    factor_map["vol_60d"] = pct.tail(60).std() * np.sqrt(252)
    factor_map["vol_120d"] = pct.tail(120).std() * np.sqrt(252)
    dd_window = px.tail(120)
    factor_map["max_drawdown_120d"] = (dd_window / dd_window.cummax() - 1.0).min()

    df = pd.DataFrame(factor_map).reset_index().rename(columns={"index": "ticker"})
    return PriceFactorTable(out_cols.merge(df, on="ticker", how="left"))


# ---------------------------------------------------------------------------
# 综合打分（按因子桶聚合）
# ---------------------------------------------------------------------------
@dataclass
class BucketScoringResult:
    scored: pd.DataFrame
    bucket_factor_usage: dict[str, list[str]]
    missing_factors_per_ticker: dict[str, list[str]]


def _safe_score(scored: pd.DataFrame, col: str, higher_is_better: bool, industry_neutral: bool) -> pd.Series:
    if col not in scored.columns:
        return pd.Series(0.5, index=scored.index)
    if industry_neutral:
        return group_percentile_score(scored, col, higher_is_better)
    return minmax_score(scored[col], higher_is_better)


def score_buckets(
    pool_df: pd.DataFrame,
    price_factors: pd.DataFrame,
    available_factor_names: Iterable[str],
    industry_neutral: bool = True,
) -> BucketScoringResult:
    """对每个桶计算 0-100 分，并记录每只股票缺失的因子。"""
    df = pool_df.copy()
    df["ticker"] = df["ticker"].astype(str)
    scored = df.merge(price_factors, on="ticker", how="left")

    available = set(available_factor_names)
    bucket_usage: dict[str, list[str]] = {bucket: [] for bucket in BUCKETS}

    # 行业相对强度
    industry = _industry_series(scored)
    scored["行业动量"] = pd.to_numeric(scored.get("ret_60d", np.nan), errors="coerce").groupby(industry).transform("median")
    scored["rel_strength_industry"] = pd.to_numeric(scored.get("ret_60d", np.nan), errors="coerce") - scored["行业动量"]

    # 行业内估值分位
    if "PB" in scored.columns:
        scored["industry_valuation_quantile"] = group_percentile_score(scored, "PB", higher_is_better=False) * 100

    # ---- trend ----
    trend_components: list[tuple[str, str, bool, float]] = []
    if "ma_alignment" in available and "ma_alignment" in scored.columns:
        trend_components.append(("ma_alignment", "ma_alignment", True, 0.30))
    if "dist_52w_high" in available:
        trend_components.append(("dist_52w_high", "dist_52w_high", True, 0.25))
    if "trend_slope_60d" in available:
        trend_components.append(("trend_slope_60d", "trend_slope_60d", True, 0.25))
    if "breakout_20d" in available and "breakout_20d" in scored.columns:
        trend_components.append(("breakout_20d", "breakout_20d", True, 0.20))
    if trend_components:
        total_w = sum(w for *_, w in trend_components)
        score = sum(_safe_score(scored, col, higher, industry_neutral) * (w / total_w) for _, col, higher, w in trend_components)
        scored["trend_score"] = score * 100
        bucket_usage["trend"] = [name for name, *_ in trend_components]
    else:
        scored["trend_score"] = 50.0

    # ---- momentum ----
    momentum_components = []
    if "ret_20d" in available:
        momentum_components.append(("ret_20d", "ret_20d", True, 0.30))
    if "ret_60d" in available:
        momentum_components.append(("ret_60d", "ret_60d", True, 0.35))
    if "ret_120d" in available:
        momentum_components.append(("ret_120d", "ret_120d", True, 0.20))
    if "rel_strength_industry" in available:
        momentum_components.append(("rel_strength_industry", "rel_strength_industry", True, 0.15))
    if momentum_components:
        total_w = sum(w for *_, w in momentum_components)
        score = sum(_safe_score(scored, col, higher, industry_neutral) * (w / total_w) for _, col, higher, w in momentum_components)
        scored["momentum_score"] = score * 100
        bucket_usage["momentum"] = [name for name, *_ in momentum_components]
    else:
        scored["momentum_score"] = 50.0

    # ---- volume ----
    volume_components = []
    if "volume_ratio_20d" in available and "成交额" in scored.columns:
        volume_components.append(("volume_ratio_20d", "成交额", True, 1.0))
    if "amount_change" in available and "成交额" in scored.columns:
        volume_components.append(("amount_change", "成交额", True, 0.5))
    if volume_components:
        total_w = sum(w for *_, w in volume_components)
        score = sum(_safe_score(scored, col, higher, industry_neutral) * (w / total_w) for _, col, higher, w in volume_components)
        scored["volume_score"] = score * 100
        bucket_usage["volume"] = [name for name, *_ in volume_components]
    else:
        scored["volume_score"] = 50.0

    # ---- valuation ----
    val_components = []
    if "pe_ttm" in available and "PE" in scored.columns:
        val_components.append(("pe_ttm", "PE", False, 0.50))
    if "pb" in available and "PB" in scored.columns:
        val_components.append(("pb", "PB", False, 0.40))
    if "industry_valuation_quantile" in available and "industry_valuation_quantile" in scored.columns:
        val_components.append(("industry_valuation_quantile", "industry_valuation_quantile", False, 0.10))
    if val_components:
        total_w = sum(w for *_, w in val_components)
        score = sum(_safe_score(scored, col, higher, industry_neutral) * (w / total_w) for _, col, higher, w in val_components)
        scored["valuation_score"] = score * 100
        bucket_usage["valuation"] = [name for name, *_ in val_components]
    else:
        scored["valuation_score"] = 50.0

    # ---- quality ----
    quality_components = []
    if "roe" in available and "ROE" in scored.columns:
        quality_components.append(("roe", "ROE", True, 0.60))
    if "revenue_growth" in available and "GROWTH" in scored.columns:
        quality_components.append(("revenue_growth", "GROWTH", True, 0.40))
    if quality_components:
        total_w = sum(w for *_, w in quality_components)
        score = sum(_safe_score(scored, col, higher, industry_neutral) * (w / total_w) for _, col, higher, w in quality_components)
        scored["quality_score"] = score * 100
        bucket_usage["quality"] = [name for name, *_ in quality_components]
    else:
        scored["quality_score"] = 50.0

    # ---- risk ----
    risk_components = []
    if "vol_60d" in available and "vol_60d" in scored.columns:
        risk_components.append(("vol_60d", "vol_60d", False, 0.40))
    if "max_drawdown_120d" in available and "max_drawdown_120d" in scored.columns:
        risk_components.append(("max_drawdown_120d", "max_drawdown_120d", True, 0.40))  # 越接近 0 越好（值为负）
    if "turnover_rate" in available and "成交额" in scored.columns:
        risk_components.append(("turnover_rate", "成交额", False, 0.20))
    if risk_components:
        total_w = sum(w for *_, w in risk_components)
        score = sum(_safe_score(scored, col, higher, industry_neutral) * (w / total_w) for _, col, higher, w in risk_components)
        scored["risk_score"] = score * 100
        bucket_usage["risk"] = [name for name, *_ in risk_components]
    else:
        scored["risk_score"] = 50.0

    # ---- capital ---- 默认不可用
    scored["capital_score"] = 50.0
    bucket_usage["capital"] = []

    # ---- event ---- 不参与打分
    scored["event_score"] = 50.0
    bucket_usage["event"] = []

    # 每只股票的缺失因子（pool/价格中字段为 NaN）
    missing_per_ticker: dict[str, list[str]] = {}
    check_columns: dict[str, str] = {
        "ret_20d": "ret_20d",
        "ret_60d": "ret_60d",
        "ret_120d": "ret_120d",
        "vol_60d": "vol_60d",
        "max_drawdown_120d": "max_drawdown_120d",
        "pe_ttm": "PE",
        "pb": "PB",
        "roe": "ROE",
        "revenue_growth": "GROWTH",
        "volume_ratio_20d": "成交额",
    }
    for _, row in scored.iterrows():
        ticker = str(row["ticker"])
        missing: list[str] = []
        for fname, col in check_columns.items():
            if fname not in available:
                continue
            if col not in scored.columns:
                missing.append(fname)
                continue
            v = row.get(col)
            if pd.isna(v):
                missing.append(fname)
        if missing:
            missing_per_ticker[ticker] = missing

    return BucketScoringResult(scored=scored, bucket_factor_usage=bucket_usage, missing_factors_per_ticker=missing_per_ticker)


__all__ = [
    "compute_price_factors",
    "score_buckets",
    "BucketScoringResult",
    "BUCKETS",
    "BUCKET_DISPLAY_NAMES",
]
