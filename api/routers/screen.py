"""按因子桶展示的新选股 API：/api/screen/v2。

与旧 /api/screen 并存，旧端点保留以兼容。
"""
from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import web_app
from myquant.factors.registry import sync_availability
from myquant.screening.pipeline import DEFAULT_BUCKET_WEIGHTS, run_screen

from ._utils import sanitize


router = APIRouter(prefix="/api/screen", tags=["screen"])

# ── 热门主题 → 行业关键词映射 ─────────────────────────────────
# 用 pool_cache 的"行业"字段匹配，无需 tushare concept API
_THEME_INDUSTRY_MAP: list[dict[str, Any]] = [
    {"id": "AI",     "name": "人工智能/大模型",   "keywords": ["IT设备", "软件", "通信设备", "元器件", "电子", "计算机"]},
    {"id": "ROBOT",  "name": "机器人/自动化",     "keywords": ["专用机械", "机械基件", "仪器仪表", "电气设备", "自动化"]},
    {"id": "SEMI",   "name": "半导体/芯片",       "keywords": ["元器件", "半导体", "电子制造", "光学光电"]},
    {"id": "PV",     "name": "光伏/储能",         "keywords": ["电气设备", "光伏", "电池", "储能", "新能源"]},
    {"id": "WIND",   "name": "风电/绿电",         "keywords": ["电气设备", "风电", "新能源"]},
    {"id": "NEV",    "name": "新能源汽车",         "keywords": ["汽车配件", "汽车", "电池", "充电"]},
    {"id": "BIMED",  "name": "生物医药/创新药",    "keywords": ["生物制药", "化学制药", "医疗保健", "医疗器械", "CRO", "医药"]},
    {"id": "DEF",    "name": "军工/国防",         "keywords": ["国防", "军工", "航空", "航天", "船舶"]},
    {"id": "DIGI",   "name": "数字经济/数据要素",  "keywords": ["通信设备", "IT设备", "软件", "云计算", "互联网"]},
    {"id": "LOWALT", "name": "低空经济/无人机",    "keywords": ["航空", "无人机", "专用机械", "通信设备"]},
    {"id": "CHEM",   "name": "化工新材料",         "keywords": ["化工原料", "化工机械", "精细化工", "新材料", "塑料", "橡胶"]},
    {"id": "CONS",   "name": "消费电子",           "keywords": ["家用电器", "电器仪表", "元器件", "通信设备"]},
    {"id": "AGRI",   "name": "农业/粮食安全",      "keywords": ["农业综合", "农用机械", "饲料", "农药化肥"]},
]
# ─────────────────────────────────────────────────────────────


def _build_theme_ticker_map(pool_df: pd.DataFrame) -> dict[str, set[str]]:
    """根据 pool_cache 的行业字段，建立主题→ticker 映射。"""
    if pool_df.empty or "行业" not in pool_df.columns:
        return {}
    result: dict[str, set[str]] = {}
    industry_series = pool_df["行业"].fillna("").astype(str)
    for theme in _THEME_INDUSTRY_MAP:
        tid: str = theme["id"]
        keywords: list[str] = theme["keywords"]
        mask = industry_series.apply(lambda ind: any(kw in ind for kw in keywords))
        result[tid] = set(pool_df.loc[mask, "ticker"].tolist())
    return result
# ─────────────────────────────────────────────────────────────


class ScreenV2Request(BaseModel):
    top_n: int = Field(default=30, ge=1, le=500)
    industries: list[str] = Field(default_factory=list)
    concept_codes: list[str] = Field(default_factory=list, description="主题 id 列表，非空时按主题限定范围")
    bucket_weights: dict[str, float] | None = None
    risk_filters: dict[str, Any] | None = None
    industry_neutral: bool = True
    allow_incomplete_factors: bool = False


@router.get("/concepts")
def list_concepts() -> dict[str, Any]:
    """返回热门主题列表及其在股票池中的标的数量（基于行业字段匹配，无需 tushare concept API）。"""
    pool_df = web_app.load_pool_cache()
    ticker_map = _build_theme_ticker_map(pool_df)
    result = []
    for theme in _THEME_INDUSTRY_MAP:
        tid: str = theme["id"]
        count = len(ticker_map.get(tid, set()))
        if count > 0:
            result.append({
                "ts_code": tid,
                "name": theme["name"],
                "count": count,
            })
    result.sort(key=lambda x: x["count"], reverse=True)
    return sanitize({"concepts": result, "cached_at": pd.Timestamp.now().timestamp()})


@router.post("/concepts/refresh")
def refresh_concepts() -> dict[str, Any]:
    """重新统计主题标的数（直接从 pool_cache 计算，无需网络请求）。"""
    pool_df = web_app.load_pool_cache()
    ticker_map = _build_theme_ticker_map(pool_df)
    return {"ok": True, "concept_count": sum(1 for v in ticker_map.values() if v)}


@router.post("/v2")
def screen_v2(request: ScreenV2Request) -> dict[str, Any]:
    price_cache = web_app.load_price_cache()
    pool_cache = web_app.load_pool_cache()
    readiness = web_app.analyze_data_readiness(price_cache, pool_cache)
    sync_availability(price_cache, pool_cache)

    if (not readiness.get("factor_ok", False)) and (not request.allow_incomplete_factors):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "选股因子数据预检未通过，请先修复缓存或允许不完整因子。",
                "readiness": sanitize(readiness),
            },
        )

    # 主题过滤
    if request.concept_codes:
        ticker_map = _build_theme_ticker_map(pool_cache)
        concept_tickers: set[str] = set()
        for code in request.concept_codes:
            concept_tickers |= ticker_map.get(code, set())
        if concept_tickers:
            pool_cache = pool_cache[pool_cache["ticker"].isin(concept_tickers)].copy()

    end_date = pd.Timestamp.today().strftime("%Y-%m-%d")
    try:
        result = run_screen(
            pool_df=pool_cache,
            price_cache_df=price_cache,
            end_date=end_date,
            top_n=request.top_n,
            bucket_weights=request.bucket_weights or DEFAULT_BUCKET_WEIGHTS,
            industry_neutral=request.industry_neutral,
            industries=request.industries,
            risk_filters=request.risk_filters,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return sanitize({**result, "readiness": readiness, "end_date": end_date})


@router.get("/defaults")
def screen_defaults() -> dict[str, Any]:
    return sanitize({"bucket_weights": DEFAULT_BUCKET_WEIGHTS})
