from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class KimiClientError(RuntimeError):
    pass


def _join_chat_endpoint(base_url: str) -> str:
    clean = (base_url or "").rstrip("/")
    if clean.endswith("/chat/completions"):
        return clean
    if clean.endswith("/v1"):
        return clean + "/chat/completions"
    # DeepSeek base_url is https://api.deepseek.com (no /v1) → /chat/completions
    if "deepseek.com" in clean and not clean.endswith("/v1"):
        return clean + "/chat/completions"
    return clean + "/v1/chat/completions"


def _strip_html(text: str) -> str:
    """Strip HTML tags and collapse whitespace for cleaner error messages."""
    no_tags = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", no_tags).strip()


_HTTP_HINTS: dict[int, str] = {
    400: "请求参数错误，请检查模型名称和参数是否正确。",
    401: "API Key 无效或未携带，请在高级设置中填写正确的 API Key。",
    402: "账户余额不足，请前往服务商控制台充值。",
    403: "访问被拒绝（403）。常见原因：API Key 无权限访问该模型、Key 已过期，或当前模型未向您的账户开放。请换用低级别模型（如 moonshot-v1-8k）或检查 Key 权限。",
    429: "请求过于频繁，请稍后重试。",
    500: "LLM 服务器内部错误，请稍后重试。",
    503: "LLM 服务暂时不可用，请稍后重试。",
}


def _resolve_temperature(model: str, temperature: float) -> float:
    name = (model or "").strip().lower()
    if name.startswith("kimi-k2"):
        return 1.0
    return float(temperature)


class KimiClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_sec: int,
        temperature: float,
        max_output_tokens: int,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = _join_chat_endpoint(base_url)
        self.model = model
        self.timeout_sec = max(5, int(timeout_sec))
        self.temperature = float(temperature)
        requested_max_tokens = int(max_output_tokens)
        self.max_output_tokens = max(256, requested_max_tokens) if requested_max_tokens > 0 else 0

    def chat(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, str | None, str, dict[str, int] | None]:
        return self.chat_messages(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )

    def chat_messages(
        self,
        *,
        messages: list[dict[str, str]],
    ) -> tuple[str, str | None, str, dict[str, int] | None]:
        if not self.api_key:
            raise KimiClientError("API_KEY 未配置")

        effective_temperature = _resolve_temperature(self.model, self.temperature)
        payload: dict = {
            "model": self.model,
            "temperature": effective_temperature,
            "messages": messages,
        }
        if self.max_output_tokens > 0:
            payload["max_tokens"] = self.max_output_tokens
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        def _request(call_body: bytes) -> str:
            req = Request(
                self.base_url,
                data=call_body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            with urlopen(req, timeout=self.timeout_sec) as resp:
                return resp.read().decode("utf-8", errors="replace")

        def _raise_http(exc: HTTPError, raw_detail: str) -> None:
            clean = _strip_html(raw_detail)
            hint = _HTTP_HINTS.get(exc.code, "")
            if hint:
                raise KimiClientError(f"{hint}（HTTP {exc.code}）") from exc
            raise KimiClientError(f"LLM 请求失败: HTTP {exc.code} {clean[:300]}") from exc

        try:
            raw = _request(body)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
            if exc.code == 400 and "invalid temperature" in detail.lower() and payload["temperature"] != 1.0:
                payload["temperature"] = 1.0
                retry_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                try:
                    raw = _request(retry_body)
                except HTTPError as retry_exc:
                    retry_detail = (
                        retry_exc.read().decode("utf-8", errors="replace")
                        if hasattr(retry_exc, "read")
                        else str(retry_exc)
                    )
                    _raise_http(retry_exc, retry_detail)
                except URLError as retry_exc:
                    raise KimiClientError(f"LLM 请求失败: {retry_exc.reason}") from retry_exc
                except Exception as retry_exc:  # noqa: BLE001
                    raise KimiClientError(f"LLM 请求异常: {retry_exc}") from retry_exc
            else:
                _raise_http(exc, detail)
        except URLError as exc:
            raise KimiClientError(f"LLM 请求失败: {exc.reason}") from exc
        except Exception as exc:  # noqa: BLE001
            raise KimiClientError(f"LLM 请求异常: {exc}") from exc

        try:
            data = json.loads(raw)
            choices = data.get("choices") or []
            if not choices:
                raise ValueError("empty choices")
            msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            text = msg.get("content") if isinstance(msg, dict) else ""
            reasoning = msg.get("reasoning_content") if isinstance(msg, dict) else None
            if not isinstance(text, str) or not text.strip():
                finish_reason = choices[0].get("finish_reason") if isinstance(choices[0], dict) else None
                if reasoning:
                    raise ValueError(f"empty content; reasoning returned but final answer missing (finish_reason={finish_reason})")
                raise ValueError(f"empty content (finish_reason={finish_reason})")
            usage_raw = data.get("usage") if isinstance(data, dict) else None
            usage: dict[str, int] | None = None
            if isinstance(usage_raw, dict):
                prompt_tokens = usage_raw.get("prompt_tokens", usage_raw.get("input_tokens", 0))
                completion_tokens = usage_raw.get("completion_tokens", usage_raw.get("output_tokens", 0))
                total_tokens = usage_raw.get("total_tokens", 0)
                try:
                    p = max(0, int(prompt_tokens or 0))
                    c = max(0, int(completion_tokens or 0))
                    t = max(0, int(total_tokens or 0))
                    usage = {
                        "prompt_tokens": p,
                        "completion_tokens": c,
                        "total_tokens": t or (p + c),
                    }
                except Exception:
                    usage = None
            return text.strip(), reasoning or None, self.model, usage
        except Exception as exc:  # noqa: BLE001
            raise KimiClientError(f"LLM 返回解析失败: {exc}") from exc
