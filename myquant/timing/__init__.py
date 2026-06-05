"""Trading state engine: 把 6 种择时状态从价格特征中推导出来。"""
from .states import TradingState, STATE_LABELS, STATE_COLORS, STATE_DESCRIPTIONS
from .rules import evaluate_features, TimingResult
from .calculator import (
    evaluate_ticker,
    evaluate_tickers,
    evaluate_pool,
)

__all__ = [
    "TradingState",
    "STATE_LABELS",
    "STATE_COLORS",
    "STATE_DESCRIPTIONS",
    "evaluate_features",
    "TimingResult",
    "evaluate_ticker",
    "evaluate_tickers",
    "evaluate_pool",
]
