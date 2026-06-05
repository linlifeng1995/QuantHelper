"""交易计划生成：把择时结果 + 风控参数 + 价格特征整合成完整买入计划。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from myquant.factors.buckets import compute_price_factors, normalize_price_discontinuities
from myquant.risk.settings import get_settings as get_risk_settings
from myquant.timing.rules import evaluate_features
from myquant.timing.states import TradingState

from .position_sizing import PositionResult, compute_position
from .stop_loss import StopLossResult, compute_stop_loss


@dataclass
class GeneratedPlan:
    ticker: str
    name: str | None = None
    pool_id: int | None = None
    action: str = "avoid"   # buy / add / hold / reduce / exit / avoid
    trading_state: str | None = None
    confidence: str = "medium"
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    stop_loss: float | None = None
    stop_loss_method: str | None = None
    take_profits: list[dict[str, Any]] = field(default_factory=list)
    risk_reward: float | None = None
    position_pct: float | None = None
    position_shares: int | None = None
    risk_per_trade_pct: float | None = None
    account_capital: float | None = None
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    features_snapshot: dict[str, Any] = field(default_factory=dict)
    valid_until: datetime | None = None
    status: str = "draft"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.valid_until is not None:
            d["valid_until"] = self.valid_until.isoformat()
        return d


# 把择时状态映射成 action / 置信度
_STATE_TO_ACTION = {
    TradingState.BREAKOUT_CONFIRMED.value: ("buy", "high"),
    TradingState.STRONG_WATCH.value: ("buy", "medium"),
    TradingState.PULLBACK_WAIT.value: ("buy", "medium"),
    TradingState.HIGH_RISK.value: ("avoid", "low"),
    TradingState.TREND_BROKEN.value: ("exit", "low"),
    TradingState.DO_NOT_TRADE.value: ("avoid", "low"),
}


def _swing_low(price_cache_df: pd.DataFrame, ticker: str, end_date: str, window: int = 20) -> float | None:
    if ticker not in price_cache_df.columns:
        return None
    px = normalize_price_discontinuities(price_cache_df[[ticker]].loc[: pd.Timestamp(end_date)])
    s = px[ticker].dropna()
    if len(s) < 5:
        return None
    return float(s.tail(window).min())


def _entry_zone(state: str, close: float, ma_20: float | None) -> tuple[float | None, float | None]:
    if state == TradingState.BREAKOUT_CONFIRMED.value:
        return round(close * 0.998, 4), round(close * 1.02, 4)
    if state == TradingState.STRONG_WATCH.value:
        return round(close * 0.98, 4), round(close * 1.01, 4)
    if state == TradingState.PULLBACK_WAIT.value and ma_20:
        return round(min(close, ma_20) * 0.99, 4), round(max(close, ma_20) * 1.01, 4)
    return None, None


def _build_take_profits(entry: float, risk_per_share: float) -> list[dict[str, Any]]:
    if risk_per_share <= 0:
        return []
    t1 = round(entry + 2 * risk_per_share, 4)
    t2 = round(entry + 3 * risk_per_share, 4)
    return [
        {"level": 1, "price": t1, "ratio": 0.5, "label": "盈亏比 2:1，减持半仓"},
        {"level": 2, "price": t2, "ratio": 0.5, "label": "盈亏比 3:1，剩余仓位移动止盈"},
    ]


def generate_plan(
    *,
    ticker: str,
    price_cache_df: pd.DataFrame,
    end_date: str | None = None,
    pool_id: int | None = None,
    name: str | None = None,
    risk_override: dict[str, float] | None = None,
    valid_days: int = 5,
) -> GeneratedPlan:
    """根据价格数据生成单标的交易计划。

    risk_override 可覆盖 ``account_capital`` / ``max_loss_per_trade_pct`` /
    ``max_single_position_pct``；其余默认从 RiskSettings 读取。
    """
    if price_cache_df is None or price_cache_df.empty:
        raise ValueError("price_cache 为空，无法生成计划")
    eff_end = end_date or pd.Timestamp(price_cache_df.index.max()).strftime("%Y-%m-%d")

    table = compute_price_factors(price_cache_df, [ticker], eff_end)
    df = table.df
    feats: dict[str, Any] = {}
    if df is not None and not df.empty:
        rows = df[df["ticker"] == ticker].to_dict(orient="records")
        if rows:
            feats = rows[0]

    timing = evaluate_features(feats)
    action, confidence = _STATE_TO_ACTION.get(timing.state, ("avoid", "low"))

    # 风险设置
    risk = dict(get_risk_settings())
    if risk_override:
        risk.update({k: v for k, v in risk_override.items() if v is not None})
    account_capital = float(risk.get("account_capital") or 0.0)
    max_loss = float(risk.get("max_loss_per_trade_pct") or 1.0)
    max_single = float(risk.get("max_single_position_pct") or 10.0)

    plan = GeneratedPlan(
        ticker=ticker,
        name=name,
        pool_id=pool_id,
        action=action,
        trading_state=timing.state,
        confidence=confidence,
        reasons=list(timing.reasons),
        risks=list(timing.risks),
        features_snapshot=timing.features,
        risk_per_trade_pct=max_loss,
        account_capital=account_capital,
        valid_until=datetime.utcnow() + timedelta(days=valid_days),
    )

    close = feats.get("close")
    ma_20 = feats.get("ma_20")
    ma_60 = feats.get("ma_60")
    if close is None:
        plan.reasons.append("价格数据缺失，无法生成具体计划")
        return plan

    # 非可交易状态：返回带说明但无具体价位的计划
    if action in ("avoid", "exit"):
        if action == "exit":
            plan.reasons.append("已触发离场状态，建议核查持仓并退出")
        else:
            plan.reasons.append("当前不建议建仓，仅观察")
        return plan

    # 计算止损 / 仓位 / 止盈
    swing_low = _swing_low(price_cache_df, ticker, eff_end, window=20)
    try:
        stop: StopLossResult = compute_stop_loss(
            float(close),
            ma_60=float(ma_60) if ma_60 is not None else None,
            swing_low=swing_low,
            fallback_pct=0.08,
        )
    except ValueError as exc:
        plan.reasons.append(f"止损计算失败：{exc}")
        return plan

    low, high = _entry_zone(timing.state, float(close), float(ma_20) if ma_20 is not None else None)
    entry_for_sizing = high if high is not None else float(close)

    try:
        pos: PositionResult = compute_position(
            close=entry_for_sizing,
            stop_loss=stop.price,
            account_capital=account_capital,
            max_loss_per_trade_pct=max_loss,
            max_single_position_pct=max_single,
        )
    except ValueError as exc:
        plan.reasons.append(f"仓位计算失败：{exc}")
        return plan

    risk_per_share = entry_for_sizing - stop.price
    take_profits = _build_take_profits(entry_for_sizing, risk_per_share)
    risk_reward = 2.0 if take_profits else None

    plan.entry_zone_low = low
    plan.entry_zone_high = high
    plan.stop_loss = stop.price
    plan.stop_loss_method = stop.method
    plan.take_profits = take_profits
    plan.risk_reward = risk_reward
    plan.position_pct = pos.position_pct
    plan.position_shares = pos.position_shares
    plan.reasons.append(f"建议止损：{stop.label}")
    plan.reasons.append(pos.label)
    if pos.position_shares == 0:
        plan.confidence = "low"
        plan.reasons.append("按当前风险预算无法建立最小一手仓位（建议增加资金或放宽止损）")
    return plan
