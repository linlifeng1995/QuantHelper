"""股票池 CRUD DAO。"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import session_scope
from ..db.models import Pool, PoolItem


POOL_TYPE_LABELS: dict[str, str] = {
    "short_term": "短线观察池",
    "mid_term": "中线趋势池",
    "value": "低估值价值池",
    "dividend": "高股息防守池",
    "theme": "主题池",
    "custom": "自定义池",
}

_ALIAS_NAME_RE = re.compile(r"^t\d+$", re.IGNORECASE)


def _pool_cache_name_map() -> dict[str, str]:
    try:
        import web_app  # type: ignore

        df = web_app.load_pool_cache()
    except Exception:
        return {}
    if df is None or df.empty or "ticker" not in df.columns:
        return {}
    name_col = "名称" if "名称" in df.columns else ("name" if "name" in df.columns else None)
    if not name_col:
        return {}
    out: dict[str, str] = {}
    for _, row in df.iterrows():
        ticker = str(row.get("ticker") or "").strip()
        name = str(row.get(name_col) or "").strip()
        if ticker and name:
            out[ticker] = name
    return out


def _fill_item_name(item: dict[str, Any], name_map: dict[str, str]) -> dict[str, Any]:
    ticker = str(item.get("ticker") or "").strip()
    name = str(item.get("name") or "").strip()
    if ticker and (not name or _ALIAS_NAME_RE.match(name)):
        fallback = name_map.get(ticker)
        if fallback:
            item["name"] = fallback
    return item


def _serialize_pool(pool: Pool, item_count: int | None = None) -> dict[str, Any]:
    return {
        "id": pool.id,
        "name": pool.name,
        "pool_type": pool.pool_type,
        "pool_type_label": POOL_TYPE_LABELS.get(pool.pool_type, pool.pool_type),
        "description": pool.description or "",
        "is_default": bool(pool.is_default),
        "created_at": pool.created_at.isoformat() if pool.created_at else None,
        "updated_at": pool.updated_at.isoformat() if pool.updated_at else None,
        "item_count": int(item_count) if item_count is not None else len(pool.items),
    }


def _serialize_item(item: PoolItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "pool_id": item.pool_id,
        "ticker": item.ticker,
        "name": item.name,
        "industry": item.industry,
        "added_at": item.added_at.isoformat() if item.added_at else None,
        "added_score": item.added_score,
        "added_reason": item.added_reason,
        "added_snapshot": item.added_snapshot or {},
        "current_score": item.current_score,
        "last_review_at": item.last_review_at.isoformat() if item.last_review_at else None,
        "last_review_snapshot": item.last_review_snapshot or {},
        "tags": list(item.tags or []),
        "priority": item.priority,
        "status": item.status,
        "note": item.note,
    }


def list_pools() -> list[dict[str, Any]]:
    with session_scope() as session:
        pools = session.execute(select(Pool).order_by(Pool.is_default.desc(), Pool.id)).scalars().all()
        return [_serialize_pool(p) for p in pools]


def get_pool(pool_id: int) -> dict[str, Any] | None:
    with session_scope() as session:
        pool = session.get(Pool, pool_id)
        if not pool:
            return None
        out = _serialize_pool(pool)
        name_map = _pool_cache_name_map()
        out["items"] = [_fill_item_name(_serialize_item(item), name_map) for item in pool.items]
        return out


def get_default_pool_id() -> int:
    with session_scope() as session:
        pool = session.execute(select(Pool).where(Pool.is_default.is_(True))).scalar_one_or_none()
        if pool:
            return pool.id
        # 如果没有默认池，取最早创建的池
        pool = session.execute(select(Pool).order_by(Pool.id)).scalar_one_or_none()
        if pool:
            return pool.id
        # 兜底创建
        pool = Pool(name="短线观察池", pool_type="short_term", is_default=True, description="默认池")
        session.add(pool)
        session.flush()
        return pool.id


def create_pool(name: str, pool_type: str = "custom", description: str = "", is_default: bool = False) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("股票池名称不能为空")
    with session_scope() as session:
        existing = session.execute(select(Pool).where(Pool.name == name)).scalar_one_or_none()
        if existing:
            raise ValueError(f"股票池 “{name}” 已存在")
        if is_default:
            session.execute(select(Pool).where(Pool.is_default.is_(True)))
            for row in session.execute(select(Pool).where(Pool.is_default.is_(True))).scalars().all():
                row.is_default = False
        pool = Pool(name=name, pool_type=pool_type, description=description or "", is_default=bool(is_default))
        session.add(pool)
        session.flush()
        return _serialize_pool(pool, item_count=0)


def update_pool(pool_id: int, *, name: str | None = None, pool_type: str | None = None, description: str | None = None) -> dict[str, Any]:
    with session_scope() as session:
        pool = session.get(Pool, pool_id)
        if not pool:
            raise ValueError("股票池不存在")
        if name is not None:
            cleaned = name.strip()
            if cleaned and cleaned != pool.name:
                clash = session.execute(select(Pool).where(Pool.name == cleaned, Pool.id != pool.id)).scalar_one_or_none()
                if clash:
                    raise ValueError(f"股票池 “{cleaned}” 已存在")
                pool.name = cleaned
        if pool_type is not None:
            pool.pool_type = pool_type
        if description is not None:
            pool.description = description
        return _serialize_pool(pool)


def delete_pool(pool_id: int) -> None:
    with session_scope() as session:
        pool = session.get(Pool, pool_id)
        if not pool:
            return
        if pool.is_default:
            raise ValueError("不能删除默认股票池，请先在其他池上设为默认")
        session.delete(pool)


def upsert_item(
    pool_id: int,
    ticker: str,
    *,
    name: str | None = None,
    industry: str | None = None,
    score: float | None = None,
    reason: str | None = None,
    snapshot: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    priority: int | None = None,
    status: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    ticker = str(ticker or "").strip()
    if not ticker:
        raise ValueError("ticker 不能为空")
    with session_scope() as session:
        pool = session.get(Pool, pool_id)
        if not pool:
            raise ValueError("股票池不存在")
        item = session.execute(
            select(PoolItem).where(PoolItem.pool_id == pool_id, PoolItem.ticker == ticker)
        ).scalar_one_or_none()
        is_new = item is None
        if is_new:
            item = PoolItem(pool_id=pool_id, ticker=ticker, added_at=datetime.utcnow())
            if score is not None:
                item.added_score = float(score)
            if reason is not None:
                item.added_reason = reason
            if snapshot is not None:
                item.added_snapshot = snapshot
            session.add(item)
        if name is not None:
            item.name = name
        if industry is not None:
            item.industry = industry
        if score is not None:
            item.current_score = float(score)
            item.last_review_at = datetime.utcnow()
            if snapshot is not None:
                item.last_review_snapshot = snapshot
        if tags is not None:
            item.tags = list(tags)
        if priority is not None:
            item.priority = int(priority)
        if status is not None:
            item.status = status
        if note is not None:
            item.note = note
        session.flush()
        return _fill_item_name(_serialize_item(item), _pool_cache_name_map())


def bulk_upsert_items(pool_id: int, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in items:
        out.append(
            upsert_item(
                pool_id,
                str(entry.get("ticker", "")).strip(),
                name=entry.get("name") or entry.get("名称"),
                industry=entry.get("industry") or entry.get("行业"),
                score=entry.get("score") if entry.get("score") is not None else entry.get("综合评分"),
                reason=entry.get("reason") or entry.get("入选原因"),
                snapshot=entry.get("snapshot"),
                tags=entry.get("tags"),
                priority=entry.get("priority"),
                status=entry.get("status"),
                note=entry.get("note"),
            )
        )
    return out


def remove_item(pool_id: int, ticker: str) -> None:
    with session_scope() as session:
        session.execute(
            delete(PoolItem).where(PoolItem.pool_id == pool_id, PoolItem.ticker == str(ticker).strip())
        )


def clear_pool(pool_id: int) -> None:
    with session_scope() as session:
        session.execute(delete(PoolItem).where(PoolItem.pool_id == pool_id))


def review_item(
    pool_id: int,
    ticker: str,
    *,
    current_score: float | None,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with session_scope() as session:
        item = session.execute(
            select(PoolItem).where(PoolItem.pool_id == pool_id, PoolItem.ticker == str(ticker).strip())
        ).scalar_one_or_none()
        if not item:
            raise ValueError("池中不存在该股票")
        if current_score is not None:
            item.current_score = float(current_score)
        item.last_review_at = datetime.utcnow()
        if snapshot is not None:
            item.last_review_snapshot = snapshot
        return _fill_item_name(_serialize_item(item), _pool_cache_name_map())


__all__ = [
    "POOL_TYPE_LABELS",
    "list_pools",
    "get_pool",
    "get_default_pool_id",
    "create_pool",
    "update_pool",
    "delete_pool",
    "upsert_item",
    "bulk_upsert_items",
    "remove_item",
    "clear_pool",
    "review_item",
]
