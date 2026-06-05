from __future__ import annotations

from collections import deque
from threading import Lock
from time import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from myquant import config
from myquant.agents.schemas import AgentInvokeRequest
from myquant.agents.service import KimiClientError, run_agent_scene

from ._utils import sanitize
from .stock import get_summary


router = APIRouter(prefix="/api/agent", tags=["agent"])


_RATE_LOCK = Lock()
_RATE_BUCKETS: dict[str, deque[float]] = {}


def _check_access_token(authorization: str | None) -> None:
    expected = config.AGENT_ACCESS_TOKEN.strip()
    if not expected:
        return
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少 Authorization 头")
    prefix = "Bearer "
    token = authorization[len(prefix) :].strip() if authorization.startswith(prefix) else authorization.strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="Agent 访问口令错误")


def _check_rate_limit(request: Request) -> None:
    per_minute = max(5, int(config.AGENT_RATE_LIMIT_PER_MINUTE))
    ip = request.client.host if request.client else "unknown"
    key = f"{ip}:{request.url.path}"
    now = time()
    window_start = now - 60.0

    with _RATE_LOCK:
        bucket = _RATE_BUCKETS.setdefault(key, deque())
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= per_minute:
            raise HTTPException(status_code=429, detail=f"请求过于频繁，请稍后再试（每分钟最多 {per_minute} 次）")
        bucket.append(now)


def _build_scene_payload(req: AgentInvokeRequest) -> dict[str, Any]:
    payload = dict(req.payload or {})
    if req.scene == "stock_diagnosis":
        ticker = str(payload.get("ticker") or "").strip()
        if not ticker:
            raise HTTPException(status_code=422, detail="stock_diagnosis 场景需要 payload.ticker")
        summary = get_summary(ticker=ticker, end_date=payload.get("end_date"))
        payload["stock_summary"] = summary
    return payload


@router.get("/health")
def health() -> dict[str, Any]:
    default_provider = config.AGENT_DEFAULT_PROVIDER if config.AGENT_DEFAULT_PROVIDER in {"kimi", "deepseek"} else "kimi"
    if default_provider == "deepseek":
        model = config.DEEPSEEK_MODEL
    else:
        model = config.KIMI_MODEL

    return {
        "ok": True,
        "provider": default_provider,
        "model": model,
        "available_providers": ["kimi", "deepseek"],
        "kimi_configured": bool(config.KIMI_API_KEY),
        "deepseek_configured": bool(config.DEEPSEEK_API_KEY),
        "token_required": bool(config.AGENT_ACCESS_TOKEN.strip()),
    }


@router.post("/invoke")
def invoke_agent(
    req: AgentInvokeRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_access_token(authorization)
    _check_rate_limit(request)

    payload = _build_scene_payload(req)
    try:
        out = run_agent_scene(
            req.scene,
            user_input=req.user_input,
            payload=payload,
            provider_config=req.provider_config,
            messages=req.messages,
            response_style=req.response_style,
        )
    except KimiClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Agent 调用失败: {exc}") from exc

    return sanitize(out.model_dump())
