from __future__ import annotations

import json
from typing import Any

from .schemas import AgentScene


def _to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def build_prompt(
    scene: AgentScene,
    user_input: str,
    payload: dict[str, Any],
    response_style: str = "natural",
) -> tuple[str, str]:
    safety = (
        "你是 MyQuant 的量化研究助手。"
        "只能基于提供的数据做研究性分析，不得承诺收益，不得给出确定性买卖结论。"
        "如果数据不足，请直接说明缺口，并给出下一步需要补充或验证的内容。"
    )

    if response_style == "structured":
        base_system = (
            safety
            + "请输出 JSON 对象，字段必须包含："
            "summary(字符串),key_points(字符串数组),risks(字符串数组),actions(字符串数组)。"
            "不要输出 markdown，不要输出额外字段。"
        )
    else:
        base_system = (
            safety
            + "请用自然、完整的中文回答，像一位资深研究搭档在解释判断。"
            "不要套固定模板，不要强行使用“结论/关键点/风险/建议动作”四段式。"
            "可以按问题需要使用短段落或少量项目符号，但优先保证顺畅、具体、可读。"
            "先回答用户真正问的内容，再补充必要的风险和下一步动作。"
            "回答要完整收尾；如果篇幅较长，宁可压缩细节，也不要在句子中间结束。"
        )

    if scene == "stock_diagnosis":
        system = (
            base_system
            + "场景是个股诊断。重点关注趋势状态、风险触发、计划执行前检查项和失效条件。"
        )
    elif scene == "screen_explain":
        system = (
            base_system
            + "场景是筛选结果解释。重点关注权重偏向、行业/风格暴露、关键风险与调参建议。"
        )
    elif scene == "backtest_review":
        system = (
            base_system
            + "场景是回测复盘。重点关注收益来源、回撤阶段、稳健性问题和下一轮实验计划。"
        )
    elif scene == "news_analysis":
        system = (
            safety
            + "场景是新闻资讯分析。请先判断新闻对基本面、预期和短期交易情绪的影响，"
            "再给出需要跟踪的验证点。不要套固定五段式；只有在用户要求时才使用明确模板。"
            "使用自然中文输出，不要输出 JSON。"
        )
    else:
        system = (
            base_system
            + "场景是全局助手。重点解释应用功能、当前页面数据含义和操作建议。"
        )

    user = _to_json(
        {
            "scene": scene,
            "user_input": (user_input or "").strip(),
            "context": payload or {},
        }
    )
    return system, user
