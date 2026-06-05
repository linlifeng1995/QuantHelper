"""启动建表 + 旧 watchlist.json → SQLite 默认池迁移。

调用入口：myquant.migrations.run_startup_migrations()
- 建表（idempotent）
- 创建默认池"短线观察池"（is_default=True）
- 把 outputs/cache/watchlist.json 中的股票一次性导入默认池，并备份原文件
- seed factor_defs
- ensure risk_settings
"""
from __future__ import annotations

import json
import shutil

from sqlalchemy import select

from .config import WATCHLIST_BACKUP_FILE, WATCHLIST_LEGACY_FILE
from .db import engine, session_scope
from .db.models import Base, Pool, PoolItem
from .factors.registry import seed_factor_registry
from .risk.settings import ensure_default as ensure_risk_defaults


def _ensure_default_pool() -> int:
    with session_scope() as session:
        existing = session.execute(select(Pool).where(Pool.is_default.is_(True))).scalar_one_or_none()
        if existing:
            return existing.id
        # 兼容历史 name="短线观察池" 已存在但 is_default=false 的情况
        legacy = session.execute(select(Pool).where(Pool.name == "短线观察池")).scalar_one_or_none()
        if legacy:
            legacy.is_default = True
            session.flush()
            return legacy.id
        pool = Pool(
            name="短线观察池",
            pool_type="short_term",
            description="默认池，沿用旧版自选清单 (watchlist.json)",
            is_default=True,
        )
        session.add(pool)
        session.flush()
        return pool.id


def _ensure_preset_pools() -> None:
    presets = [
        ("中线趋势池", "mid_term", "中期趋势向上、均线多头排列的标的"),
        ("低估值价值池", "value", "PE/PB/股息率综合靠前的标的"),
        ("高股息防守池", "dividend", "波动低、股息率高的防守型标的"),
    ]
    with session_scope() as session:
        for name, pool_type, desc in presets:
            existing = session.execute(select(Pool).where(Pool.name == name)).scalar_one_or_none()
            if existing:
                continue
            session.add(Pool(name=name, pool_type=pool_type, description=desc, is_default=False))


def _migrate_legacy_watchlist(default_pool_id: int) -> int:
    if not WATCHLIST_LEGACY_FILE.exists():
        return 0
    try:
        raw = json.loads(WATCHLIST_LEGACY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(raw, list):
        return 0
    rows = [r for r in raw if isinstance(r, dict) and str(r.get("ticker", "")).strip()]
    if not rows:
        return 0

    migrated = 0
    with session_scope() as session:
        for entry in rows:
            ticker = str(entry.get("ticker", "")).strip()
            existing = session.execute(
                select(PoolItem).where(PoolItem.pool_id == default_pool_id, PoolItem.ticker == ticker)
            ).scalar_one_or_none()
            if existing:
                continue
            snapshot = {k: v for k, v in entry.items() if k != "ticker"}
            item = PoolItem(
                pool_id=default_pool_id,
                ticker=ticker,
                name=entry.get("名称") or entry.get("name"),
                industry=entry.get("行业") or entry.get("industry"),
                added_score=_to_float(entry.get("综合评分")),
                current_score=_to_float(entry.get("综合评分")),
                added_reason=entry.get("入选原因") or entry.get("决策解释"),
                added_snapshot=snapshot,
                last_review_snapshot=snapshot,
                tags=entry.get("风格标签") if isinstance(entry.get("风格标签"), list) else None,
            )
            session.add(item)
            migrated += 1

    # 备份原文件
    if migrated > 0:
        try:
            shutil.copy2(WATCHLIST_LEGACY_FILE, WATCHLIST_BACKUP_FILE)
        except OSError:
            pass
    return migrated


def _to_float(value):
    try:
        if value is None:
            return None
        v = float(value)
        if v != v:  # NaN
            return None
        return v
    except (TypeError, ValueError):
        return None


def run_startup_migrations() -> dict[str, int | str]:
    Base.metadata.create_all(engine)
    default_pool_id = _ensure_default_pool()
    _ensure_preset_pools()
    migrated = _migrate_legacy_watchlist(default_pool_id)
    seed_factor_registry()
    ensure_risk_defaults()
    return {
        "default_pool_id": default_pool_id,
        "legacy_migrated": migrated,
    }
