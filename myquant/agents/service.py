from __future__ import annotations

import json
import time
from typing import Any, Literal

from myquant import config

from .kimi_client import KimiClient, KimiClientError
from .prompt_builder import build_prompt
from .schemas import AgentOutputSchema, AgentResponse, AgentScene

DEFAULT_DISCLAIMER = (
    "本结果仅用于研究与复盘，不构成确定性投资建议；"
    "实际交易请结合实时行情、公告、流动性与个人风险承受能力。"
)


def _resolve_provider(provider_config: dict[str, Any]) -> str:
    provider = str(provider_config.get("provider") or config.AGENT_DEFAULT_PROVIDER or "kimi").strip().lower()
    if provider not in {"kimi", "deepseek"}:
        return "kimi"
    return provider


def _force_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _parse_model_json(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        return {}

    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        chunk = text[start : end + 1]
        try:
            return json.loads(chunk)
        except Exception:
            return {}
    return {}


def _fallback_summary(raw_text: str) -> tuple[str, list[str]]:
    lines = [line.strip(" -•\t") for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return "模型未返回可解析内容。", []
    return lines[0], lines[1:6]


def _natural_text_from_raw(raw_text: str, summary: str) -> str:
    text = (raw_text or "").strip()
    if text.startswith("{") and text.endswith("}"):
        return summary
    return text or summary


def _is_transient_agent_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(token in text for token in ["http 429", "http 500", "http 503", "timeout", "timed out"])


def _call_with_retry(
    *,
    client: KimiClient,
    messages: list[dict[str, str]],
    max_attempts: int = 3,
) -> tuple[str, str | None, str, dict[str, int] | None]:
    attempt = 0
    while True:
        attempt += 1
        try:
            return client.chat_messages(messages=messages)
        except KimiClientError as exc:
            if attempt >= max_attempts or not _is_transient_agent_error(exc):
                raise
            time.sleep(min(1.5 * attempt, 4.0))


def run_agent_scene(
    scene: AgentScene,
    *,
    user_input: str,
    payload: dict[str, Any],
    provider_config: dict[str, Any] | None = None,
    messages: list[dict[str, str]] | None = None,
    response_style: Literal["natural", "structured"] = "natural",
) -> AgentResponse:
    system_prompt, user_prompt = build_prompt(scene, user_input, payload, response_style=response_style)
    provider_config = provider_config or {}
    provider = _resolve_provider(provider_config)

    if provider == "deepseek":
        api_key = str(provider_config.get("api_key") or config.DEEPSEEK_API_KEY).strip()
        base_url = str(provider_config.get("base_url") or config.DEEPSEEK_BASE_URL).strip()
        model = str(provider_config.get("model") or config.DEEPSEEK_MODEL).strip()
        timeout_sec = config.DEEPSEEK_TIMEOUT_SEC
        temperature = config.DEEPSEEK_TEMPERATURE
        max_output_tokens = config.DEEPSEEK_MAX_OUTPUT_TOKENS
    else:
        api_key = str(provider_config.get("api_key") or config.KIMI_API_KEY).strip()
        base_url = str(provider_config.get("base_url") or config.KIMI_BASE_URL).strip()
        model = str(provider_config.get("model") or config.KIMI_MODEL).strip()
        timeout_sec = config.KIMI_TIMEOUT_SEC
        temperature = config.KIMI_TEMPERATURE
        max_output_tokens = config.KIMI_MAX_OUTPUT_TOKENS

    client = KimiClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_sec=timeout_sec,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    chat_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for item in messages or []:
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            chat_messages.append({"role": role, "content": content})
    chat_messages.append({"role": "user", "content": user_prompt})

    raw_text, reasoning_content, model, usage = _call_with_retry(client=client, messages=chat_messages)

    # Natural mode is the default chat experience. Structured fields are still
    # derived lightly so downstream quick actions can keep using summary text.
    if response_style != "structured" or scene == "news_analysis":
        natural_text = (raw_text or "").strip()
        summary, points = _fallback_summary(natural_text)
        return AgentResponse(
            scene=scene,
            render_mode="natural",
            natural_text=natural_text,
            summary=summary,
            key_points=points,
            risks=[],
            actions=[],
            disclaimer=DEFAULT_DISCLAIMER,
            raw_text=raw_text,
            provider=provider,
            model=model,
            reasoning_content=reasoning_content,
            usage=usage,
        )

    parsed = _parse_model_json(raw_text)

    if not parsed:
        summary, points = _fallback_summary(raw_text)
        natural_text = _natural_text_from_raw(raw_text, summary)
        return AgentResponse(
            scene=scene,
            render_mode="natural",
            natural_text=natural_text,
            summary=summary,
            key_points=points,
            risks=[],
            actions=[],
            disclaimer=DEFAULT_DISCLAIMER,
            raw_text=raw_text,
            provider=provider,
            model=model,
            reasoning_content=reasoning_content,
            usage=usage,
        )

    try:
        validated = AgentOutputSchema.model_validate(parsed)
    except Exception:
        summary, points = _fallback_summary(raw_text)
        natural_text = _natural_text_from_raw(raw_text, summary)
        return AgentResponse(
            scene=scene,
            render_mode="natural",
            natural_text=natural_text,
            summary=summary,
            key_points=points,
            risks=[],
            actions=[],
            disclaimer=DEFAULT_DISCLAIMER,
            raw_text=raw_text,
            provider=provider,
            model=model,
            reasoning_content=reasoning_content,
            usage=usage,
        )

    summary = str(validated.summary).strip() or "已完成分析。"
    raw_stripped = (raw_text or "").strip()
    render_mode: Literal["natural", "structured"] = "structured" if raw_stripped.startswith("{") and raw_stripped.endswith("}") else "natural"
    natural_text = _natural_text_from_raw(raw_text, summary)
    return AgentResponse(
        scene=scene,
        render_mode=render_mode,
        natural_text=natural_text,
        summary=summary,
        key_points=_force_list(validated.key_points),
        risks=_force_list(validated.risks),
        actions=_force_list(validated.actions),
        disclaimer=DEFAULT_DISCLAIMER,
        raw_text=raw_text,
        provider=provider,
        model=model,
        reasoning_content=reasoning_content,
        usage=usage,
    )


__all__ = ["run_agent_scene", "KimiClientError"]
