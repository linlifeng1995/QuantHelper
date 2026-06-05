from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from http.client import IncompleteRead, RemoteDisconnected
from datetime import date, time as dt_time
from pathlib import Path
import random
import threading
import time
from typing import Any, Callable, Dict, List, Tuple

import numpy as np
import pandas as pd
try:
    import streamlit as st
except ModuleNotFoundError:
    st = None  # type: ignore[assignment]
import requests
import tushare as ts
import vectorbt as vbt
from myquant.tushare_client import (
    DEFAULT_TUSHARE_HTTP_URL,
    DEFAULT_TUSHARE_TOKEN,
    init_tushare_pro,
)
from requests.exceptions import ConnectionError as RequestsConnectionError, HTTPError, ReadTimeout
from urllib3.exceptions import ProtocolError

from myquant.factors.buckets import normalize_price_discontinuities


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
CACHE_DIR = OUTPUT_DIR / "cache"
PRICE_CACHE_FILE = CACHE_DIR / "price_cache.pkl"
POOL_CACHE_FILE = CACHE_DIR / "pool_cache.pkl"
TOKEN_CACHE_FILE = CACHE_DIR / "tushare_token.txt"
DEFAULT_TEAJOIN_TIMEOUT = 60
TS_MIN_INTERVAL_SEC = 1.2
_TS_CALL_LOCK = threading.Lock()
_TS_LAST_CALL_TS = 0.0


def inject_app_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --mq-bg: #f6f7f9;
            --mq-surface: #ffffff;
            --mq-surface-muted: #f0f4f8;
            --mq-border: #d8dee8;
            --mq-text: #172033;
            --mq-muted: #667085;
            --mq-accent: #0f766e;
            --mq-accent-strong: #115e59;
            --mq-warn: #b45309;
            --mq-danger: #b42318;
        }

        .stApp {
            background: var(--mq-bg);
            color: var(--mq-text);
        }

        .block-container {
            padding-top: 1.25rem;
            padding-bottom: 2rem;
            max-width: 1440px;
        }

        .mq-header {
            background: var(--mq-surface);
            border: 1px solid var(--mq-border);
            border-radius: 8px;
            padding: 18px 22px;
            margin-bottom: 16px;
        }

        .mq-title {
            margin: 0;
            font-size: 1.55rem;
            font-weight: 700;
            letter-spacing: 0;
        }

        .mq-subtitle {
            margin: 6px 0 0 0;
            color: var(--mq-muted);
            font-size: 0.94rem;
        }

        div[data-testid="stMetric"] {
            background: var(--mq-surface);
            border: 1px solid var(--mq-border);
            border-radius: 8px;
            padding: 14px 16px;
        }

        div[data-testid="stMetric"] label {
            color: var(--mq-muted) !important;
            font-size: 0.82rem !important;
        }

        div[data-testid="stMetricValue"] {
            color: var(--mq-text);
            font-size: 1.28rem;
            font-weight: 700;
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: 6px;
            background: transparent;
            border-bottom: 1px solid var(--mq-border);
        }

        .stTabs [data-baseweb="tab"] {
            height: 40px;
            padding: 0 16px;
            border-radius: 8px 8px 0 0;
            color: var(--mq-muted);
            font-weight: 600;
        }

        .stTabs [aria-selected="true"] {
            background: var(--mq-surface-muted);
            color: var(--mq-accent-strong) !important;
        }

        .stButton > button {
            border-radius: 6px;
            border: 1px solid var(--mq-border);
            font-weight: 650;
        }

        .stButton > button[kind="primary"] {
            background: var(--mq-accent);
            border-color: var(--mq-accent);
        }

        .stButton > button:hover {
            border-color: var(--mq-accent);
            color: var(--mq-accent-strong);
        }

        div[data-testid="stExpander"] {
            background: var(--mq-surface);
            border: 1px solid var(--mq-border);
            border-radius: 8px;
        }

        div[data-testid="stAlert"] {
            border-radius: 8px;
            border: 1px solid var(--mq-border);
        }

        div[data-testid="stDataFrame"] {
            border: 1px solid var(--mq-border);
            border-radius: 8px;
            overflow: hidden;
        }

        h2, h3 {
            letter-spacing: 0;
        }

        .mq-panel-title {
            font-size: 1.02rem;
            font-weight: 700;
            margin: 8px 0 4px 0;
        }

        .mq-panel-note {
            color: var(--mq-muted);
            font-size: 0.9rem;
            margin: 0 0 10px 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_panel_heading(title: str, note: str = "") -> None:
    st.markdown(f'<div class="mq-panel-title">{title}</div>', unsafe_allow_html=True)
    if note:
        st.markdown(f'<div class="mq-panel-note">{note}</div>', unsafe_allow_html=True)


@dataclass
class AppParams:
    token: str
    http_url: str
    start_date: str
    end_date: str
    init_cash: float
    fees: float
    slippage: float
    small_cap_quantile: float
    min_turnover: float
    universe_size: int
    fast_window: int
    slow_window: int
    trail_stop: float
    mom_window: int
    top_pct: float
    rsi_window: int
    rsi_buy: float
    rsi_sell: float
    download_workers: int
    ts_min_interval_sec: float = 0.15
    batch_trade_date_max_days: int = 7
    batch_ticker_chunk_size: int = 200
    batch_min_tickers: int = 10


class TeaJoinClient:
    def __init__(self, token: str, http_url: str, timeout: int = DEFAULT_TEAJOIN_TIMEOUT):
        self.token = str(token).strip()
        self.http_url = str(http_url).strip().rstrip("/")
        self.timeout = int(timeout)

    def query(self, api_name, fields="", **kwargs):
        # Keep parity with tushare.pro DataApi behavior.
        kwargs.setdefault("ts_type_name", self.http_url)
        req_params = {
            "api_name": api_name,
            "token": self.token,
            "params": kwargs,
            "fields": fields,
        }
        response = requests.post(
            f"{self.http_url}/{api_name}",
            json=req_params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("code", -1) != 0:
            raise RuntimeError(result.get("msg", f"TeaJoin request failed: {api_name}"))

        data = result.get("data") or {}
        columns = data.get("fields") or []
        items = data.get("items") or []
        if not columns:
            return pd.DataFrame()
        return pd.DataFrame(items, columns=columns)

    def __getattr__(self, name):
        from functools import partial

        return partial(self.query, name)


def to_ts_code(ticker: str) -> str:
    code = str(ticker).split(".")[0].zfill(6)
    suffix = str(ticker).split(".")[-1].upper() if "." in str(ticker) else ""
    exchange_map = {"SS": "SH", "SH": "SH", "SZ": "SZ", "BJ": "BJ"}
    exchange = exchange_map.get(suffix, "SZ")
    return f"{code}.{exchange}"


def to_ticker(ts_code: str) -> str:
    return str(ts_code).replace(".SH", ".SS").replace(".SZ", ".SZ")


def is_transient_download_error(exc: Exception) -> bool:
    if isinstance(exc, (RemoteDisconnected, IncompleteRead, ProtocolError, RequestsConnectionError, ReadTimeout)):
        return True
    if isinstance(exc, HTTPError) and getattr(getattr(exc, "response", None), "status_code", None) is not None:
        status_code = int(exc.response.status_code)
        if status_code == 429 or status_code >= 500:
            return True
    message = str(exc)
    transient_tokens = [
        "Connection aborted",
        "Remote end closed connection",
        "IncompleteRead",
        "Connection broken",
        "Read timed out",
        "EOF occurred in violation of protocol",
    ]
    return any(token in message for token in transient_tokens)


def is_rate_limit_error(exc: Exception) -> bool:
    if isinstance(exc, HTTPError) and getattr(getattr(exc, "response", None), "status_code", None) is not None:
        return int(exc.response.status_code) == 429
    message = str(exc)
    tokens = ["429", "Too Many Requests", "每分钟最多访问", "频次", "rate limit"]
    return any(token in message for token in tokens)


def ts_call_with_retry(fn, max_retry: int = 3, wait_sec: int = 3):
    global _TS_LAST_CALL_TS

    last_err = None
    for i in range(max_retry):
        try:
            # Apply process-wide pacing across worker threads to reduce API burst.
            with _TS_CALL_LOCK:
                now_ts = time.time()
                sleep_needed = TS_MIN_INTERVAL_SEC - (now_ts - _TS_LAST_CALL_TS)
                if sleep_needed > 0:
                    time.sleep(sleep_needed)
                _TS_LAST_CALL_TS = time.time()
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if (is_rate_limit_error(exc) or is_transient_download_error(exc)) and i < max_retry - 1:
                # Exponential backoff for 429, linear fallback for transient connection issues.
                if is_rate_limit_error(exc):
                    backoff = max(float(wait_sec), 2.0) * (2 ** i)
                else:
                    backoff = float(wait_sec) * (i + 1)
                jitter = random.uniform(0, 0.8)
                time.sleep(backoff + jitter)
                continue
            raise
    raise RuntimeError(f"Tushare request failed: {last_err}")


def set_ts_min_interval_sec(value: float) -> None:
    global TS_MIN_INTERVAL_SEC
    try:
        TS_MIN_INTERVAL_SEC = max(0.0, float(value))
    except Exception:
        TS_MIN_INTERVAL_SEC = 1.2


def _chunk_list(values: List[str], chunk_size: int) -> List[List[str]]:
    size = max(1, int(chunk_size))
    return [values[i : i + size] for i in range(0, len(values), size)]


def get_open_trade_dates_in_range(pro, start_date_str: str, end_date_str: str) -> List[str]:
    start_compact = pd.Timestamp(start_date_str).strftime("%Y%m%d")
    end_compact = pd.Timestamp(end_date_str).strftime("%Y%m%d")
    try:
        cal = ts_call_with_retry(
            lambda: pro.trade_cal(
                exchange="SSE",
                start_date=start_compact,
                end_date=end_compact,
                fields="cal_date,is_open",
            ),
            max_retry=2,
            wait_sec=2,
        )
        if cal is None or cal.empty or ("cal_date" not in cal.columns) or ("is_open" not in cal.columns):
            return []
        open_days = cal[cal["is_open"] == 1]["cal_date"].astype(str).tolist()
        return sorted(open_days)
    except Exception:
        return []


def fetch_prices_by_trade_date_batches(
    pro,
    ticker_start_map: Dict[str, pd.Timestamp],
    target_end: pd.Timestamp,
    ticker_chunk_size: int,
    status_text=None,
    stage_label: str = "更新",
    cancel_event=None,
) -> Tuple[Dict[str, pd.Series], Dict[str, int]]:
    if not ticker_start_map:
        return {}, {"batch_requests": 0, "batch_rows": 0, "batch_days": 0, "batch_cancelled": 0}

    min_start = min(ticker_start_map.values())
    trade_days = get_open_trade_dates_in_range(
        pro,
        start_date_str=min_start.strftime("%Y-%m-%d"),
        end_date_str=target_end.strftime("%Y-%m-%d"),
    )
    if not trade_days:
        return {}, {"batch_requests": 0, "batch_rows": 0, "batch_days": 0, "batch_cancelled": 0}

    ts_code_to_ticker = {to_ts_code(ticker): ticker for ticker in ticker_start_map.keys()}
    all_ts_codes = list(ts_code_to_ticker.keys())
    code_chunks = _chunk_list(all_ts_codes, ticker_chunk_size)
    bucket: Dict[str, List[Tuple[pd.Timestamp, float]]] = {}
    request_count = 0
    row_count = 0
    cancelled = False
    full_day_hits = 0

    for day in trade_days:
        day_ts = pd.Timestamp(day)
        eligible_codes = [code for code, ticker in ts_code_to_ticker.items() if ticker_start_map[ticker] <= day_ts]
        if not eligible_codes:
            continue

        def _collect_rows(df_in: pd.DataFrame) -> int:
            if df_in is None or df_in.empty:
                return 0
            use = df_in.copy()
            if ("ts_code" not in use.columns) or ("trade_date" not in use.columns) or ("close" not in use.columns):
                return 0
            use["trade_date"] = pd.to_datetime(use["trade_date"], errors="coerce")
            use["close"] = pd.to_numeric(use["close"], errors="coerce")
            use = use.dropna(subset=["trade_date", "close", "ts_code"])
            if use.empty:
                return 0
            use = use[use["ts_code"].astype(str).isin(set(eligible_codes))]
            if use.empty:
                return 0
            use["ticker"] = use["ts_code"].astype(str).map(to_ticker)
            hit_rows = 0
            for ticker, grp in use.groupby("ticker"):
                if ticker not in ticker_start_map:
                    continue
                start_ts = ticker_start_map[ticker]
                grp = grp[pd.to_datetime(grp["trade_date"], errors="coerce") >= start_ts]
                rows = list(zip(pd.to_datetime(grp["trade_date"]), pd.to_numeric(grp["close"], errors="coerce")))
                if not rows:
                    continue
                bucket.setdefault(ticker, []).extend(rows)
                hit_rows += len(rows)
            return int(hit_rows)

        # Preferred path: one full-market request per trade day.
        day_success = False
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        request_count += 1
        try:
            day_df = ts_call_with_retry(
                lambda trade_date=day: pro.daily(
                    trade_date=trade_date,
                    fields="ts_code,trade_date,close",
                ),
                max_retry=3,
                wait_sec=2,
            )
            hit = _collect_rows(day_df)
            row_count += hit
            if hit > 0:
                day_success = True
                full_day_hits += 1
        except Exception:
            day_success = False

        if not day_success:
            eligible_set = set(eligible_codes)
            day_chunks = [chunk for chunk in code_chunks if any(code in eligible_set for code in chunk)]
            for code_chunk in day_chunks:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                request_count += 1
                try:
                    df = ts_call_with_retry(
                        lambda chunk=code_chunk, trade_date=day: pro.daily(
                            ts_code=",".join(chunk),
                            trade_date=trade_date,
                            fields="ts_code,trade_date,close",
                        ),
                        max_retry=3,
                        wait_sec=2,
                    )
                except Exception:
                    continue
                row_count += _collect_rows(df)

        if cancelled:
            break

    out: Dict[str, pd.Series] = {}
    for ticker, rows in bucket.items():
        if not rows:
            continue
        rows_df = pd.DataFrame(rows, columns=["trade_date", "close"]).dropna(subset=["trade_date", "close"])
        if rows_df.empty:
            continue
        rows_df = rows_df.drop_duplicates(subset=["trade_date"], keep="last").sort_values("trade_date")
        s = pd.to_numeric(rows_df["close"], errors="coerce")
        s.index = pd.to_datetime(rows_df["trade_date"])
        s = s.dropna().rename(ticker)
        if not s.empty:
            out[ticker] = s

    if status_text is not None:
        status_text.markdown(
            f"**{stage_label}中**：按交易日批量抓取完成，交易日 {len(trade_days)} 天，请求 {request_count} 次，命中 {len(out)} 只"
        )

    return out, {
        "batch_requests": int(request_count),
        "batch_rows": int(row_count),
        "batch_days": int(len(trade_days)),
        "batch_full_day_hits": int(full_day_hits),
        "batch_cancelled": 1 if cancelled else 0,
    }


def financial_period_candidates(end_date_str: str) -> List[str]:
    dt = pd.Timestamp(end_date_str)
    candidates = [
        pd.Timestamp(dt.year, 9, 30),
        pd.Timestamp(dt.year, 6, 30),
        pd.Timestamp(dt.year, 3, 31),
        pd.Timestamp(dt.year - 1, 12, 31),
    ]
    return [x.strftime("%Y%m%d") for x in candidates if x <= dt]


def init_tushare_client(token: str, http_url: str):
    return init_tushare_pro(token=token, http_url=http_url)


def load_price_cache() -> pd.DataFrame:
    if not PRICE_CACHE_FILE.exists():
        return pd.DataFrame()
    try:
        cache_df = pd.read_pickle(PRICE_CACHE_FILE)
    except Exception:
        return pd.DataFrame()
    if not isinstance(cache_df, pd.DataFrame):
        return pd.DataFrame()
    if cache_df.empty:
        return cache_df
    cache_df = cache_df.copy()
    cache_df.index = pd.to_datetime(cache_df.index)
    cache_df = cache_df.sort_index()
    return cache_df


def save_price_cache(cache_df: pd.DataFrame) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_df.sort_index().to_pickle(PRICE_CACHE_FILE)


def load_pool_cache() -> pd.DataFrame:
    if not POOL_CACHE_FILE.exists():
        # Legacy fallback: if old runs only produced CSV, reuse it as pool cache.
        legacy_csv = OUTPUT_DIR / "小盘池样本清单.csv"
        if legacy_csv.exists():
            try:
                pool_df = pd.read_csv(legacy_csv)
                if isinstance(pool_df, pd.DataFrame) and (not pool_df.empty):
                    if "ticker" in pool_df.columns:
                        save_pool_cache(pool_df)
                        return pool_df
            except Exception:
                return pd.DataFrame()
        return pd.DataFrame()
    try:
        pool_df = pd.read_pickle(POOL_CACHE_FILE)
    except Exception:
        return pd.DataFrame()
    if not isinstance(pool_df, pd.DataFrame):
        return pd.DataFrame()
    return pool_df.copy()


def save_pool_cache(pool_df: pd.DataFrame) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pool_df.to_pickle(POOL_CACHE_FILE)


def load_token_cache() -> str:
    if not TOKEN_CACHE_FILE.exists():
        return DEFAULT_TUSHARE_TOKEN
    try:
        value = TOKEN_CACHE_FILE.read_text(encoding="utf-8").strip()
        return value or DEFAULT_TUSHARE_TOKEN
    except Exception:
        return DEFAULT_TUSHARE_TOKEN


def save_token_cache(token: str) -> None:
    token = str(token).strip()
    if not token:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_CACHE_FILE.write_text(token, encoding="utf-8")


def cache_date_range(cache_df: pd.DataFrame) -> Tuple[str, str]:
    if cache_df is None or cache_df.empty:
        return "无", "无"
    return cache_df.index.min().strftime("%Y-%m-%d"), cache_df.index.max().strftime("%Y-%m-%d")


def analyze_cache_completeness(
    price_cache_df: pd.DataFrame,
    pool_df: pd.DataFrame | None = None,
    tickers: List[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Dict[str, object]:
    if price_cache_df is None or not isinstance(price_cache_df, pd.DataFrame):
        price_cache_df = pd.DataFrame()
    else:
        price_cache_df = price_cache_df.copy()
        if not price_cache_df.empty:
            price_cache_df.index = pd.to_datetime(price_cache_df.index)
            price_cache_df = price_cache_df.sort_index()

    if tickers is not None:
        expected_tickers = [str(t) for t in tickers if str(t).strip()]
    elif pool_df is not None and isinstance(pool_df, pd.DataFrame) and "ticker" in pool_df.columns:
        expected_tickers = [str(t) for t in pool_df["ticker"].dropna().astype(str)]
    else:
        expected_tickers = [str(c) for c in price_cache_df.columns]

    expected_tickers = list(dict.fromkeys(expected_tickers))
    price_columns = [str(c) for c in price_cache_df.columns]
    price_column_set = set(price_columns)
    missing_tickers = [t for t in expected_tickers if t not in price_column_set]
    present_tickers = [t for t in expected_tickers if t in price_column_set]

    cache_range = cache_date_range(price_cache_df)
    summary: Dict[str, object] = {
        "expected_count": int(len(expected_tickers)),
        "price_ticker_count": int(len(price_columns)),
        "present_count": int(len(present_tickers)),
        "missing_count": int(len(missing_tickers)),
        "missing_tickers": missing_tickers,
        "coverage_pct": float(len(present_tickers) / len(expected_tickers) * 100) if expected_tickers else 0.0,
        "cache_start": cache_range[0],
        "cache_end": cache_range[1],
        "cache_rows": int(price_cache_df.shape[0]),
        "usable_count": int(len(present_tickers)),
        "no_data_in_range_count": 0,
        "dropped_for_gaps_count": 0,
        "stale_count": 0,
        "stale_tickers": [],
    }

    if price_cache_df.empty or not present_tickers:
        return summary

    latest_per_col = price_cache_df[present_tickers].apply(
        lambda s: s.dropna().index.max() if s.notna().any() else pd.NaT
    )
    global_max = price_cache_df.index.max()
    stale_cutoff = global_max - pd.Timedelta(days=7)
    stale = latest_per_col[(latest_per_col.notna()) & (latest_per_col < stale_cutoff)].sort_values()
    summary["stale_count"] = int(len(stale))
    summary["stale_tickers"] = [str(x) for x in stale.index.tolist()]

    if start_date and end_date:
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        window_df = price_cache_df.loc[(price_cache_df.index >= start_ts) & (price_cache_df.index <= end_ts), present_tickers].copy()
        any_data_cols = [str(c) for c in window_df.columns if window_df[c].notna().any()]
        no_data_cols = [t for t in present_tickers if t not in set(any_data_cols)]
        usable_cols = [str(c) for c in window_df.ffill().dropna(axis=1, how="any").columns]
        summary["usable_count"] = int(len(usable_cols))
        summary["no_data_in_range_count"] = int(len(no_data_cols))
        summary["dropped_for_gaps_count"] = int(max(0, len(any_data_cols) - len(usable_cols)))
        summary["no_data_in_range_tickers"] = no_data_cols[:20]
        summary["dropped_for_gaps_tickers"] = [t for t in any_data_cols if t not in set(usable_cols)][:20]

    return summary


def render_cache_completeness(summary: Dict[str, object], title: str = "数据完整性") -> None:
    st.markdown(f"### {title}")
    expected_count = int(summary.get("expected_count", 0))
    present_count = int(summary.get("present_count", 0))
    missing_count = int(summary.get("missing_count", 0))
    usable_count = int(summary.get("usable_count", present_count))
    coverage_pct = float(summary.get("coverage_pct", 0.0))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("覆盖率", f"{coverage_pct:.1f}%")
    c2.metric("已缓存/应缓存", f"{present_count}/{expected_count}")
    c3.metric("区间可回测", f"{usable_count}/{expected_count}")
    c4.metric("缓存日期", f"{summary.get('cache_start', '无')} ~ {summary.get('cache_end', '无')}")

    no_data_count = int(summary.get("no_data_in_range_count", 0))
    gap_count = int(summary.get("dropped_for_gaps_count", 0))
    stale_count = int(summary.get("stale_count", 0))

    if expected_count == 0:
        st.info("暂无可检查的股票列表。")
    elif missing_count == 0 and no_data_count == 0 and gap_count == 0 and stale_count == 0:
        st.success("当前检查范围内的数据完整，可以作为回测输入。")
    elif coverage_pct >= 95 and usable_count > 0:
        st.warning("数据基本可用，但存在缺失、日期落后或区间内不可用标的；回测结果会只基于可用标的。")
    else:
        st.error("数据不完整程度较高，建议先更新或重建缓存后再回测。")

    detail_parts = []
    if missing_count > 0:
        detail_parts.append(f"价格缓存缺失 {missing_count} 只")
    if no_data_count > 0:
        detail_parts.append(f"当前日期区间内无价格 {no_data_count} 只")
    if gap_count > 0:
        detail_parts.append(f"因区间内存在缺口被剔除 {gap_count} 只")
    if stale_count > 0:
        detail_parts.append(f"最新日期早于全局最新缓存日期 {stale_count} 只")
    if detail_parts:
        st.caption("；".join(detail_parts))

    missing_tickers = summary.get("missing_tickers", [])
    if isinstance(missing_tickers, list) and missing_tickers:
        with st.expander("查看缺失标的样本"):
            st.write("、".join(str(x) for x in missing_tickers[:80]))

    stale_tickers = summary.get("stale_tickers", [])
    if isinstance(stale_tickers, list) and stale_tickers:
        with st.expander("查看落后标的样本"):
            st.write("、".join(str(x) for x in stale_tickers[:80]))


def analyze_data_readiness(price_cache_df: pd.DataFrame, pool_df: pd.DataFrame) -> Dict[str, object]:
    cache_summary = analyze_cache_completeness(price_cache_df=price_cache_df, pool_df=pool_df)
    readiness: Dict[str, object] = {
        "price_ok": False,
        "fundamental_ok": False,
        "factor_ok": False,
        "issues": [],
        "repair_actions": [],
        "fundamental_missing": {},
        "factor_status": {},
    }

    missing_count = int(cache_summary.get("missing_count", 0))
    stale_count = int(cache_summary.get("stale_count", 0))
    if missing_count == 0 and stale_count == 0 and (not price_cache_df.empty):
        readiness["price_ok"] = True
    else:
        readiness["issues"].append(f"行情价格缓存存在缺口：完全缺失 {missing_count} 只，日期落后 {stale_count} 只。")
        readiness["repair_actions"].append("使用“修复行情价格缓存”。")

    required_fundamental_cols = ["ROE", "GROWTH", "PE", "PB", "成交额"]
    fundamental_missing: Dict[str, int] = {}
    pool_total = int(len(pool_df)) if isinstance(pool_df, pd.DataFrame) else 0
    for col in required_fundamental_cols:
        if pool_df is None or pool_df.empty or col not in pool_df.columns:
            fundamental_missing[col] = pool_total
        else:
            fundamental_missing[col] = int(pool_df[col].isna().sum())
    readiness["fundamental_missing"] = fundamental_missing
    required_total_missing = sum(fundamental_missing.get(c, 0) for c in ["ROE", "GROWTH", "PB", "成交额"])
    if pool_total > 0 and required_total_missing <= max(5, int(pool_total * 0.02)):
        readiness["fundamental_ok"] = True
    else:
        readiness["issues"].append(
            "基础面字段存在缺口："
            + "，".join(f"{k} 缺失 {v}" for k, v in fundamental_missing.items() if v > 0)
            + "。PE 为空常见于亏损公司，不一定代表缓存错误。"
        )
        if fundamental_missing.get("ROE", 0) > 0 or fundamental_missing.get("GROWTH", 0) > 0:
            readiness["repair_actions"].append("使用“刷新基础面字段缓存”。")
        if any(fundamental_missing.get(c, 0) > 0 for c in ["PB", "成交额"]):
            readiness["repair_actions"].append("使用“同步到最新”刷新股票池快照。")

    price_days = int(price_cache_df.shape[0]) if isinstance(price_cache_df, pd.DataFrame) else 0
    enough_price_data = (not price_cache_df.empty) and price_days >= 121 and float(cache_summary.get("coverage_pct", 0.0)) >= 95.0
    factor_status = {
        "动量": enough_price_data,
        "质量": fundamental_missing.get("ROE", pool_total) < pool_total,
        "估值": fundamental_missing.get("PE", pool_total) < pool_total and fundamental_missing.get("PB", pool_total) < pool_total,
        "成长": fundamental_missing.get("GROWTH", pool_total) < pool_total,
        "风险控制": enough_price_data,
        "资金情绪": fundamental_missing.get("成交额", pool_total) < pool_total,
    }
    readiness["factor_status"] = factor_status
    readiness["factor_ok"] = all(bool(v) for v in factor_status.values())
    if not readiness["factor_ok"]:
        unavailable = [k for k, v in factor_status.items() if not v]
        readiness["issues"].append("以下因子当前数据不足，筛选科学性会下降：" + "、".join(unavailable))
    return readiness


def render_data_readiness(readiness: Dict[str, object], title: str = "数据缺口诊断") -> None:
    st.markdown(f"### {title}")
    c1, c2, c3 = st.columns(3)
    c1.metric("行情价格", "可用" if readiness.get("price_ok") else "需修复")
    c2.metric("基础面字段", "可用" if readiness.get("fundamental_ok") else "需刷新")
    c3.metric("筛选因子", "可用" if readiness.get("factor_ok") else "不完整")

    issues = readiness.get("issues", [])
    if isinstance(issues, list) and issues:
        for issue in issues:
            st.warning(str(issue))
    else:
        st.success("当前缓存可以支撑已实现因子的筛选和回测。")

    actions = readiness.get("repair_actions", [])
    if isinstance(actions, list) and actions:
        st.info("建议修复：" + " ".join(dict.fromkeys(str(x) for x in actions)))

    factor_status = readiness.get("factor_status", {})
    if isinstance(factor_status, dict) and factor_status:
        with st.expander("查看因子可用性"):
            status_df = pd.DataFrame(
                [{"因子": name, "状态": "可用" if ok else "数据不足"} for name, ok in factor_status.items()]
            )
            st.dataframe(status_df, width="stretch", hide_index=True)


def get_last_trade_date(pro, end_date_str: str) -> str:
    try:
        cal = ts_call_with_retry(
            lambda: pro.trade_cal(
                exchange="SSE",
                start_date="20000101",
                end_date=end_date_str,
                fields="cal_date,is_open",
            ),
            max_retry=2,
            wait_sec=2,
        )
        if cal is not None and not cal.empty and "is_open" in cal.columns:
            cal = cal[cal["is_open"] == 1]
            if not cal.empty:
                return str(cal["cal_date"].max())
    except Exception:
        pass
    return end_date_str


def _cap_incomplete_cn_trading_day(end_date_str: str, close_time: dt_time = dt_time(15, 30)) -> str:
    """A 股未收盘前不把今天作为可下载的完整日线日期。"""
    end_ts = pd.Timestamp(end_date_str)
    try:
        now_cn = pd.Timestamp.now(tz="Asia/Shanghai")
    except Exception:
        now_cn = pd.Timestamp.now()
    if end_ts.date() >= now_cn.date() and now_cn.time() < close_time:
        return (pd.Timestamp(now_cn.date()) - pd.Timedelta(days=1)).strftime("%Y%m%d")
    return end_ts.strftime("%Y%m%d")


def get_latest_available_trade_date(pro, end_date_str: str, lookback_days: int = 10) -> str:
    end_date_str = _cap_incomplete_cn_trading_day(end_date_str)
    recent_days = get_recent_open_trade_dates(pro, end_date_str, lookback_days=lookback_days)
    if not recent_days:
        return get_last_trade_date(pro, end_date_str)

    for trade_date in recent_days:
        try:
            snap = ts_call_with_retry(
                lambda td=trade_date: pro.daily(
                    trade_date=td,
                    fields="ts_code,trade_date,close",
                ),
                max_retry=2,
                wait_sec=2,
            )
            if snap is not None and not snap.empty and "ts_code" in snap.columns:
                return trade_date
        except Exception:
            continue

    return recent_days[-1]


def get_recent_open_trade_dates(pro, end_date_str: str, lookback_days: int = 60) -> List[str]:
    end_ts = pd.Timestamp(end_date_str)
    start_str = (end_ts - pd.Timedelta(days=max(lookback_days, 10))).strftime("%Y%m%d")
    try:
        cal = ts_call_with_retry(
            lambda: pro.trade_cal(
                exchange="SSE",
                start_date=start_str,
                end_date=end_ts.strftime("%Y%m%d"),
                fields="cal_date,is_open",
            ),
            max_retry=2,
            wait_sec=2,
        )
        if cal is None or cal.empty or ("cal_date" not in cal.columns) or ("is_open" not in cal.columns):
            return []
        open_days = cal[cal["is_open"] == 1]["cal_date"].astype(str).tolist()
        return sorted(open_days, reverse=True)
    except Exception:
        return []


def fetch_daily_basic_snapshot(pro, trade_date: str, fields: str) -> pd.DataFrame:
    if str(trade_date).strip():
        try:
            snap = ts_call_with_retry(
                lambda: pro.daily_basic(trade_date=str(trade_date).strip(), fields=fields),
                max_retry=3,
                wait_sec=2,
            )
            if snap is not None and not snap.empty:
                return snap
        except Exception:
            pass

    # Fallback: pull a short date range and take the latest row per ts_code.
    end_ts = pd.Timestamp(trade_date)
    start_str = (end_ts - pd.Timedelta(days=45)).strftime("%Y%m%d")
    try:
        rng = ts_call_with_retry(
            lambda: pro.daily_basic(start_date=start_str, end_date=end_ts.strftime("%Y%m%d"), fields=f"trade_date,{fields}"),
            max_retry=3,
            wait_sec=2,
        )
        if rng is not None and not rng.empty and {"ts_code", "trade_date"}.issubset(rng.columns):
            rng = rng.copy()
            rng["trade_date"] = pd.to_datetime(rng["trade_date"], errors="coerce")
            rng = rng.dropna(subset=["trade_date"]).sort_values("trade_date")
            rng = rng.drop_duplicates(subset=["ts_code"], keep="last")
            return rng
    except Exception:
        pass

    return pd.DataFrame()


def fetch_financial_snapshot(pro, period_list: List[str], ts_codes: List[str]) -> pd.DataFrame:
    return fetch_financial_snapshot_for_codes(pro, period_list, ts_codes=ts_codes)


def chunk_items(items: List[str], chunk_size: int) -> List[List[str]]:
    chunk_size = max(1, int(chunk_size))
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def fetch_financial_snapshot_for_codes(
    pro,
    period_list: List[str],
    ts_codes: List[str],
    batch_size: int = 80,
) -> pd.DataFrame:
    ts_codes = [str(x).strip() for x in ts_codes if str(x).strip()]
    ts_codes = list(dict.fromkeys(ts_codes))
    if not ts_codes:
        return pd.DataFrame(columns=["ts_code", "ROE", "GROWTH"])

    frames = []
    for period in period_list:
        for code_batch in chunk_items(ts_codes, batch_size):
            batch_arg = ",".join(code_batch)
            try:
                fin = ts_call_with_retry(
                    lambda: pro.fina_indicator(
                        ts_code=batch_arg,
                        period=period,
                        fields="ts_code,end_date,roe,or_yoy",
                    ),
                    max_retry=2,
                    wait_sec=2,
                )
                if fin is not None and not fin.empty:
                    frames.append(fin)
            except Exception:
                continue

    if not frames:
        return pd.DataFrame(columns=["ts_code", "ROE", "GROWTH"])

    fin_all = pd.concat(frames, ignore_index=True)
    if "ts_code" not in fin_all.columns:
        return pd.DataFrame(columns=["ts_code", "ROE", "GROWTH"])

    fin_all = fin_all.copy()
    if "end_date" in fin_all.columns:
        fin_all["end_date"] = pd.to_datetime(fin_all["end_date"], errors="coerce")
        fin_all = fin_all.sort_values("end_date")
    fin_all = fin_all.drop_duplicates(subset=["ts_code"], keep="last")
    fin_all["ROE"] = pd.to_numeric(fin_all.get("roe"), errors="coerce")
    fin_all["GROWTH"] = pd.to_numeric(fin_all.get("or_yoy"), errors="coerce")
    return fin_all[["ts_code", "ROE", "GROWTH"]].reset_index(drop=True)


def fetch_stock_pool(pro, params: AppParams) -> pd.DataFrame:
    end_str = pd.Timestamp(params.end_date).strftime("%Y%m%d")
    trade_date = get_latest_available_trade_date(pro, end_str)

    basic = ts_call_with_retry(
        lambda: pro.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,name,industry,list_date")
    )
    if basic is None or basic.empty:
        raise RuntimeError("stock_basic returned empty")

    daily = fetch_daily_basic_snapshot(
        pro,
        trade_date=trade_date,
        fields="ts_code,circ_mv,turnover_rate_f,pe_ttm,pb",
    )
    if daily is None or daily.empty:
        raise RuntimeError("daily_basic returned empty, check token permissions or date")

    periods = financial_period_candidates(params.end_date)
    fin = fetch_financial_snapshot(pro, periods, basic["ts_code"].dropna().astype(str).tolist())

    pool = basic.merge(daily, on="ts_code", how="inner")
    if not fin.empty:
        pool = pool.merge(fin, on="ts_code", how="left")
    else:
        pool["ROE"] = np.nan
        pool["GROWTH"] = np.nan

    pool["ticker"] = pool["ts_code"].map(to_ticker)
    pool["名称"] = pool["name"].astype(str)
    pool["行业"] = pool.get("industry", "").astype(str)
    pool["上市日期"] = pool.get("list_date", "").astype(str)
    pool["交易所"] = pool["ticker"].apply(lambda x: str(x).split(".")[-1] if "." in str(x) else "")
    pool["流通市值"] = pd.to_numeric(pool["circ_mv"], errors="coerce") * 1e4
    pool["成交额"] = pd.to_numeric(pool["turnover_rate_f"], errors="coerce")
    pool["PE"] = pd.to_numeric(pool["pe_ttm"], errors="coerce")
    pool["PB"] = pd.to_numeric(pool["pb"], errors="coerce")
    pool["最新收盘价"] = np.nan

    pool = pool.dropna(subset=["流通市值"]).copy()
    pool = pool.sort_values(["流通市值", "成交额"], ascending=[True, False])
    pool = pool.drop_duplicates(subset=["ticker"])

    out_cols = ["ticker", "名称", "行业", "上市日期", "交易所", "PE", "PB", "ROE", "GROWTH", "流通市值", "成交额", "最新收盘价"]
    return pool[out_cols].reset_index(drop=True)


def filter_pool_by_rules(
    pool_df: pd.DataFrame,
    small_cap_quantile: float,
    min_turnover: float,
    universe_size: int,
    enable_price_range: bool = False,
    price_min: float = 0.0,
    price_max: float = 0.0,
    enable_pe_cap: bool = False,
    pe_cap: float = 0.0,
    enable_pb_cap: bool = False,
    pb_cap: float = 0.0,
    enable_roe_floor: bool = False,
    roe_floor: float = 0.0,
    enable_growth_floor: bool = False,
    growth_floor: float = 0.0,
    enable_list_age_floor: bool = False,
    list_age_floor: int = 0,
    reference_date: str | None = None,
    enable_industry_exclude: bool = False,
    industry_exclude_keywords: str = "",
) -> pd.DataFrame:
    if pool_df is None or pool_df.empty:
        raise RuntimeError("股票池缓存为空，请先点击'更新数据到今天（增量）'或'重建缓存（全量)'")

    df = pool_df.copy()
    if "ticker" not in df.columns:
        raise RuntimeError("股票池缓存格式不正确，请先重建缓存")

    if "流通市值" in df.columns and df["流通市值"].notna().any():
        cap_threshold = df["流通市值"].quantile(small_cap_quantile)
        df = df[df["流通市值"] <= cap_threshold]

    if min_turnover > 0 and "成交额" in df.columns:
        df = df[df["成交额"].fillna(0) >= min_turnover]

    if enable_price_range and "最新收盘价" in df.columns:
        if price_min > 0:
            df = df[df["最新收盘价"].fillna(0) >= price_min]
        if price_max > 0:
            df = df[df["最新收盘价"].fillna(np.inf) <= price_max]

    if enable_pe_cap and "PE" in df.columns:
        df = df[df["PE"].fillna(np.inf) <= pe_cap]

    if enable_pb_cap and "PB" in df.columns:
        df = df[df["PB"].fillna(np.inf) <= pb_cap]

    if enable_roe_floor and "ROE" in df.columns:
        df = df[df["ROE"].fillna(-np.inf) >= roe_floor]

    if enable_growth_floor and "GROWTH" in df.columns:
        df = df[df["GROWTH"].fillna(-np.inf) >= growth_floor]

    if enable_list_age_floor and "上市日期" in df.columns:
        ref_date = pd.Timestamp(reference_date or pd.Timestamp.today().strftime("%Y-%m-%d"))
        list_dates = pd.to_datetime(df["上市日期"], errors="coerce")
        list_age_days = (ref_date - list_dates).dt.days
        df = df[list_age_days.fillna(-np.inf) >= int(list_age_floor)]

    if enable_industry_exclude and "行业" in df.columns and industry_exclude_keywords.strip():
        keywords = [k.strip() for k in industry_exclude_keywords.replace("，", ",").split(",") if k.strip()]
        if keywords:
            mask = pd.Series(True, index=df.index)
            for kw in keywords:
                mask &= ~df["行业"].astype(str).str.contains(kw, case=False, na=False)
            df = df[mask]

    sort_cols = [c for c in ["流通市值", "成交额"] if c in df.columns]
    if sort_cols:
        ascending = [True if c == "流通市值" else False for c in sort_cols]
        df = df.sort_values(sort_cols, ascending=ascending)

    df = df.drop_duplicates(subset=["ticker"]).head(universe_size).reset_index(drop=True)
    if df.empty:
        raise RuntimeError("按当前筛选条件，缓存股票池为空，请放宽筛选条件或先更新缓存")
    return df


def filter_pool_from_cache(pool_df: pd.DataFrame, params: AppParams) -> pd.DataFrame:
    return filter_pool_by_rules(
        pool_df=pool_df,
        small_cap_quantile=params.small_cap_quantile,
        min_turnover=params.min_turnover,
        universe_size=params.universe_size,
    )


def build_pool_from_price_cache(price_cache_df: pd.DataFrame) -> pd.DataFrame:
    if price_cache_df is None or price_cache_df.empty:
        return pd.DataFrame()
    tickers = [str(c) for c in price_cache_df.columns]
    if not tickers:
        return pd.DataFrame()
    pool_df = pd.DataFrame({
        "ticker": tickers,
        "名称": tickers,
        "行业": "",
        "上市日期": "",
        "交易所": "",
        "PE": np.nan,
        "PB": np.nan,
        "ROE": np.nan,
        "GROWTH": np.nan,
        "流通市值": np.nan,
        "成交额": np.nan,
        "最新收盘价": np.nan,
    })
    return pool_df


FACTOR_TEMPLATES: Dict[str, Dict[str, object]] = {
    "稳健质量股": {
        "weights": {"动量": 0.18, "质量": 0.34, "估值": 0.18, "成长": 0.10, "风险控制": 0.17, "资金情绪": 0.03},
        "filters": {"roe_floor": 8.0, "growth_floor": -15.0, "pe_cap": 60.0, "pb_cap": 6.0, "min_turnover": 0.15, "list_age_floor": 365},
    },
    "趋势质量股": {
        "weights": {"动量": 0.30, "质量": 0.30, "估值": 0.10, "成长": 0.15, "风险控制": 0.10, "资金情绪": 0.05},
        "filters": {"roe_floor": 8.0, "growth_floor": -20.0, "pe_cap": 120.0, "min_turnover": 0.2, "list_age_floor": 180},
    },
    "低估值修复股": {
        "weights": {"动量": 0.15, "质量": 0.25, "估值": 0.35, "成长": 0.10, "风险控制": 0.10, "资金情绪": 0.05},
        "filters": {"roe_floor": 3.0, "growth_floor": -40.0, "pe_cap": 60.0, "pb_cap": 4.0, "min_turnover": 0.1, "list_age_floor": 365},
    },
    "高成长强势股": {
        "weights": {"动量": 0.30, "质量": 0.20, "估值": 0.10, "成长": 0.25, "风险控制": 0.10, "资金情绪": 0.05},
        "filters": {"roe_floor": 5.0, "growth_floor": 10.0, "pe_cap": 180.0, "min_turnover": 0.3, "list_age_floor": 180},
    },
}


def normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    clean = {k: max(0.0, float(v)) for k, v in weights.items()}
    total = sum(clean.values())
    if total <= 0:
        return {k: 1.0 / max(1, len(clean)) for k in clean}
    return {k: v / total for k, v in clean.items()}


def group_percentile_score(df: pd.DataFrame, value_col: str, higher_is_better: bool = True) -> pd.Series:
    if value_col not in df.columns:
        return pd.Series(0.5, index=df.index)
    values = pd.to_numeric(df[value_col], errors="coerce")
    industry = df["行业"].fillna("未分类").astype(str) if "行业" in df.columns else pd.Series("未分类", index=df.index)
    ranked = values.groupby(industry).rank(pct=True, ascending=higher_is_better)
    global_ranked = values.rank(pct=True, ascending=higher_is_better)
    group_size = values.groupby(industry).transform("count")
    out = ranked.where(group_size >= 5, global_ranked)
    out = (out * 0.7 + global_ranked * 0.3).fillna(global_ranked).fillna(0.5)
    return out.clip(0.0, 1.0)


def minmax_score(values: pd.Series, higher_is_better: bool = True) -> pd.Series:
    values = pd.to_numeric(values, errors="coerce")
    finite = values.replace([np.inf, -np.inf], np.nan)
    min_val = finite.min(skipna=True)
    max_val = finite.max(skipna=True)
    if pd.isna(min_val) or pd.isna(max_val) or min_val == max_val:
        score = pd.Series(0.5, index=values.index)
    else:
        score = (finite - min_val) / (max_val - min_val)
    if not higher_is_better:
        score = 1.0 - score
    return score.fillna(0.5).clip(0.0, 1.0)


def calculate_price_factors(price_cache_df: pd.DataFrame, tickers: List[str], end_date: str) -> pd.DataFrame:
    out = pd.DataFrame({"ticker": list(dict.fromkeys([str(t) for t in tickers]))})
    if price_cache_df is None or price_cache_df.empty or out.empty:
        return out

    px = price_cache_df.copy()
    px.index = pd.to_datetime(px.index)
    px = px.sort_index()
    end_ts = pd.Timestamp(end_date)
    px = px.loc[px.index <= end_ts]
    available = [t for t in out["ticker"].tolist() if t in px.columns]
    if not available or px.empty:
        return out

    px = normalize_price_discontinuities(px[available]).ffill()
    last = px.iloc[-1]
    factor_map: Dict[str, pd.Series] = {}
    for window in [20, 60, 120]:
        if len(px) > window:
            factor_map[f"ret_{window}d"] = last / px.shift(window).iloc[-1] - 1.0
        else:
            factor_map[f"ret_{window}d"] = pd.Series(np.nan, index=available)

    high_window = min(252, len(px))
    if high_window > 1:
        high_52w = px.tail(high_window).max()
        factor_map["dist_52w_high"] = last / high_52w - 1.0
    factor_map["momentum_accel"] = factor_map.get("ret_120d", pd.Series(np.nan, index=available)) - factor_map.get("ret_20d", pd.Series(np.nan, index=available))
    factor_map["vol_60d"] = px.pct_change().tail(60).std() * np.sqrt(252)
    factor_map["vol_120d"] = px.pct_change().tail(120).std() * np.sqrt(252)
    dd_window = px.tail(120)
    factor_map["max_drawdown_120d"] = (dd_window / dd_window.cummax() - 1.0).min()

    factor_df = pd.DataFrame(factor_map).reset_index().rename(columns={"index": "ticker"})
    return out.merge(factor_df, on="ticker", how="left")


def apply_risk_filters(
    pool_df: pd.DataFrame,
    price_factor_df: pd.DataFrame,
    filters: Dict[str, object],
    reference_date: str,
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    df = pool_df.copy()
    start_count = len(df)
    removed: Dict[str, int] = {}

    def keep_mask(mask: pd.Series, reason: str) -> None:
        nonlocal df
        before = len(df)
        df = df[mask.reindex(df.index).fillna(False)].copy()
        removed[reason] = int(before - len(df))

    if "名称" in df.columns:
        name = df["名称"].astype(str)
        keep_mask(~name.str.contains("ST|退", case=False, na=False), "ST/退市风险")

    if bool(filters.get("exclude_bj", False)) and "交易所" in df.columns:
        keep_mask(df["交易所"].astype(str) != "BJ", "北交所")

    min_turnover = float(filters.get("min_turnover", 0.0))
    if min_turnover > 0 and "成交额" in df.columns:
        keep_mask(pd.to_numeric(df["成交额"], errors="coerce").fillna(0) >= min_turnover, "流动性过低")

    list_age_floor = int(filters.get("list_age_floor", 0))
    if list_age_floor > 0 and "上市日期" in df.columns:
        ref_date = pd.Timestamp(reference_date)
        list_dates = pd.to_datetime(df["上市日期"], errors="coerce")
        list_age_days = (ref_date - list_dates).dt.days
        keep_mask(list_age_days.fillna(-np.inf) >= list_age_floor, "上市时间过短")

    roe_floor = float(filters.get("roe_floor", -np.inf))
    if np.isfinite(roe_floor) and "ROE" in df.columns:
        keep_mask(pd.to_numeric(df["ROE"], errors="coerce").fillna(-np.inf) >= roe_floor, "ROE过低")

    growth_floor = float(filters.get("growth_floor", -np.inf))
    if np.isfinite(growth_floor) and "GROWTH" in df.columns:
        keep_mask(pd.to_numeric(df["GROWTH"], errors="coerce").fillna(-np.inf) >= growth_floor, "成长异常")

    pe_cap = float(filters.get("pe_cap", np.inf))
    if np.isfinite(pe_cap) and "PE" in df.columns:
        pe = pd.to_numeric(df["PE"], errors="coerce")
        keep_mask(pe.notna() & (pe > 0) & (pe <= pe_cap), "PE异常")

    pb_cap = float(filters.get("pb_cap", np.inf))
    if np.isfinite(pb_cap) and "PB" in df.columns:
        pb = pd.to_numeric(df["PB"], errors="coerce")
        keep_mask(pb.notna() & (pb > 0) & (pb <= pb_cap), "PB异常")

    if bool(filters.get("exclude_stale_price", True)) and not price_factor_df.empty:
        available = set(price_factor_df.loc[price_factor_df[["ret_20d", "ret_60d"]].notna().any(axis=1), "ticker"].astype(str))
        keep_mask(df["ticker"].astype(str).isin(available), "价格长期不可用")

    removed["保留"] = int(len(df))
    removed["过滤前"] = int(start_count)
    return df.reset_index(drop=True), removed


def build_factor_screen(
    pool_df: pd.DataFrame,
    price_cache_df: pd.DataFrame,
    weights: Dict[str, float],
    filters: Dict[str, object],
    top_n: int,
    reference_date: str,
    industry_neutral: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    if pool_df is None or pool_df.empty or "ticker" not in pool_df.columns:
        raise RuntimeError("股票池缓存为空，请先到“数据更新”页更新数据")

    df = pool_df.copy()
    df["ticker"] = df["ticker"].astype(str)
    price_factors = calculate_price_factors(price_cache_df, df["ticker"].tolist(), reference_date)
    filtered, removed = apply_risk_filters(df, price_factors, filters, reference_date)
    if filtered.empty:
        raise RuntimeError("风险过滤后候选池为空，请放宽硬性过滤条件")

    scored = filtered.merge(price_factors, on="ticker", how="left")
    if industry_neutral:
        score_fn = group_percentile_score
    else:
        def score_fn(d: pd.DataFrame, c: str, h: bool = True) -> pd.Series:
            if c not in d.columns:
                return pd.Series(0.5, index=d.index)
            return minmax_score(d[c], h)

    for factor_col in ["ret_20d", "ret_60d", "ret_120d", "dist_52w_high", "momentum_accel", "vol_60d", "vol_120d", "max_drawdown_120d"]:
        if factor_col not in scored.columns:
            scored[factor_col] = np.nan

    scored["行业动量"] = scored.groupby(scored.get("行业", pd.Series("未分类", index=scored.index)).fillna("未分类"))["ret_60d"].transform("median")
    scored["相对行业强度"] = pd.to_numeric(scored["ret_60d"], errors="coerce") - pd.to_numeric(scored["行业动量"], errors="coerce")

    scored["动量分"] = (
        score_fn(scored, "ret_20d", True) * 0.20
        + score_fn(scored, "ret_60d", True) * 0.30
        + score_fn(scored, "ret_120d", True) * 0.20
        + score_fn(scored, "dist_52w_high", True) * 0.15
        + score_fn(scored, "相对行业强度", True) * 0.10
        + score_fn(scored, "momentum_accel", True) * 0.05
    ) * 100
    scored["质量分"] = score_fn(scored, "ROE", True) * 100
    scored["估值分"] = (score_fn(scored, "PE", False) * 0.55 + score_fn(scored, "PB", False) * 0.45) * 100
    scored["成长分"] = score_fn(scored, "GROWTH", True) * 100
    scored["风险控制分"] = (
        score_fn(scored, "vol_60d", False) * 0.40
        + score_fn(scored, "vol_120d", False) * 0.30
        + score_fn(scored, "max_drawdown_120d", True) * 0.30
    ) * 100
    scored["资金情绪分"] = score_fn(scored, "成交额", True) * 100
    scored["行业内动量分位"] = group_percentile_score(scored, "ret_60d", True) * 100
    scored["行业内质量分位"] = group_percentile_score(scored, "ROE", True) * 100
    scored["行业内估值分位"] = group_percentile_score(scored, "PB", False) * 100

    pe_pressure = minmax_score(scored.get("PE", pd.Series(np.nan, index=scored.index)), True)
    pb_pressure = minmax_score(scored.get("PB", pd.Series(np.nan, index=scored.index)), True)
    scored["估值压力"] = (pe_pressure * 0.45 + pb_pressure * 0.55) * 100
    scored["波动风险"] = minmax_score(scored["vol_60d"], True) * 100
    scored["回撤风险"] = minmax_score(-pd.to_numeric(scored["max_drawdown_120d"], errors="coerce"), True) * 100
    scored["流动性风险"] = minmax_score(scored.get("成交额", pd.Series(np.nan, index=scored.index)), False) * 100
    scored["进攻分"] = (
        pd.to_numeric(scored["动量分"], errors="coerce").fillna(50) * 0.45
        + pd.to_numeric(scored["成长分"], errors="coerce").fillna(50) * 0.25
        + pd.to_numeric(scored["资金情绪分"], errors="coerce").fillna(50) * 0.15
        + pd.to_numeric(scored["质量分"], errors="coerce").fillna(50) * 0.15
    )
    scored["防守分"] = (
        pd.to_numeric(scored["质量分"], errors="coerce").fillna(50) * 0.35
        + pd.to_numeric(scored["估值分"], errors="coerce").fillna(50) * 0.25
        + pd.to_numeric(scored["风险控制分"], errors="coerce").fillna(50) * 0.30
        + (100 - pd.to_numeric(scored["流动性风险"], errors="coerce").fillna(50)) * 0.10
    )

    normalized_weights = normalize_weights(weights)
    scored["综合评分"] = sum(
        scored[f"{factor}分"].fillna(50.0) * weight for factor, weight in normalized_weights.items() if f"{factor}分" in scored.columns
    )

    def explain_row(row: pd.Series) -> str:
        reasons = []
        risks = []
        if row.get("动量分", 0) >= 75:
            reasons.append("动量行业前25%")
        if pd.notna(row.get("ROE")) and float(row.get("ROE")) >= 10:
            reasons.append("ROE较高")
        if row.get("质量分", 0) >= 70:
            reasons.append("质量因子靠前")
        if row.get("估值分", 0) >= 70:
            reasons.append("估值处于相对低位")
        if pd.notna(row.get("GROWTH")) and float(row.get("GROWTH")) >= 20:
            reasons.append("营收增长较强")
        if row.get("相对行业强度", 0) > 0:
            reasons.append("近期强于行业中位数")
        if row.get("风险控制分", 0) >= 70:
            reasons.append("波动和回撤较低")

        if pd.notna(row.get("vol_60d")) and float(row.get("vol_60d")) > 0.6:
            risks.append("近期波动率偏高")
        if pd.notna(row.get("max_drawdown_120d")) and float(row.get("max_drawdown_120d")) < -0.35:
            risks.append("120日回撤偏深")
        if pd.notna(row.get("PE")) and float(row.get("PE")) > 80:
            risks.append("PE偏高")
        if pd.notna(row.get("GROWTH")) and float(row.get("GROWTH")) < 0:
            risks.append("营收同比为负")
        if not risks:
            risks.append("暂未触发当前规则下的主要风险项")
        return "；".join(reasons[:4] or ["综合评分靠前"]) + " | 风险：" + "；".join(risks[:3])

    def style_tags(row: pd.Series) -> List[str]:
        tags: List[str] = []
        if row.get("动量分", 0) >= 75 and row.get("波动风险", 0) >= 65:
            tags.append("强趋势高波动")
        if row.get("成长分", 0) >= 70 and row.get("估值压力", 0) >= 65:
            tags.append("高估值成长")
        if row.get("估值分", 0) >= 70 and row.get("ret_60d", 0) > 0:
            tags.append("低估值修复")
        if row.get("质量分", 0) >= 70 and row.get("风险控制分", 0) >= 65:
            tags.append("稳健质量")
        if row.get("资金情绪分", 0) >= 85 and row.get("ret_60d", 0) > 0.25:
            tags.append("交易拥挤")
        if row.get("回撤风险", 0) >= 65 or (pd.notna(row.get("max_drawdown_120d")) and float(row.get("max_drawdown_120d")) < -0.30):
            tags.append("回撤偏深")
        if not tags:
            tags.append("均衡候选")
        return tags[:4]

    def decision_explanation(row: pd.Series) -> str:
        style = "、".join(style_tags(row))
        momentum_pct = row.get("行业内动量分位")
        momentum_text = f"动量行业前 {100 - float(momentum_pct):.0f}%" if pd.notna(momentum_pct) and float(momentum_pct) >= 50 else "动量尚未明显领先行业"
        risk_notes = []
        if row.get("估值压力", 0) >= 70:
            risk_notes.append("估值压力较高")
        if row.get("波动风险", 0) >= 70:
            risk_notes.append("60日波动率偏高")
        if row.get("回撤风险", 0) >= 70:
            risk_notes.append("120日回撤偏深")
        if row.get("流动性风险", 0) >= 70:
            risk_notes.append("流动性偏弱")
        risk_text = "，".join(risk_notes) if risk_notes else "当前量化风险项未明显集中"
        posture = "适合进攻型观察" if row.get("进攻分", 0) >= row.get("防守分", 0) + 8 else "更适合稳健型观察" if row.get("防守分", 0) >= row.get("进攻分", 0) + 8 else "适合均衡观察"
        return f"{momentum_text}，风格为{style}；{risk_text}，{posture}。"

    scored["入选原因"] = scored.apply(explain_row, axis=1)
    scored["风格标签"] = scored.apply(style_tags, axis=1)
    scored["决策解释"] = scored.apply(decision_explanation, axis=1)
    scored = scored.sort_values("综合评分", ascending=False).drop_duplicates(subset=["ticker"]).head(int(top_n))
    display_cols = [
        "ticker", "名称", "行业", "综合评分", "动量分", "质量分", "估值分", "成长分", "风险控制分", "资金情绪分",
        "进攻分", "防守分", "估值压力", "波动风险", "回撤风险", "流动性风险",
        "ROE", "GROWTH", "PE", "PB", "ret_20d", "ret_60d", "ret_120d", "vol_60d", "max_drawdown_120d",
        "行业内动量分位", "行业内质量分位", "行业内估值分位", "风格标签", "入选原因", "决策解释",
    ]
    display_cols = [c for c in display_cols if c in scored.columns]
    return scored[display_cols].reset_index(drop=True), removed


def _download_price_chunk(
    pro,
    ts_code: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    status_text=None,
    chunk_note: str = "",
) -> pd.DataFrame:
    start_str = start_ts.strftime("%Y%m%d")
    end_str = end_ts.strftime("%Y%m%d")

    if status_text is not None:
        status_text.markdown(f"**分段下载**：{chunk_note} {start_str} ~ {end_str}")

    # Use daily endpoint only to minimize request count and avoid extra adj_factor calls.
    hist = ts_call_with_retry(
        lambda: pro.daily(ts_code=ts_code, start_date=start_str, end_date=end_str, fields="trade_date,close"),
        max_retry=3,
        wait_sec=2,
    )

    if hist is None or hist.empty or "trade_date" not in hist.columns or "close" not in hist.columns:
        return pd.DataFrame()

    hist = hist.copy()
    hist["trade_date"] = pd.to_datetime(hist["trade_date"], errors="coerce")
    hist = hist.dropna(subset=["trade_date", "close"])
    return hist[["trade_date", "close"]]


def _download_price_chunked(
    pro,
    ts_code: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    chunk_days: int = 120,
    status_text=None,
) -> pd.DataFrame:
    if start_ts > end_ts:
        return pd.DataFrame(columns=["trade_date", "close"])

    chunks = []
    current_start = start_ts
    segment_idx = 0
    while current_start <= end_ts:
        current_end = min(current_start + pd.Timedelta(days=chunk_days - 1), end_ts)
        try:
            segment_idx += 1
            chunk = _download_price_chunk(
                pro,
                ts_code,
                current_start,
                current_end,
                status_text=status_text,
                chunk_note=f"第 {segment_idx} 段",
            )
            if not chunk.empty:
                chunks.append(chunk)
        except Exception as exc:
            if is_rate_limit_error(exc):
                # Do not split chunk on 429; splitting increases total request count.
                raise
            # If a large chunk fails, split it smaller and try again.
            if chunk_days > 30 and (current_end - current_start).days > 0:
                mid_end = current_start + pd.Timedelta(days=max(1, (current_end - current_start).days // 2))
                left = _download_price_chunked(
                    pro,
                    ts_code,
                    current_start,
                    mid_end,
                    chunk_days=max(30, chunk_days // 2),
                    status_text=status_text,
                )
                right_start = mid_end + pd.Timedelta(days=1)
                right = _download_price_chunked(
                    pro,
                    ts_code,
                    right_start,
                    current_end,
                    chunk_days=max(30, chunk_days // 2),
                    status_text=status_text,
                )
                if not left.empty:
                    chunks.append(left)
                if not right.empty:
                    chunks.append(right)
            else:
                raise
        current_start = current_end + pd.Timedelta(days=1)

    if not chunks:
        return pd.DataFrame(columns=["trade_date", "close"])

    out = pd.concat(chunks, ignore_index=True)
    out = out.drop_duplicates(subset=["trade_date"], keep="last").sort_values("trade_date")
    return out


def fetch_single_ticker_history(pro, ticker: str, start_date: str, end_date: str) -> pd.Series | None:
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    ts_code = to_ts_code(ticker)

    hist = _download_price_chunked(pro, ts_code, start_ts, end_ts, chunk_days=120)
    if hist is None or hist.empty:
        return None

    px = pd.to_numeric(hist["close"], errors="coerce")
    px.index = pd.to_datetime(hist["trade_date"])
    px = px.sort_index().rename(ticker)
    px = px[~px.index.duplicated(keep="last")]
    return px


def update_price_cache_incremental(
    pro,
    tickers: List[str],
    cache_df: pd.DataFrame,
    initial_start_date: str,
    target_end_date: str,
    progress_bar=None,
    chunk_progress_bar=None,
    status_text=None,
    stage_label: str = "更新",
    workers: int = 4,
    save_callback=None,
    save_every: int = 50,
    cancel_event=None,
    progress_stats_callback: Callable[[dict[str, int]], Any] | None = None,
    ts_min_interval_sec: float = 1.2,
    batch_trade_date_max_days: int = 2,
    batch_ticker_chunk_size: int = 200,
    batch_min_tickers: int = 40,
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    if cache_df is None or not isinstance(cache_df, pd.DataFrame):
        cache_df = pd.DataFrame()
    if not cache_df.empty:
        cache_df = cache_df.copy()
        cache_df.index = pd.to_datetime(cache_df.index)
        cache_df = cache_df.sort_index()

    target_end = pd.Timestamp(target_end_date)
    workers = max(1, int(workers))
    set_ts_min_interval_sec(ts_min_interval_sec)

    plans: List[Tuple[str, pd.Timestamp]] = []
    for ticker in tickers:
        fetch_start = pd.Timestamp(initial_start_date)
        if (not cache_df.empty) and (ticker in cache_df.columns):
            valid_idx = cache_df.index[cache_df[ticker].notna()]
            if len(valid_idx) > 0:
                fetch_start = valid_idx.max() + pd.Timedelta(days=1)
        if fetch_start <= target_end:
            plans.append((ticker, fetch_start))
    already_current_count = max(0, len(tickers) - len(plans))

    # For near-real-time updates, prefer trade-date batched pulls.
    short_plans: List[Tuple[str, pd.Timestamp]] = []
    long_plans: List[Tuple[str, pd.Timestamp]] = []
    max_days = max(1, int(batch_trade_date_max_days))
    for ticker, fetch_start in plans:
        span_days = int((target_end - fetch_start).days) + 1
        if span_days <= max_days:
            short_plans.append((ticker, fetch_start))
        else:
            long_plans.append((ticker, fetch_start))

    use_batch_mode = len(short_plans) >= max(1, int(batch_min_tickers))

    total_tickers = len(plans)
    fetched_ticker_count = 0
    appended_rows = 0
    failed_ticker_count = 0
    skipped_ticker_count = 0

    if total_tickers == 0:
        return cache_df, {
            "tickers_requested": len(tickers),
            "total_tickers": 0,
            "processed_tickers": 0,
            "tickers_updated": 0,
            "tickers_failed": 0,
            "tickers_skipped": 0,
            "rows_appended": 0,
            "tickers_already_current": int(already_current_count),
        }

    if progress_bar is not None:
        progress_bar.progress(0.0)
    if chunk_progress_bar is not None:
        chunk_progress_bar.progress(0.0)
    if progress_stats_callback is not None:
        progress_stats_callback(
            {
                "total_tickers": int(total_tickers),
                "processed_tickers": 0,
                "tickers_updated": 0,
                "tickers_skipped": 0,
                "tickers_failed": 0,
            }
        )

    def _merge_ticker_series(target_df: pd.DataFrame, ticker: str, px: pd.Series) -> pd.DataFrame:
        if target_df.empty:
            return px.to_frame()
        if ticker in target_df.columns:
            base = target_df[ticker]
            incoming = px.reindex(target_df.index.union(px.index))
            base = base.reindex(incoming.index)
            target_df = target_df.reindex(incoming.index)
            target_df[ticker] = incoming.combine_first(base)
            return target_df
        return target_df.join(px, how="outer")

    def _fetch_one(plan: Tuple[str, pd.Timestamp]) -> Tuple[str, pd.Series | None]:
        ticker, fetch_start_ts = plan
        series = fetch_single_ticker_history(
            pro=pro,
            ticker=ticker,
            start_date=fetch_start_ts.strftime("%Y-%m-%d"),
            end_date=target_end.strftime("%Y-%m-%d"),
        )
        return ticker, series

    completed = 0
    cancelled = False
    recent_tickers: list[str] = []

    def _recent_suffix() -> str:
        if not recent_tickers:
            return ""
        return f"，最近：{', '.join(recent_tickers[-3:])}"

    batch_stats: Dict[str, int] = {"batch_requests": 0, "batch_rows": 0, "batch_days": 0, "batch_cancelled": 0}
    if use_batch_mode and short_plans:
        ticker_start_map = {ticker: start for ticker, start in short_plans}
        batched_series, batch_stats = fetch_prices_by_trade_date_batches(
            pro=pro,
            ticker_start_map=ticker_start_map,
            target_end=target_end,
            ticker_chunk_size=max(20, int(batch_ticker_chunk_size)),
            status_text=status_text,
            stage_label=stage_label,
            cancel_event=cancel_event,
        )
        for ticker, _ in short_plans:
            completed += 1
            px = batched_series.get(ticker)
            if px is not None and not px.empty:
                fetched_ticker_count += 1
                appended_rows += int(len(px))
                cache_df = _merge_ticker_series(cache_df, ticker, px)
            else:
                skipped_ticker_count += 1

            recent_tickers.append(ticker)
            if len(recent_tickers) > 6:
                recent_tickers.pop(0)

            if progress_bar is not None:
                progress_bar.progress(completed / total_tickers)
            if chunk_progress_bar is not None:
                chunk_progress_bar.progress(completed / total_tickers)
            if progress_stats_callback is not None:
                progress_stats_callback(
                    {
                        "total_tickers": int(total_tickers),
                        "processed_tickers": int(completed),
                        "tickers_updated": int(fetched_ticker_count),
                        "tickers_skipped": int(skipped_ticker_count),
                        "tickers_failed": int(failed_ticker_count),
                    }
                )

    remaining_plans = long_plans if use_batch_mode else plans

    if remaining_plans:
        with ThreadPoolExecutor(max_workers=min(workers, len(remaining_plans))) as executor:
            future_map = {executor.submit(_fetch_one, plan): plan[0] for plan in remaining_plans}
            for future in as_completed(future_map):
                completed += 1
                ticker = future_map[future]
                had_error = False
                try:
                    ticker, px = future.result()
                except Exception as exc:  # noqa: BLE001
                    px = None
                    had_error = True
                    if status_text is not None:
                        status_text.markdown(f"**{stage_label}中**：{completed}/{total_tickers} 只，{ticker} 下载失败：{exc}{_recent_suffix()}")

                if px is not None and (not px.empty):
                    fetched_ticker_count += 1
                    appended_rows += len(px)
                    cache_df = _merge_ticker_series(cache_df, ticker, px)

                    if status_text is not None:
                        status_text.markdown(f"**{stage_label}中**：{completed}/{total_tickers} 只，已完成 {ticker}{_recent_suffix()}")
                else:
                    if had_error:
                        failed_ticker_count += 1
                    else:
                        skipped_ticker_count += 1
                    if status_text is not None:
                        status_text.markdown(f"**{stage_label}中**：{completed}/{total_tickers} 只，{ticker} 无可用数据，跳过{_recent_suffix()}")

                recent_tickers.append(ticker)
                if len(recent_tickers) > 6:
                    recent_tickers.pop(0)

                if progress_bar is not None:
                    progress_bar.progress(completed / total_tickers)
                if chunk_progress_bar is not None:
                    chunk_progress_bar.progress(completed / total_tickers)
                if progress_stats_callback is not None:
                    progress_stats_callback(
                        {
                            "total_tickers": int(total_tickers),
                            "processed_tickers": int(completed),
                            "tickers_updated": int(fetched_ticker_count),
                            "tickers_skipped": int(skipped_ticker_count),
                            "tickers_failed": int(failed_ticker_count),
                        }
                    )

                if save_callback is not None and save_every > 0 and completed % save_every == 0:
                    try:
                        save_callback(cache_df)
                    except Exception:  # noqa: BLE001
                        pass

                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    for pending in future_map:
                        if not pending.done():
                            pending.cancel()
                    if save_callback is not None:
                        try:
                            save_callback(cache_df)
                        except Exception:  # noqa: BLE001
                            pass
                    if status_text is not None:
                        status_text.markdown(f"{stage_label}已取消：完成 {completed}/{total_tickers} 只后中止")
                    break

    if not cache_df.empty:
        cache_df = cache_df.sort_index()
        cache_df = cache_df[~cache_df.index.duplicated(keep="last")]

    stats = {
        "tickers_requested": len(tickers),
        "total_tickers": int(total_tickers),
        "processed_tickers": int(completed),
        "tickers_updated": fetched_ticker_count,
        "tickers_failed": int(failed_ticker_count),
        "tickers_skipped": int(skipped_ticker_count),
        "rows_appended": appended_rows,
        "tickers_already_current": int(already_current_count),
        "cancelled": 1 if cancelled else 0,
        "batch_mode_used": 1 if use_batch_mode else 0,
        "batch_tickers": int(len(short_plans) if use_batch_mode else 0),
        "batch_trade_date_max_days": int(max_days),
        "batch_ticker_chunk_size": int(batch_ticker_chunk_size),
        "ts_min_interval_sec": float(ts_min_interval_sec),
        **batch_stats,
    }
    return cache_df, stats


def build_price_matrix_from_cache(cache_df: pd.DataFrame, tickers: List[str], start_date: str, end_date: str) -> pd.DataFrame:
    if cache_df is None or cache_df.empty:
        raise RuntimeError("Price cache is empty")

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)

    usable_cols = [c for c in tickers if c in cache_df.columns]
    if not usable_cols:
        raise RuntimeError("No requested symbols found in cache")

    price_df = cache_df.loc[(cache_df.index >= start_ts) & (cache_df.index <= end_ts), usable_cols].copy()
    price_df = price_df.sort_index().dropna(how="all")
    price_df = price_df.ffill().dropna(axis=1, how="any")
    if price_df.empty:
        raise RuntimeError("No usable prices after cache slicing")
    return price_df


BACKTEST_STRATEGIES: Dict[str, Dict[str, str]] = {
    "双均线趋势": {"category": "趋势", "description": "快均线位于慢均线上方时持有，跌回慢均线下方退出。"},
    "均线趋势+止损": {"category": "趋势风控", "description": "双均线趋势基础上叠加固定回撤止损。"},
    "小盘动量轮动": {"category": "轮动", "description": "按动量排名持有强势股票，排名跌出后调仓。"},
    "均值回归(RSI)": {"category": "反转", "description": "RSI 低位买入，RSI 回升到卖出阈值退出。"},
    "布林带均值回归": {"category": "反转", "description": "价格跌破下轨后观察反弹，回到中轨附近退出。"},
    "MACD趋势确认": {"category": "趋势确认", "description": "MACD 柱线转正且 DIF 上穿 DEA 时买入，转弱时退出。"},
    "52周新高突破": {"category": "突破", "description": "价格突破近一年高点时跟踪，跌破中期均线退出。"},
}


def run_selected_strategies(
    price_df: pd.DataFrame,
    params: AppParams,
    strategy_names: List[str] | None = None,
) -> Tuple[pd.DataFrame, List[Dict[str, object]], List[Dict[str, object]]]:
    def align_indicator_frame(indicator_df: pd.DataFrame) -> pd.DataFrame:
        out = indicator_df.copy()
        if isinstance(out.columns, pd.MultiIndex):
            out.columns = out.columns.get_level_values(-1)
        return out.reindex(index=price_df.index, columns=price_df.columns)

    def ema(frame: pd.DataFrame, span: int) -> pd.DataFrame:
        return frame.ewm(span=int(span), adjust=False, min_periods=max(2, int(span) // 2)).mean()

    def signal_rows(strategy_name: str, entries: pd.DataFrame, exits: pd.DataFrame, buy_reason: str, sell_reason: str) -> List[Dict[str, object]]:
        rows: List[Dict[str, object]] = []
        for ticker in price_df.columns:
            entry_dates = entries.index[entries[ticker].fillna(False)] if ticker in entries.columns else []
            exit_dates = exits.index[exits[ticker].fillna(False)] if ticker in exits.columns else []
            for dt in entry_dates:
                rows.append({"date": dt.strftime("%Y-%m-%d"), "ticker": str(ticker), "action": "buy", "action_text": "买入", "price": float(price_df.loc[dt, ticker]), "strategy": strategy_name, "reason": buy_reason})
            for dt in exit_dates:
                rows.append({"date": dt.strftime("%Y-%m-%d"), "ticker": str(ticker), "action": "sell", "action_text": "卖出", "price": float(price_df.loc[dt, ticker]), "strategy": strategy_name, "reason": sell_reason})
        return rows

    def advice_rows(strategy_name: str, entries: pd.DataFrame, exits: pd.DataFrame, buy_reason: str, sell_reason: str) -> List[Dict[str, object]]:
        rows: List[Dict[str, object]] = []
        last_date = price_df.index[-1]
        for ticker in price_df.columns:
            entry_dates = list(entries.index[entries[ticker].fillna(False)]) if ticker in entries.columns else []
            exit_dates = list(exits.index[exits[ticker].fillna(False)]) if ticker in exits.columns else []
            last_entry = entry_dates[-1] if entry_dates else None
            last_exit = exit_dates[-1] if exit_dates else None
            holding = bool(last_entry is not None and (last_exit is None or last_entry > last_exit))
            current_buy = bool(ticker in entries.columns and bool(entries.loc[last_date, ticker]))
            current_sell = bool(ticker in exits.columns and bool(exits.loc[last_date, ticker]))
            last_price = float(price_df[ticker].iloc[-1])
            stop_price = float(last_price * (1.0 - float(params.trail_stop)))
            if current_sell:
                status = "卖出复核"
                suggestion = f"{sell_reason}。若已有持仓，建议优先复核退出条件和流动性。"
                risk_level = "高"
            elif current_buy:
                status = "买入触发"
                suggestion = f"{buy_reason}。仅在数据已更新且个股风险项可接受时考虑小仓位试探。"
                risk_level = "中"
            elif holding:
                status = "继续持有"
                suggestion = f"最近买入信号仍未被卖出规则否定。可继续跟踪，跌破约 {stop_price:.2f} 时触发止损复核。"
                risk_level = "中"
            else:
                status = "观望"
                suggestion = "当前未触发买入信号，适合等待策略条件重新成立。"
                risk_level = "低"
            rows.append(
                {
                    "ticker": str(ticker),
                    "strategy": strategy_name,
                    "status": status,
                    "last_price": last_price,
                    "reference_stop": stop_price,
                    "risk_level": risk_level,
                    "suggestion": suggestion,
                    "last_entry_date": last_entry.strftime("%Y-%m-%d") if last_entry is not None else None,
                    "last_exit_date": last_exit.strftime("%Y-%m-%d") if last_exit is not None else None,
                }
            )
        return rows

    common_kwargs = {
        "init_cash": float(params.init_cash),
        "fees": float(params.fees),
        "slippage": float(params.slippage),
        "freq": "1D",
    }

    requested = list(dict.fromkeys(strategy_names or ["双均线趋势"]))
    requested = [name for name in requested if name in BACKTEST_STRATEGIES]
    if not requested:
        requested = ["双均线趋势"]

    rows: List[Dict[str, object]] = []
    signals: List[Dict[str, object]] = []
    advice: List[Dict[str, object]] = []

    fast_ma = align_indicator_frame(vbt.MA.run(price_df, window=int(params.fast_window)).ma)
    slow_ma = align_indicator_frame(vbt.MA.run(price_df, window=int(params.slow_window)).ma)
    returns = price_df.pct_change()

    def append_strategy(strategy_name: str, entries: pd.DataFrame, exits: pd.DataFrame, buy_reason: str, sell_reason: str) -> None:
        entry_state = entries.reindex(index=price_df.index, columns=price_df.columns).fillna(False).astype(bool)
        exit_state = exits.reindex(index=price_df.index, columns=price_df.columns).fillna(False).astype(bool)
        clean_entries = entry_state & (~entry_state.shift(1, fill_value=False))
        clean_exits = exit_state & (~exit_state.shift(1, fill_value=False))
        portfolio = vbt.Portfolio.from_signals(price_df, clean_entries, clean_exits, **common_kwargs)
        rows.append(
            {
                "策略": strategy_name,
                "类型": BACKTEST_STRATEGIES.get(strategy_name, {}).get("category", "策略"),
                "总收益率": float(portfolio.total_return().mean()),
                "最大回撤": float(portfolio.max_drawdown().mean()),
                "夏普比率": float(portfolio.sharpe_ratio().mean()),
                "买入信号数": int(clean_entries.sum().sum()),
                "卖出信号数": int(clean_exits.sum().sum()),
            }
        )
        signals.extend(signal_rows(strategy_name, clean_entries, clean_exits, buy_reason, sell_reason))
        advice.extend(advice_rows(strategy_name, clean_entries, clean_exits, buy_reason, sell_reason))

    if "双均线趋势" in requested:
        append_strategy("双均线趋势", fast_ma > slow_ma, fast_ma < slow_ma, f"{params.fast_window}日均线位于{params.slow_window}日均线上方", f"{params.fast_window}日均线跌破{params.slow_window}日均线")

    if "均线趋势+止损" in requested:
        stop_line = fast_ma * (1.0 - float(params.trail_stop))
        append_strategy("均线趋势+止损", fast_ma > slow_ma, (fast_ma < slow_ma) | (price_df < stop_line), "趋势条件成立，且价格仍在止损线之上", f"趋势转弱或价格跌破快均线下方 {float(params.trail_stop) * 100:.1f}% 止损线")

    momentum = price_df.pct_change(int(params.mom_window))
    hold_mask = momentum.rank(axis=1, pct=True, ascending=False) <= float(params.top_pct)
    hold_mask = hold_mask.fillna(False).astype(bool)
    prev_hold = hold_mask.shift(1, fill_value=False).astype(bool)
    if "小盘动量轮动" in requested:
        append_strategy("小盘动量轮动", hold_mask & (~prev_hold), (~hold_mask) & prev_hold, f"{params.mom_window}日动量排名进入前 {float(params.top_pct) * 100:.0f}%", "动量排名跌出持仓范围")

    rsi = align_indicator_frame(vbt.RSI.run(price_df, window=int(params.rsi_window)).rsi)
    if "均值回归(RSI)" in requested:
        append_strategy("均值回归(RSI)", rsi < float(params.rsi_buy), rsi > float(params.rsi_sell), f"RSI 低于 {params.rsi_buy}，出现超跌反弹观察信号", f"RSI 高于 {params.rsi_sell}，反弹修复后退出")

    if "布林带均值回归" in requested:
        ma20 = price_df.rolling(20, min_periods=10).mean()
        std20 = price_df.rolling(20, min_periods=10).std()
        lower = ma20 - 2 * std20
        append_strategy("布林带均值回归", price_df < lower, price_df >= ma20, "价格跌破布林下轨，出现均值回归观察信号", "价格回到布林中轨附近，反弹目标完成")

    if "MACD趋势确认" in requested:
        dif = ema(price_df, 12) - ema(price_df, 26)
        dea = ema(dif, 9)
        macd_hist = dif - dea
        append_strategy("MACD趋势确认", (dif > dea) & (macd_hist > 0), (dif < dea) | (macd_hist < 0), "DIF 上穿 DEA 且 MACD 柱线转正", "DIF 下穿 DEA 或 MACD 柱线转负")

    if "52周新高突破" in requested:
        high_252 = price_df.rolling(252, min_periods=60).max().shift(1)
        ma60 = price_df.rolling(60, min_periods=20).mean()
        append_strategy("52周新高突破", price_df > high_252, price_df < ma60, "价格突破近一年高点，强趋势突破成立", "价格跌破60日均线，突破趋势失败")

    signal_out = sorted(signals, key=lambda item: str(item.get("date", "")), reverse=True)[:500]
    strategy_df = pd.DataFrame(rows).sort_values("总收益率", ascending=False).reset_index(drop=True)
    return strategy_df, signal_out, advice


def run_three_strategies(price_df: pd.DataFrame, params: AppParams) -> pd.DataFrame:
    strategy_df, _, _ = run_selected_strategies(price_df, params, ["双均线趋势", "小盘动量轮动", "均值回归(RSI)"])
    return strategy_df


def calculate_portfolio_metric_summary(price_df: pd.DataFrame, benchmark_price: pd.Series | None = None) -> Dict[str, float]:
    returns = price_df.pct_change().dropna(how="all").mean(axis=1).dropna()
    if returns.empty:
        return {
            "累计收益": np.nan,
            "年化收益": np.nan,
            "最大回撤": np.nan,
            "夏普比率": np.nan,
            "胜率": np.nan,
            "基准收益": np.nan,
            "超额收益": np.nan,
            "相对最大回撤": np.nan,
        }

    equity = (1.0 + returns).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)
    annual_return = float(equity.iloc[-1] ** (252 / max(1, len(returns))) - 1.0)
    max_drawdown = float((equity / equity.cummax() - 1.0).min())
    sharpe = float((returns.mean() / returns.std()) * np.sqrt(252)) if returns.std() and returns.std() > 0 else np.nan
    win_rate = float((returns > 0).mean())

    excess_return = np.nan
    benchmark_return = np.nan
    relative_max_drawdown = np.nan
    if benchmark_price is not None and not benchmark_price.empty:
        benchmark = benchmark_price.reindex(price_df.index).ffill().dropna()
        if len(benchmark) > 1:
            benchmark_return = float(benchmark.iloc[-1] / benchmark.iloc[0] - 1.0)
            excess_return = total_return - benchmark_return
            benchmark_equity = benchmark / benchmark.iloc[0]
            relative_equity = equity.reindex(benchmark_equity.index).ffill() / benchmark_equity
            relative_max_drawdown = float((relative_equity / relative_equity.cummax() - 1.0).min())

    return {
        "累计收益": total_return,
        "年化收益": annual_return,
        "最大回撤": max_drawdown,
        "夏普比率": sharpe,
        "胜率": win_rate,
        "基准收益": benchmark_return,
        "超额收益": excess_return,
        "相对最大回撤": relative_max_drawdown,
    }


def benchmark_column_name(benchmark_name: str) -> str | None:
    mapping = {
        "沪深300": "000300.SH",
        "中证500": "000905.SH",
        "中证1000": "000852.SH",
        "创业板指": "399006.SZ",
    }
    return mapping.get(benchmark_name)


def make_download_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def build_params() -> AppParams:
    st.sidebar.header("参数设置")
    token = st.sidebar.text_input("Tushare Token", value=load_token_cache() or DEFAULT_TUSHARE_TOKEN, type="password")
    http_url = st.sidebar.text_input("HTTP URL", value=DEFAULT_TUSHARE_HTTP_URL)

    default_start = date(2025, 6, 1)
    default_end = date(2025, 12, 1)
    start_date = st.sidebar.date_input("开始日期", value=default_start)
    end_date = st.sidebar.date_input("结束日期", value=default_end)

    init_cash = st.sidebar.number_input("初始资金", min_value=10000.0, value=100000.0, step=10000.0)
    fees = st.sidebar.number_input("手续费", min_value=0.0, value=0.001, step=0.0005, format="%.4f")
    slippage = st.sidebar.number_input("滑点", min_value=0.0, value=0.001, step=0.0005, format="%.4f")

    small_cap_quantile = st.sidebar.slider("小盘分位", min_value=0.05, max_value=0.8, value=0.30, step=0.05)
    min_turnover = st.sidebar.number_input("换手率下限", min_value=0.0, value=0.0, step=0.1)
    universe_size = st.sidebar.number_input("股票池上限", min_value=10, max_value=200, value=30, step=5)

    st.sidebar.subheader("策略参数")
    fast_window = st.sidebar.number_input("快均线", min_value=2, max_value=120, value=10, step=1)
    slow_window = st.sidebar.number_input("慢均线", min_value=5, max_value=240, value=50, step=1)
    trail_stop = st.sidebar.number_input("移动止损", min_value=0.01, max_value=0.5, value=0.08, step=0.01)

    mom_window = st.sidebar.number_input("动量窗口", min_value=5, max_value=120, value=20, step=1)
    top_pct = st.sidebar.slider("动量持仓比例", min_value=0.05, max_value=0.8, value=0.2, step=0.05)

    rsi_window = st.sidebar.number_input("RSI窗口", min_value=5, max_value=60, value=14, step=1)
    rsi_buy = st.sidebar.number_input("RSI买入阈值", min_value=5.0, max_value=50.0, value=30.0, step=1.0)
    rsi_sell = st.sidebar.number_input("RSI卖出阈值", min_value=40.0, max_value=95.0, value=55.0, step=1.0)
    download_workers = st.sidebar.number_input("下载并发数", min_value=1, max_value=16, value=2, step=1)

    return AppParams(
        token=token.strip(),
        http_url=http_url.strip(),
        start_date=pd.Timestamp(start_date).strftime("%Y-%m-%d"),
        end_date=pd.Timestamp(end_date).strftime("%Y-%m-%d"),
        init_cash=float(init_cash),
        fees=float(fees),
        slippage=float(slippage),
        small_cap_quantile=float(small_cap_quantile),
        min_turnover=float(min_turnover),
        universe_size=int(universe_size),
        fast_window=int(fast_window),
        slow_window=int(slow_window),
        trail_stop=float(trail_stop),
        mom_window=int(mom_window),
        top_pct=float(top_pct),
        rsi_window=int(rsi_window),
        rsi_buy=float(rsi_buy),
        rsi_sell=float(rsi_sell),
        download_workers=int(download_workers),
    )


def run_pipeline(params: AppParams) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, int], Tuple[str, str]]:
    if pd.Timestamp(params.start_date) >= pd.Timestamp(params.end_date):
        raise ValueError("Start date must be earlier than end date")

    cache_df = load_price_cache()
    if cache_df.empty:
        raise RuntimeError("价格缓存为空，请先点击'更新数据到今天（增量）'或'重建缓存（全量）'")

    pool_cache_df = load_pool_cache()
    if pool_cache_df.empty:
        # If user already has price cache, allow backtest by deriving a minimal pool.
        pool_cache_df = build_pool_from_price_cache(cache_df)
        if not pool_cache_df.empty:
            save_pool_cache(pool_cache_df)

    pool_df = filter_pool_from_cache(pool_cache_df, params)

    tickers = pool_df["ticker"].tolist()

    available_cols = [c for c in tickers if c in cache_df.columns]
    used_fallback_universe = False
    fallback_count = 0
    if len(available_cols) == 0:
        used_fallback_universe = True
        fallback_count = min(len(cache_df.columns), params.universe_size)
        available_cols = [str(c) for c in list(cache_df.columns)[:fallback_count]]
        pool_df = pool_df[pool_df["ticker"].isin(available_cols)].copy()
        if pool_df.empty:
            # If pool cache is fully disjoint with price cache, derive minimal pool rows from price cache columns.
            pool_df = pd.DataFrame(
                {
                    "ticker": available_cols,
                    "名称": available_cols,
                    "PE": np.nan,
                    "PB": np.nan,
                    "ROE": np.nan,
                    "GROWTH": np.nan,
                    "流通市值": np.nan,
                    "成交额": np.nan,
                }
            )

    update_stats = {
        "tickers_requested": len(tickers),
        "tickers_updated": 0,
        "rows_appended": 0,
        "tickers_in_cache": len(available_cols),
        "used_fallback_universe": int(used_fallback_universe),
        "fallback_count": int(fallback_count),
    }
    cache_range = cache_date_range(cache_df)

    price_df = build_price_matrix_from_cache(
        cache_df=cache_df,
        tickers=available_cols,
        start_date=params.start_date,
        end_date=params.end_date,
    )
    if price_df.shape[1] < 10:
        raise RuntimeError("Tradable symbols < 10. Relax filters or shorten date range")

    pool_df = pool_df[pool_df["ticker"].isin(price_df.columns)].reset_index(drop=True)
    strategy_df = run_three_strategies(price_df, params)
    return pool_df, price_df, strategy_df, update_stats, cache_range


def run_backtest_from_pool(
    params: AppParams,
    selected_pool_df: pd.DataFrame,
    allow_fallback_universe: bool = False,
    strategy_names: List[str] | None = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, int], Tuple[str, str], List[Dict[str, object]], List[Dict[str, object]]]:
    if pd.Timestamp(params.start_date) >= pd.Timestamp(params.end_date):
        raise ValueError("Start date must be earlier than end date")
    if selected_pool_df is None or selected_pool_df.empty or "ticker" not in selected_pool_df.columns:
        raise RuntimeError("未检测到可回测股票池，请先到'筛选择股'页执行筛选")

    cache_df = load_price_cache()
    if cache_df.empty:
        raise RuntimeError("价格缓存为空，请先到'数据更新'页执行更新")

    tickers = selected_pool_df["ticker"].astype(str).tolist()
    available_cols = [c for c in tickers if c in cache_df.columns]
    used_fallback_universe = False
    fallback_count = 0
    missing_count = len(tickers) - len(available_cols)

    if len(available_cols) == 0 and (not allow_fallback_universe):
        raise RuntimeError(
            "筛选股票与价格缓存无交集。"
            f"筛选股票 {len(tickers)} 只, 缓存命中 0 只。"
            "请先到“数据更新”页执行更新/重建缓存，或开启回退模式。"
        )

    if len(available_cols) == 0:
        used_fallback_universe = True
        fallback_count = min(len(cache_df.columns), max(1, params.universe_size))
        available_cols = [str(c) for c in list(cache_df.columns)[:fallback_count]]
        pool_df = selected_pool_df[selected_pool_df["ticker"].isin(available_cols)].copy()
        if pool_df.empty:
            pool_df = pd.DataFrame(
                {
                    "ticker": available_cols,
                    "名称": available_cols,
                    "PE": np.nan,
                    "PB": np.nan,
                    "ROE": np.nan,
                    "GROWTH": np.nan,
                    "流通市值": np.nan,
                    "成交额": np.nan,
                }
            )
    else:
        pool_df = selected_pool_df[selected_pool_df["ticker"].isin(available_cols)].copy()

    cache_range = cache_date_range(cache_df)
    price_df = build_price_matrix_from_cache(
        cache_df=cache_df,
        tickers=available_cols,
        start_date=params.start_date,
        end_date=params.end_date,
    )
    if price_df.shape[1] < 1:
        raise RuntimeError("缓存区间内无可用价格数据，请先更新缓存")

    pool_df = pool_df[pool_df["ticker"].isin(price_df.columns)].reset_index(drop=True)
    strategy_df, signals, advice = run_selected_strategies(price_df, params, strategy_names)

    stats = {
        "tickers_requested": len(tickers),
        "tickers_in_cache": len(available_cols),
        "tickers_missing": int(missing_count),
        "used_fallback_universe": int(used_fallback_universe),
        "fallback_count": int(fallback_count),
    }
    return pool_df, price_df, strategy_df, stats, cache_range, signals, advice


def update_cache_to_today(params: AppParams) -> Tuple[Dict[str, int], Tuple[str, str]]:
    if not params.token:
        raise ValueError("Please provide Tushare token")

    pro = init_tushare_client(params.token, params.http_url)
    today_str = pd.Timestamp.today().strftime("%Y-%m-%d")
    effective_end_date = get_latest_available_trade_date(pro, pd.Timestamp(today_str).strftime("%Y%m%d"))
    pool_params = AppParams(**{**params.__dict__, "end_date": effective_end_date})
    pool_df = load_pool_cache()
    if pool_df.empty:
        pool_df = fetch_stock_pool(pro, pool_params)
        save_pool_cache(pool_df)
    tickers = pool_df["ticker"].astype(str).tolist()

    cache_df = load_price_cache()
    cache_df, update_stats = update_price_cache_incremental(
        pro=pro,
        tickers=tickers,
        cache_df=cache_df,
        initial_start_date=params.start_date,
        target_end_date=effective_end_date,
        progress_bar=st.session_state.get("update_progress_bar"),
        chunk_progress_bar=st.session_state.get("update_chunk_progress_bar"),
        status_text=st.session_state.get("update_status_text"),
        stage_label="增量更新",
        workers=int(params.download_workers),
    )
    update_stats["pool_total"] = int(len(pool_df))
    update_stats["pool_scoped"] = int(len(tickers))
    save_price_cache(cache_df)
    return update_stats, cache_date_range(cache_df)


def rebuild_cache_to_today(params: AppParams) -> Tuple[Dict[str, int], Tuple[str, str]]:
    if not params.token:
        raise ValueError("Please provide Tushare token")

    pro = init_tushare_client(params.token, params.http_url)
    today_str = pd.Timestamp.today().strftime("%Y-%m-%d")
    effective_end_date = get_latest_available_trade_date(pro, pd.Timestamp(today_str).strftime("%Y%m%d"))
    pool_params = AppParams(**{**params.__dict__, "end_date": effective_end_date})
    pool_df = fetch_stock_pool(pro, pool_params)
    save_pool_cache(pool_df)
    tickers = pool_df["ticker"].astype(str).tolist()

    cache_df = pd.DataFrame()
    cache_df, update_stats = update_price_cache_incremental(
        pro=pro,
        tickers=tickers,
        cache_df=cache_df,
        initial_start_date=params.start_date,
        target_end_date=effective_end_date,
        progress_bar=st.session_state.get("update_progress_bar"),
        chunk_progress_bar=st.session_state.get("update_chunk_progress_bar"),
        status_text=st.session_state.get("update_status_text"),
        stage_label="重建缓存",
        workers=int(params.download_workers),
    )
    update_stats["pool_total"] = int(len(pool_df))
    update_stats["pool_scoped"] = int(len(tickers))
    save_price_cache(cache_df)
    return update_stats, cache_date_range(cache_df)


def supplement_missing_cache_to_today(
    params: AppParams,
    include_stale_tickers: bool = False,
) -> Tuple[Dict[str, int], Tuple[str, str]]:
    if not params.token:
        raise ValueError("Please provide Tushare token")

    pro = init_tushare_client(params.token, params.http_url)
    today_str = pd.Timestamp.today().strftime("%Y-%m-%d")
    effective_end_date = get_latest_available_trade_date(pro, pd.Timestamp(today_str).strftime("%Y%m%d"))

    pool_df = load_pool_cache()
    if pool_df.empty:
        pool_params = AppParams(**{**params.__dict__, "end_date": effective_end_date})
        pool_df = fetch_stock_pool(pro, pool_params)
        save_pool_cache(pool_df)

    cache_df = load_price_cache()
    summary = analyze_cache_completeness(price_cache_df=cache_df, pool_df=pool_df)
    missing_tickers = [str(x) for x in summary.get("missing_tickers", [])]
    stale_tickers = [str(x) for x in summary.get("stale_tickers", [])] if include_stale_tickers else []
    repair_tickers = list(dict.fromkeys(missing_tickers + stale_tickers))

    if not repair_tickers:
        return {
            "tickers_requested": 0,
            "tickers_updated": 0,
            "rows_appended": 0,
            "pool_total": int(len(pool_df)),
            "missing_requested": int(len(missing_tickers)),
            "stale_requested": int(len(stale_tickers)),
            "repair_requested": 0,
        }, cache_date_range(cache_df)

    cache_df, update_stats = update_price_cache_incremental(
        pro=pro,
        tickers=repair_tickers,
        cache_df=cache_df,
        initial_start_date=params.start_date,
        target_end_date=effective_end_date,
        progress_bar=st.session_state.get("update_progress_bar"),
        chunk_progress_bar=st.session_state.get("update_chunk_progress_bar"),
        status_text=st.session_state.get("update_status_text"),
        stage_label="补充缺失",
        workers=int(params.download_workers),
    )
    update_stats["pool_total"] = int(len(pool_df))
    update_stats["missing_requested"] = int(len(missing_tickers))
    update_stats["stale_requested"] = int(len(stale_tickers))
    update_stats["repair_requested"] = int(len(repair_tickers))
    save_price_cache(cache_df)
    return update_stats, cache_date_range(cache_df)


def refresh_pool_financial_metrics(params: AppParams) -> Dict[str, int]:
    if not params.token:
        raise ValueError("Please provide Tushare token")

    pool_df = load_pool_cache()
    if pool_df.empty or "ticker" not in pool_df.columns:
        raise RuntimeError("股票池缓存为空，请先执行更新或重建缓存")

    pro = init_tushare_client(params.token, params.http_url)
    today_str = pd.Timestamp.today().strftime("%Y-%m-%d")
    periods = financial_period_candidates(today_str)
    ts_codes = [to_ts_code(ticker) for ticker in pool_df["ticker"].dropna().astype(str).tolist()]
    fin = fetch_financial_snapshot(pro, periods, ts_codes)
    if fin.empty:
        raise RuntimeError("未获取到财务指标，请检查 token 权限或 TeaJoin fina_indicator 接口状态")

    out_df = pool_df.copy()
    out_df["_ts_code"] = out_df["ticker"].astype(str).map(to_ts_code)
    out_df = out_df.drop(columns=["ROE", "GROWTH"], errors="ignore")
    out_df = out_df.merge(fin, left_on="_ts_code", right_on="ts_code", how="left")
    out_df = out_df.drop(columns=["_ts_code", "ts_code"], errors="ignore")

    ordered_cols = [
        "ticker",
        "名称",
        "行业",
        "上市日期",
        "交易所",
        "PE",
        "PB",
        "ROE",
        "GROWTH",
        "流通市值",
        "成交额",
        "最新收盘价",
    ]
    existing_ordered_cols = [c for c in ordered_cols if c in out_df.columns]
    extra_cols = [c for c in out_df.columns if c not in existing_ordered_cols]
    out_df = out_df[existing_ordered_cols + extra_cols]
    save_pool_cache(out_df)

    return {
        "pool_total": int(len(out_df)),
        "financial_rows": int(len(fin)),
        "roe_filled": int(out_df["ROE"].notna().sum()) if "ROE" in out_df.columns else 0,
        "growth_filled": int(out_df["GROWTH"].notna().sum()) if "GROWTH" in out_df.columns else 0,
    }


def save_outputs(pool_df: pd.DataFrame, strategy_df: pd.DataFrame) -> Dict[str, Path]:
    out_dir = OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    pool_path = out_dir / "小盘池样本清单.csv"
    compare_path = out_dir / "小盘三策略对比.csv"
    pool_df.to_csv(pool_path, index=False, encoding="utf-8-sig")
    strategy_df.to_csv(compare_path, index=False, encoding="utf-8-sig")

    return {"pool": pool_path, "compare": compare_path}


def main() -> None:
    st.set_page_config(page_title="MyQuant Web", page_icon="📈", layout="wide")
    inject_app_theme()
    st.markdown(
        """
        <div class="mq-header">
            <h1 class="mq-title">MyQuant 多因子选股与回测</h1>
            <p class="mq-subtitle">数据同步、风险过滤、多因子评分和策略回测集中在一个工作台中。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    price_cache_df = load_price_cache()
    cache_start, cache_end = cache_date_range(price_cache_df)
    pool_cache_df = load_pool_cache()
    status_c1, status_c2 = st.columns(2)
    status_c1.metric("价格缓存范围", f"{cache_start} ~ {cache_end}")
    status_c2.metric("股票池缓存数量", 0 if pool_cache_df.empty else int(len(pool_cache_df)))

    tab_update, tab_screen, tab_backtest = st.tabs(["数据更新", "筛选择股", "策略回测"])

    with tab_update:
        render_panel_heading("数据更新", "日常只需要同步到最新；当诊断提示缺口时，再进入修复工具。")
        update_readiness = analyze_data_readiness(price_cache_df=price_cache_df, pool_df=pool_cache_df)
        render_data_readiness(update_readiness, title="缺口诊断与修复建议")

        default_token = st.session_state.get("update_token", "") or load_token_cache() or ""
        cfg1, cfg2 = st.columns(2)
        token = cfg1.text_input("Tushare Token", value=default_token, type="password", key="update_token")
        http_url = cfg2.text_input("HTTP URL", value=DEFAULT_TUSHARE_HTTP_URL, key="update_http")

        cfg3, cfg4 = st.columns(2)
        start_date_cfg = cfg3.date_input("价格缓存起始日期", value=date(2025, 6, 1), key="update_start")
        download_workers = cfg4.number_input("下载并发数", min_value=1, max_value=16, value=2, step=1, key="update_workers")
        st.caption("下载按股票逐只请求并分段拉取历史价格；TeaJoin 限流场景建议并发 2-3。")

        params_update = AppParams(
            token=str(token).strip(),
            http_url=str(http_url).strip(),
            start_date=pd.Timestamp(start_date_cfg).strftime("%Y-%m-%d"),
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
            download_workers=int(download_workers),
        )

        render_panel_heading("日常同步", "刷新股票池、基础面字段，并把价格缓存增量补到最新。")
        st.info("同步到最新会刷新股票池快照和财务字段，并只补每只股票缺少的价格日期；不会清空已有价格缓存。")
        sync_clicked = st.button("同步到最新", type="primary", width="stretch")

        render_panel_heading("修复工具", "根据诊断结果选择要修复的缓存类型。")
        repair_type = st.radio(
            "选择要修复的缓存类型",
            options=["行情价格缓存", "基础面字段缓存"],
            horizontal=True,
            label_visibility="collapsed",
        )
        repair_price_clicked = False
        refresh_financial_clicked = False
        include_stale_tickers = True
        if repair_type == "行情价格缓存":
            st.caption("修复收盘价历史数据。用于诊断提示“行情价格需修复”、价格缓存完全缺失或某些标的日期落后时。只补缺口，不会重拉全部股票。")
            include_stale_tickers = st.checkbox(
                "同时补齐日期落后的标的",
                value=True,
                help="缺失标的是价格缓存里完全没有的股票；落后标的是已有价格但最新日期早于当前全局缓存最新日期的股票。",
            )
            repair_price_clicked = st.button("开始修复行情价格缓存", width="stretch")
        else:
            st.caption("修复股票池里的 ROE/GROWTH 财务字段。若缺的是 PE/PB/成交额，请使用上方“同步到最新”刷新股票池快照。")
            refresh_financial_clicked = st.button("开始刷新基础面字段缓存", width="stretch")

        with st.expander("高级操作：全量重建价格缓存"):
            st.warning("全量重建会从起始日期重新拉取全市场价格，耗时最长。只有在缓存结构异常、日期范围错误或修复工具无法解决时使用。")
            confirm_rebuild = st.checkbox("我确认需要清空并重建价格缓存", value=False)
            rebuild_clicked = st.button("开始全量重建", disabled=not confirm_rebuild, width="stretch")

        st.caption("下面两个进度条分别表示：股票级进度、分段下载进度。")
        update_stock_progress_bar = st.progress(0.0)
        update_chunk_progress_bar = st.progress(0.0)
        update_status_text = st.empty()
        st.session_state["update_progress_bar"] = update_stock_progress_bar
        st.session_state["update_chunk_progress_bar"] = update_chunk_progress_bar
        st.session_state["update_status_text"] = update_status_text

        if sync_clicked:
            with st.spinner("正在同步股票池、基础面和价格缓存..."):
                try:
                    save_token_cache(token)
                    update_stats, new_range = update_cache_to_today(params_update)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"同步失败: {exc}")
                else:
                    st.success(
                        "同步完成: "
                        f"更新股票 {update_stats['tickers_updated']}/{update_stats['tickers_requested']} 只 "
                        f"(股票池 {update_stats.get('pool_total', 0)} 只)，"
                        f"新增数据行 {update_stats['rows_appended']}"
                    )
                    st.info(f"同步后缓存范围: {new_range[0]} ~ {new_range[1]}")

        if repair_price_clicked:
            with st.spinner("正在修复价格缺口..."):
                try:
                    save_token_cache(token)
                    supplement_stats, supplement_range = supplement_missing_cache_to_today(
                        params_update,
                        include_stale_tickers=bool(include_stale_tickers),
                    )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"价格修复失败: {exc}")
                else:
                    if supplement_stats.get("repair_requested", 0) == 0:
                        st.success("无需修复：当前未发现价格缺口。")
                    else:
                        st.success(
                            "价格缺口修复完成: "
                            f"尝试修复 {supplement_stats.get('repair_requested', supplement_stats['tickers_requested'])} 只，"
                            f"成功写入 {supplement_stats['tickers_updated']} 只，"
                            f"新增数据行 {supplement_stats['rows_appended']}"
                        )
                        st.caption(
                            f"本次目标包含：完全缺失 {supplement_stats.get('missing_requested', 0)} 只，"
                            f"落后标的 {supplement_stats.get('stale_requested', 0)} 只。"
                        )
                    st.info(f"修复后缓存范围: {supplement_range[0]} ~ {supplement_range[1]}")

        if refresh_financial_clicked:
            with st.spinner("正在刷新基础面指标..."):
                try:
                    save_token_cache(token)
                    fin_stats = refresh_pool_financial_metrics(params_update)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"刷新基础面指标失败: {exc}")
                else:
                    st.success(
                        "基础面指标刷新完成: "
                        f"股票池 {fin_stats['pool_total']} 只，"
                        f"ROE 有效 {fin_stats['roe_filled']} 只，"
                        f"GROWTH 有效 {fin_stats['growth_filled']} 只"
                    )

        if rebuild_clicked:
            with st.spinner("正在全量重建价格缓存..."):
                try:
                    save_token_cache(token)
                    rebuild_stats, rebuild_range = rebuild_cache_to_today(params_update)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"全量重建失败: {exc}")
                else:
                    st.success(
                        "全量重建完成: "
                        f"更新股票 {rebuild_stats['tickers_updated']}/{rebuild_stats['tickers_requested']} 只 "
                        f"(股票池 {rebuild_stats.get('pool_total', 0)} 只，全量下载 {rebuild_stats.get('pool_scoped', rebuild_stats['tickers_requested'])} 只)，"
                        f"新增数据行 {rebuild_stats['rows_appended']}"
                    )
                    st.info(f"重建后缓存范围: {rebuild_range[0]} ~ {rebuild_range[1]}")

    with tab_screen:
        render_panel_heading("筛选择股", "先过滤风险，再用行业归一化后的多因子评分排序。")
        pool_cache_df = load_pool_cache()
        if pool_cache_df.empty:
            st.warning("股票池缓存为空，请先到“数据更新”页更新数据。")
        else:
            st.caption("筛选流程：先做风险过滤，再按行业内归一化后的多因子评分排序。当前优先实现已有缓存可计算的因子；审计非标、北向资金、融资余额、机构持仓等需要后续接入数据源。")

            saved_strategies = st.session_state.get("saved_screen_strategies", {})
            template_options = list(FACTOR_TEMPLATES.keys()) + list(saved_strategies.keys())
            template_name = st.selectbox("筛选模板", options=template_options, index=0)
            template = saved_strategies.get(template_name) or FACTOR_TEMPLATES.get(template_name, FACTOR_TEMPLATES["趋势质量股"])
            template_weights = dict(template.get("weights", {}))
            template_filters = dict(template.get("filters", {}))

            render_panel_heading("风险过滤", "先排除明显不适合进入候选池的标的。")
            rf1, rf2, rf3, rf4 = st.columns(4)
            top_n = rf1.number_input("最终持仓数量", min_value=5, max_value=500, value=30, step=5)
            min_turnover = rf2.number_input("最低换手率", min_value=0.0, value=float(template_filters.get("min_turnover", 0.2)), step=0.1)
            list_age_floor = rf3.number_input("上市天数下限", min_value=0, value=int(template_filters.get("list_age_floor", 180)), step=30)
            exclude_bj = rf4.checkbox("排除北交所", value=False)

            rf5, rf6, rf7, rf8 = st.columns(4)
            roe_floor = rf5.number_input("ROE 下限(%)", min_value=-100.0, value=float(template_filters.get("roe_floor", 5.0)), step=1.0)
            growth_floor = rf6.number_input("营收同比下限(%)", min_value=-100.0, value=float(template_filters.get("growth_floor", -20.0)), step=1.0)
            pe_cap = rf7.number_input("PE 上限", min_value=0.0, value=float(template_filters.get("pe_cap", 120.0)), step=5.0)
            pb_cap = rf8.number_input("PB 上限", min_value=0.0, value=float(template_filters.get("pb_cap", 20.0)), step=0.5)

            industry_neutral = st.checkbox("使用行业内排名/分位数归一化", value=True)
            exclude_stale_price = st.checkbox("剔除价格长期不可用标的", value=True)

            render_panel_heading("因子权重", "权重越高，综合评分越偏向该类风格。")
            with st.expander("如何理解和调整因子权重", expanded=True):
                st.markdown(
                    """
                    因子权重决定综合评分更偏向哪类股票。每个因子先被转换为 0~100 分，再按权重加权求和；权重会自动归一化，所以总和不必刚好等于 100%。

                    - 动量：看 20/60/120 日涨幅、52 周高点距离、相对行业强度和动量加速度。调高后更偏向近期走势强、强于同行的股票，但也更容易买到短期拥挤或过热标的。
                    - 质量：当前主要用 ROE 衡量。调高后更偏向盈利能力强的公司，通常更稳，但可能错过尚未释放利润的早期成长股。
                    - 估值：当前用 PE/PB 的行业内低分位衡量。调高后更偏向便宜或估值修复机会，但也更容易选到基本面承压的低估值陷阱。
                    - 成长：当前用营收同比增长衡量。调高后更偏向收入扩张快的公司，但需要结合估值和质量，避免只买高增长叙事。
                    - 风险控制：看 60/120 日波动率和 120 日最大回撤。调高后更偏向波动低、回撤浅的股票，组合可能更稳，但进攻性会下降。
                    - 资金情绪：当前用成交/换手相关数据做代理。调高后更偏向市场关注度和交易活跃度较高的股票，但短期噪音也会增加。
                    """
                )
                st.caption(
                    "计算原理：先对每个原始指标做分位数归一化；开启行业内归一化时，优先在同一行业内排名，样本太少则回退到全市场分位。"
                    "综合评分 = 动量分×动量权重 + 质量分×质量权重 + 估值分×估值权重 + 成长分×成长权重 + 风险控制分×风险权重 + 资金情绪分×情绪权重。"
                )
            w1, w2, w3 = st.columns(3)
            momentum_w = w1.slider("动量", min_value=0, max_value=100, value=int(template_weights.get("动量", 0.25) * 100), step=5)
            quality_w = w1.slider("质量", min_value=0, max_value=100, value=int(template_weights.get("质量", 0.25) * 100), step=5)
            valuation_w = w2.slider("估值", min_value=0, max_value=100, value=int(template_weights.get("估值", 0.20) * 100), step=5)
            growth_w = w2.slider("成长", min_value=0, max_value=100, value=int(template_weights.get("成长", 0.15) * 100), step=5)
            risk_w = w3.slider("风险控制", min_value=0, max_value=100, value=int(template_weights.get("风险控制", 0.10) * 100), step=5)
            sentiment_w = w3.slider("资金情绪", min_value=0, max_value=100, value=int(template_weights.get("资金情绪", 0.05) * 100), step=5)

            weights = normalize_weights({
                "动量": momentum_w,
                "质量": quality_w,
                "估值": valuation_w,
                "成长": growth_w,
                "风险控制": risk_w,
                "资金情绪": sentiment_w,
            })
            st.caption("实际归一化权重：" + "，".join(f"{k} {v:.0%}" for k, v in weights.items()))

            screen_readiness = analyze_data_readiness(price_cache_df=load_price_cache(), pool_df=pool_cache_df)
            render_data_readiness(screen_readiness, title="筛选因子数据预检")

            with st.expander("当前版本因子覆盖情况"):
                st.write("已参与当前评分：20/60/120日涨幅、52周高点距离、相对行业强度、120日动量减20日动量、ROE、PE、PB、营收同比、60/120日波动率、120日最大回撤、换手率/成交额代理。")
                st.write("接口已验证但尚未接入缓存和评分：ROA、毛利率、净利率、经营现金流/净利润、自由现金流、资产负债率、商誉/净资产、PS、PEG、股息率、历史估值分位、扣非利润增长、Beta、涨跌停、北向资金、融资余额、机构持仓、审计非标、连续亏损。当前不会把这些字段假装计入评分。")
                st.write("如果某个因子接口不可用，后续应改用不依赖该数据的替代计算方案；如果接口可用但本地未缓存，则应先在数据更新页补缓存，再允许该因子参与评分。")

            allow_incomplete_factors = st.checkbox("允许因子数据不完整时继续筛选", value=False)

            strategy_name = st.text_input("保存策略名称", value=template_name if template_name not in FACTOR_TEMPLATES else "")
            save_strategy_clicked = st.button("保存筛选策略")
            if save_strategy_clicked and strategy_name.strip():
                saved_strategies[strategy_name.strip()] = {
                    "weights": weights,
                    "filters": {
                        "min_turnover": float(min_turnover),
                        "list_age_floor": int(list_age_floor),
                        "roe_floor": float(roe_floor),
                        "growth_floor": float(growth_floor),
                        "pe_cap": float(pe_cap),
                        "pb_cap": float(pb_cap),
                        "exclude_bj": bool(exclude_bj),
                        "exclude_stale_price": bool(exclude_stale_price),
                    },
                }
                st.session_state["saved_screen_strategies"] = saved_strategies
                st.success(f"已保存策略：{strategy_name.strip()}")

            do_screen = st.button("执行多因子筛选", type="primary", width="stretch")
            if do_screen:
                try:
                    current_readiness = analyze_data_readiness(price_cache_df=load_price_cache(), pool_df=pool_cache_df)
                    if (not current_readiness.get("factor_ok", False)) and (not allow_incomplete_factors):
                        raise RuntimeError("筛选因子数据预检未通过。请先到“数据更新”页按建议修复缓存，或勾选“允许因子数据不完整时继续筛选”。")
                    filters = {
                        "min_turnover": float(min_turnover),
                        "list_age_floor": int(list_age_floor),
                        "roe_floor": float(roe_floor),
                        "growth_floor": float(growth_floor),
                        "pe_cap": float(pe_cap),
                        "pb_cap": float(pb_cap),
                        "exclude_bj": bool(exclude_bj),
                        "exclude_stale_price": bool(exclude_stale_price),
                    }
                    screened_pool_df, removed_stats = build_factor_screen(
                        pool_df=pool_cache_df,
                        price_cache_df=load_price_cache(),
                        weights=weights,
                        filters=filters,
                        top_n=int(top_n),
                        reference_date=pd.Timestamp.today().strftime("%Y-%m-%d"),
                        industry_neutral=bool(industry_neutral),
                    )
                    previous_df = st.session_state.get("screened_pool_df", pd.DataFrame())
                    st.session_state["screened_pool_df"] = screened_pool_df
                    st.session_state["last_screen_params"] = {
                        "template_name": str(template_name),
                        "top_n": int(top_n),
                        "weights": weights,
                        "filters": filters,
                        "industry_neutral": bool(industry_neutral),
                        "removed_stats": removed_stats,
                    }

                    st.success(f"筛选完成，当前结果 {len(screened_pool_df)} 只")
                    st.caption("风险过滤统计：" + "，".join(f"{k} {v}" for k, v in removed_stats.items()))
                    if isinstance(previous_df, pd.DataFrame) and (not previous_df.empty):
                        prev_set = set(previous_df["ticker"].astype(str))
                        curr_set = set(screened_pool_df["ticker"].astype(str))
                        added = len(curr_set - prev_set)
                        removed = len(prev_set - curr_set)
                        st.caption(f"相较上次结果：新增 {added} 只，移除 {removed} 只")
                        if added == 0 and removed == 0:
                            st.info("本次筛选结果与上次一致，通常表示当前参数变化不足以改变筛选集合。")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"筛选失败: {exc}")

            current_screened = st.session_state.get("screened_pool_df", pd.DataFrame())
            if isinstance(current_screened, pd.DataFrame) and (not current_screened.empty):
                st.success(f"当前筛选结果: {len(current_screened)} 只")
                render_cache_completeness(
                    analyze_cache_completeness(
                        price_cache_df=load_price_cache(),
                        tickers=current_screened["ticker"].astype(str).tolist(),
                    ),
                    title="筛选结果缓存命中情况",
                )
                last_params = st.session_state.get("last_screen_params")
                if isinstance(last_params, dict):
                    st.caption(
                        "上次筛选参数："
                        f"模板 {last_params.get('template_name', '')}，"
                        f"数量上限 {last_params.get('top_n', 0)}，"
                        f"行业内归一化 {'开启' if last_params.get('industry_neutral') else '关闭'}"
                    )
                    removed_stats = last_params.get("removed_stats")
                    if isinstance(removed_stats, dict):
                        st.caption("过滤统计：" + "，".join(f"{k} {v}" for k, v in removed_stats.items()))
                st.caption("提示：修改参数后需要再次点击“执行筛选”才会重新计算。")
                st.dataframe(current_screened, width="stretch", hide_index=True)
            else:
                st.info("尚未执行筛选，点击“执行筛选”后会在此展示结果。")

    with tab_backtest:
        render_panel_heading("策略回测", "使用当前筛选结果和本地价格缓存进行回测。")
        selected_pool_df = st.session_state.get("screened_pool_df", pd.DataFrame())
        if not isinstance(selected_pool_df, pd.DataFrame) or selected_pool_df.empty:
            st.warning("请先到“筛选择股”页执行筛选，再进行回测。")

        b1, b2 = st.columns(2)
        start_date_bt = b1.date_input("回测开始日期", value=date(2025, 6, 1), key="bt_start")
        end_date_bt = b2.date_input("回测结束日期", value=date(2025, 12, 1), key="bt_end")

        p1, p2, p3 = st.columns(3)
        init_cash = p1.number_input("初始资金", min_value=10000.0, value=100000.0, step=10000.0)
        fees = p2.number_input("手续费", min_value=0.0, value=0.001, step=0.0005, format="%.4f")
        slippage = p3.number_input("滑点", min_value=0.0, value=0.001, step=0.0005, format="%.4f")

        render_panel_heading("策略参数")
        a1, a2, a3 = st.columns(3)
        fast_window = a1.number_input("快均线", min_value=2, max_value=120, value=10, step=1)
        slow_window = a2.number_input("慢均线", min_value=5, max_value=240, value=50, step=1)
        trail_stop = a3.number_input("移动止损", min_value=0.01, max_value=0.5, value=0.08, step=0.01)

        b_m1, b_m2, b_m3 = st.columns(3)
        mom_window = b_m1.number_input("动量窗口", min_value=5, max_value=120, value=20, step=1)
        top_pct = b_m2.slider("动量持仓比例", min_value=0.05, max_value=0.8, value=0.2, step=0.05)
        universe_for_fallback = b_m3.number_input("回退标的上限", min_value=1, max_value=500, value=30, step=1)

        rbt1, rbt2, rbt3, rbt4 = st.columns(4)
        rebalance_period = rbt1.selectbox("调仓周期", options=["20日", "月度", "季度"], index=0)
        holding_count = rbt2.number_input("持仓数量", min_value=1, max_value=500, value=30, step=1)
        limit_trade_guard = rbt3.checkbox("模拟涨跌停无法成交", value=False)
        benchmark_name = rbt4.selectbox("对比基准", options=["无", "沪深300", "中证500", "中证1000"], index=0)

        c1, c2, c3 = st.columns(3)
        rsi_window = c1.number_input("RSI窗口", min_value=5, max_value=60, value=14, step=1)
        rsi_buy = c2.number_input("RSI买入阈值", min_value=5.0, max_value=50.0, value=30.0, step=1.0)
        rsi_sell = c3.number_input("RSI卖出阈值", min_value=40.0, max_value=95.0, value=55.0, step=1.0)

        allow_fallback_universe = st.checkbox("当筛选股票与缓存无交集时，允许回退到缓存内标的", value=False)
        allow_incomplete_data = st.checkbox("允许在数据不完整时继续回测", value=False)

        if isinstance(selected_pool_df, pd.DataFrame) and (not selected_pool_df.empty):
            preflight_summary = analyze_cache_completeness(
                price_cache_df=load_price_cache(),
                tickers=selected_pool_df["ticker"].astype(str).tolist(),
                start_date=pd.Timestamp(start_date_bt).strftime("%Y-%m-%d"),
                end_date=pd.Timestamp(end_date_bt).strftime("%Y-%m-%d"),
            )
            render_cache_completeness(preflight_summary, title="本次回测数据预检")
        else:
            preflight_summary = {}

        run_clicked = st.button("运行回测", type="primary", width="stretch")
        if run_clicked:
            params_bt = AppParams(
                token="",
                http_url="",
                start_date=pd.Timestamp(start_date_bt).strftime("%Y-%m-%d"),
                end_date=pd.Timestamp(end_date_bt).strftime("%Y-%m-%d"),
                init_cash=float(init_cash),
                fees=float(fees),
                slippage=float(slippage),
                small_cap_quantile=0.30,
                min_turnover=0.0,
                universe_size=int(universe_for_fallback),
                fast_window=int(fast_window),
                slow_window=int(slow_window),
                trail_stop=float(trail_stop),
                mom_window=int(mom_window),
                top_pct=float(top_pct),
                rsi_window=int(rsi_window),
                rsi_buy=float(rsi_buy),
                rsi_sell=float(rsi_sell),
                download_workers=4,
            )

            with st.spinner("正在按缓存回测..."):
                try:
                    if isinstance(preflight_summary, dict) and preflight_summary:
                        incomplete_reasons = [
                            int(preflight_summary.get("missing_count", 0)) > 0,
                            int(preflight_summary.get("no_data_in_range_count", 0)) > 0,
                            int(preflight_summary.get("dropped_for_gaps_count", 0)) > 0,
                        ]
                        if any(incomplete_reasons) and (not allow_incomplete_data):
                            raise RuntimeError("本次回测数据预检未通过。请先更新缓存，或勾选“允许在数据不完整时继续回测”。")
                    pool_df, price_df, strategy_df, stats, cache_range, _, _ = run_backtest_from_pool(
                        params=params_bt,
                        selected_pool_df=selected_pool_df.head(int(holding_count)),
                        allow_fallback_universe=bool(allow_fallback_universe),
                    )
                    benchmark_series = None
                    benchmark_col = benchmark_column_name(str(benchmark_name))
                    full_cache_df = load_price_cache()
                    if benchmark_col and benchmark_col in full_cache_df.columns:
                        benchmark_series = full_cache_df[benchmark_col]
                    metric_summary = calculate_portfolio_metric_summary(price_df, benchmark_series)
                    output_paths = save_outputs(pool_df, strategy_df)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"运行失败: {exc}")
                else:
                    st.success("运行成功")
                    m1, m2, m3 = st.columns(3)
                    m1.metric("股票池数量", value=int(pool_df.shape[0]))
                    m2.metric("价格矩阵", value=f"{price_df.shape[0]} x {price_df.shape[1]}")
                    m3.metric("最佳策略", value=str(strategy_df.iloc[0]["策略"]))

                    st.caption(
                        "本次按缓存读取: "
                        f"缓存命中股票 {stats['tickers_in_cache']}/{stats['tickers_requested']} 只, "
                        f"缓存范围 {cache_range[0]} ~ {cache_range[1]}"
                    )
                    if stats.get("tickers_missing", 0) > 0:
                        st.warning(f"有 {stats['tickers_missing']} 只筛选股票在价格缓存中缺失。")
                    if stats.get("used_fallback_universe", 0) == 1:
                        st.warning(
                            "筛选结果与价格缓存无交集，已自动回退到价格缓存内可用标的回测。"
                            f"当前回退标的数: {stats.get('fallback_count', 0)}"
                        )
                    st.caption(
                        f"回测约束：调仓周期 {rebalance_period}，持仓数量 {int(holding_count)}，"
                        f"涨跌停成交约束 {'已开启' if limit_trade_guard else '未开启'}。"
                        "当前版本基于当前筛选结果做静态组合回测；历史滚动重选需要后续接入历史因子快照。"
                    )
                    if benchmark_name != "无" and benchmark_series is None:
                        st.warning(f"当前价格缓存中没有 {benchmark_name} 指数序列，暂无法计算基准超额收益。")

                    st.subheader("组合指标")
                    metric_df = pd.DataFrame([metric_summary])
                    formatted_metric_df = metric_df.copy()
                    for col in ["累计收益", "年化收益", "最大回撤", "胜率", "超额收益"]:
                        if col in formatted_metric_df.columns:
                            formatted_metric_df[col] = formatted_metric_df[col].map(lambda x: "无" if pd.isna(x) else f"{x:.2%}")
                    if "夏普比率" in formatted_metric_df.columns:
                        formatted_metric_df["夏普比率"] = formatted_metric_df["夏普比率"].map(lambda x: "无" if pd.isna(x) else f"{x:.4f}")
                    formatted_metric_df["换手率"] = "静态组合暂不估算"
                    st.dataframe(formatted_metric_df, width="stretch", hide_index=True)

                    st.subheader("策略对比")
                    show_df = strategy_df.copy()
                    show_df["总收益率"] = show_df["总收益率"].map(lambda x: f"{x:.2%}")
                    show_df["最大回撤"] = show_df["最大回撤"].map(lambda x: f"{x:.2%}")
                    show_df["夏普比率"] = show_df["夏普比率"].map(lambda x: f"{x:.4f}")
                    st.dataframe(show_df, width="stretch")

                    st.subheader("本次回测股票池")
                    st.dataframe(pool_df, width="stretch", hide_index=True)

                    d1, d2 = st.columns(2)
                    d1.download_button(
                        label="下载 小盘三策略对比.csv",
                        data=make_download_bytes(strategy_df),
                        file_name="小盘三策略对比.csv",
                        mime="text/csv",
                        width="stretch",
                    )
                    d2.download_button(
                        label="下载 小盘池样本清单.csv",
                        data=make_download_bytes(pool_df),
                        file_name="小盘池样本清单.csv",
                        mime="text/csv",
                        width="stretch",
                    )

                    st.info(f"本地已写入: {output_paths['compare']} | {output_paths['pool']}")


if __name__ == "__main__":
    main()
