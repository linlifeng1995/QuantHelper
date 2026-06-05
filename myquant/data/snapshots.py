"""财务/估值快照采集与查询。

设计原则
~~~~~~~~
* **防未来函数**：``FinaSnapshot.ann_date`` 是公告日；在评估日 ``D`` 只能使用
  ``ann_date <= D`` 的记录。``get_fina_for_ticker_at`` 直接体现这一约束。
* **冷启动可拒绝**：``assert_fina_snapshots_available`` / ``assert_daily_basic_available``
  在 ``fina_snapshots`` / ``daily_basic_snapshots`` 表为空时显式抛错，防止下游
  在没有真实基本面时偷偷退化为合成数据。
* **Idempotent upsert**：``UniqueConstraint`` + SQLite ``ON CONFLICT DO NOTHING``
  语义，允许重复同步同一交易日不会重复插入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Sequence

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..db import SessionLocal, session_scope
from ..db.models import DailyBasicSnapshot, FinaSnapshot, SnapshotSyncLog


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------
def _norm_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None
    if len(text) == 8 and text.isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10]


def _to_compact_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.replace("-", "")[:8]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(out):
        return None
    return out


DAILY_BASIC_COLUMNS = (
    "pe",
    "pe_ttm",
    "pb",
    "ps",
    "ps_ttm",
    "dv_ratio",
    "dv_ttm",
    "total_mv",
    "circ_mv",
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
)

FINA_COLUMNS = (
    "eps",
    "bps",
    "roe",
    "roe_yearly",
    "roa",
    "netprofit_margin",
    "grossprofit_margin",
    "debt_to_assets",
    "current_ratio",
    "netprofit_yoy",
    "or_yoy",
)


# ---------------------------------------------------------------------------
# 同步结果
# ---------------------------------------------------------------------------
@dataclass
class SyncResult:
    kind: str
    requested: int = 0
    inserted: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    log_id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "requested": self.requested,
            "inserted": self.inserted,
            "skipped": self.skipped,
            "failed": self.failed,
            "errors": self.errors[:5],
            "log_id": self.log_id,
        }


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------
def _upsert_daily_basic(session: Session, rows: list[dict[str, Any]]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    stmt = sqlite_insert(DailyBasicSnapshot).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["ts_code", "trade_date"])
    result = session.execute(stmt)
    inserted = result.rowcount if result.rowcount and result.rowcount > 0 else 0
    skipped = len(rows) - inserted
    return inserted, skipped


def _upsert_fina(session: Session, rows: list[dict[str, Any]]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    stmt = sqlite_insert(FinaSnapshot).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["ts_code", "end_date", "ann_date"])
    result = session.execute(stmt)
    inserted = result.rowcount if result.rowcount and result.rowcount > 0 else 0
    skipped = len(rows) - inserted
    return inserted, skipped


def _flush_rows(session_factory, upsert_fn, rows: list[dict[str, Any]]) -> tuple[int, int]:
    if not rows:
        return 0, 0
    with session_factory() as session:
        return upsert_fn(session, rows)


# ---------------------------------------------------------------------------
# 行 → ORM dict 转换
# ---------------------------------------------------------------------------
def _df_row_to_daily_basic(row: pd.Series) -> dict[str, Any] | None:
    ts_code = str(row.get("ts_code") or "").strip()
    trade_date = _norm_date(row.get("trade_date"))
    if not ts_code or not trade_date:
        return None
    payload: dict[str, Any] = {"ts_code": ts_code, "trade_date": trade_date}
    for col in DAILY_BASIC_COLUMNS:
        payload[col] = _to_float(row.get(col))
    payload["data"] = {k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in row.to_dict().items()}
    return payload


def _df_row_to_fina(row: pd.Series) -> dict[str, Any] | None:
    ts_code = str(row.get("ts_code") or "").strip()
    end_date = _norm_date(row.get("end_date"))
    if not ts_code or not end_date:
        return None
    ann_date = _norm_date(row.get("ann_date"))
    payload: dict[str, Any] = {
        "ts_code": ts_code,
        "end_date": end_date,
        "ann_date": ann_date,
    }
    for col in FINA_COLUMNS:
        payload[col] = _to_float(row.get(col))
    payload["data"] = {k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in row.to_dict().items()}
    return payload


# ---------------------------------------------------------------------------
# 同步：daily_basic
# ---------------------------------------------------------------------------
def sync_daily_basic(
    pro: Any,
    trade_dates: Sequence[str],
    ts_codes: Sequence[str] | None = None,
) -> SyncResult:
    """按交易日批量拉取 daily_basic。

    Parameters
    ----------
    pro:
        ``web_app.TeaJoinClient`` 或兼容 ``daily_basic(trade_date=...)`` 接口的对象。
    trade_dates:
        ``YYYY-MM-DD`` / ``YYYYMMDD`` 形式都可。
    ts_codes:
        可选过滤；为空则保留全市场。
    """
    result = SyncResult(kind="daily_basic", requested=len(trade_dates))
    ts_filter = {str(c).strip() for c in (ts_codes or []) if str(c).strip()}

    with session_scope() as session:
        log = SnapshotSyncLog(
            kind="daily_basic",
            status="running",
            requested=len(trade_dates),
            params={"trade_dates": list(trade_dates)[:50], "ts_codes_filter": len(ts_filter)},
        )
        session.add(log)
        session.flush()
        log_id = log.id

    inserted_total = 0
    skipped_total = 0
    failed_total = 0
    errors: list[str] = []
    pending_rows: list[dict[str, Any]] = []

    for raw_date in trade_dates:
        compact = _to_compact_date(raw_date)
        if not compact:
            failed_total += 1
            errors.append(f"非法日期: {raw_date}")
            continue
        try:
            df = pro.daily_basic(trade_date=compact)
        except Exception as exc:  # noqa: BLE001
            failed_total += 1
            errors.append(f"{compact}: {exc!r}")
            continue
        if df is None or len(df) == 0:
            continue
        if ts_filter:
            df = df[df["ts_code"].astype(str).isin(ts_filter)]
        for _, row in df.iterrows():
            payload = _df_row_to_daily_basic(row)
            if payload is not None:
                pending_rows.append(payload)
        if len(pending_rows) >= 2000:
            try:
                ins, skip = _flush_rows(session_scope, _upsert_daily_basic, pending_rows)
                inserted_total += ins
                skipped_total += skip
                pending_rows.clear()
            except Exception as exc:  # noqa: BLE001
                failed_total += 1
                errors.append(f"upsert {compact}: {exc!r}")

    if pending_rows:
        try:
            ins, skip = _flush_rows(session_scope, _upsert_daily_basic, pending_rows)
            inserted_total += ins
            skipped_total += skip
        except Exception as exc:  # noqa: BLE001
            failed_total += 1
            errors.append(f"final upsert: {exc!r}")
        finally:
            pending_rows.clear()

    status = "succeeded" if failed_total == 0 else ("partial" if inserted_total or skipped_total else "failed")
    with session_scope() as session:
        log_obj = session.get(SnapshotSyncLog, log_id)
        if log_obj is not None:
            log_obj.finished_at = datetime.utcnow()
            log_obj.status = status
            log_obj.inserted = inserted_total
            log_obj.skipped = skipped_total
            log_obj.failed = failed_total
            log_obj.error = " | ".join(errors[:3]) if errors else None
    result.inserted = inserted_total
    result.skipped = skipped_total
    result.failed = failed_total
    result.errors = errors
    result.log_id = log_id
    return result


# ---------------------------------------------------------------------------
# 同步：fina_indicator
# ---------------------------------------------------------------------------
def sync_fina_indicator(
    pro: Any,
    ts_codes: Sequence[str],
    start_date: str | None = None,
    end_date: str | None = None,
) -> SyncResult:
    """按股票拉取 ``fina_indicator``（按 ts_code 逐条调用）。"""
    codes = [str(c).strip() for c in ts_codes if str(c).strip()]
    result = SyncResult(kind="fina", requested=len(codes))
    if not codes:
        return result

    start_compact = _to_compact_date(start_date) if start_date else None
    end_compact = _to_compact_date(end_date) if end_date else None

    with session_scope() as session:
        log = SnapshotSyncLog(
            kind="fina",
            status="running",
            requested=len(codes),
            params={
                "ts_codes_preview": codes[:20],
                "start_date": start_compact,
                "end_date": end_compact,
                "total": len(codes),
            },
        )
        session.add(log)
        session.flush()
        log_id = log.id

    inserted_total = 0
    skipped_total = 0
    failed_total = 0
    errors: list[str] = []
    pending_rows: list[dict[str, Any]] = []

    for batch_codes in (codes[i : i + 80] for i in range(0, len(codes), 80)):
        kwargs: dict[str, Any] = {"ts_code": ",".join(batch_codes)}
        if start_compact:
            kwargs["start_date"] = start_compact
        if end_compact:
            kwargs["end_date"] = end_compact
        try:
            df = pro.fina_indicator(**kwargs)
        except Exception as exc:  # noqa: BLE001
            failed_total += 1
            errors.append(f"{batch_codes[0]}...: {exc!r}")
            continue
        if df is None or len(df) == 0:
            continue
        for _, row in df.iterrows():
            payload = _df_row_to_fina(row)
            if payload is not None:
                pending_rows.append(payload)
        if len(pending_rows) >= 2000:
            try:
                ins, skip = _flush_rows(session_scope, _upsert_fina, pending_rows)
                inserted_total += ins
                skipped_total += skip
                pending_rows.clear()
            except Exception as exc:  # noqa: BLE001
                failed_total += 1
                errors.append(f"upsert {batch_codes[0]}...: {exc!r}")

    if pending_rows:
        try:
            ins, skip = _flush_rows(session_scope, _upsert_fina, pending_rows)
            inserted_total += ins
            skipped_total += skip
        except Exception as exc:  # noqa: BLE001
            failed_total += 1
            errors.append(f"final upsert: {exc!r}")
        finally:
            pending_rows.clear()

    status = "succeeded" if failed_total == 0 else ("partial" if inserted_total or skipped_total else "failed")
    with session_scope() as session:
        log_obj = session.get(SnapshotSyncLog, log_id)
        if log_obj is not None:
            log_obj.finished_at = datetime.utcnow()
            log_obj.status = status
            log_obj.inserted = inserted_total
            log_obj.skipped = skipped_total
            log_obj.failed = failed_total
            log_obj.error = " | ".join(errors[:3]) if errors else None
    result.inserted = inserted_total
    result.skipped = skipped_total
    result.failed = failed_total
    result.errors = errors
    result.log_id = log_id
    return result


# ---------------------------------------------------------------------------
# 状态 / 查询
# ---------------------------------------------------------------------------
def snapshot_status() -> dict[str, Any]:
    with SessionLocal() as session:
        db_count = session.scalar(select(func.count()).select_from(DailyBasicSnapshot)) or 0
        db_last = session.scalar(select(func.max(DailyBasicSnapshot.trade_date)))
        db_codes = session.scalar(select(func.count(func.distinct(DailyBasicSnapshot.ts_code))))
        fi_count = session.scalar(select(func.count()).select_from(FinaSnapshot)) or 0
        fi_last_ann = session.scalar(select(func.max(FinaSnapshot.ann_date)))
        fi_last_end = session.scalar(select(func.max(FinaSnapshot.end_date)))
        fi_codes = session.scalar(select(func.count(func.distinct(FinaSnapshot.ts_code))))
        recent_logs_rows = session.execute(
            select(SnapshotSyncLog).order_by(SnapshotSyncLog.id.desc()).limit(5)
        ).scalars().all()
        recent_logs = [
            {
                "id": log.id,
                "kind": log.kind,
                "status": log.status,
                "requested": log.requested,
                "inserted": log.inserted,
                "skipped": log.skipped,
                "failed": log.failed,
                "started_at": log.started_at.isoformat() if log.started_at else None,
                "finished_at": log.finished_at.isoformat() if log.finished_at else None,
                "error": log.error,
            }
            for log in recent_logs_rows
        ]
    return {
        "daily_basic": {
            "rows": int(db_count),
            "tickers": int(db_codes or 0),
            "latest_trade_date": db_last,
        },
        "fina": {
            "rows": int(fi_count),
            "tickers": int(fi_codes or 0),
            "latest_ann_date": fi_last_ann,
            "latest_end_date": fi_last_end,
        },
        "recent_logs": recent_logs,
    }


def assert_fina_snapshots_available() -> None:
    """Phase 4 起强制：fina_snapshots 表空时拒绝运行，避免合成基本面。"""
    with SessionLocal() as session:
        count = session.scalar(select(func.count()).select_from(FinaSnapshot)) or 0
    if count == 0:
        raise RuntimeError(
            "fina_snapshots 表为空：请先到「数据更新」页同步财务指标，"
            "禁止在缺失真实基本面的情况下运行下游评估。"
        )


def assert_daily_basic_available() -> None:
    with SessionLocal() as session:
        count = session.scalar(select(func.count()).select_from(DailyBasicSnapshot)) or 0
    if count == 0:
        raise RuntimeError(
            "daily_basic_snapshots 表为空：请先到「数据更新」页同步估值/换手率切片。"
        )


def get_fina_for_ticker_at(
    ts_code: str,
    as_of_date: str,
    session: Session | None = None,
) -> dict[str, Any] | None:
    """返回 ``ts_code`` 在 ``as_of_date`` 之前已公告的最新一期财务指标。"""
    as_of = _norm_date(as_of_date)
    if not as_of:
        return None
    owned = False
    if session is None:
        session = SessionLocal()
        owned = True
    try:
        stmt = (
            select(FinaSnapshot)
            .where(FinaSnapshot.ts_code == ts_code)
            .where(FinaSnapshot.ann_date.is_not(None))
            .where(FinaSnapshot.ann_date <= as_of)
            .order_by(FinaSnapshot.ann_date.desc(), FinaSnapshot.end_date.desc())
            .limit(1)
        )
        row = session.execute(stmt).scalar_one_or_none()
        if row is None:
            return None
        return {
            "ts_code": row.ts_code,
            "end_date": row.end_date,
            "ann_date": row.ann_date,
            **{col: getattr(row, col) for col in FINA_COLUMNS},
        }
    finally:
        if owned:
            session.close()


def get_daily_basic_for_ticker_at(
    ts_code: str,
    trade_date: str,
    session: Session | None = None,
) -> dict[str, Any] | None:
    target = _norm_date(trade_date)
    if not target:
        return None
    owned = False
    if session is None:
        session = SessionLocal()
        owned = True
    try:
        stmt = (
            select(DailyBasicSnapshot)
            .where(DailyBasicSnapshot.ts_code == ts_code)
            .where(DailyBasicSnapshot.trade_date <= target)
            .order_by(DailyBasicSnapshot.trade_date.desc())
            .limit(1)
        )
        row = session.execute(stmt).scalar_one_or_none()
        if row is None:
            return None
        return {
            "ts_code": row.ts_code,
            "trade_date": row.trade_date,
            **{col: getattr(row, col) for col in DAILY_BASIC_COLUMNS},
        }
    finally:
        if owned:
            session.close()


__all__ = [
    "SyncResult",
    "sync_daily_basic",
    "sync_fina_indicator",
    "snapshot_status",
    "assert_fina_snapshots_available",
    "assert_daily_basic_available",
    "get_fina_for_ticker_at",
    "get_daily_basic_for_ticker_at",
]
