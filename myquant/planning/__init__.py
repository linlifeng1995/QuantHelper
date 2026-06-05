"""交易计划生成模块（B2）。"""
from .generator import generate_plan, GeneratedPlan
from .stop_loss import compute_stop_loss, StopLossResult
from .position_sizing import compute_position, PositionResult

__all__ = [
    "generate_plan",
    "GeneratedPlan",
    "compute_stop_loss",
    "StopLossResult",
    "compute_position",
    "PositionResult",
]
