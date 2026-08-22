"""LLM 调用封装：DeepSeek chat/completions，强制 JSON 输出

所有业务侧 LLM 调用统一走这里，便于统计成本、控制超时与重试。
"""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


def _mock_response(system: str, user: str) -> dict:
    """无 API Key 且启用 mock 时的预设响应（用于验收/演示全流程）"""
    if "提取" in system or "尽调数据提取" in system:
        # 提取场景：从用户输入里抓债务人名和金额关键词（尽力模拟）
        import re

        m_name = re.search(r"(债务人[：:]\s*([^\s，,。；]+)|([^\s，,。；]{2,20}?(?:公司|集团|厂|中心)))", user)
        m_principal = re.search(r"([\d,.]+)\s*(万|亿)?\s*元?", user)
        principal = f"{m_principal.group(1)}万元" if m_principal and m_principal.group(2) == "万" else (m_principal.group(1) if m_principal else None)
        return {
            "debtors": [{
                "debtor_name": m_name.group(2) if m_name and m_name.group(2) else (m_name.group(3) if m_name else "模拟债务人"),
                "debtor_type": "enterprise",
                "principal_text": principal,
                "interest_text": None,
                "fees_text": None,
                "guaranty_type": None,
                "guarantor_text": None,
                "collateral_text": None,
                "judicial_status": None,
                "listing_price_text": None,
                "deadline": None,
                "extra_notes": "MOCK模式生成",
            }],
            "multi_debtor_ambiguous": False,
            "extraction_confidence": "low",
        }
    if "估值" in system:
        return {
            "conservative": {"total_cents": 800000000, "basis": "MOCK估值"},
            "neutral": {"total_cents": 1000000000, "basis": "MOCK估值"},
            "optimistic": {"total_cents": 1200000000, "basis": "MOCK估值"},
            "coverage": {"at_neutral": "103%", "at_auction_discount_70pct": "72%"},
            "liquidity_analysis": "MOCK分析",
        }
    if "尽调分析" in system:
        return {
            "summary": {
                "rating": "★★★",
                "core_logic": ["MOCK模式：请配置 DEEPSEEK_API_KEY 获取真实分析"],
                "suggested_buy_ratio": "需人工核实",
                "expected_recovery_rate": "60%~80%",
            },
            "risk": {
                "favorable": ["MOCK模式数据"],
                "risk": ["MOCK模式数据"],
                "need_manual_verify": ["真实尽调需配置 API Key"],
            },
        }
    # 默认
    return {"mock": True, "note": "MOCK模式：未配置 DEEPSEEK_API_KEY"}


async def chat_json(system: str, user: str, temperature: float = 0.1) -> dict[str, Any]:
    """调用 DeepSeek，要求 JSON 输出，校验为 dict。

    Raises:
        LLMError: 调用失败或两次重试后仍非合法 JSON
    """
    from ..config import get_settings  # 延迟导入，保持模块可独立加载

    settings = get_settings()

    if not settings.deepseek_api_key:
        if settings.llm_mock:
            logger.warning("LLM mock 模式：未配置 DEEPSEEK_API_KEY，返回预设数据")
            return _mock_response(system, user)
        raise LLMError("未配置 DEEPSEEK_API_KEY（可在 .env 配置；或设置 LLM_MOCK=true 启用演示模式）")

    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.deepseek_api_key}"}

    last_err: Exception | None = None
    for attempt in range(settings.llm_max_retries + 1):
        try:
            import httpx  # 延迟导入

            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                resp = await client.post(
                    f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                # 统计 token（用于积分核算）
                usage = data.get("usage", {})
                logger.info("LLM tokens: prompt=%s completion=%s", usage.get("prompt_tokens"), usage.get("completion_tokens"))
                obj = json.loads(content)
                if isinstance(obj, dict):
                    return obj
                last_err = LLMError(f"LLM 返回非对象 JSON: {type(obj)}")
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("LLM attempt %s failed: %s", attempt + 1, e)
    raise LLMError(f"LLM 调用失败: {last_err}")
