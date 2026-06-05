"""6 种择时状态枚举及前端展示元数据。"""
from __future__ import annotations

from enum import Enum


class TradingState(str, Enum):
    BREAKOUT_CONFIRMED = "breakout_confirmed"
    STRONG_WATCH = "strong_watch"
    PULLBACK_WAIT = "pullback_wait"
    TREND_BROKEN = "trend_broken"
    HIGH_RISK = "high_risk"
    DO_NOT_TRADE = "do_not_trade"


STATE_LABELS: dict[str, str] = {
    TradingState.BREAKOUT_CONFIRMED.value: "突破确认",
    TradingState.STRONG_WATCH.value: "强势观察",
    TradingState.PULLBACK_WAIT.value: "回踩等待",
    TradingState.TREND_BROKEN.value: "趋势破位",
    TradingState.HIGH_RISK.value: "高位风险",
    TradingState.DO_NOT_TRADE.value: "暂不交易",
}

# 对应 antd Tag color
STATE_COLORS: dict[str, str] = {
    TradingState.BREAKOUT_CONFIRMED.value: "green",
    TradingState.STRONG_WATCH.value: "blue",
    TradingState.PULLBACK_WAIT.value: "gold",
    TradingState.TREND_BROKEN.value: "volcano",
    TradingState.HIGH_RISK.value: "magenta",
    TradingState.DO_NOT_TRADE.value: "default",
}

STATE_DESCRIPTIONS: dict[str, str] = {
    TradingState.BREAKOUT_CONFIRMED.value: "已突破近 20 日新高且趋势向上，可考虑顺势进场",
    TradingState.STRONG_WATCH.value: "多头排列趋势完好，等待回踩或突破信号",
    TradingState.PULLBACK_WAIT.value: "趋势向上但已回踩到 MA20 附近，等待企稳信号",
    TradingState.TREND_BROKEN.value: "跌破关键均线，趋势走坏，不建议进场",
    TradingState.HIGH_RISK.value: "短期涨幅过大、波动率高或回撤剧烈，追高风险大",
    TradingState.DO_NOT_TRADE.value: "无明确信号或数据不足，等待形态明朗",
}
