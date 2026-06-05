"""共享工具：复用 api.main.sanitize / dataframe_records 逻辑，避免循环依赖。"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, tuple):
        return [sanitize(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        try:
            return None if not np.isfinite(value) else float(value)
        except (TypeError, ValueError):
            return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value
