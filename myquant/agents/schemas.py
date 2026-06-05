from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AgentScene = Literal[
    "global_chat",
    "stock_diagnosis",
    "screen_explain",
    "backtest_review",
    "news_analysis",
]


class AgentInvokeRequest(BaseModel):
    scene: AgentScene
    user_input: str = Field(default="", max_length=4000)
    payload: dict[str, Any] = Field(default_factory=dict)
    messages: list[dict[str, str]] = Field(default_factory=list)
    provider_config: dict[str, Any] = Field(default_factory=dict)
    response_style: Literal["natural", "structured"] = "natural"


class AgentResponse(BaseModel):
    scene: AgentScene
    render_mode: Literal["natural", "structured"] = "natural"
    natural_text: str = ""
    summary: str
    key_points: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    disclaimer: str
    raw_text: str
    provider: str = "kimi"
    model: str
    reasoning_content: str | None = None
    usage: dict[str, int] | None = None


class AgentOutputSchema(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    key_points: list[str] = Field(default_factory=list, max_length=12)
    risks: list[str] = Field(default_factory=list, max_length=12)
    actions: list[str] = Field(default_factory=list, max_length=12)
