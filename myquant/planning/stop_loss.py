"""止损价计算：基于 MA60 / 摆动低点（近期低）/ 百分比。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StopLossResult:
    price: float
    method: str       # ma60 / swing_low / pct
    label: str
    distance_pct: float  # (close - stop)/close


def _safe(v) -> float | None:
    try:
        x = float(v)
        if x != x:  # NaN
            return None
        return x
    except (TypeError, ValueError):
        return None


def compute_stop_loss(
    close: float,
    *,
    ma_60: float | None = None,
    swing_low: float | None = None,
    fallback_pct: float = 0.08,
) -> StopLossResult:
    """选择 max(MA60, swing_low, close*(1-pct)) 中最贴近的合理止损。

    规则：
      1. 候选：MA60 下方 1%、近 20 日最低点下方 0.5%、close*(1-fallback_pct)
      2. 取低于 close 的最高候选（最贴近止损，最小损失）。
      3. 若全部失败，回退 close*(1-fallback_pct)。
    """
    cl = _safe(close)
    if cl is None or cl <= 0:
        raise ValueError("close 价格无效")
    candidates: list[tuple[float, str, str]] = []
    m60 = _safe(ma_60)
    if m60 is not None and m60 < cl:
        p = round(m60 * 0.99, 4)
        candidates.append((p, "ma60", f"MA60 下方 1%（{p:.2f}）"))
    sl = _safe(swing_low)
    if sl is not None and sl < cl:
        p = round(sl * 0.995, 4)
        candidates.append((p, "swing_low", f"近 20 日低点下方 0.5%（{p:.2f}）"))
    p_pct = round(cl * (1 - fallback_pct), 4)
    candidates.append((p_pct, "pct", f"成本下方 {fallback_pct:.0%}（{p_pct:.2f}）"))

    # 选最高的（亏损最小）作为初始止损
    best = max(candidates, key=lambda x: x[0])
    price, method, label = best
    distance = (cl - price) / cl
    return StopLossResult(price=price, method=method, label=label, distance_pct=distance)
