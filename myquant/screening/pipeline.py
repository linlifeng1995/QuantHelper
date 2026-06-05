"""多因子选股流水线（按因子桶 + 入选原因 + 风险 + 缺失项）。

复用 web_app.apply_risk_filters 做风险硬过滤，然后调用 myquant.factors.buckets 打分。
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..factors.buckets import (
    BUCKETS,
    BUCKET_DISPLAY_NAMES,
    BucketScoringResult,
    compute_price_factors,
    score_buckets,
)
from ..factors.registry import list_factor_defs


DEFAULT_BUCKET_WEIGHTS: dict[str, float] = {
    "trend": 0.20,
    "momentum": 0.20,
    "volume": 0.10,
    "valuation": 0.15,
    "quality": 0.20,
    "risk": 0.15,
    "capital": 0.0,
    "event": 0.0,
}


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    clean = {k: max(0.0, float(v)) for k, v in weights.items() if k in BUCKETS}
    total = sum(clean.values())
    if total <= 0:
        return {k: 1.0 / max(1, len(clean)) for k in clean}
    return {k: v / total for k, v in clean.items()}


def _build_reasons_and_risks(row: pd.Series) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    risks: list[str] = []

    if row.get("trend_score", 0) >= 70:
        reasons.append("技术趋势靠前")
    if row.get("momentum_score", 0) >= 70:
        reasons.append("动量行业前列")
    if row.get("quality_score", 0) >= 70:
        reasons.append("财务质量优秀")
    if row.get("valuation_score", 0) >= 70:
        reasons.append("估值处于相对低位")
    if row.get("risk_score", 0) >= 70:
        reasons.append("波动和回撤可控")
    if pd.notna(row.get("ROE")) and float(row.get("ROE", 0)) >= 12:
        reasons.append(f"ROE={float(row['ROE']):.1f}%")
    if pd.notna(row.get("GROWTH")) and float(row.get("GROWTH", 0)) >= 20:
        reasons.append("营收增速领先")
    if pd.notna(row.get("rel_strength_industry")) and float(row.get("rel_strength_industry", 0)) > 0.02:
        reasons.append("近期强于行业中位数")

    if pd.notna(row.get("vol_60d")) and float(row.get("vol_60d", 0)) > 0.6:
        risks.append("60 日波动率偏高")
    if pd.notna(row.get("max_drawdown_120d")) and float(row.get("max_drawdown_120d", 0)) < -0.35:
        risks.append("120 日回撤偏深")
    if pd.notna(row.get("PE")) and float(row.get("PE", 0)) > 80:
        risks.append("PE 偏高")
    if pd.notna(row.get("GROWTH")) and float(row.get("GROWTH", 0)) < 0:
        risks.append("营收同比为负")
    if row.get("valuation_score", 50) <= 30:
        risks.append("估值压力较大")
    if row.get("risk_score", 50) <= 30:
        risks.append("风险因子得分偏低")
    if not risks:
        risks.append("当前未触发主要风险项")
    if not reasons:
        reasons.append("综合评分相对靠前")

    return reasons[:5], risks[:4]


def run_screen(
    pool_df: pd.DataFrame,
    price_cache_df: pd.DataFrame,
    *,
    end_date: str,
    top_n: int = 30,
    bucket_weights: dict[str, float] | None = None,
    industry_neutral: bool = True,
    industries: list[str] | None = None,
    risk_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按因子桶打分，输出 rows + bucket_meta + scope。

    与 web_app.build_factor_screen 算法保持等价的核心：动量/质量/估值/风险使用
    相同的 group_percentile_score；新增 trend 桶；event/capital 默认 50。
    """
    if pool_df is None or pool_df.empty or "ticker" not in pool_df.columns:
        raise RuntimeError("股票池缓存为空，请先到“数据中心”同步行情")

    df = pool_df.copy()
    df["ticker"] = df["ticker"].astype(str)

    # 行业过滤
    if industries:
        industries = list(dict.fromkeys(str(x).strip() for x in industries if str(x).strip()))
        if industries:
            if "行业" not in df.columns:
                raise RuntimeError("股票池缓存缺少行业字段，无法按板块筛选")
            industry_series = df["行业"].fillna("未分类").astype(str).str.strip().replace("", "未分类")
            df = df[industry_series.isin(industries)].copy()
            if df.empty:
                raise RuntimeError("所选板块/行业内没有可筛选股票，请调整范围")

    # 风险硬过滤（复用 web_app）
    import web_app as _legacy  # 局部 import 避免循环
    filters = dict(risk_filters or {})
    price_factors_table = compute_price_factors(price_cache_df, df["ticker"].tolist(), end_date)
    filtered, removed = _legacy.apply_risk_filters(df, price_factors_table.df, filters, end_date)
    if filtered.empty:
        raise RuntimeError("风险过滤后候选池为空，请放宽硬性过滤条件")

    # 因子注册表可用性
    factor_defs = list_factor_defs()
    available_names = [fd["factor_name"] for fd in factor_defs if fd["is_available"] and fd["participates_in_score"]]
    bucket_def_info: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in BUCKETS}
    for fd in factor_defs:
        bucket_def_info.setdefault(fd["bucket"], []).append(fd)

    # 打分
    result: BucketScoringResult = score_buckets(filtered, price_factors_table.df, available_names, industry_neutral=industry_neutral)
    scored = result.scored

    weights = _normalize_weights(bucket_weights or DEFAULT_BUCKET_WEIGHTS)
    composite = sum(scored.get(f"{b}_score", pd.Series(50.0, index=scored.index)) * w for b, w in weights.items())
    scored["综合评分"] = composite

    # 排序 + 截断
    scored = scored.sort_values("综合评分", ascending=False).drop_duplicates(subset=["ticker"]).head(int(top_n))

    rows: list[dict[str, Any]] = []
    for _, row in scored.iterrows():
        reasons, risks = _build_reasons_and_risks(row)
        ticker = str(row["ticker"])
        buckets_payload = {
            bucket: {
                "score": _to_float(row.get(f"{bucket}_score")),
                "label": BUCKET_DISPLAY_NAMES[bucket],
                "factors_used": result.bucket_factor_usage.get(bucket, []),
                "available": bool(result.bucket_factor_usage.get(bucket)),
                "participates": weights.get(bucket, 0) > 0,
            }
            for bucket in BUCKETS
        }
        rows.append(
            {
                "ticker": ticker,
                "名称": row.get("名称"),
                "行业": row.get("行业"),
                "综合评分": _to_float(row.get("综合评分")),
                "buckets": buckets_payload,
                "trend_score": _to_float(row.get("trend_score")),
                "momentum_score": _to_float(row.get("momentum_score")),
                "volume_score": _to_float(row.get("volume_score")),
                "valuation_score": _to_float(row.get("valuation_score")),
                "quality_score": _to_float(row.get("quality_score")),
                "risk_score": _to_float(row.get("risk_score")),
                "capital_score": _to_float(row.get("capital_score")),
                "event_score": _to_float(row.get("event_score")),
                "PE": _to_float(row.get("PE")),
                "PB": _to_float(row.get("PB")),
                "ROE": _to_float(row.get("ROE")),
                "GROWTH": _to_float(row.get("GROWTH")),
                "ret_20d": _to_float(row.get("ret_20d")),
                "ret_60d": _to_float(row.get("ret_60d")),
                "ret_120d": _to_float(row.get("ret_120d")),
                "vol_60d": _to_float(row.get("vol_60d")),
                "max_drawdown_120d": _to_float(row.get("max_drawdown_120d")),
                "ma_alignment": _to_float(row.get("ma_alignment")),
                "dist_52w_high": _to_float(row.get("dist_52w_high")),
                "breakout_20d": _to_float(row.get("breakout_20d")),
                "rel_strength_industry": _to_float(row.get("rel_strength_industry")),
                "入选原因": "；".join(reasons),
                "主要风险": "；".join(risks),
                "数据缺失": result.missing_factors_per_ticker.get(ticker, []),
            }
        )

    return {
        "rows": rows,
        "bucket_weights": weights,
        "removed": removed,
        "bucket_meta": [
            {
                "bucket": bucket,
                "label": BUCKET_DISPLAY_NAMES[bucket],
                "factors": bucket_def_info.get(bucket, []),
                "weight": weights.get(bucket, 0.0),
            }
            for bucket in BUCKETS
        ],
    }


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    return v
