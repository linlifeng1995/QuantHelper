"""Factor Registry：定义首版因子清单与可用性检测。

数据缺失时不报错，只把 is_available 置 false + 给出 missing_reason，
打分阶段按 fallback_behavior（默认 neutral_50）处理。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import select

from ..db import session_scope
from ..db.models import FactorDef


@dataclass(frozen=True)
class FactorSpec:
    factor_name: str
    bucket: str
    display_name: str
    description: str
    tushare_api: str | None
    required_fields: tuple[str, ...]
    refresh_frequency: str
    permission_required: str
    higher_is_better: bool = True
    fallback_behavior: str = "neutral_50"
    participates_in_score: bool = True


# 首版因子清单。事件因子默认 participates_in_score=False（仅展示）。
DEFAULT_FACTORS: tuple[FactorSpec, ...] = (
    # ---- trend ----
    FactorSpec("ma_alignment", "trend", "均线多头排列", "MA20 > MA60 > MA120 为多头排列", "pro_bar/daily", ("close",), "daily", "basic"),
    FactorSpec("dist_52w_high", "trend", "距 52 周高点", "当前价相对 252 日最高价的距离", "daily", ("close",), "daily", "basic", higher_is_better=True),
    FactorSpec("trend_slope_60d", "trend", "60 日趋势斜率", "60 日收益率的线性回归斜率", "daily", ("close",), "daily", "basic"),
    FactorSpec("breakout_20d", "trend", "20 日突破", "收盘价是否突破前 20 日最高", "daily", ("close",), "daily", "basic"),
    # ---- momentum ----
    FactorSpec("ret_20d", "momentum", "20 日收益率", "近 20 个交易日收益", "daily", ("close",), "daily", "basic"),
    FactorSpec("ret_60d", "momentum", "60 日收益率", "近 60 个交易日收益", "daily", ("close",), "daily", "basic"),
    FactorSpec("ret_120d", "momentum", "120 日收益率", "近 120 个交易日收益", "daily", ("close",), "daily", "basic"),
    FactorSpec("rel_strength_industry", "momentum", "相对行业强度", "60 日收益相对行业中位数", "daily", ("close", "行业"), "daily", "basic"),
    # ---- volume ----
    FactorSpec("volume_ratio_20d", "volume", "量比(20日)", "成交额相对 20 日均量", "daily/daily_basic", ("成交额",), "daily", "basic"),
    FactorSpec("amount_change", "volume", "成交额变化", "近期成交额环比", "daily", ("成交额",), "daily", "basic"),
    # ---- valuation ----
    FactorSpec("pe_ttm", "valuation", "市盈率(TTM)", "PE TTM，越低越好", "daily_basic", ("PE",), "daily", "basic", higher_is_better=False),
    FactorSpec("pb", "valuation", "市净率", "PB，越低越好", "daily_basic", ("PB",), "daily", "basic", higher_is_better=False),
    FactorSpec("dv_ratio", "valuation", "股息率", "近 12 月股息率", "daily_basic", ("dv_ratio",), "daily", "basic", fallback_behavior="skip"),
    FactorSpec("industry_valuation_quantile", "valuation", "行业估值分位", "行业内 PB 分位，越低越好", "computed", ("PB", "行业"), "daily", "basic", higher_is_better=False),
    # ---- quality ----
    FactorSpec("roe", "quality", "ROE", "净资产收益率", "fina_indicator", ("ROE",), "quarterly", "basic"),
    FactorSpec("revenue_growth", "quality", "营收增速", "营业收入同比", "fina_indicator", ("GROWTH",), "quarterly", "basic"),
    FactorSpec("debt_ratio", "quality", "资产负债率", "越低越好", "balancesheet", ("debt_ratio",), "quarterly", "basic", higher_is_better=False, fallback_behavior="skip"),
    # ---- risk ----
    FactorSpec("vol_60d", "risk", "60 日年化波动率", "越低越好", "daily", ("close",), "daily", "basic", higher_is_better=False),
    FactorSpec("max_drawdown_120d", "risk", "120 日最大回撤", "越接近 0 越好", "daily", ("close",), "daily", "basic", higher_is_better=True),
    FactorSpec("turnover_rate", "risk", "换手率", "流动性", "daily_basic", ("成交额",), "daily", "basic", higher_is_better=False),
    FactorSpec("consecutive_limit_down", "risk", "连续跌停", "近 N 日连续跌停次数", "stk_limit/limit_list", ("limit_status",), "daily", "basic+", fallback_behavior="skip"),
    # ---- capital ----
    FactorSpec("capital_flow_main", "capital", "主力资金净流入", "需 moneyflow 权限", "moneyflow", ("net_amount",), "daily", "premium", fallback_behavior="skip"),
    # ---- event (展示，默认不参与打分) ----
    FactorSpec("disclosure_due", "event", "财报临近", "下次披露日临近", "disclosure_date", ("ann_date",), "weekly", "basic+", participates_in_score=False, fallback_behavior="skip"),
    FactorSpec("dividend_event", "event", "分红除权", "近 30 日分红/除权", "dividend", ("ex_date",), "weekly", "basic+", participates_in_score=False, fallback_behavior="skip"),
    FactorSpec("share_float_event", "event", "限售解禁", "近 30 日解禁", "share_float", ("float_date",), "weekly", "basic+", participates_in_score=False, fallback_behavior="skip"),
    FactorSpec("forecast_event", "event", "业绩预告", "近期业绩预告/快报", "forecast/express", ("ann_date",), "weekly", "basic+", participates_in_score=False, fallback_behavior="skip"),
)


BUCKETS: tuple[str, ...] = (
    "trend",
    "momentum",
    "volume",
    "valuation",
    "quality",
    "risk",
    "capital",
    "event",
)

BUCKET_DISPLAY_NAMES: dict[str, str] = {
    "trend": "技术趋势",
    "momentum": "动量",
    "volume": "成交量",
    "valuation": "估值",
    "quality": "财务质量",
    "risk": "风险控制",
    "capital": "资金面",
    "event": "事件",
}


def seed_factor_registry() -> None:
    """初次启动时把默认因子清单写入数据库。已存在的因子不覆盖用户配置。"""
    with session_scope() as session:
        existing: set[str] = {row[0] for row in session.execute(select(FactorDef.factor_name)).all()}
        for spec in DEFAULT_FACTORS:
            if spec.factor_name in existing:
                continue
            session.add(
                FactorDef(
                    factor_name=spec.factor_name,
                    bucket=spec.bucket,
                    display_name=spec.display_name,
                    description=spec.description,
                    tushare_api=spec.tushare_api,
                    required_fields=list(spec.required_fields),
                    refresh_frequency=spec.refresh_frequency,
                    permission_required=spec.permission_required,
                    higher_is_better=spec.higher_is_better,
                    is_available=True,
                    missing_reason=None,
                    fallback_behavior=spec.fallback_behavior,
                    participates_in_score=spec.participates_in_score,
                )
            )


def evaluate_availability(price_cache_df: pd.DataFrame | None, pool_df: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    """对每个因子检查依赖字段是否齐备。返回 factor_name -> {is_available, missing_reason}。

    规则：
    - permission=premium 默认不可用（除非 pool_df 中能看到对应字段）
    - participates_in_score=False 的事件类因子，默认 is_available=False（接口不稳定）
    - basic+ 权限因子，如果依赖字段在 pool_df 中不存在，则不可用
    - daily 价格类因子，依赖 price_cache_df 非空
    """
    availability: dict[str, dict[str, Any]] = {}
    pool_columns: set[str] = set(pool_df.columns.astype(str).tolist()) if pool_df is not None and not pool_df.empty else set()
    price_ok = price_cache_df is not None and not price_cache_df.empty

    for spec in DEFAULT_FACTORS:
        ok = True
        reason: str | None = None

        if spec.permission_required == "premium":
            ok = False
            reason = "需要付费权限（moneyflow 等接口）"
        elif spec.bucket == "event":
            ok = False
            reason = "事件接口未稳定接入，暂不参与打分"
        elif spec.tushare_api in {"daily", "pro_bar/daily"} and not price_ok:
            ok = False
            reason = "价格缓存为空，请先同步行情"
        else:
            for field in spec.required_fields:
                if field == "close":
                    if not price_ok:
                        ok = False
                        reason = "价格缓存缺失 close"
                        break
                elif field == "行业":
                    if "行业" not in pool_columns:
                        ok = False
                        reason = "股票池缓存缺少行业字段"
                        break
                elif field in {"PE", "PB", "ROE", "GROWTH", "成交额", "dv_ratio"}:
                    if pool_columns and field not in pool_columns:
                        ok = False
                        reason = f"股票池缓存缺少 {field}"
                        break
                # 其他字段当前阶段不强制校验
        availability[spec.factor_name] = {
            "is_available": ok,
            "missing_reason": reason,
        }
    return availability


def sync_availability(price_cache_df: pd.DataFrame | None, pool_df: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    """评估可用性并写回数据库。"""
    result = evaluate_availability(price_cache_df, pool_df)
    with session_scope() as session:
        rows = session.execute(select(FactorDef)).scalars().all()
        for row in rows:
            info = result.get(row.factor_name)
            if not info:
                continue
            row.is_available = bool(info["is_available"])
            row.missing_reason = info["missing_reason"]
    return result


def list_factor_defs() -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.execute(select(FactorDef).order_by(FactorDef.bucket, FactorDef.factor_name)).scalars().all()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "factor_name": row.factor_name,
                    "bucket": row.bucket,
                    "bucket_label": BUCKET_DISPLAY_NAMES.get(row.bucket, row.bucket),
                    "display_name": row.display_name,
                    "description": row.description,
                    "tushare_api": row.tushare_api,
                    "required_fields": list(row.required_fields or []),
                    "refresh_frequency": row.refresh_frequency,
                    "permission_required": row.permission_required,
                    "higher_is_better": bool(row.higher_is_better),
                    "is_available": bool(row.is_available),
                    "missing_reason": row.missing_reason,
                    "fallback_behavior": row.fallback_behavior,
                    "participates_in_score": bool(row.participates_in_score),
                }
            )
        return out


def group_by_bucket(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in BUCKETS}
    for row in rows:
        grouped.setdefault(row["bucket"], []).append(row)
    return grouped
