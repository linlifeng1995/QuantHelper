"""滚动回测运行持久化（D4）：保存 BacktestRun + BacktestTrade。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from myquant.db import session_scope
from myquant.db.models import BacktestRun, BacktestTrade


def _derive_trades(holdings: list[dict[str, Any]], period_returns: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """从 holdings 序列推导每段的 enter/hold/exit 记录。

    holdings 每项 ``{date, tickers:[...], scores:{ticker:score}}``。
    period_returns 每项 ``{start, end, ...}``，长度通常 = len(holdings)。
    """
    out: list[dict[str, Any]] = []
    prev: set[str] = set()
    pr_map = {p.get("start"): p for p in (period_returns or [])}
    for idx, period in enumerate(holdings):
        date = str(period.get("date") or "")
        tickers = list(period.get("tickers") or [])
        scores = dict(period.get("scores") or {})
        pr = pr_map.get(date) or {}
        period_end = pr.get("end")
        weight = 1.0 / len(tickers) if tickers else None
        cur = set(tickers)
        entered = cur - prev
        held = cur & prev
        exited = prev - cur
        for tk in tickers:
            action = "enter" if tk in entered else "hold"
            out.append(
                {
                    "period_index": idx,
                    "period_start": date,
                    "period_end": period_end,
                    "action": action,
                    "ticker": tk,
                    "weight": weight,
                    "score": float(scores.get(tk)) if scores.get(tk) is not None else None,
                }
            )
        for tk in exited:
            out.append(
                {
                    "period_index": idx,
                    "period_start": date,
                    "period_end": period_end,
                    "action": "exit",
                    "ticker": tk,
                    "weight": None,
                    "score": None,
                }
            )
        prev = cur
    return out


def _serialize_run(run: BacktestRun, *, include_trades: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": run.id,
        "label": run.label,
        "strategy": run.strategy,
        "rebalance": run.rebalance,
        "start_date": run.start_date,
        "end_date": run.end_date,
        "top_n": run.top_n,
        "universe_size": run.universe_size,
        "pool_id": run.pool_id,
        "total_return": run.total_return,
        "annualized_return": run.annualized_return,
        "max_drawdown": run.max_drawdown,
        "sharpe_ratio": run.sharpe_ratio,
        "win_rate": run.win_rate,
        "bench_total_return": run.bench_total_return,
        "bench_annualized_return": run.bench_annualized_return,
        "params": run.params,
        "warnings": run.warnings or [],
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
    if include_trades:
        d["equity_curve"] = run.equity_curve or []
        d["period_returns"] = run.period_returns or []
        d["trades"] = [
            {
                "id": t.id,
                "period_index": t.period_index,
                "period_start": t.period_start,
                "period_end": t.period_end,
                "action": t.action,
                "ticker": t.ticker,
                "weight": t.weight,
                "score": t.score,
            }
            for t in sorted(run.trades, key=lambda x: (x.period_index, x.action, x.ticker))
        ]
    return d


def save_run(
    result: dict[str, Any],
    *,
    label: str | None = None,
    pool_id: int | None = None,
    params: dict[str, Any] | None = None,
) -> int:
    """持久化一次回测结果，返回 run_id。"""
    metrics = result.get("metrics") or {}
    bench = result.get("benchmark_metrics") or {}
    trades = _derive_trades(result.get("holdings") or [], result.get("period_returns") or [])

    with session_scope() as session:
        run = BacktestRun(
            label=label,
            strategy=str(result.get("strategy") or "unknown"),
            rebalance=str(result.get("rebalance") or "month"),
            start_date=str(result.get("start_date") or ""),
            end_date=str(result.get("end_date") or ""),
            top_n=int(result.get("top_n") or 10),
            universe_size=int(result.get("universe_size") or 0),
            pool_id=pool_id,
            total_return=metrics.get("total_return"),
            annualized_return=metrics.get("annualized_return"),
            max_drawdown=metrics.get("max_drawdown"),
            sharpe_ratio=metrics.get("sharpe_ratio"),
            win_rate=metrics.get("win_rate"),
            bench_total_return=bench.get("total_return"),
            bench_annualized_return=bench.get("annualized_return"),
            params=params or {},
            equity_curve=result.get("equity_curve") or [],
            period_returns=result.get("period_returns") or [],
            warnings=result.get("warnings") or [],
        )
        session.add(run)
        session.flush()  # 取得 id
        for t in trades:
            session.add(BacktestTrade(run_id=run.id, **t))
        session.flush()
        return int(run.id)


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = (
            session.execute(
                select(BacktestRun).order_by(BacktestRun.created_at.desc(), BacktestRun.id.desc()).limit(limit)
            )
            .scalars()
            .all()
        )
        return [_serialize_run(r) for r in rows]


def get_run(run_id: int) -> dict[str, Any] | None:
    with session_scope() as session:
        run = session.execute(
            select(BacktestRun).options(selectinload(BacktestRun.trades)).where(BacktestRun.id == run_id)
        ).scalar_one_or_none()
        if run is None:
            return None
        return _serialize_run(run, include_trades=True)


def delete_run(run_id: int) -> bool:
    with session_scope() as session:
        run = session.get(BacktestRun, run_id)
        if run is None:
            return False
        session.delete(run)
        return True
