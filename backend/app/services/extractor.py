"""AI 结构化提取服务（尽调引擎节点①）

三种输入（文本/链接/Excel行）统一走这里。LLM 只做提取，金额/日期规范化和完整度评估在后端做。
"""
import json
import logging
import re
from typing import Any

from .llm import LLMError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是不良资产债权尽调领域的资深数据提取助手。
你的任务：从用户提供的【债权原始信息】中，提取出结构化的债权字段。
严格要求：
1. 只输出一个 JSON 对象，不要输出任何其他文字、解释或 Markdown 代码块标记。
2. 所有字段值必须是字符串或 null，金额字段保持"原始文本"形式（例如"539万元""1.2亿"），不要换算。
3. 严禁编造：原文中没有的信息必须填 null，不要猜测、不要补全。
4. 如果一段文字中包含多个债务人的债权信息，必须拆分为多条 debtor 记录；如果信息混杂无法准确拆分，设置 multi_debtor_ambiguous=true。
5. 担保类型枚举：抵押 / 保证 / 质押 / 信用；无法判断填 null。
6. 债务人类型枚举：enterprise（企业）/ person（自然人）；无法判断填 null。
7. 日期统一为 YYYY-MM-DD 格式；原文只有年份填 YYYY-01-01；无法判断填 null。

输出 JSON 结构：
{
  "debtors": [
    {
      "debtor_name": "债务人名称",
      "debtor_type": "enterprise | person | null",
      "principal_text": "债权本金原文，如'539万元'",
      "interest_text": "利息/罚息原文；无则 null",
      "fees_text": "费用原文；无则 null",
      "guaranty_type": "抵押 | 保证 | 质押 | 信用 | null",
      "guarantor_text": "保证人描述原文摘录；无则 null",
      "collateral_text": "抵押物完整描述原文摘录，含位置/面积/产权证号；无则 null",
      "judicial_status": "司法状态原文；无则 null",
      "listing_price_text": "挂牌价/起拍价原文；无则 null",
      "deadline": "YYYY-MM-DD；无则 null",
      "extra_notes": "其他有用信息原文摘录；无则 null"
    }
  ],
  "multi_debtor_ambiguous": false,
  "extraction_confidence": "high | medium | low"
}"""

# ---------- 金额/日期规范化 ----------

_CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def parse_amount_to_cents(text: str | None) -> int | None:
    """'539万元' → 539000000；'1.2亿' → 120000000；'未知/面议' → None"""
    if not text:
        return None
    t = text.strip()
    if not t or t in ("未知", "无", "暂无", "面议", "待定", "-", "—"):
        return None
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*(万亿|亿|万|元|角|分)?", t)
    if not m:
        return None
    num_str = m.group(1).replace(",", "")
    # 健壮性：逗号/小数点残缺导致的空串或非法数字（如 ",万"）直接返回 None，不抛异常
    if not num_str or not num_str.replace(".", "").isdigit():
        return None
    num = float(num_str)
    unit = m.group(2) or "元"
    multiplier = {"万亿": 10**12, "亿": 10**8, "万": 10**4, "元": 1, "角": 0.1, "分": 0.01}.get(unit, 1)
    return int(round(num * multiplier * 100))


def normalize_date(text: str | None) -> str | None:
    """'2025年4月20日' → '2025-04-20'；失败返回 None"""
    if not text:
        return None
    t = text.strip()
    m = re.match(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"(\d{4})[年/-](\d{1,2})[月]?", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-01"
    m = re.match(r"(\d{4})年?$", t)  # 纯年份："2025年" / "2025"
    if m:
        return f"{m.group(1)}-01-01"
    return None


def clean_empty(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if v in ("", "无", "暂无", "未知", "null", "None"):
        return None
    return v


# ---------- 完整度评估 ----------

# 关键字段（产品决策 2026-08-20）：债务人名称 / 债权本金 / 抵押物 三者齐备才可尽调
KEY_FIELDS = ["debtor_name", "principal_cents", "collateral"]
KEY_FIELD_LABELS = {
    "debtor_name": "债务人名称",
    "principal_cents": "债权本金",
    "collateral": "抵押物",
}


def evaluate_completeness(fields: dict[str, Any]) -> tuple[str, list[str]]:
    """返回 (等级, 缺失字段列表)。

    规则（产品确认）：
    - 关键字段（债务人/本金/抵押物）任一缺失 → red，不可勾选尽调；
    - 关键字段齐备：次要字段（利息/担保类型/司法状态）缺失 ≤1 → green，否则 yellow。
    """
    missing: list[str] = []
    for k in KEY_FIELDS:
        v = fields.get(k)
        if k == "principal_cents":
            if v is None:
                missing.append(KEY_FIELD_LABELS[k])
        elif not v:
            missing.append(KEY_FIELD_LABELS[k])

    if missing:
        return "red", missing

    secondary_missing = 0
    secondary: list[str] = []
    if fields.get("interest_cents") is None:
        secondary_missing += 1
        secondary.append("利息")
    if not fields.get("guaranty_type"):
        secondary_missing += 1
        secondary.append("担保类型")
    if not fields.get("judicial_status"):
        secondary_missing += 1
        secondary.append("司法状态")

    if secondary_missing <= 1:
        return "green", []
    return "yellow", secondary


def synthesize_description(fields: dict[str, Any]) -> str:
    """基于结构化字段自动生成债权描述文本（description 缺失时补全，供尽调上下文使用）"""
    parts = []
    if fields.get("debtor_name"):
        parts.append(f"债务人：{fields['debtor_name']}")
    if fields.get("principal_cents") is not None:
        parts.append(f"本金：{fields['principal_cents'] / 100 / 10000:.2f}万元")
    if fields.get("collateral"):
        parts.append(f"抵押物：{fields['collateral']}")
    if fields.get("guaranty_type"):
        parts.append(f"担保方式：{fields['guaranty_type']}")
    if fields.get("guarantor"):
        parts.append(f"保证人：{fields['guarantor']}")
    if fields.get("judicial_status"):
        parts.append(f"司法状态：{fields['judicial_status']}")
    if fields.get("listing_price_cents") is not None:
        parts.append(f"挂牌价：{fields['listing_price_cents'] / 100 / 10000:.2f}万元")
    return "；".join(parts) + "。" if parts else ""


# ---------- 主流程 ----------

async def extract_from_text(raw_text: str) -> list[dict]:
    """输入原始文本，返回规范化后的 claim 字段列表（含完整度）。
    抛 LLMError 表示提取失败。
    """
    if not raw_text or len(raw_text.strip()) < 10:
        raise LLMError("输入内容过少，请提供更完整的债权信息")

    user_prompt = f"""请从以下【债权原始信息】中提取结构化字段：

===== 原始信息开始 =====
{raw_text[:8000]}
===== 原始信息结束 =====

注意：
- 金额保持原文形式即可（如"539万元"），不要换算。
- 抵押物描述要完整保留（面积、产权证号、位置是尽调关键）。
- 严格按 JSON schema 输出。"""

    from .llm import chat_json  # 延迟导入（保持纯函数可独立测试）

    result = await chat_json(SYSTEM_PROMPT, user_prompt, temperature=0.1)
    debtors = result.get("debtors", [])
    if not debtors:
        raise LLMError("未能从输入中提取到债权信息")

    claims = []
    for d in debtors:
        fields = {
            "debtor_name": clean_empty(d.get("debtor_name")),
            "debtor_type": d.get("debtor_type"),
            "principal_cents": parse_amount_to_cents(d.get("principal_text")),
            "interest_cents": parse_amount_to_cents(d.get("interest_text")),
            "fees_cents": parse_amount_to_cents(d.get("fees_text")),
            "guaranty_type": clean_empty(d.get("guaranty_type")),
            "guarantor": clean_empty(d.get("guarantor_text")),
            "collateral": clean_empty(d.get("collateral_text")),
            "judicial_status": clean_empty(d.get("judicial_status")),
            "listing_price_cents": parse_amount_to_cents(d.get("listing_price_text")),
            "deadline": normalize_date(d.get("deadline")),
            "extra_notes": clean_empty(d.get("extra_notes")),
        }
        completeness, missing = evaluate_completeness(fields)
        fields["completeness"] = completeness
        fields["missing_fields"] = missing
        claims.append(fields)
    return claims


def extract_from_excel_row(row: dict[str, Any]) -> dict[str, Any]:
    """Excel 行（已按列映射）→ claim 字段。规范表头直接映射，不调 LLM。"""
    fields = {
        "debtor_name": clean_empty(row.get("debtor_name")),
        "debtor_type": None,
        "principal_cents": parse_amount_to_cents(str(row.get("principal_text", "")) if row.get("principal_text") is not None else None),
        "interest_cents": parse_amount_to_cents(str(row.get("interest_text", "")) if row.get("interest_text") is not None else None),
        "fees_cents": None,
        "guaranty_type": clean_empty(row.get("guaranty_type")),
        "guarantor": clean_empty(row.get("guarantor")),
        "collateral": clean_empty(row.get("collateral")),
        "judicial_status": clean_empty(row.get("judicial_status")),
        "listing_price_cents": None,
        "deadline": normalize_date(row.get("deadline")),
        "extra_notes": clean_empty(row.get("extra_notes")),
    }
    completeness, missing = evaluate_completeness(fields)
    fields["completeness"] = completeness
    fields["missing_fields"] = missing
    # 自动补全描述文本（description 缺失时供尽调上下文使用）
    fields["synthesized_description"] = synthesize_description(fields)
    return fields
