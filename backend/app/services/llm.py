"""LLM 调用封装：DeepSeek chat/completions，强制 JSON 输出

所有业务侧 LLM 调用统一走这里，便于统计成本、控制超时与重试。
每次调用自动注入《AI 分析与约束规则文档》（backend/data/llm_constraints.md），
该文档随时可更新（保存即生效，无需重启）。
"""
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


def _constraints_path() -> Path:
    """约束文档路径：backend/data/llm_constraints.md（相对本文件上溯两级）"""
    base = Path(__file__).resolve().parent.parent.parent  # backend/
    for cand in [base / "data" / "llm_constraints.md", base / "llm_constraints.md"]:
        if cand.exists():
            return cand
    return base / "data" / "llm_constraints.md"


def _load_constraints() -> str:
    """读取约束文档内容（每次调用实时读取，文档更新立即生效；读取失败降级为内置默认约束）"""
    try:
        p = _constraints_path()
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("读取约束文档失败: %s", e)
    return _DEFAULT_CONSTRAINTS


# 内置兜底约束（文档缺失时使用，内容与文档一致的精简版）
_DEFAULT_CONSTRAINTS = (
    "【平台铁律】\n"
    "1. 绝对禁止编造：所有结论必须来自给定数据，缺失一律写「需人工核实」，宁可说不知道绝不编造。\n"
    "2. 关键数字（本金/利息/本息/估值/司法条数）严格以系统传入数据为准，禁止改写或推算新数字。\n"
    "3. 禁止买卖建议：不得输出建议买入价、收益率、利润测算、买入/卖出决策。\n"
    "4. 严禁出现\"AI\"字样，涉及系统能力一律用「系统」。\n"
    "5. 综合评级只给星（★~★★★★★），不给文字建议。\n"
    "6. 处置方案多路径并列展示，绝不推荐单一路径。\n"
    "7. 缺失数据标「需人工核实」，不得编造案号/判决结果/金额。"
)


def _mock_response(system: str, user: str) -> dict:
    """无 API Key 且启用 mock 时的预设响应（用于验收/演示全流程）"""
    if "提取" in system or "尽调数据提取" in system:
        # 提取场景：从用户输入里尽力抓取关键字段（模拟真实 LLM 的部分能力）
        import re

        m_name = re.search(r"债务人[：:]\s*([^\s，,。；]+)", user)
        if not m_name:
            m_name = re.search(r"([^\s，,。；]{2,20}?(?:公司|集团|厂|中心|商行|商行))", user)
        m_principal = re.search(r"本金[：:]?\s*([\d,.]+)\s*(万|亿)?", user) or re.search(r"([\d,.]+)\s*(万|亿)?\s*元", user)
        principal = None
        if m_principal:
            principal = f"{m_principal.group(1)}{m_principal.group(2) or ''}元" if m_principal.group(2) else f"{m_principal.group(1)}元"
        # 抵押物
        m_collateral = re.search(r"抵押物[：:]?\s*([^\n。；]+)", user)
        # 担保人
        m_guarantor = re.search(r"(?:保证人|担保人)[：:]?\s*([^\n。；]+)", user)
        # 计息起始日
        m_date = re.search(r"(?:计息起始日|计息日|起算日)[：:]?\s*(\d{4}[年/-]\d{1,2}[月/-]\d{1,2}日?)", user)
        # 地区
        m_region = re.search(r"地区[：:]?\s*([^\s，,。；]+)", user)
        # 执行法院
        m_court = re.search(r"(?:执行法院|法院)[：:]?\s*([^\s，,。；]+)", user)
        # 司法状态
        m_status = re.search(r"(?:司法状态|诉讼状态)[：:]?\s*([^\s，,。；]+)", user)

        def _norm_date(s):
            if not s:
                return None
            m = re.match(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?", s)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            return None

        return {
            "debtors": [{
                "debtor_name": m_name.group(1) if m_name else "模拟债务人",
                "debtor_type": "enterprise",
                "principal_text": principal,
                "interest_text": None,
                "fees_text": None,
                "guaranty_type": "抵押" if m_collateral else None,
                "guarantor_text": m_guarantor.group(1).strip() if m_guarantor else None,
                "collateral_text": m_collateral.group(1).strip() if m_collateral else None,
                "collateral_type": None,
                "mortgagor": None,
                "region": m_region.group(1).strip() if m_region else None,
                "judicial_status": m_status.group(1).strip() if m_status else None,
                "interest_base_date": _norm_date(m_date.group(1)) if m_date else None,
                "case_number": None,
                "case_cause": None,
                "listing_price_text": None,
                "deadline": None,
                "extra_notes": "演示模式生成（从输入文本尽力提取）",
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
                "core_logic": ["本报告为系统演示模式生成，建议完善数据后重新生成"],
            },
            "risk": {
                "favorable": ["系统演示模式"],
                "risk": ["数据完整性待提升"],
                "need_manual_verify": ["建议完善录入数据后重新生成报告"],
            },
        }
    # 默认
    return {"mock": True, "note": "系统演示模式"}


async def chat_json(system: str, user: str, temperature: float = 0.1) -> dict[str, Any]:
    """调用 DeepSeek，要求 JSON 输出，校验为 dict。

    自动在 system prompt 前注入《AI 分析与约束规则文档》内容。

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

    # 注入约束文档（实时读取，用户更新立即生效）
    constraints = _load_constraints()
    system_full = f"{constraints}\n\n===== 以下为本次任务的专用指令 =====\n{system}"

    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_full},
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
