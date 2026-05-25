from __future__ import annotations

import json
from datetime import datetime
from threading import Lock, Thread
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import web_app


class ScreenRequest(BaseModel):
    template_name: str = Field(default="趋势质量股")
    top_n: int = Field(default=30, ge=1, le=500)
    industries: list[str] = Field(default_factory=list)
    weights: dict[str, float] | None = None
    filters: dict[str, Any] | None = None
    industry_neutral: bool = True
    allow_incomplete_factors: bool = False


class UpdateTaskRequest(BaseModel):
    action: str = Field(default="sync_latest")
    token: str | None = None
    http_url: str = Field(default="http://teajoin.com")
    start_date: str = Field(default="2025-06-01")
    download_workers: int = Field(default=2, ge=1, le=16)
    include_stale_tickers: bool = True


class BacktestRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    strategy_names: list[str] = Field(default_factory=lambda: ["双均线趋势"])
    start_date: str = Field(default="2025-06-01")
    end_date: str = Field(default="2025-12-01")
    init_cash: float = Field(default=100000.0, ge=10000.0)
    fees: float = Field(default=0.001, ge=0.0, le=0.1)
    slippage: float = Field(default=0.001, ge=0.0, le=0.1)
    fast_window: int = Field(default=10, ge=2, le=120)
    slow_window: int = Field(default=50, ge=5, le=240)
    trail_stop: float = Field(default=0.08, ge=0.01, le=0.5)
    mom_window: int = Field(default=20, ge=5, le=120)
    top_pct: float = Field(default=0.2, ge=0.05, le=0.8)
    rsi_window: int = Field(default=14, ge=5, le=60)
    rsi_buy: float = Field(default=30.0, ge=5.0, le=50.0)
    rsi_sell: float = Field(default=55.0, ge=40.0, le=95.0)
    holding_count: int = Field(default=30, ge=1, le=500)
    allow_incomplete_data: bool = False
    allow_fallback_universe: bool = False
    benchmark_name: str = Field(default="无")


class RollingBacktestRequest(BaseModel):
    template_name: str = Field(default="稳健质量股")
    start_date: str = Field(default="2025-06-01")
    end_date: str = Field(default="2025-12-01")
    rebalance_frequency: str = Field(default="monthly")
    holding_count: int = Field(default=30, ge=1, le=500)
    benchmark_name: str = Field(default="沪深300")


class WatchlistItem(BaseModel):
    ticker: str
    名称: str | None = None
    行业: str | None = None
    综合评分: float | None = None
    动量分: float | None = None
    质量分: float | None = None
    估值分: float | None = None
    成长分: float | None = None
    风险控制分: float | None = None
    资金情绪分: float | None = None
    ROE: float | None = None
    GROWTH: float | None = None
    PE: float | None = None
    PB: float | None = None
    ret_20d: float | None = None
    ret_60d: float | None = None
    ret_120d: float | None = None
    vol_60d: float | None = None
    max_drawdown_120d: float | None = None
    入选原因: str | None = None
    风格标签: list[str] | None = None
    进攻分: float | None = None
    防守分: float | None = None
    估值压力: float | None = None
    波动风险: float | None = None
    回撤风险: float | None = None
    流动性风险: float | None = None
    决策解释: str | None = None
    行业内动量分位: float | None = None
    行业内质量分位: float | None = None
    行业内估值分位: float | None = None


app = FastAPI(title="MyQuant API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


TASKS: dict[str, dict[str, Any]] = {}
TASKS_LOCK = Lock()
TASK_EXECUTION_LOCK = Lock()
TASK_HISTORY_LIMIT = 20
WATCHLIST_LOCK = Lock()
WATCHLIST_FILE = web_app.CACHE_DIR / "watchlist.json"


class TaskProgressBar:
    def __init__(self, task_id: str, field: str = "progress") -> None:
        self.task_id = task_id
        self.field = field

    def progress(self, value: float) -> None:
        update_task(self.task_id, **{self.field: max(0.0, min(1.0, float(value)))})


class TaskStatusText:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id

    def markdown(self, value: str) -> None:
        update_task(self.task_id, message=str(value).replace("**", ""))


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def update_task(task_id: str, **updates: Any) -> None:
    with TASKS_LOCK:
        task = TASKS.get(task_id)
        if not task:
            return
        task.update(updates)
        task["updated_at"] = utc_now()


def snapshot_task(task_id: str) -> dict[str, Any]:
    with TASKS_LOCK:
        task = TASKS.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return sanitize(dict(task))


def has_running_task() -> bool:
    with TASKS_LOCK:
        return any(task.get("status") in {"queued", "running"} for task in TASKS.values())


def task_duration_seconds(task: dict[str, Any]) -> float | None:
    started_at = task.get("started_at") or task.get("created_at")
    finished_at = task.get("finished_at") or task.get("updated_at")
    if not started_at or not finished_at:
        return None
    try:
        start_dt = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        finish_dt = datetime.fromisoformat(str(finished_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (finish_dt - start_dt).total_seconds())


def task_history(limit: int = 10) -> list[dict[str, Any]]:
    with TASKS_LOCK:
        tasks = sorted(TASKS.values(), key=lambda item: str(item.get("created_at", "")), reverse=True)
        rows = []
        for task in tasks[: max(1, min(int(limit), TASK_HISTORY_LIMIT))]:
            row = dict(task)
            row["duration_seconds"] = task_duration_seconds(row)
            rows.append(row)
        return sanitize(rows)


def latest_trade_date_from_cache() -> str | None:
    token = (web_app.load_token_cache() or "").strip()
    if not token:
        return None
    try:
        pro = web_app.init_tushare_client(token, "http://teajoin.com")
        latest_yyyymmdd = web_app.get_last_trade_date(pro, pd.Timestamp.today().strftime("%Y%m%d"))
        return pd.Timestamp(latest_yyyymmdd).strftime("%Y-%m-%d")
    except Exception:
        return None


def build_cache_diagnostic(summary: dict[str, Any], readiness: dict[str, Any], latest_trade_date: str | None) -> dict[str, Any]:
    cache_end = summary.get("cache_end")
    missing_count = int(summary.get("missing_count") or 0)
    stale_count = int(summary.get("stale_count") or 0)
    price_has_gaps = missing_count > 0 or stale_count > 0 or not bool(readiness.get("price_ok"))
    price_current = bool(cache_end and latest_trade_date and str(cache_end) >= str(latest_trade_date))
    if not latest_trade_date:
        price_current = False
    lag_days = None
    if cache_end and latest_trade_date:
        try:
            cache_ts = pd.Timestamp(cache_end)
            latest_ts = pd.Timestamp(latest_trade_date)
            if latest_ts > cache_ts:
                lag_days = max(0, len(pd.bdate_range(cache_ts + pd.Timedelta(days=1), latest_ts)))
            else:
                lag_days = 0
        except Exception:
            lag_days = None

    fundamental_missing = readiness.get("fundamental_missing") or {}
    fundamental_missing_total = int(sum(int(value or 0) for value in fundamental_missing.values())) if isinstance(fundamental_missing, dict) else 0
    pool_total = int(summary.get("expected_count") or summary.get("present_count") or 0)
    strict_missing = sum(int(fundamental_missing.get(name, 0) or 0) for name in ["ROE", "GROWTH", "PB", "成交额"]) if isinstance(fundamental_missing, dict) else 0
    fundamental_limit = max(5, int(pool_total * 0.02)) if pool_total > 0 else 0
    factor_status = readiness.get("factor_status") or {}
    unavailable_factors = [name for name, ok in factor_status.items() if not ok]

    data_available = (not price_has_gaps) and bool(readiness.get("fundamental_ok")) and bool(readiness.get("factor_ok"))

    if price_has_gaps:
        status = "needs_repair"
        recommended_action = "repair_price"
        recommended_label = "补齐缺失/落后的行情"
        conclusion = "行情缓存存在缺口，选股前建议先修复行情。"
    elif not bool(readiness.get("fundamental_ok")):
        status = "needs_repair"
        recommended_action = "refresh_fundamentals"
        recommended_label = "更新财务与估值数据"
        conclusion = "基础面字段缺失较多，选股前建议刷新财务与估值数据。"
    elif latest_trade_date and not price_current:
        status = "suggest_update"
        recommended_action = "sync_latest"
        recommended_label = "更新到最新交易日"
        conclusion = f"本地缓存内部完整，但尚未覆盖最新交易日 {latest_trade_date}。"
    elif not bool(readiness.get("factor_ok")):
        status = "needs_repair"
        recommended_action = "refresh_fundamentals"
        recommended_label = "更新财务与估值数据"
        conclusion = "部分因子不可用，建议刷新相关数据后再选股。"
    else:
        status = "normal"
        recommended_action = None
        recommended_label = "无需更新"
        conclusion = "当前数据可用于选股。"

    if latest_trade_date and cache_end:
        freshness_text = "已覆盖最新交易日" if price_current else f"本地行情到 {cache_end}，最新交易日为 {latest_trade_date}"
    elif cache_end:
        freshness_text = f"本地行情到 {cache_end}，最新交易日待确认"
    else:
        freshness_text = "行情缓存为空或日期未知"
    if not data_available:
        usage_status = "blocked"
        usage_label = "禁止选股"
        usage_advice = "行情、基础面或因子不可用，当前不应生成选股结果。"
    elif price_current:
        usage_status = "live"
        usage_label = "可实盘使用"
        usage_advice = "数据已覆盖最新交易日，可以作为交易前研究输入。"
    elif lag_days is not None and lag_days <= 2:
        usage_status = "research"
        usage_label = "可研究使用"
        usage_advice = "当前结果仅适合研究，不建议直接实盘使用。"
    else:
        usage_status = "blocked"
        usage_label = "禁止选股"
        usage_advice = "行情缓存落后过多，当前结果不适合选股。"

    screen_text = "可以用于研究选股" if data_available else "选股前建议先处理数据问题"
    full_conclusion = f"{conclusion} {freshness_text}；行情{'完整' if not price_has_gaps else '存在缺口'}，基础面{'可用' if readiness.get('fundamental_ok') else '需更新'}，因子{'可用' if readiness.get('factor_ok') else '不可用'}，当前{screen_text}。"
    if bool(readiness.get("fundamental_ok")) and fundamental_missing_total > 0:
        fundamental_explanation = (
            f"基础面字段允许少量缺失：ROE/GROWTH/PB/成交额这些关键字段合计缺失 {strict_missing} 条，"
            f"未超过当前股票池 {pool_total} 只的 2% 阈值（上限 {fundamental_limit} 条），所以仍判定为可用。"
            "PE 缺失较多通常来自亏损公司没有有效市盈率，不直接视为缓存错误；因子打分会对缺失值做降权或排位处理。"
        )
    elif bool(readiness.get("fundamental_ok")):
        fundamental_explanation = "关键基础面字段完整度满足选股要求。"
    else:
        fundamental_explanation = "关键基础面字段缺失超过可接受阈值，建议先更新财务与估值数据。"

    return {
        "status": status,
        "status_text": {"normal": "正常", "suggest_update": "建议更新", "needs_repair": "需要修复"}[status],
        "can_screen": data_available and usage_status in {"live", "research"},
        "usage_status": usage_status,
        "usage_label": usage_label,
        "usage_advice": usage_advice,
        "lag_trading_days": lag_days,
        "latest_trade_date": latest_trade_date,
        "price_complete": not price_has_gaps,
        "price_current": price_current,
        "fundamental_ok": bool(readiness.get("fundamental_ok")),
        "factor_ok": bool(readiness.get("factor_ok")),
        "recommended_action": recommended_action,
        "recommended_label": recommended_label,
        "conclusion": conclusion,
        "full_conclusion": full_conclusion,
        "fundamental_explanation": fundamental_explanation,
        "anomalies": {
            "missing_price_count": missing_count,
            "stale_price_count": stale_count,
            "fundamental_missing_total": fundamental_missing_total,
            "fundamental_missing": fundamental_missing,
            "unavailable_factors": unavailable_factors,
            "issues": readiness.get("issues") or [],
            "repair_actions": readiness.get("repair_actions") or [],
            "missing_tickers": summary.get("missing_tickers") or [],
            "stale_tickers": summary.get("stale_tickers") or [],
        },
    }


def build_update_params(request: UpdateTaskRequest) -> web_app.AppParams:
    token = (request.token or web_app.load_token_cache() or "").strip()
    if not token:
        raise ValueError("请提供 Tushare Token，或先在缓存中保存 token")
    if request.token and request.token.strip():
        web_app.save_token_cache(request.token)
    return web_app.AppParams(
        token=token,
        http_url=request.http_url.strip() or "http://teajoin.com",
        start_date=pd.Timestamp(request.start_date).strftime("%Y-%m-%d"),
        end_date=pd.Timestamp.today().strftime("%Y-%m-%d"),
        init_cash=100000.0,
        fees=0.001,
        slippage=0.001,
        small_cap_quantile=0.30,
        min_turnover=0.0,
        universe_size=30,
        fast_window=10,
        slow_window=50,
        trail_stop=0.08,
        mom_window=20,
        top_pct=0.2,
        rsi_window=14,
        rsi_buy=30,
        rsi_sell=55,
        download_workers=int(request.download_workers),
    )


def run_sync_latest(task_id: str, params: web_app.AppParams) -> dict[str, Any]:
    update_task(task_id, message="初始化 Tushare/TeaJoin 客户端")
    pro = web_app.init_tushare_client(params.token, params.http_url)
    today_yyyymmdd = pd.Timestamp.today().strftime("%Y%m%d")
    target_trade_yyyymmdd = web_app.get_last_trade_date(pro, today_yyyymmdd)
    target_trade_date = pd.Timestamp(target_trade_yyyymmdd).strftime("%Y-%m-%d")
    cache_df = web_app.load_price_cache()
    pool_df = web_app.load_pool_cache()
    pool_params = web_app.AppParams(**{**params.__dict__, "end_date": target_trade_date})
    if pool_df.empty:
        update_task(task_id, message="股票池缓存为空，先刷新股票池", progress=0.05)
        pool_df = web_app.fetch_stock_pool(pro, pool_params)
        web_app.save_pool_cache(pool_df)

    tickers = pool_df["ticker"].astype(str).tolist() if "ticker" in pool_df.columns else []
    cache_end = None if cache_df.empty else pd.Timestamp(cache_df.index.max()).strftime("%Y-%m-%d")
    cache_summary = web_app.analyze_cache_completeness(price_cache_df=cache_df, pool_df=pool_df)
    readiness = web_app.analyze_data_readiness(cache_df, pool_df)
    missing_count = int(cache_summary.get("missing_count", 0))
    stale_count = int(cache_summary.get("stale_count", 0))
    price_is_current = cache_end is not None and cache_end >= target_trade_date and missing_count == 0 and stale_count == 0
    if price_is_current and readiness.get("fundamental_ok"):
        update_task(task_id, message="价格缓存和基础面字段已可用，无需同步", progress=1.0, chunk_progress=1.0)
        stats = {
            "tickers_requested": 0,
            "tickers_updated": 0,
            "rows_appended": 0,
            "pool_total": int(len(pool_df)),
            "pool_scoped": int(len(tickers)),
            "target_trade_date": target_trade_date,
            "price_sync_skipped": 1,
            "pool_refresh_skipped": 1,
        }
        return {"stats": stats, "cache_range": web_app.cache_date_range(cache_df)}

    if price_is_current:
        update_task(task_id, message="价格缓存已覆盖最新交易日，跳过价格下载", progress=0.5, chunk_progress=1.0)
        stats = {"tickers_requested": 0, "tickers_updated": 0, "rows_appended": 0, "price_sync_skipped": 1}
    else:
        update_task(task_id, message=f"同步价格缓存到最新交易日 {target_trade_date}", progress=0.08)
        cache_df, stats = web_app.update_price_cache_incremental(
            pro=pro,
            tickers=tickers,
            cache_df=cache_df,
            initial_start_date=params.start_date,
            target_end_date=target_trade_date,
            progress_bar=TaskProgressBar(task_id),
            chunk_progress_bar=TaskProgressBar(task_id, "chunk_progress"),
            status_text=TaskStatusText(task_id),
            stage_label="同步到最新",
            workers=int(params.download_workers),
        )
        web_app.save_price_cache(cache_df)

    update_task(task_id, message="刷新股票池和基础面快照", progress=max(0.9, float(stats.get("tickers_updated", 0)) / max(1, len(tickers))))
    refreshed_pool_df = web_app.fetch_stock_pool(pro, pool_params)
    web_app.save_pool_cache(refreshed_pool_df)
    stats["pool_total"] = int(len(refreshed_pool_df))
    stats["pool_scoped"] = int(len(tickers))
    stats["target_trade_date"] = target_trade_date
    stats.setdefault("price_sync_skipped", 0)
    stats["pool_refresh_skipped"] = 0
    return {"stats": stats, "cache_range": web_app.cache_date_range(cache_df)}


def run_repair_price(task_id: str, params: web_app.AppParams, include_stale_tickers: bool) -> dict[str, Any]:
    update_task(task_id, message="分析行情价格缺口", progress=0.02)
    pro = web_app.init_tushare_client(params.token, params.http_url)
    today_str = pd.Timestamp.today().strftime("%Y-%m-%d")
    pool_df = web_app.load_pool_cache()
    if pool_df.empty:
        pool_params = web_app.AppParams(**{**params.__dict__, "end_date": today_str})
        pool_df = web_app.fetch_stock_pool(pro, pool_params)
        web_app.save_pool_cache(pool_df)

    cache_df = web_app.load_price_cache()
    summary = web_app.analyze_cache_completeness(price_cache_df=cache_df, pool_df=pool_df)
    missing_tickers = [str(x) for x in summary.get("missing_tickers", [])]
    stale_tickers = [str(x) for x in summary.get("stale_tickers", [])] if include_stale_tickers else []
    repair_tickers = list(dict.fromkeys(missing_tickers + stale_tickers))
    if not repair_tickers:
        return {
            "stats": {
                "tickers_requested": 0,
                "tickers_updated": 0,
                "rows_appended": 0,
                "pool_total": int(len(pool_df)),
                "missing_requested": int(len(missing_tickers)),
                "stale_requested": int(len(stale_tickers)),
                "repair_requested": 0,
            },
            "cache_range": web_app.cache_date_range(cache_df),
        }

    cache_df, stats = web_app.update_price_cache_incremental(
        pro=pro,
        tickers=repair_tickers,
        cache_df=cache_df,
        initial_start_date=params.start_date,
        target_end_date=today_str,
        progress_bar=TaskProgressBar(task_id),
        chunk_progress_bar=TaskProgressBar(task_id, "chunk_progress"),
        status_text=TaskStatusText(task_id),
        stage_label="修复行情价格缓存",
        workers=int(params.download_workers),
    )
    stats["pool_total"] = int(len(pool_df))
    stats["missing_requested"] = int(len(missing_tickers))
    stats["stale_requested"] = int(len(stale_tickers))
    stats["repair_requested"] = int(len(repair_tickers))
    web_app.save_price_cache(cache_df)
    return {"stats": stats, "cache_range": web_app.cache_date_range(cache_df)}


def run_rebuild(task_id: str, params: web_app.AppParams) -> dict[str, Any]:
    update_task(task_id, message="准备全量重建价格缓存", progress=0.02)
    pro = web_app.init_tushare_client(params.token, params.http_url)
    today_str = pd.Timestamp.today().strftime("%Y-%m-%d")
    pool_params = web_app.AppParams(**{**params.__dict__, "end_date": today_str})
    pool_df = web_app.fetch_stock_pool(pro, pool_params)
    web_app.save_pool_cache(pool_df)
    tickers = pool_df["ticker"].astype(str).tolist()
    cache_df, stats = web_app.update_price_cache_incremental(
        pro=pro,
        tickers=tickers,
        cache_df=pd.DataFrame(),
        initial_start_date=params.start_date,
        target_end_date=today_str,
        progress_bar=TaskProgressBar(task_id),
        chunk_progress_bar=TaskProgressBar(task_id, "chunk_progress"),
        status_text=TaskStatusText(task_id),
        stage_label="全量重建",
        workers=int(params.download_workers),
    )
    stats["pool_total"] = int(len(pool_df))
    stats["pool_scoped"] = int(len(tickers))
    web_app.save_price_cache(cache_df)
    return {"stats": stats, "cache_range": web_app.cache_date_range(cache_df)}


def execute_update_task(task_id: str, request: UpdateTaskRequest) -> None:
    update_task(task_id, status="running", message="任务已开始", progress=0.0, chunk_progress=0.0, started_at=utc_now())
    try:
        params = build_update_params(request)
        with TASK_EXECUTION_LOCK:
            if request.action == "sync_latest":
                result = run_sync_latest(task_id, params)
            elif request.action == "repair_price":
                result = run_repair_price(task_id, params, request.include_stale_tickers)
            elif request.action == "refresh_fundamentals":
                update_task(task_id, message="刷新 ROE/GROWTH 基础面字段", progress=0.1)
                result = {"stats": web_app.refresh_pool_financial_metrics(params), "cache_range": web_app.cache_date_range(web_app.load_price_cache())}
            elif request.action == "rebuild_price":
                result = run_rebuild(task_id, params)
            else:
                raise ValueError(f"未知任务类型: {request.action}")
        update_task(task_id, status="succeeded", progress=1.0, chunk_progress=1.0, message="任务完成", result=result, finished_at=utc_now())
    except Exception as exc:
        update_task(task_id, status="failed", message="任务失败", error=str(exc), finished_at=utc_now())


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, tuple):
        return [sanitize(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if pd.isna(value):
        return None
    return value


def dataframe_records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    out = df.copy()
    if limit is not None:
        out = out.head(int(limit))
    out = out.replace([np.inf, -np.inf], np.nan)
    return sanitize(out.to_dict(orient="records"))


def load_watchlist() -> list[dict[str, Any]]:
    if not WATCHLIST_FILE.exists():
        return []
    try:
        data = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    rows = [row for row in data if isinstance(row, dict) and str(row.get("ticker", "")).strip()]
    return sanitize(rows)


def save_watchlist(rows: list[dict[str, Any]]) -> None:
    web_app.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    WATCHLIST_FILE.write_text(json.dumps(sanitize(rows), ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_watchlist_item(item: WatchlistItem) -> list[dict[str, Any]]:
    row = item.model_dump(exclude_none=True)
    ticker = str(row.get("ticker", "")).strip()
    if not ticker:
        raise ValueError("股票代码不能为空")
    row["ticker"] = ticker
    row["added_at"] = utc_now()
    rows = load_watchlist()
    existing = {str(value.get("ticker")): idx for idx, value in enumerate(rows)}
    if ticker in existing:
        rows[existing[ticker]] = {**rows[existing[ticker]], **row, "added_at": rows[existing[ticker]].get("added_at") or row["added_at"], "updated_at": utc_now()}
    else:
        rows.append(row)
    save_watchlist(rows)
    return rows


def delete_watchlist_item(ticker: str) -> list[dict[str, Any]]:
    clean_ticker = str(ticker).strip()
    rows = [row for row in load_watchlist() if str(row.get("ticker")) != clean_ticker]
    save_watchlist(rows)
    return rows


def build_backtest_params(request: BacktestRequest) -> web_app.AppParams:
    return web_app.AppParams(
        token="",
        http_url="",
        start_date=pd.Timestamp(request.start_date).strftime("%Y-%m-%d"),
        end_date=pd.Timestamp(request.end_date).strftime("%Y-%m-%d"),
        init_cash=float(request.init_cash),
        fees=float(request.fees),
        slippage=float(request.slippage),
        small_cap_quantile=0.30,
        min_turnover=0.0,
        universe_size=int(request.holding_count),
        fast_window=int(request.fast_window),
        slow_window=int(request.slow_window),
        trail_stop=float(request.trail_stop),
        mom_window=int(request.mom_window),
        top_pct=float(request.top_pct),
        rsi_window=int(request.rsi_window),
        rsi_buy=float(request.rsi_buy),
        rsi_sell=float(request.rsi_sell),
        download_workers=4,
    )


def build_selected_pool(tickers: list[str], pool_cache: pd.DataFrame) -> pd.DataFrame:
    clean_tickers = list(dict.fromkeys(str(ticker).strip() for ticker in tickers if str(ticker).strip()))
    if not clean_tickers:
        raise ValueError("请先从筛选结果或观察池选择至少 1 只股票")
    if isinstance(pool_cache, pd.DataFrame) and (not pool_cache.empty) and "ticker" in pool_cache.columns:
        out = pool_cache[pool_cache["ticker"].astype(str).isin(clean_tickers)].copy()
        missing = [ticker for ticker in clean_tickers if ticker not in set(out["ticker"].astype(str))]
    else:
        out = pd.DataFrame()
        missing = clean_tickers
    if missing:
        out = pd.concat([out, pd.DataFrame({"ticker": missing, "名称": missing, "行业": "未分类"})], ignore_index=True)
    order = {ticker: idx for idx, ticker in enumerate(clean_tickers)}
    out["_order"] = out["ticker"].astype(str).map(order)
    return out.sort_values("_order").drop(columns=["_order"]).reset_index(drop=True)


def build_equity_curve(price_df: pd.DataFrame) -> list[dict[str, Any]]:
    returns = price_df.pct_change().dropna(how="all").mean(axis=1).dropna()
    if returns.empty:
        return []
    equity = (1.0 + returns).cumprod()
    return [{"date": idx.strftime("%Y-%m-%d"), "equity": float(value)} for idx, value in equity.items()]


def build_benchmark_curve(benchmark_price: pd.Series | None, index: pd.Index) -> list[dict[str, Any]]:
    if benchmark_price is None or benchmark_price.empty:
        return []
    benchmark = benchmark_price.reindex(index).ffill().dropna()
    if len(benchmark) <= 1:
        return []
    equity = benchmark / benchmark.iloc[0]
    return [{"date": idx.strftime("%Y-%m-%d"), "equity": float(value)} for idx, value in equity.items()]


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "myquant-api"}


@app.get("/api/cache/summary")
def cache_summary() -> dict[str, Any]:
    price_cache = web_app.load_price_cache()
    pool_cache = web_app.load_pool_cache()
    summary = web_app.analyze_cache_completeness(price_cache_df=price_cache, pool_df=pool_cache)
    readiness = web_app.analyze_data_readiness(price_cache, pool_cache)
    latest_trade_date = latest_trade_date_from_cache()
    diagnostic = build_cache_diagnostic(summary, readiness, latest_trade_date)
    return sanitize(
        {
            "cache": summary,
            "readiness": readiness,
            "diagnostic": diagnostic,
            "latest_task": task_history(1)[0] if task_history(1) else None,
            "pool_count": int(len(pool_cache)) if isinstance(pool_cache, pd.DataFrame) else 0,
            "price_symbol_count": int(price_cache.shape[1]) if isinstance(price_cache, pd.DataFrame) else 0,
            "price_row_count": int(price_cache.shape[0]) if isinstance(price_cache, pd.DataFrame) else 0,
        }
    )


@app.get("/api/factor/templates")
def factor_templates() -> dict[str, Any]:
    return sanitize({"templates": web_app.FACTOR_TEMPLATES})


@app.get("/api/backtest/strategies")
def backtest_strategies() -> dict[str, Any]:
    return sanitize({"strategies": web_app.BACKTEST_STRATEGIES})


@app.get("/api/pool/sample")
def pool_sample(limit: int = 50) -> dict[str, Any]:
    pool_cache = web_app.load_pool_cache()
    return {"rows": dataframe_records(pool_cache, limit=max(1, min(int(limit), 500)))}


@app.get("/api/pool/industries")
def pool_industries() -> dict[str, Any]:
    pool_cache = web_app.load_pool_cache()
    if pool_cache is None or pool_cache.empty or "行业" not in pool_cache.columns:
        return {"industries": []}
    counts = (
        pool_cache["行业"]
        .fillna("未分类")
        .astype(str)
        .str.strip()
        .replace("", "未分类")
        .value_counts()
        .sort_index()
    )
    return sanitize(
        {
            "industries": [
                {"name": str(name), "count": int(count)}
                for name, count in counts.items()
            ]
        }
    )


@app.get("/api/watchlist")
def get_watchlist() -> dict[str, Any]:
    with WATCHLIST_LOCK:
        return {"rows": load_watchlist()}


@app.post("/api/watchlist")
def add_watchlist_item(item: WatchlistItem) -> dict[str, Any]:
    try:
        with WATCHLIST_LOCK:
            rows = upsert_watchlist_item(item)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rows": rows}


@app.delete("/api/watchlist/{ticker}")
def remove_watchlist_item(ticker: str) -> dict[str, Any]:
    with WATCHLIST_LOCK:
        return {"rows": delete_watchlist_item(ticker)}


@app.delete("/api/watchlist")
def clear_watchlist() -> dict[str, Any]:
    with WATCHLIST_LOCK:
        save_watchlist([])
        return {"rows": []}


@app.post("/api/tasks")
def start_update_task(request: UpdateTaskRequest) -> dict[str, Any]:
    allowed_actions = {"sync_latest", "repair_price", "refresh_fundamentals", "rebuild_price"}
    if request.action not in allowed_actions:
        raise HTTPException(status_code=400, detail="Unsupported task action")
    if has_running_task():
        raise HTTPException(status_code=409, detail="已有数据更新任务正在执行，请等待完成后再开始新任务")

    task_id = str(uuid4())
    with TASKS_LOCK:
        TASKS[task_id] = {
            "id": task_id,
            "action": request.action,
            "status": "queued",
            "progress": 0.0,
            "chunk_progress": 0.0,
            "message": "任务已排队",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "result": None,
            "error": None,
        }
    worker = Thread(target=execute_update_task, args=(task_id, request), daemon=True)
    worker.start()
    return snapshot_task(task_id)


@app.get("/api/tasks/history")
def get_task_history(limit: int = 10) -> dict[str, Any]:
    return {"tasks": task_history(limit)}


@app.get("/api/tasks/{task_id}")
def get_update_task(task_id: str) -> dict[str, Any]:
    return snapshot_task(task_id)


@app.post("/api/screen")
def screen(request: ScreenRequest) -> dict[str, Any]:
    price_cache = web_app.load_price_cache()
    pool_cache = web_app.load_pool_cache()
    readiness = web_app.analyze_data_readiness(price_cache, pool_cache)
    if (not readiness.get("factor_ok", False)) and (not request.allow_incomplete_factors):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "筛选因子数据预检未通过，请先修复缓存或允许不完整因子。",
                "readiness": sanitize(readiness),
            },
        )

    template = web_app.FACTOR_TEMPLATES.get(request.template_name, web_app.FACTOR_TEMPLATES["趋势质量股"])
    weights = request.weights or dict(template.get("weights", {}))
    filters = dict(template.get("filters", {}))
    filters.update(request.filters or {})
    selected_industries = list(dict.fromkeys(str(item).strip() for item in request.industries if str(item).strip()))
    scoped_pool_cache = pool_cache
    industry_scope = {"selected": selected_industries, "before_count": int(len(pool_cache)) if isinstance(pool_cache, pd.DataFrame) else 0, "after_count": int(len(pool_cache)) if isinstance(pool_cache, pd.DataFrame) else 0}
    if selected_industries:
        if pool_cache is None or pool_cache.empty or "行业" not in pool_cache.columns:
            raise HTTPException(status_code=400, detail="当前股票池缺少行业字段，无法按板块/行业筛选。请先刷新股票池缓存。")
        industry_series = pool_cache["行业"].fillna("未分类").astype(str).str.strip().replace("", "未分类")
        scoped_pool_cache = pool_cache[industry_series.isin(selected_industries)].copy()
        industry_scope["after_count"] = int(len(scoped_pool_cache))
        if scoped_pool_cache.empty:
            raise HTTPException(status_code=400, detail="所选板块/行业内没有可筛选股票，请调整行业范围。")

    try:
        screened, removed = web_app.build_factor_screen(
            pool_df=scoped_pool_cache,
            price_cache_df=price_cache,
            weights=web_app.normalize_weights(weights),
            filters=filters,
            top_n=request.top_n,
            reference_date=pd.Timestamp.today().strftime("%Y-%m-%d"),
            industry_neutral=request.industry_neutral,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return sanitize(
        {
            "rows": dataframe_records(screened),
            "removed": removed,
            "readiness": readiness,
            "weights": web_app.normalize_weights(weights),
            "filters": filters,
            "industry_scope": industry_scope,
        }
    )


@app.post("/api/backtest")
def backtest(request: BacktestRequest) -> dict[str, Any]:
    price_cache = web_app.load_price_cache()
    pool_cache = web_app.load_pool_cache()
    selected_pool = build_selected_pool(request.tickers[: request.holding_count], pool_cache)
    params = build_backtest_params(request)
    preflight = web_app.analyze_cache_completeness(
        price_cache_df=price_cache,
        tickers=selected_pool["ticker"].astype(str).tolist(),
        start_date=params.start_date,
        end_date=params.end_date,
    )
    incomplete_reasons = [
        int(preflight.get("missing_count", 0)) > 0,
        int(preflight.get("no_data_in_range_count", 0)) > 0,
        int(preflight.get("dropped_for_gaps_count", 0)) > 0,
    ]
    if any(incomplete_reasons) and (not request.allow_incomplete_data):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "本次回测数据预检未通过，请先更新缓存或允许不完整数据继续回测。",
                "preflight": sanitize(preflight),
            },
        )

    try:
        pool_df, price_df, strategy_df, stats, cache_range, signals, advice = web_app.run_backtest_from_pool(
            params=params,
            selected_pool_df=selected_pool,
            allow_fallback_universe=bool(request.allow_fallback_universe),
            strategy_names=request.strategy_names,
        )
        benchmark_series = None
        benchmark_col = web_app.benchmark_column_name(str(request.benchmark_name))
        if benchmark_col and benchmark_col in price_cache.columns:
            benchmark_series = price_cache[benchmark_col]
        metrics = web_app.calculate_portfolio_metric_summary(price_df, benchmark_series)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return sanitize(
        {
            "metrics": metrics,
            "strategies": dataframe_records(strategy_df),
            "pool": dataframe_records(pool_df, limit=500),
            "stats": stats,
            "cache_range": cache_range,
            "price_shape": {"rows": int(price_df.shape[0]), "columns": int(price_df.shape[1])},
            "preflight": preflight,
            "equity_curve": build_equity_curve(price_df),
            "benchmark_curve": build_benchmark_curve(benchmark_series, price_df.index),
            "benchmark_available": bool(benchmark_series is not None),
            "signals": signals,
            "advice": advice,
            "selected_strategies": request.strategy_names,
        }
    )


@app.post("/api/backtest/rolling")
def rolling_backtest(request: RollingBacktestRequest) -> dict[str, Any]:
    return sanitize(
        {
            "implemented": False,
            "mode": "rolling_factor_backtest",
            "message": "滚动选股回测已预留接口，但当前缓存缺少逐期历史基础面/估值快照，不能生成可信结果。",
            "required_data": [
                "每个调仓日可获得的行情窗口",
                "每个调仓日可获得的 ROE/GROWTH/PE/PB/成交额快照",
                "指数基准日线序列",
                "调仓成交约束和费用模型",
            ],
            "methodology": [
                "每周或每月在调仓日重新计算因子",
                "每期只使用调仓日前已经可获得的数据",
                "按当前模板和权重选择前 N 只",
                "下一期调仓并记录收益、换手率和超额收益",
            ],
            "requested": request.model_dump(),
        }
    )
