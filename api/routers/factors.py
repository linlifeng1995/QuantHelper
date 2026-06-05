"""Factor Registry API。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

import web_app
from myquant.factors.registry import (
    BUCKET_DISPLAY_NAMES,
    BUCKETS,
    group_by_bucket,
    list_factor_defs,
    sync_availability,
)

from ._utils import sanitize

router = APIRouter(prefix="/api/factors", tags=["factors"])


@router.get("")
def get_factor_defs(refresh: bool = False) -> dict[str, Any]:
    """返回因子注册表。refresh=true 时基于当前缓存重新评估可用性。"""
    if refresh:
        price_cache = web_app.load_price_cache()
        pool_cache = web_app.load_pool_cache()
        sync_availability(price_cache, pool_cache)
    defs = list_factor_defs()
    grouped = group_by_bucket(defs)
    available_buckets = {bucket: any(d["is_available"] and d["participates_in_score"] for d in items) for bucket, items in grouped.items()}
    return sanitize(
        {
            "factors": defs,
            "buckets": [
                {
                    "bucket": bucket,
                    "label": BUCKET_DISPLAY_NAMES[bucket],
                    "factors": grouped.get(bucket, []),
                    "available": available_buckets.get(bucket, False),
                }
                for bucket in BUCKETS
            ],
        }
    )
