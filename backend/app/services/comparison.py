"""对比分析服务（P2 基础）

对多个已尽调债权报告做横向对比：评级/回收率/覆盖率/建议买入价/风险点。
纯代码提取 + LLM 补充总结（mock 可用）。
"""
import json
import logging

from ..models import Report, Task, User
from .llm import LLMError, chat_json

logger = logging.getLogger(__name__)

# 对比维度定义（从报告 content 提取）
COMPARE_FIELDS = [
    {"key": "rating", "label": "综合评级", "section": "summary", "path": ["rating"]},
    {"key": "recovery_rate", "label": "预计回收率", "section": "summary", "path": ["expected_recovery_rate"]},
    {"key": "buy_price", "label": "建议买入价", "section": "summary", "path": ["suggested_buy_ratio", "suggested_buy_price_text"]},
    {"key": "principal", "label": "债权本金", "section": "claim_basic", "path": ["basic_table", "principal_cents"]},
    {"key": "guaranty", "label": "担保类型", "section": "claim_basic", "path": ["basic_table", "guaranty_type"]},
    {"key": "collateral", "label": "抵押物", "section": "collateral", "path": ["present"]},
    {"key": "legal_status", "label": "司法状态", "section": "claim_basic", "path": ["basic_table", "judicial_status"]},
]


def _extract_field(section: dict, path: list) -> object:
    """按路径从版块数据取值"""
    cur = section
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _report_key_metrics(report: Report) -> dict:
    """提取单份报告对比指标"""
    content = json.loads(report.content) if report.content else {}
    sections = content.get("sections", {})
    result = {
        "report_id": report.id,
        "version": report.version,
        "debtor_name": content.get("report_meta", {}).get("debtor_name"),
        "style": content.get("report_meta", {}).get("report_style"),
    }
    for field in COMPARE_FIELDS:
        sec = sections.get(field["section"], {})
        val = None
        for path in field["path"]:
            val = _extract_field(sec, path if isinstance(path, list) else [path])
            if val is not None:
                break
        result[field["key"]] = val
    # 风险点（risk 版块）
    risk = sections.get("risk", {})
    result["risk_points"] = risk.get("risk") or []
    return result


def build_comparison(reports: list[Report]) -> dict:
    """多报告对比。reports 需属于同一用户且已生成内容。"""
    metrics = [_report_key_metrics(r) for r in reports if r.content]
    return {
        "fields": COMPARE_FIELDS,
        "reports": metrics,
        "count": len(metrics),
    }


async def summarize_comparison(comparison: dict) -> dict:
    """LLM 生成对比总结（可选，mock 可用）"""
    system = """你是不良资产尽调分析助手。基于多个债权的对比指标，给出横向对比分析（仅供用户参考，不做买入决策）。
输出 JSON：{"highlights": ["亮点1"...], "recommendation": "优先关注xxx", "warnings": ["注意..."], "ranking": ["债务人A", "债务人B"...]}
要求：基于给定数据，禁止编造；数据缺失标注需人工核实；输出内容中严禁出现"AI"字样（AI生成/AI分析等一律禁用），涉及系统能力表述时使用"系统"二字。"""
    user = json.dumps(comparison, ensure_ascii=False)
    try:
        return await chat_json(system, user, temperature=0.3)
    except LLMError:
        return {
            "highlights": ["数据不足，暂无法生成智能对比，请完善数据后重试"],
            "recommendation": "需人工分析",
            "warnings": [],
            "ranking": [],
        }
