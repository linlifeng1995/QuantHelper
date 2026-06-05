"""组合情景模拟。

给定当前活跃 / 草稿交易计划，对每只持仓施加 ``shock_pct`` 价格冲击（也可按
ticker 自定义覆盖），决定是否触发止损，并把每只标的的盈亏按 ``position_pct``
（占账户百分比）汇总成组合 P&L。

仅依赖价格缓存（无需财务快照）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import pandas as pd

from myquant.planning.dao import list_plans

ACTIVE_STATUSES: tuple[str, ...] = ("draft", "active")
EXCLUDE_ACTIONS: tuple[str, ...] = ("exit", "avoid")


DEFAULT_SCENARIOS: list[dict[str, Any]] = [
    {"name": "大涨 +10%", "shock_pct": 0.10},
    {"name": "上涨 +5%", "shock_pct": 0.05},
    {"name": "震荡 0%", "shock_pct": 0.0},
    {"name": "回调 -5%", "shock_pct": -0.05},
    {"name": "下跌 -10%", "shock_pct": -0.10},
    {"name": "暴跌 -15%", "shock_pct": -0.15},
]


@dataclass
class ScenarioInput:
    name: str
    shock_pct: float = 0.0
    overrides: dict[str, float] = field(default_factory=dict)  # ticker -> shock_pct

    def shock_for(self, ticker: str) -> float:
        if ticker in self.overrides:
            return float(self.overrides[ticker])
        return float(self.shock_pct)


def _collect_plans(
    statuses: Iterable[str] = ACTIVE_STATUSES,
    plan_ids: Iterable[int] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for status in statuses:
        rows.extend(list_plans(status=status, limit=500))
    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    id_filter = set(int(x) for x in plan_ids) if plan_ids is not None else None
    for r in rows:
        rid = r.get("id")
        if rid in seen:
            continue
        if rid is not None:
            seen.add(rid)
        if id_filter is not None and rid not in id_filter:
            continue
        if r.get("action") in EXCLUDE_ACTIONS:
            continue
        if r.get("position_pct") is None:
            continue
        out.append(r)
    return out


def _resolve_current_price(
    plan: dict[str, Any],
    price_cache: pd.DataFrame | None,
) -> tuple[float | None, str]:
    """返回 (price, source)；source ∈ {'cache', 'entry_mid', 'unavailable'}。"""
    ticker = str(plan.get("ticker") or "").strip()
    if price_cache is not None and not price_cache.empty and ticker in price_cache.columns:
        series = price_cache[ticker].dropna()
        if len(series) > 0:
            return float(series.iloc[-1]), "cache"
    low = plan.get("entry_zone_low")
    high = plan.get("entry_zone_high")
    if low is not None and high is not None:
        try:
            return float((float(low) + float(high)) / 2.0), "entry_mid"
        except (TypeError, ValueError):
            pass
    if low is not None:
        try:
            return float(low), "entry_mid"
        except (TypeError, ValueError):
            pass
    return None, "unavailable"


def _simulate_single_plan(
    plan: dict[str, Any],
    shock: float,
    current_price: float | None,
    apply_stop_loss: bool,
) -> dict[str, Any]:
    pos_pct = float(plan.get("position_pct") or 0.0)
    stop = plan.get("stop_loss")
    try:
        stop_loss = float(stop) if stop is not None else None
    except (TypeError, ValueError):
        stop_loss = None

    stopped = False
    realized_return: float  # 单股相对当前价的收益率（保证金 / 持仓口径）
    new_price = None
    if current_price is None or current_price <= 0:
        realized_return = float(shock)  # 无可用价格时退化为按 shock 计算
    else:
        new_price = current_price * (1.0 + shock)
        # 区间内是否曾触及止损：当 shock<0 时，若 stop_loss>=new_price 且 stop_loss<=current_price → 触发
        if (
            apply_stop_loss
            and stop_loss is not None
            and stop_loss > 0
            and shock < 0
            and new_price <= stop_loss <= current_price
        ):
            stopped = True
            realized_return = stop_loss / current_price - 1.0
        else:
            realized_return = new_price / current_price - 1.0

    contribution_pct = realized_return * pos_pct  # 对账户贡献，单位 % 点（pos_pct 已是 0-100）

    return {
        "plan_id": plan.get("id"),
        "ticker": plan.get("ticker"),
        "name": plan.get("name"),
        "position_pct": pos_pct,
        "current_price": current_price,
        "stop_loss": stop_loss,
        "new_price": new_price,
        "shock_pct": shock,
        "stopped": stopped,
        "stock_return": realized_return,
        "account_contribution_pct": contribution_pct,
    }


def simulate_portfolio(
    scenarios: list[ScenarioInput] | None = None,
    *,
    plan_ids: Iterable[int] | None = None,
    include_drafts: bool = True,
    apply_stop_loss: bool = True,
    price_cache: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """运行组合情景模拟。

    Args:
        scenarios: 若为空使用默认 6 档（+10%~-15%）。
        plan_ids: 可选筛选指定 plan_id 集合。
        include_drafts: 是否包含 status=draft 的计划。
        apply_stop_loss: 是否在跌破止损时按 stop_loss 价结清损失。
        price_cache: 价格缓存 DataFrame；为空时尝试从 web_app.load_price_cache 读取。

    Returns:
        ``{as_of, plans_count, total_position_pct, plans:[...meta...],
            scenarios:[{name, shock_pct, portfolio_pnl_pct, stops_triggered,
                        worst_ticker, best_ticker, by_ticker:[...]}]}``
    """
    if scenarios is None or len(scenarios) == 0:
        scenarios = [ScenarioInput(name=s["name"], shock_pct=float(s["shock_pct"])) for s in DEFAULT_SCENARIOS]

    statuses = ACTIVE_STATUSES if include_drafts else ("active",)
    plans = _collect_plans(statuses=statuses, plan_ids=plan_ids)

    if price_cache is None:
        try:
            import web_app  # 延迟导入避免循环

            price_cache = web_app.load_price_cache()
        except Exception:
            price_cache = None

    # 解析持仓元信息
    plan_meta: list[dict[str, Any]] = []
    total_pos_pct = 0.0
    as_of = None
    if price_cache is not None and not price_cache.empty:
        as_of = str(price_cache.index.max().date())

    for p in plans:
        price, source = _resolve_current_price(p, price_cache)
        pos_pct = float(p.get("position_pct") or 0.0)
        total_pos_pct += pos_pct
        plan_meta.append(
            {
                "plan_id": p.get("id"),
                "ticker": p.get("ticker"),
                "name": p.get("name"),
                "status": p.get("status"),
                "action": p.get("action"),
                "position_pct": pos_pct,
                "current_price": price,
                "price_source": source,
                "stop_loss": p.get("stop_loss"),
                "entry_zone_low": p.get("entry_zone_low"),
                "entry_zone_high": p.get("entry_zone_high"),
            }
        )

    # 逐情景模拟
    scenario_results: list[dict[str, Any]] = []
    for sc in scenarios:
        by_ticker: list[dict[str, Any]] = []
        portfolio_pnl = 0.0
        stops = 0
        for p, meta in zip(plans, plan_meta, strict=True):
            shock = sc.shock_for(str(p.get("ticker") or ""))
            row = _simulate_single_plan(p, shock, meta["current_price"], apply_stop_loss)
            by_ticker.append(row)
            portfolio_pnl += row["account_contribution_pct"]
            if row["stopped"]:
                stops += 1
        worst = min(by_ticker, key=lambda r: r["account_contribution_pct"]) if by_ticker else None
        best = max(by_ticker, key=lambda r: r["account_contribution_pct"]) if by_ticker else None
        scenario_results.append(
            {
                "name": sc.name,
                "shock_pct": sc.shock_pct,
                "overrides": dict(sc.overrides),
                "portfolio_pnl_pct": round(portfolio_pnl, 4),
                "stops_triggered": stops,
                "worst_ticker": worst["ticker"] if worst else None,
                "worst_contribution_pct": round(worst["account_contribution_pct"], 4) if worst else None,
                "best_ticker": best["ticker"] if best else None,
                "best_contribution_pct": round(best["account_contribution_pct"], 4) if best else None,
                "by_ticker": by_ticker,
            }
        )

    return {
        "as_of": as_of,
        "plans_count": len(plans),
        "total_position_pct": round(total_pos_pct, 4),
        "apply_stop_loss": apply_stop_loss,
        "include_drafts": include_drafts,
        "plans": plan_meta,
        "scenarios": scenario_results,
    }


def simulate_plan_sensitivity(
    plan_id: int,
    *,
    shock_start: float = -0.20,
    shock_end: float = 0.20,
    shock_step: float = 0.01,
    apply_stop_loss: bool = True,
    price_cache: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """对单个 plan 在 [shock_start, shock_end] 范围内按 step 生成灵敏度曲线。

    返回 ``{plan, current_price, price_source, stop_loss, stop_trigger_shock,
    break_even_shock, take_profits:[{level, price, ratio, shock_pct}],
    points:[{shock_pct, new_price, stopped, stock_return, account_contribution_pct}]}``。
    """
    if shock_step <= 0:
        raise ValueError("shock_step 必须 > 0")
    if shock_end <= shock_start:
        raise ValueError("shock_end 必须 > shock_start")
    span = shock_end - shock_start
    n = int(round(span / shock_step)) + 1
    if n > 501:
        raise ValueError(f"采样点数过多 ({n})，请增大 step 或缩小区间")

    # 加载 plan（不限 status，避免 active/draft 之外的计划无法分析）
    rows: list[dict[str, Any]] = []
    for status in ("draft", "active", "executed", "cancelled", "expired"):
        rows.extend(list_plans(status=status, limit=500))
    plan: dict[str, Any] | None = next((r for r in rows if int(r.get("id") or 0) == int(plan_id)), None)
    if plan is None:
        raise ValueError(f"plan_id={plan_id} 不存在")

    if price_cache is None:
        try:
            import web_app  # 延迟导入

            price_cache = web_app.load_price_cache()
        except Exception:
            price_cache = None

    current_price, source = _resolve_current_price(plan, price_cache)
    stop = plan.get("stop_loss")
    try:
        stop_loss = float(stop) if stop is not None else None
    except (TypeError, ValueError):
        stop_loss = None

    # 采样
    points: list[dict[str, Any]] = []
    break_even_shock: float | None = None
    prev_contrib: float | None = None
    prev_shock: float | None = None
    for i in range(n):
        shock = shock_start + i * shock_step
        row = _simulate_single_plan(plan, shock, current_price, apply_stop_loss)
        points.append(
            {
                "shock_pct": round(shock, 6),
                "new_price": row["new_price"],
                "stopped": row["stopped"],
                "stock_return": round(row["stock_return"], 6),
                "account_contribution_pct": round(row["account_contribution_pct"], 6),
            }
        )
        # 检测 contribution 零交叉
        if prev_contrib is not None and prev_shock is not None and break_even_shock is None:
            if (prev_contrib <= 0 <= row["account_contribution_pct"]) or (
                prev_contrib >= 0 >= row["account_contribution_pct"]
            ):
                denom = row["account_contribution_pct"] - prev_contrib
                if abs(denom) > 1e-12:
                    t = -prev_contrib / denom
                    break_even_shock = round(prev_shock + t * (shock - prev_shock), 6)
                else:
                    break_even_shock = round(shock, 6)
        prev_contrib = row["account_contribution_pct"]
        prev_shock = shock

    # 止损阈值（解析）：shock = stop_loss/current_price - 1
    stop_trigger_shock: float | None = None
    if (
        apply_stop_loss
        and stop_loss is not None
        and stop_loss > 0
        and current_price is not None
        and current_price > 0
        and stop_loss < current_price
    ):
        stop_trigger_shock = round(stop_loss / current_price - 1.0, 6)

    # 止盈点对应 shock
    tp_out: list[dict[str, Any]] = []
    if current_price and current_price > 0:
        for tp in plan.get("take_profits") or []:
            price = tp.get("price")
            try:
                p = float(price) if price is not None else None
            except (TypeError, ValueError):
                p = None
            if p is None or p <= 0:
                continue
            tp_out.append(
                {
                    "level": tp.get("level"),
                    "price": p,
                    "ratio": tp.get("ratio"),
                    "shock_pct": round(p / current_price - 1.0, 6),
                }
            )

    return {
        "plan_id": int(plan_id),
        "ticker": plan.get("ticker"),
        "name": plan.get("name"),
        "status": plan.get("status"),
        "action": plan.get("action"),
        "position_pct": plan.get("position_pct"),
        "current_price": current_price,
        "price_source": source,
        "stop_loss": stop_loss,
        "entry_zone_low": plan.get("entry_zone_low"),
        "entry_zone_high": plan.get("entry_zone_high"),
        "apply_stop_loss": apply_stop_loss,
        "shock_start": shock_start,
        "shock_end": shock_end,
        "shock_step": shock_step,
        "stop_trigger_shock": stop_trigger_shock,
        "break_even_shock": break_even_shock,
        "take_profits": tp_out,
        "points": points,
    }
