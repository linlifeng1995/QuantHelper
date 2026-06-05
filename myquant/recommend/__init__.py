"""推荐关注：根据择时状态把候选标的归类为 5+ 组。"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Iterable

import pandas as pd

from myquant.pools.dao import get_pool, list_pools
from myquant.risk.market_regime import resolve_effective_end_date
from myquant.timing.calculator import evaluate_tickers
from myquant.timing.states import STATE_COLORS, STATE_LABELS


GROUP_ORDER: list[dict[str, Any]] = [
    {"key": "breakout", "label": "突破强势", "states": ["breakout_confirmed"], "color": "green"},
    {"key": "trend", "label": "强势观察", "states": ["strong_watch"], "color": "blue"},
    {"key": "pullback", "label": "回踩布局", "states": ["pullback_wait"], "color": "gold"},
    {"key": "defense", "label": "防御止损", "states": ["trend_broken", "high_risk"], "color": "volcano"},
    {"key": "avoid", "label": "暂不交易", "states": ["do_not_trade"], "color": "default"},
]

# 全市场扫描结果的 TTL 缓存（避免每次请求重新计算 5000+ 支）
_market_cache: dict[str, tuple[tuple[str, int, dict[str, list[dict[str, Any]]]], float]] = {}
_MARKET_CACHE_TTL = 300  # 5 分钟


_ALIAS_NAME_RE = re.compile(r"^t\d+$", re.IGNORECASE)


def _is_bad_name(name: str | None) -> bool:
    text = (name or "").strip()
    if not text:
        return True
    return bool(_ALIAS_NAME_RE.match(text))


def _pool_cache_name_industry_map() -> dict[str, tuple[str | None, str | None]]:
    """Build ticker -> (name, industry) from pool_cache as a fallback source."""
    try:
        from web_app import load_pool_cache  # type: ignore

        df = load_pool_cache()
    except Exception:
        return {}

    if df is None or df.empty or "ticker" not in df.columns:
        return {}

    name_col = "名称" if "名称" in df.columns else ("name" if "name" in df.columns else None)
    industry_col = "行业" if "行业" in df.columns else ("industry" if "industry" in df.columns else None)
    if not name_col and not industry_col:
        return {}

    out: dict[str, tuple[str | None, str | None]] = {}
    for _, row in df.iterrows():
        tk = str(row.get("ticker") or "").strip()
        if not tk:
            continue
        name = str(row.get(name_col) or "").strip() if name_col else ""
        industry = str(row.get(industry_col) or "").strip() if industry_col else ""
        out[tk] = (name or None, industry or None)
    return out


def _load_watchlist_items() -> list[dict[str, Any]]:
    """从 watchlist.json 加载筛选观察池标的（不依赖数据库）。"""
    try:
        from web_app import CACHE_DIR  # type: ignore
        wf = CACHE_DIR / "watchlist.json"
        if wf.exists():
            data = json.loads(wf.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _collect_tickers(pool_ids: Iterable[int] | None) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """返回 (去重 ticker 列表, ticker→pool/name 元信息)。"""
    meta: dict[str, dict[str, Any]] = {}
    fallback_map = _pool_cache_name_industry_map()
    if pool_ids is None:
        pools = list_pools()
        ids = [p["id"] for p in pools]
    else:
        ids = list(pool_ids)
    for pid in ids:
        pool = get_pool(pid)
        if not pool:
            continue
        for it in pool.get("items", []):
            tk = it.get("ticker")
            if not tk:
                continue
            if tk not in meta:
                raw_name = it.get("name")
                raw_industry = it.get("industry")
                fb_name, fb_industry = fallback_map.get(tk, (None, None))
                name = fb_name if _is_bad_name(str(raw_name or "")) and fb_name else raw_name
                industry = fb_industry if (not raw_industry and fb_industry) else raw_industry
                meta[tk] = {
                    "ticker": tk,
                    "name": name,
                    "industry": industry,
                    "pool_ids": [pid],
                    "pool_names": [pool.get("name")],
                }
            else:
                meta[tk]["pool_ids"].append(pid)
                meta[tk]["pool_names"].append(pool.get("name"))

                # If existing name looks like alias, try to fix with current item/fallback.
                existing_name = str(meta[tk].get("name") or "")
                if _is_bad_name(existing_name):
                    candidate = str(it.get("name") or "").strip()
                    if not _is_bad_name(candidate):
                        meta[tk]["name"] = candidate
                    else:
                        fb_name, _ = fallback_map.get(tk, (None, None))
                        if fb_name:
                            meta[tk]["name"] = fb_name

                if not meta[tk].get("industry"):
                    candidate_industry = str(it.get("industry") or "").strip()
                    if candidate_industry:
                        meta[tk]["industry"] = candidate_industry
                    else:
                        _, fb_industry = fallback_map.get(tk, (None, None))
                        if fb_industry:
                            meta[tk]["industry"] = fb_industry

    # 同时纳入筛选观察池（watchlist）的标的——这些是用户筛出但尚未正式入池的候选股
    for item in _load_watchlist_items():
        tk = str(item.get("ticker") or "").strip()
        if not tk:
            continue
        if tk not in meta:
            raw_name = item.get("name")
            raw_industry = item.get("industry")
            fb_name, fb_industry = fallback_map.get(tk, (None, None))
            name = fb_name if _is_bad_name(str(raw_name or "")) and fb_name else raw_name
            industry = fb_industry if (not raw_industry and fb_industry) else raw_industry
            meta[tk] = {
                "ticker": tk,
                "name": name,
                "industry": industry,
                "pool_ids": [],
                "pool_names": ["筛选观察池"],
            }
        else:
            if "筛选观察池" not in meta[tk]["pool_names"]:
                meta[tk]["pool_names"].append("筛选观察池")

    return list(meta.keys()), meta


def _composite_score(features: dict[str, Any], state: str) -> float:
    """简单加权打分：用于组内排序。"""
    def _f(key: str, default: float = 0.0) -> float:
        v = features.get(key)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    slope = _f("trend_slope_60d")
    ret20 = _f("ret_20d")
    breakout20 = _f("breakout_20d")
    drawdown = _f("max_drawdown_120d")
    align = _f("ma_alignment")

    score = slope * 50.0 + ret20 * 30.0 + breakout20 * 5.0 + align * 8.0 + drawdown * 10.0
    # 不同分组给予额外加成
    if state == "breakout_confirmed":
        score += 15.0
    elif state == "strong_watch":
        score += 8.0
    elif state == "pullback_wait":
        score += 4.0
    elif state in {"trend_broken", "high_risk"}:
        score -= 10.0
    return round(score, 4)


def _collect_market_wide_tickers(price_cache_df: pd.DataFrame) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """从 price_cache 列名收集全市场标的，name/industry 从 pool_cache 补全。"""
    fallback_map = _pool_cache_name_industry_map()
    meta: dict[str, dict[str, Any]] = {}
    for col in price_cache_df.columns:
        tk = str(col).strip()
        if not tk:
            continue
        fb_name, fb_industry = fallback_map.get(tk, (None, None))
        meta[tk] = {
            "ticker": tk,
            "name": fb_name,
            "industry": fb_industry,
            "pool_ids": [],
            "pool_names": [],
        }
    return list(meta.keys()), meta


def _compute_raw_groups(
    price_cache_df: pd.DataFrame,
    tickers: list[str],
    meta: dict[str, dict[str, Any]],
    eff_end_date: str,
) -> tuple[str, int, dict[str, list[dict[str, Any]]]]:
    """执行择时计算，返回 (eff_end, total, by_group)，按 score 降序，不限数量。"""
    state_to_group: dict[str, str] = {}
    for g in GROUP_ORDER:
        for st in g["states"]:
            state_to_group[st] = g["key"]

    items = evaluate_tickers(price_cache_df, tickers, eff_end_date)
    eff_end = items[0].get("end_date") if items else eff_end_date

    by_group: dict[str, list[dict[str, Any]]] = {g["key"]: [] for g in GROUP_ORDER}
    for it in items:
        state = it.get("state") or "do_not_trade"
        group_key = state_to_group.get(state, "avoid")
        feats = it.get("features") or {}
        score = _composite_score(feats, state)
        tk = it.get("ticker")
        m = meta.get(tk, {})
        by_group[group_key].append({
            "ticker": tk,
            "name": m.get("name"),
            "industry": m.get("industry"),
            "pool_ids": m.get("pool_ids", []),
            "pool_names": m.get("pool_names", []),
            "state": state,
            "state_label": STATE_LABELS.get(state, state),
            "state_color": STATE_COLORS.get(state, "default"),
            "confidence": it.get("confidence") if "confidence" in it else None,
            "reasons": it.get("reasons", []),
            "risks": it.get("risks", []),
            "score": score,
            "close": feats.get("close"),
            "ret_20d": feats.get("ret_20d"),
            "max_drawdown_120d": feats.get("max_drawdown_120d"),
            "ma_alignment": feats.get("ma_alignment"),
            "trend_slope_60d": feats.get("trend_slope_60d"),
        })

    for key in by_group:
        by_group[key].sort(key=lambda r: -r["score"])

    return str(eff_end), len(items), by_group


def _format_output(
    eff_end: str,
    total: int,
    by_group: dict[str, list[dict[str, Any]]],
    limit_per_group: int,
    industries: list[str] | None = None,
) -> dict[str, Any]:
    """将 by_group 转为 API 响应格式，可附加行业过滤和分组数量限制。"""
    groups_out: list[dict[str, Any]] = []
    for g in GROUP_ORDER:
        rows = by_group.get(g["key"], [])
        if industries:
            rows = [r for r in rows if r.get("industry") in industries]
        groups_out.append({
            "key": g["key"],
            "label": g["label"],
            "color": g["color"],
            "count": len(rows),
            "items": rows[:limit_per_group],
        })
    return {"end_date": eff_end, "total_evaluated": total, "groups": groups_out}


def get_all_industries() -> list[str]:
    """返回 pool_cache 中所有可用行业（供前端下拉使用）。"""
    industry_map = _pool_cache_name_industry_map()
    return sorted({ind for _, ind in industry_map.values() if ind})


def recommend(
    price_cache_df: pd.DataFrame,
    pool_ids: Iterable[int] | None = None,
    end_date: str | None = None,
    limit_per_group: int = 20,
    market_wide: bool = False,
    industries: list[str] | None = None,
) -> dict[str, Any]:
    # 与 classify_regime 口径统一：当未指定 end_date 时，选 breadth-aware 有效末日，
    # 避免增量更新时最新一行半截数据污染择时与组合暴露评估。
    eff_end_date = resolve_effective_end_date(price_cache_df, end_date)

    if market_wide:
        # 全市场模式：从 price_cache 列取全量标的，结果带 TTL 缓存
        cache_key = f"mw_{eff_end_date}"
        cached = _market_cache.get(cache_key)
        if cached is not None and time.time() - cached[1] < _MARKET_CACHE_TTL:
            eff_end, total, by_group = cached[0]
        else:
            tickers, meta = _collect_market_wide_tickers(price_cache_df)
            eff_end, total, by_group = _compute_raw_groups(price_cache_df, tickers, meta, eff_end_date)
            _market_cache[cache_key] = ((eff_end, total, by_group), time.time())
        return _format_output(eff_end, total, by_group, limit_per_group, industries)

    # 普通模式：只评估股票池 + 筛选观察池
    tickers, meta = _collect_tickers(pool_ids)
    if not tickers:
        return {
            "end_date": eff_end_date,
            "total_evaluated": 0,
            "groups": [{"key": g["key"], "label": g["label"], "color": g["color"], "count": 0, "items": []} for g in GROUP_ORDER],
        }
    eff_end, total, by_group = _compute_raw_groups(price_cache_df, tickers, meta, eff_end_date)
    return _format_output(eff_end, total, by_group, limit_per_group, industries)
