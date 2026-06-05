"""推荐关注 API。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from myquant.recommend import get_all_industries, recommend

from ._utils import sanitize

router = APIRouter(prefix="/api/recommend", tags=["recommend"])


@router.get("/industries")
def get_industries() -> dict[str, Any]:
    """返回 pool_cache 中所有可用行业列表，供前端行业筛选下拉使用。"""
    return {"industries": get_all_industries()}


@router.get("")
def get_recommend(
    pool_id: list[int] | None = Query(default=None),
    end_date: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    market_wide: bool = Query(default=False, description="全市场扫描模式（结果带 5 分钟缓存）"),
    industries: list[str] | None = Query(default=None, description="行业过滤，多选；为空则不过滤"),
) -> dict[str, Any]:
    try:
        from web_app import load_price_cache  # type: ignore

        cache_df = load_price_cache()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"price_cache 不可用：{exc}") from exc

    if cache_df is None or cache_df.empty:
        raise HTTPException(status_code=503, detail="price_cache 为空，请先更新行情数据")

    pool_ids = pool_id if pool_id else None
    return sanitize(recommend(
        cache_df,
        pool_ids=pool_ids,
        end_date=end_date,
        limit_per_group=limit,
        market_wide=market_wide,
        industries=industries if industries else None,
    ))
