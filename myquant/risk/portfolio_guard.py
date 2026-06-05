"""组合风控：基于活跃交易计划与 RiskSettings 计算总体暴露与风险预警。

约束维度：
1. 单一标的仓位上限（RiskSettings.max_single_position_pct）
2. 市场状态总仓上限（cap_strong / cap_neutral / cap_weak）
3. 行业暴露上限（max_industry_exposure_pct）—— 当前未接入行业数据，预留位

调用方：
- 风控页/前端通过 GET /api/risk/portfolio 获取概览
- 计划生成器可调用 evaluate_new_plan 提示是否突破限额
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from myquant.planning.dao import list_plans
from myquant.risk.market_regime import RegimeResult, classify_regime
from myquant.risk.settings import get_settings

ACTIVE_STATUSES: tuple[str, ...] = ("draft", "active")
EXCLUDE_ACTIONS: tuple[str, ...] = ("exit", "avoid")


@dataclass
class PortfolioExposure:
    total_position_pct: float
    plan_count: int
    by_ticker: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_position_pct": self.total_position_pct,
            "plan_count": self.plan_count,
            "by_ticker": self.by_ticker,
        }


def _collect_active_plans() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for status in ACTIVE_STATUSES:
        rows.extend(list_plans(status=status, limit=500))
    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        rid = r.get("id")
        if rid in seen:
            continue
        if rid is not None:
            seen.add(rid)
        if r.get("action") in EXCLUDE_ACTIONS:
            continue
        if r.get("position_pct") is None:
            continue
        out.append(r)
    return out


def compute_exposure(plans: list[dict[str, Any]] | None = None) -> PortfolioExposure:
    rows = plans if plans is not None else _collect_active_plans()
    total = 0.0
    by_ticker: dict[str, dict[str, Any]] = {}
    for r in rows:
        pct = float(r.get("position_pct") or 0.0)
        total += pct
        tk = str(r.get("ticker"))
        existing = by_ticker.get(tk)
        if existing is None:
            by_ticker[tk] = {
                "ticker": tk,
                "name": r.get("name"),
                "position_pct": pct,
                "position_shares": r.get("position_shares") or 0,
                "plan_ids": [r.get("id")],
                "status_list": [r.get("status")],
            }
        else:
            existing["position_pct"] = round(existing["position_pct"] + pct, 4)
            existing["position_shares"] = (existing["position_shares"] or 0) + (r.get("position_shares") or 0)
            existing["plan_ids"].append(r.get("id"))
            existing["status_list"].append(r.get("status"))
    return PortfolioExposure(
        total_position_pct=round(total, 4),
        plan_count=len(rows),
        by_ticker=sorted(by_ticker.values(), key=lambda x: -x["position_pct"]),
    )


def _regime_cap(regime: str, settings: dict[str, Any]) -> float:
    if regime == "strong":
        return float(settings.get("cap_strong_market_pct") or 80.0)
    if regime == "weak":
        return float(settings.get("cap_weak_market_pct") or 20.0)
    return float(settings.get("cap_neutral_market_pct") or 50.0)


def build_warnings(
    exposure: PortfolioExposure,
    regime: RegimeResult,
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    single_cap = float(settings.get("max_single_position_pct") or 10.0)
    total_cap = _regime_cap(regime.regime, settings)

    if exposure.total_position_pct > total_cap:
        warnings.append({
            "level": "error",
            "code": "TOTAL_OVER_REGIME_CAP",
            "message": (
                f"总仓位 {exposure.total_position_pct:.1f}% 超过当前 {regime.label} "
                f"总仓上限 {total_cap:.0f}%"
            ),
        })
    elif total_cap - exposure.total_position_pct < 5.0:
        warnings.append({
            "level": "warn",
            "code": "TOTAL_NEAR_CAP",
            "message": (
                f"总仓位 {exposure.total_position_pct:.1f}% 接近 {regime.label} "
                f"上限 {total_cap:.0f}%，新建仓需谨慎"
            ),
        })

    for item in exposure.by_ticker:
        if item["position_pct"] > single_cap + 0.5:
            warnings.append({
                "level": "warn",
                "code": "SINGLE_OVER_CAP",
                "message": (
                    f"{item['ticker']} 仓位 {item['position_pct']:.1f}% 超过单一标的上限 {single_cap:.0f}%"
                ),
            })

    return warnings


def portfolio_summary(price_cache_df: pd.DataFrame | None) -> dict[str, Any]:
    settings = get_settings()
    if price_cache_df is None:
        regime = RegimeResult("unknown", "未知", "default", 0.0, 0, None)
    else:
        regime = classify_regime(price_cache_df)
    exposure = compute_exposure()
    regime_cap = _regime_cap(regime.regime, settings)
    warnings = build_warnings(exposure, regime, settings)
    return {
        "regime": regime.to_dict(),
        "exposure": exposure.to_dict(),
        "caps": {
            "single_position_pct": float(settings.get("max_single_position_pct") or 10.0),
            "industry_pct": float(settings.get("max_industry_exposure_pct") or 25.0),
            "regime_total_pct": regime_cap,
        },
        "remaining_pct": round(max(regime_cap - exposure.total_position_pct, 0.0), 2),
        "warnings": warnings,
    }


def evaluate_new_plan(
    candidate_position_pct: float,
    ticker: str,
    price_cache_df: pd.DataFrame | None,
) -> dict[str, Any]:
    """对单一候选计划，给出是否触发风控限制。"""
    settings = get_settings()
    if price_cache_df is None:
        regime = RegimeResult("unknown", "未知", "default", 0.0, 0, None)
    else:
        regime = classify_regime(price_cache_df)
    exposure = compute_exposure()
    regime_cap = _regime_cap(regime.regime, settings)
    single_cap = float(settings.get("max_single_position_pct") or 10.0)
    existing_for_ticker = next((x for x in exposure.by_ticker if x["ticker"] == ticker), None)
    existing_pct = existing_for_ticker["position_pct"] if existing_for_ticker else 0.0
    new_total = exposure.total_position_pct + candidate_position_pct
    new_single = existing_pct + candidate_position_pct
    breaches: list[str] = []
    if new_total > regime_cap:
        breaches.append(f"加上该计划后总仓位 {new_total:.1f}% 超过 {regime.label} 上限 {regime_cap:.0f}%")
    if new_single > single_cap + 0.5:
        breaches.append(f"加上该计划后 {ticker} 仓位 {new_single:.1f}% 超过单一标的上限 {single_cap:.0f}%")
    return {
        "regime": regime.to_dict(),
        "candidate_position_pct": candidate_position_pct,
        "current_total_pct": exposure.total_position_pct,
        "projected_total_pct": round(new_total, 2),
        "regime_total_pct": regime_cap,
        "single_cap_pct": single_cap,
        "ok": not breaches,
        "breaches": breaches,
    }
