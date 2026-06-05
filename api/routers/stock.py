"""Stock detail API：K 线 OHLCV + 单标的聚合摘要。

Phase 3 / 切片 C1。

K 线优先级：
1. 命中本地 parquet 缓存 (outputs/cache/ohlcv/{ts_code}.parquet) 且 < TTL 视为新鲜，直接用。
2. 否则尝试 tushare daily + adj_factor 拉取并写回 parquet。
3. tushare 不可用 / 失败 → 从 price_cache 的 close 矩阵合成蜡烛（open=prev close,
   high=max(open,close), low=min(open,close), volume=0），保证 UI 可用。
"""
from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
import time
from xml.etree import ElementTree
from urllib.parse import quote_plus
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
import requests
from sqlalchemy import select

import web_app
from myquant.db import session_scope
from myquant.db.models import Pool, PoolItem
from myquant.factors.buckets import compute_price_factors
from myquant.planning.dao import list_plans
from myquant.tushare_client import DEFAULT_TUSHARE_HTTP_URL
from myquant.timing.calculator import evaluate_ticker

from ._utils import sanitize

router = APIRouter(prefix="/api/stock", tags=["stock"])


OHLCV_CACHE_DIR = web_app.CACHE_DIR / "ohlcv"
OHLCV_TTL_SECONDS = 6 * 3600  # 6 小时
DEFAULT_LOOKBACK_DAYS = 250  # 默认返回的交易日数量
NEWS_RSS_TIMEOUT_SECONDS = 10

NEWS_TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "业绩": ("业绩", "财报", "净利润", "营收", "亏损", "预增", "预亏"),
    "政策": ("政策", "监管", "证监会", "国常会", "指导意见", "新规"),
    "并购重组": ("并购", "重组", "收购", "注入", "资产置换"),
    "回购分红": ("回购", "分红", "派息", "股息"),
    "资金面": ("融资", "融券", "北向", "增持", "减持", "机构调研"),
    "产品业务": ("新品", "订单", "中标", "合作", "扩产", "产能"),
    "风险事件": ("诉讼", "处罚", "违约", "停牌", "退市", "爆雷"),
    "股价异动": ("涨停", "跌停", "异动", "大涨", "大跌"),
}


def _normalize_date(s: str | None) -> pd.Timestamp | None:
    if not s:
        return None
    try:
        return pd.Timestamp(s).normalize()
    except Exception:
        return None


def _extract_news_tags(title: str) -> list[str]:
    text = str(title or "")
    low = text.lower()
    tags: list[str] = []
    for label, kws in NEWS_TAG_KEYWORDS.items():
        if any((kw in text) or (kw.lower() in low) for kw in kws):
            tags.append(label)
    if not tags:
        tags.append("行业动态")
    return tags[:3]


def _parse_pub_time(value: str) -> datetime | None:
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.replace(tzinfo=None)
    except Exception:
        return None


def _build_news_queries(ticker: str, name: str | None = None) -> list[str]:
    symbol = ticker.split(".")[0]
    queries = [f'"{ticker}" 股票', f'"{symbol}" 股票']
    if name:
        queries.insert(0, f'"{name}" 股票')
    out: list[str] = []
    seen: set[str] = set()
    for q in queries:
        qq = q.strip()
        if not qq or qq in seen:
            continue
        seen.add(qq)
        out.append(qq)
    return out


def _eastmoney_code(ticker: str) -> tuple[str, str]:
    """将 002668.SZ → code=002668, mkt=0（深圳=0, 上海=1）。"""
    code, exch = ticker.upper().rsplit(".", 1)
    mkt = "1" if exch in ("SH", "SS") else "0"
    return code, mkt


def _strip_em(text: str) -> str:
    """去掉 <em>...</em> 高亮标签。"""
    import re
    return re.sub(r"</?em>", "", text)


def _fetch_eastmoney_search_news(keyword: str, limit: int = 15) -> list[dict[str, Any]]:
    """东方财富搜索 API，按关键词搜个股相关新闻，国内服务器可直接访问。"""
    import json as _json
    param = _json.dumps({
        "uid": "",
        "keyword": keyword,
        "type": ["cmsArticle"],
        "client": "web",
        "clientVersion": "curr",
        "clientType": "web",
        "pageIndex": 1,
        "pageSize": limit,
    }, ensure_ascii=False)
    url = "https://search-api-web.eastmoney.com/search/jsonp?cb=&param=" + quote_plus(param)
    try:
        resp = requests.get(url, timeout=NEWS_RSS_TIMEOUT_SECONDS,
                            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.eastmoney.com/"})
        resp.raise_for_status()
        # 响应为 JSONP 格式 ({"..."}), 需去掉外层括号
        text = resp.text.strip()
        if text.startswith("(") and text.endswith(")"):
            text = text[1:-1]
        data = _json.loads(text)
    except Exception:
        return []

    items: list[dict[str, Any]] = []
    for art in (data.get("result", {}).get("cmsArticle") or []):
        title = _strip_em((art.get("title") or "")).strip()
        if not title:
            continue
        raw_date = str(art.get("date") or "")
        try:
            dt = pd.Timestamp(raw_date)
        except Exception:
            dt = None
        art_code = str(art.get("code") or "")
        link = f"https://finance.eastmoney.com/a/{art_code}.html" if art_code else ""
        source = (art.get("mediaName") or "东方财富").strip()
        items.append({
            "title": title,
            "url": link,
            "source": source,
            "published_at": dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None,
            "published_display": dt.strftime("%Y-%m-%d %H:%M") if dt else "-",
            "tags": _extract_news_tags(title),
            "_sort_ts": dt.timestamp() if dt else 0.0,
        })
    return items


def _fetch_google_news_rss(query: str, per_query_limit: int = 12) -> list[dict[str, Any]]:
    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    )
    resp = requests.get(
        url,
        timeout=NEWS_RSS_TIMEOUT_SECONDS,
        headers={"User-Agent": "Mozilla/5.0 (MyQuantNewsBot)"},
    )
    resp.raise_for_status()
    root = ElementTree.fromstring(resp.text)
    channel = root.find("channel")
    if channel is None:
        return []

    out: list[dict[str, Any]] = []
    for item in channel.findall("item")[: max(1, int(per_query_limit))]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        source_node = item.find("source")
        source = (source_node.text.strip() if source_node is not None and source_node.text else "Google News").strip()
        if not title or not link:
            continue
        dt = _parse_pub_time(pub_date)
        out.append(
            {
                "title": title,
                "url": link,
                "source": source,
                "published_at": dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None,
                "published_display": dt.strftime("%Y-%m-%d %H:%M") if dt else "-",
                "tags": _extract_news_tags(title),
                "_sort_ts": dt.timestamp() if dt else 0.0,
            }
        )
    return out


def _collect_stock_news(ticker: str, name: str | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
    # 优先：东方财富搜索（国内服务器可直接访问，按股票名称或代码查询）
    keyword = name or ticker.split(".")[0]
    merged = _fetch_eastmoney_search_news(keyword, limit=limit + 5)

    # 若按名称查无结果（如名称太新），补一次按代码查询
    if not merged:
        code = ticker.split(".")[0]
        merged = _fetch_eastmoney_search_news(code, limit=limit + 5)

    # 最终兜底：Google News RSS（境外服务器或有代理时可用）
    if not merged:
        queries = _build_news_queries(ticker, name)
        per_limit = max(6, min(18, limit))
        for q in queries:
            try:
                merged.extend(_fetch_google_news_rss(q, per_query_limit=per_limit))
            except Exception:
                continue
    else:
        queries = [keyword]

    if not merged:
        return [], [keyword]

    dedup: dict[str, dict[str, Any]] = {}
    for row in merged:
        key = (row.get("url") or "").strip() or (row.get("title") or "").strip()
        if not key:
            continue
        prev = dedup.get(key)
        if prev is None or float(row.get("_sort_ts") or 0.0) > float(prev.get("_sort_ts") or 0.0):
            dedup[key] = row

    items = sorted(dedup.values(), key=lambda x: float(x.get("_sort_ts") or 0.0), reverse=True)[: max(1, int(limit))]
    for idx, row in enumerate(items, start=1):
        row["id"] = f"n{idx}"
        row.pop("_sort_ts", None)
    return items, queries


def _load_ohlcv_cache(ts_code: str) -> pd.DataFrame:
    path = OHLCV_CACHE_DIR / f"{ts_code}.parquet"
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty or "trade_date" not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df = df.dropna(subset=["trade_date"]).sort_values("trade_date").reset_index(drop=True)
    return df


def _save_ohlcv_cache(ts_code: str, df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    OHLCV_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = OHLCV_CACHE_DIR / f"{ts_code}.parquet"
    try:
        df.to_parquet(path, index=False)
    except Exception:
        # parquet 引擎可能未安装，退化到 pickle
        df.to_pickle(path.with_suffix(".pkl"))


def _cache_is_fresh(ts_code: str) -> bool:
    path = OHLCV_CACHE_DIR / f"{ts_code}.parquet"
    if not path.exists():
        return False
    try:
        return (time.time() - path.stat().st_mtime) < OHLCV_TTL_SECONDS
    except Exception:
        return False


def _fetch_ohlcv_from_tushare(
    ts_code: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> pd.DataFrame:
    """通过 tushare daily + adj_factor 拉取一只标的的 OHLCV+adj_factor。
    失败返回空 DataFrame，由调用方决定回退策略。"""
    token = web_app.load_token_cache()
    if not token:
        return pd.DataFrame()
    try:
        pro = web_app.init_tushare_client(token, DEFAULT_TUSHARE_HTTP_URL)
    except Exception:
        return pd.DataFrame()

    start_str = start_ts.strftime("%Y%m%d")
    end_str = end_ts.strftime("%Y%m%d")
    try:
        daily = web_app.ts_call_with_retry(
            lambda: pro.daily(
                ts_code=ts_code,
                start_date=start_str,
                end_date=end_str,
                fields="trade_date,open,high,low,close,vol,amount",
            ),
            max_retry=2,
            wait_sec=2,
        )
    except Exception:
        return pd.DataFrame()
    if daily is None or daily.empty:
        return pd.DataFrame()

    try:
        adj = web_app.ts_call_with_retry(
            lambda: pro.adj_factor(
                ts_code=ts_code,
                start_date=start_str,
                end_date=end_str,
            ),
            max_retry=2,
            wait_sec=2,
        )
    except Exception:
        adj = pd.DataFrame()

    df = daily.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    for col in ("open", "high", "low", "close", "vol", "amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["trade_date", "close"]).sort_values("trade_date").reset_index(drop=True)

    if adj is not None and not adj.empty and "trade_date" in adj.columns and "adj_factor" in adj.columns:
        adj = adj.copy()
        adj["trade_date"] = pd.to_datetime(adj["trade_date"], errors="coerce")
        adj["adj_factor"] = pd.to_numeric(adj["adj_factor"], errors="coerce")
        df = df.merge(adj[["trade_date", "adj_factor"]], on="trade_date", how="left")
    else:
        df["adj_factor"] = np.nan

    return df


def _synthesize_from_price_cache(
    ticker: str,
    start_ts: pd.Timestamp | None,
    end_ts: pd.Timestamp | None,
) -> pd.DataFrame:
    """从 price_cache.close 合成 OHLCV（open=前收，high=max(o,c)，low=min(o,c)，vol=0）。"""
    cache_df = web_app.load_price_cache()
    if cache_df is None or cache_df.empty or ticker not in cache_df.columns:
        return pd.DataFrame()
    series = cache_df[ticker].dropna()
    if series.empty:
        return pd.DataFrame()
    if start_ts is not None:
        series = series[series.index >= start_ts]
    if end_ts is not None:
        series = series[series.index <= end_ts]
    if series.empty:
        return pd.DataFrame()
    closes = series.astype(float)
    opens = closes.shift(1).fillna(closes)
    highs = pd.concat([opens, closes], axis=1).max(axis=1)
    lows = pd.concat([opens, closes], axis=1).min(axis=1)
    df = pd.DataFrame(
        {
            "trade_date": closes.index,
            "open": opens.values,
            "high": highs.values,
            "low": lows.values,
            "close": closes.values,
            "vol": 0.0,
            "amount": 0.0,
            "adj_factor": np.nan,
        }
    )
    return df


def _get_ohlcv_df(
    ticker: str,
    start_ts: pd.Timestamp | None,
    end_ts: pd.Timestamp | None,
) -> tuple[pd.DataFrame, str]:
    """返回 (df, source)。source ∈ {'cache', 'tushare', 'synth', 'empty'}。"""
    ts_code = web_app.to_ts_code(ticker)

    if _cache_is_fresh(ts_code):
        cached = _load_ohlcv_cache(ts_code)
        if not cached.empty:
            req_end = end_ts if end_ts is not None else cached["trade_date"].max()
            if pd.Timestamp(cached["trade_date"].max()) >= pd.Timestamp(req_end) - pd.Timedelta(days=1):
                return cached, "cache"

    # 计算窗口
    if end_ts is None:
        end_ts_eff = pd.Timestamp.today().normalize()
    else:
        end_ts_eff = end_ts
    if start_ts is None:
        # 多抓一些以保 MA120 计算
        start_ts_eff = end_ts_eff - pd.Timedelta(days=DEFAULT_LOOKBACK_DAYS * 2)
    else:
        start_ts_eff = start_ts - pd.Timedelta(days=200)

    tushare_df = _fetch_ohlcv_from_tushare(ts_code, start_ts_eff, end_ts_eff)
    if not tushare_df.empty:
        _save_ohlcv_cache(ts_code, tushare_df)
        return tushare_df, "tushare"

    synth = _synthesize_from_price_cache(ticker, start_ts_eff, end_ts_eff)
    if not synth.empty:
        return synth, "synth"

    return pd.DataFrame(), "empty"


def _apply_qfq(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "adj_factor" not in df.columns:
        return df
    if df["adj_factor"].dropna().empty:
        return df
    last_factor = float(df["adj_factor"].dropna().iloc[-1])
    if not np.isfinite(last_factor) or last_factor == 0:
        return df
    scale = df["adj_factor"] / last_factor
    out = df.copy()
    for col in ("open", "high", "low", "close"):
        if col in out.columns:
            out[col] = out[col] * scale
    return out


def _window_filter(df: pd.DataFrame, start_ts: pd.Timestamp | None, end_ts: pd.Timestamp | None) -> pd.DataFrame:
    if df.empty:
        return df
    out = df
    if start_ts is not None:
        out = out[out["trade_date"] >= start_ts]
    if end_ts is not None:
        out = out[out["trade_date"] <= end_ts]
    return out.reset_index(drop=True)


def _compute_ma(close: pd.Series, window: int) -> list[float | None]:
    if close.empty:
        return []
    ma = close.rolling(window=window, min_periods=window).mean()
    return [None if not np.isfinite(v) else float(v) for v in ma.tolist()]


@router.get("/{ticker}/kline")
def get_kline(
    ticker: str,
    start: str | None = Query(default=None, description="YYYY-MM-DD"),
    end: str | None = Query(default=None, description="YYYY-MM-DD"),
    adjust: str = Query(default="qfq", pattern="^(qfq|raw)$"),
) -> dict[str, Any]:
    ticker = str(ticker).strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker 必填")

    start_ts = _normalize_date(start)
    end_ts = _normalize_date(end)

    raw, source = _get_ohlcv_df(ticker, start_ts, end_ts)
    if raw.empty:
        raise HTTPException(status_code=404, detail=f"未找到 {ticker} 的行情数据")

    df = raw.copy()
    if adjust == "qfq":
        df = _apply_qfq(df)

    # 默认窗口：未指定 start 时，截取最后 DEFAULT_LOOKBACK_DAYS 个交易日
    if start_ts is None and end_ts is None:
        df = df.tail(DEFAULT_LOOKBACK_DAYS).reset_index(drop=True)
    else:
        df = _window_filter(df, start_ts, end_ts)

    if df.empty:
        raise HTTPException(status_code=404, detail=f"{ticker} 在指定窗口内无数据")

    close = df["close"].astype(float)
    items = [
        {
            "date": pd.Timestamp(row["trade_date"]).strftime("%Y-%m-%d"),
            "open": None if not np.isfinite(row["open"]) else float(row["open"]),
            "high": None if not np.isfinite(row["high"]) else float(row["high"]),
            "low": None if not np.isfinite(row["low"]) else float(row["low"]),
            "close": None if not np.isfinite(row["close"]) else float(row["close"]),
            "volume": None if "vol" not in df.columns or not np.isfinite(row.get("vol", np.nan)) else float(row["vol"]),
        }
        for row in df.to_dict(orient="records")
    ]

    return sanitize(
        {
            "ticker": ticker,
            "ts_code": web_app.to_ts_code(ticker),
            "adjust": adjust,
            "source": source,
            "start": items[0]["date"],
            "end": items[-1]["date"],
            "items": items,
            "ma": {
                "ma20": _compute_ma(close, 20),
                "ma60": _compute_ma(close, 60),
                "ma120": _compute_ma(close, 120),
            },
        }
    )


def _find_pools_for_ticker(ticker: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with session_scope() as session:
        rows = session.execute(
            select(PoolItem, Pool)
            .join(Pool, Pool.id == PoolItem.pool_id)
            .where(PoolItem.ticker == ticker)
        ).all()
        for item, pool in rows:
            out.append(
                {
                    "pool_id": pool.id,
                    "pool_name": pool.name,
                    "pool_type": pool.pool_type,
                    "is_default": bool(pool.is_default),
                    "name": item.name,
                    "industry": item.industry,
                    "added_score": item.added_score,
                    "current_score": item.current_score,
                    "status": item.status,
                    "tags": list(item.tags or []),
                    "priority": item.priority,
                    "last_review_snapshot": item.last_review_snapshot or {},
                }
            )
    return out


@router.get("/{ticker}/summary")
def get_summary(
    ticker: str,
    end_date: str | None = Query(default=None, description="YYYY-MM-DD"),
) -> dict[str, Any]:
    ticker = str(ticker).strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker 必填")

    price_cache = web_app.load_price_cache()
    if price_cache is None or price_cache.empty:
        raise HTTPException(status_code=503, detail="price_cache 为空，请先更新行情数据")

    # 价格因子（单标的）
    eff_end = end_date or pd.Timestamp(price_cache.index.max()).strftime("%Y-%m-%d")
    pf_table = compute_price_factors(price_cache, [ticker], eff_end)
    pf_df = pf_table.df if pf_table is not None else pd.DataFrame()
    pf_row: dict[str, Any] = {}
    if pf_df is not None and not pf_df.empty:
        pf_row = pf_df.iloc[0].to_dict()
    # 移除 NaN
    price_factors = {k: v for k, v in pf_row.items() if k != "ticker"}

    # Timing
    try:
        timing = evaluate_ticker(price_cache, ticker, eff_end)
    except Exception as exc:
        timing = {"state": "unknown", "label": "未知", "reasons": [str(exc)], "risks": [], "features": {}}

    # 池归属 & 持仓信息
    pools_info = _find_pools_for_ticker(ticker)

    # 关联交易计划
    try:
        plans = list_plans(ticker=ticker, limit=50)
    except Exception:
        plans = []

    # 名称 / 行业兜底（取首个池子的）
    name = next((p.get("name") for p in pools_info if p.get("name")), None)
    industry = next((p.get("industry") for p in pools_info if p.get("industry")), None)

    return sanitize(
        {
            "ticker": ticker,
            "ts_code": web_app.to_ts_code(ticker),
            "name": name,
            "industry": industry,
            "end_date": eff_end,
            "price_factors": price_factors,
            "timing": timing,
            "pools": pools_info,
            "plans": plans,
            "plan_count": len(plans),
            "pool_count": len(pools_info),
        }
    )


@router.get("/{ticker}/news")
def get_stock_news(
    ticker: str,
    name: str | None = Query(default=None, description="股票名称，可选"),
    limit: int = Query(default=20, ge=1, le=50, description="返回条数"),
) -> dict[str, Any]:
    ticker = str(ticker).strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker 必填")

    resolved_name = (name or "").strip() or None
    if not resolved_name:
        pools_info = _find_pools_for_ticker(ticker)
        resolved_name = next((str(p.get("name")).strip() for p in pools_info if p.get("name")), None)

    items, queries = _collect_stock_news(ticker=ticker, name=resolved_name, limit=int(limit))
    return sanitize(
        {
            "ticker": ticker,
            "name": resolved_name,
            "count": len(items),
            "items": items,
            "queries": queries,
            "source": "eastmoney",
        }
    )
