"""股票池管理 API。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from myquant.pools.dao import (
    POOL_TYPE_LABELS,
    bulk_upsert_items,
    clear_pool,
    create_pool,
    delete_pool,
    get_pool,
    list_pools,
    remove_item,
    review_item,
    update_pool,
    upsert_item,
)

from ._utils import sanitize

router = APIRouter(prefix="/api/pools", tags=["pools"])


class PoolCreateRequest(BaseModel):
    name: str
    pool_type: str = Field(default="custom")
    description: str = ""
    is_default: bool = False


class PoolUpdateRequest(BaseModel):
    name: str | None = None
    pool_type: str | None = None
    description: str | None = None


class PoolItemUpsertRequest(BaseModel):
    ticker: str
    name: str | None = None
    industry: str | None = None
    score: float | None = None
    reason: str | None = None
    snapshot: dict[str, Any] | None = None
    tags: list[str] | None = None
    priority: int | None = None
    status: str | None = None
    note: str | None = None


class PoolItemsBulkRequest(BaseModel):
    items: list[dict[str, Any]]


class PoolItemReviewRequest(BaseModel):
    current_score: float | None = None
    snapshot: dict[str, Any] | None = None


@router.get("/types")
def get_pool_types() -> dict[str, Any]:
    return {"types": [{"value": k, "label": v} for k, v in POOL_TYPE_LABELS.items()]}


@router.get("")
def get_pools() -> dict[str, Any]:
    return sanitize({"pools": list_pools()})


@router.get("/{pool_id}")
def get_pool_detail(pool_id: int) -> dict[str, Any]:
    pool = get_pool(pool_id)
    if not pool:
        raise HTTPException(status_code=404, detail="股票池不存在")
    return sanitize(pool)


@router.post("")
def create_pool_endpoint(request: PoolCreateRequest) -> dict[str, Any]:
    try:
        pool = create_pool(
            name=request.name,
            pool_type=request.pool_type,
            description=request.description,
            is_default=request.is_default,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return sanitize(pool)


@router.patch("/{pool_id}")
def update_pool_endpoint(pool_id: int, request: PoolUpdateRequest) -> dict[str, Any]:
    try:
        pool = update_pool(
            pool_id,
            name=request.name,
            pool_type=request.pool_type,
            description=request.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return sanitize(pool)


@router.delete("/{pool_id}")
def delete_pool_endpoint(pool_id: int) -> dict[str, Any]:
    try:
        delete_pool(pool_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "deleted"}


@router.post("/{pool_id}/items")
def add_pool_item(pool_id: int, request: PoolItemUpsertRequest) -> dict[str, Any]:
    try:
        item = upsert_item(
            pool_id,
            request.ticker,
            name=request.name,
            industry=request.industry,
            score=request.score,
            reason=request.reason,
            snapshot=request.snapshot,
            tags=request.tags,
            priority=request.priority,
            status=request.status,
            note=request.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return sanitize({"item": item})


@router.post("/{pool_id}/items/bulk")
def bulk_add_pool_items(pool_id: int, request: PoolItemsBulkRequest) -> dict[str, Any]:
    try:
        items = bulk_upsert_items(pool_id, request.items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return sanitize({"items": items, "added": len(items)})


@router.delete("/{pool_id}/items/{ticker}")
def delete_pool_item(pool_id: int, ticker: str) -> dict[str, Any]:
    remove_item(pool_id, ticker)
    return {"status": "deleted"}


@router.delete("/{pool_id}/items")
def clear_pool_items(pool_id: int) -> dict[str, Any]:
    clear_pool(pool_id)
    return {"status": "cleared"}


@router.post("/{pool_id}/items/{ticker}/review")
def review_pool_item(pool_id: int, ticker: str, request: PoolItemReviewRequest) -> dict[str, Any]:
    try:
        item = review_item(pool_id, ticker, current_score=request.current_score, snapshot=request.snapshot)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return sanitize({"item": item})
