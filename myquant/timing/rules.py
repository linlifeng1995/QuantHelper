"""基于价格特征推导择时状态的规则引擎。

特征字段来源：myquant.factors.buckets.compute_price_factors。
仅使用 price-only 字段（不依赖成交量）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .states import STATE_COLORS, STATE_DESCRIPTIONS, STATE_LABELS, TradingState


@dataclass
class TimingResult:
    state: str
    label: str
    color: str
    description: str
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "label": self.label,
            "color": self.color,
            "description": self.description,
            "reasons": list(self.reasons),
            "risks": list(self.risks),
            "features": dict(self.features),
        }


def _f(v: Any) -> float | None:
    """安全转换为 float，NaN/None 返回 None。"""
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return x


def _result(state: TradingState, reasons: list[str], risks: list[str], feat_view: dict[str, Any]) -> TimingResult:
    return TimingResult(
        state=state.value,
        label=STATE_LABELS[state.value],
        color=STATE_COLORS[state.value],
        description=STATE_DESCRIPTIONS[state.value],
        reasons=reasons,
        risks=risks,
        features=feat_view,
    )


def evaluate_features(features: dict[str, Any]) -> TimingResult:
    """根据单个标的的价格特征 dict 输出择时结果。

    features 取自 ``compute_price_factors`` 的某一行，常用字段：
      close / ma_20 / ma_60 / ma_120 / ma_alignment / breakout_20d /
      trend_slope_60d / dist_52w_high / vol_60d / max_drawdown_120d /
      ret_5d / ret_20d / ret_60d / momentum_accel
    """
    close = _f(features.get("close"))
    ma20 = _f(features.get("ma_20"))
    ma60 = _f(features.get("ma_60"))
    ma120 = _f(features.get("ma_120"))
    align = _f(features.get("ma_alignment")) or 0.0
    slope60 = _f(features.get("trend_slope_60d"))
    brk20 = _f(features.get("breakout_20d")) or 0.0
    brk60 = _f(features.get("breakout_60d")) or 0.0
    dist_high = _f(features.get("dist_52w_high"))  # 通常 <=0，例如 -0.12 表示距 52w 高 12%
    vol60 = _f(features.get("vol_60d"))
    mdd = _f(features.get("max_drawdown_120d"))
    ret_5 = _f(features.get("ret_5d"))
    ret_20 = _f(features.get("ret_20d"))

    feat_view = {
        "close": close,
        "ma_20": ma20,
        "ma_60": ma60,
        "ma_120": ma120,
        "ma_alignment": align,
        "breakout_20d": brk20,
        "breakout_60d": brk60,
        "trend_slope_60d": slope60,
        "dist_52w_high": dist_high,
        "vol_60d": vol60,
        "max_drawdown_120d": mdd,
        "ret_5d": ret_5,
        "ret_20d": ret_20,
    }

    # 风险提示（不一定触发独立状态，但会附加）
    risks: list[str] = []
    if vol60 is not None and vol60 > 0.5:
        risks.append(f"年化波动率高 ({vol60:.0%})")
    if mdd is not None and mdd < -0.25:
        risks.append(f"近 120 日最大回撤 {mdd:.0%}")
    if ret_5 is not None and ret_5 > 0.15:
        risks.append(f"近 5 日急涨 {ret_5:.0%}")

    # 1) 数据不足 -> 暂不交易
    if close is None or ma20 is None or ma60 is None:
        return _result(
            TradingState.DO_NOT_TRADE,
            reasons=["关键均线数据不足，无法判断"],
            risks=risks,
            feat_view=feat_view,
        )

    # 2) 趋势破位：跌破 MA60 视为关键趋势破坏
    if close < ma60:
        reasons = [f"收盘 {close:.2f} 已跌破 MA60 ({ma60:.2f})"]
        if ma20 < ma60:
            reasons.append("MA20 已下穿 MA60，趋势走坏")
        return _result(TradingState.TREND_BROKEN, reasons, risks, feat_view)
    if ma20 < ma60 and (slope60 is None or slope60 <= 0):
        return _result(
            TradingState.TREND_BROKEN,
            reasons=[f"MA20 ({ma20:.2f}) 低于 MA60 ({ma60:.2f}) 且趋势斜率走弱"],
            risks=risks,
            feat_view=feat_view,
        )

    # 3) 高位风险：偏离 MA20 过远 / 波动过大 / 回撤过深
    dist_above_ma20 = (close - ma20) / ma20 if ma20 else None
    high_risk_reasons: list[str] = []
    if dist_above_ma20 is not None and dist_above_ma20 > 0.15:
        high_risk_reasons.append(f"收盘高于 MA20 达 {dist_above_ma20:.0%}，追高风险大")
    if vol60 is not None and vol60 > 0.6:
        high_risk_reasons.append(f"60 日波动率 {vol60:.0%} 偏高")
    if mdd is not None and mdd < -0.35:
        high_risk_reasons.append(f"120 日最大回撤 {mdd:.0%} 过深")
    if high_risk_reasons:
        return _result(TradingState.HIGH_RISK, high_risk_reasons, risks, feat_view)

    # 4) 突破确认：刚突破 20 日新高 + 趋势向上
    if brk20 >= 1.0 and close > ma20 and ma20 >= ma60 and (slope60 is None or slope60 >= 0):
        reasons = [f"突破 20 日新高（收盘 {close:.2f}）"]
        if brk60 >= 1.0:
            reasons.append("同时突破 60 日新高")
        if align >= 1.0:
            reasons.append("均线多头排列 (close>MA20>MA60>MA120)")
        return _result(TradingState.BREAKOUT_CONFIRMED, reasons, risks, feat_view)

    # 5) 回踩等待：趋势向上但已回到 MA20 附近 (±5%)
    if dist_above_ma20 is not None and -0.05 <= dist_above_ma20 <= 0.03 and ma20 >= ma60:
        reasons = [f"价格回到 MA20 附近（偏离 {dist_above_ma20:+.1%}），等待企稳"]
        if slope60 is not None and slope60 > 0:
            reasons.append("60 日趋势斜率仍向上")
        return _result(TradingState.PULLBACK_WAIT, reasons, risks, feat_view)

    # 6) 强势观察：多头排列 + 趋势向上
    if close > ma20 >= ma60 and (slope60 is None or slope60 > 0):
        reasons = [f"多头排列 (close {close:.2f} > MA20 {ma20:.2f} ≥ MA60 {ma60:.2f})"]
        if align >= 1.0 and ma120 is not None:
            reasons.append(f"MA60 ≥ MA120 ({ma120:.2f})，长期趋势完好")
        if dist_high is not None and dist_high > -0.05:
            reasons.append(f"距 52 周高仅 {dist_high:.1%}")
        return _result(TradingState.STRONG_WATCH, reasons, risks, feat_view)

    # 7) 兜底
    return _result(
        TradingState.DO_NOT_TRADE,
        reasons=["无明确信号，等待形态明朗"],
        risks=risks,
        feat_view=feat_view,
    )
