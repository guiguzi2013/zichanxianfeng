"""系统结构化提取服务（尽调引擎节点①）

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
0. 输出内容中严禁出现"AI"字样（AI生成/AI分析等一律禁用）；涉及系统能力表述时使用"系统"二字。
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
      "collateral_text": "抵押物完整描述原文摘录，含位置/面积/产权证号/结构/建成年份；无则 null",
      "judicial_status": "司法状态原文；无则 null",
      "listing_price_text": "挂牌价/起拍价原文；无则 null",
      "deadline": "YYYY-MM-DD；无则 null",
      "extra_notes": "其他有用信息原文摘录；无则 null",

      "collateral_type": "抵押物类型（住宅/商铺/商业/写字楼/工业厂房/土地等）；无则 null",
      "land_area_sqm": "土地面积，纯数字（如 9664.9），无则 null",
      "building_area_sqm": "建筑面积，纯数字（如 2631.81），无则 null",
      "build_year": "建成年份，纯数字（如 2010），无则 null",
      "structure_type": "建筑结构（轻钢结构/重钢结构/砖混框架/框架/钢结构等）；无则 null",
      "property_cert_no": "产权证号（房产证/不动产权证号，如'京房权证朝字第123456号'）；无则 null",
      "property_owner": "权利人/产权人（证载权利人，可能是债务人或抵押人）；无则 null",
      "property_use": "房屋/土地用途（住宅/商业/办公/工业/厂房/仓储等）；无则 null",
      "mortgage_reg_no": "抵押登记编号（他项权证号/抵押登记证明号）；无则 null",
      "mortgagor": "抵押人（提供抵押担保的主体）；无则 null",
      "region": "地区（省-市，如'山东-青岛'）；无则 null",
      "mortgage_amount": "抵押金额/担保金额原文；无则 null",
      "mortgage_rank": "抵押顺位/抵押权登记情况（第一顺位等）；无则 null",
      "seizure": "查封/轮候查封情况原文；无则 null",
      "collateral_status": "抵押物现状（占用/租赁/空置/在建等）；无则 null",
      "interest_base_date": "计息起始日 YYYY-MM-DD；无则 null",
      "case_number": "案号（如'（2024）鲁02民初123号'）；无则 null",
      "case_cause": "案由（如'金融借款合同纠纷'）；无则 null",
      "loan_bank": "贷款行/出让方；无则 null"
    }
  ],
  "multi_debtor_ambiguous": false,
  "extraction_confidence": "high | medium | low"
}

提取要点：
- 用户提供房产证/不动产权证书时，证上载明的全部信息都要提取：证号(property_cert_no)、权利人(property_owner)、坐落(进 collateral_text)、面积(land_area_sqm/building_area_sqm)、用途(property_use)、结构(structure_type)、建成年份(build_year)、抵押登记(mortgage_reg_no)。
- 原文没有的信息一律 null，绝不编造、不推断。"""

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


def _to_num(v) -> float | None:
    """LLM 输出的数字字符串（如 '9664.9'）→ float；无效/空 → None"""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s or s in ("null", "None", "-", "—"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _fmt_num(v) -> str | None:
    """数字 → 前端友好字符串（去尾零），None → None"""
    if v is None:
        return None
    f = float(v)
    if f == int(f):
        return str(int(f))
    return str(f)


# ---------- 完整度评估 ----------

# 关键字段（产品决策 2026-08-20）：债务人名称 / 债权本金 / 抵押物 三者齐备才可尽调
KEY_FIELDS = ["debtor_name", "principal_cents", "collateral"]
KEY_FIELD_LABELS = {
    "debtor_name": "债务人名称",
    "principal_cents": "债权本金",
    "collateral": "抵押物",
}

# ---------- 可尽调抵押物判定（2026-09-02 用户确认细化） ----------
# 用户规则：抵押物一般应是房产（我们只能对房产估价）；抵押物描述不清楚（只有类型词）、
# 或抵押物是机器设备/股权/应收账款/车辆等其他物品，不能尽调。
# "描述清楚" = 位置细节（路/街/大道/巷/弄/小区/苑/花园/幢/栋/层/室/镇/村/县/乡/
#   高新区/保税区/开发区/金融区等专有区域）或 面积(㎡) 或 证号 或 门牌号模式，至少一项。
# 普通"XX区/XX市"大范围不算（无法落到具体房产）；"XX县/XX乡"及专有区域算。
_REAL_ESTATE_TYPES = (
    "住宅", "商业", "工业", "土地", "厂房", "写字楼", "商铺", "公寓",
    "别墅", "仓储", "办公", "门店", "车位", "房产", "不动产", "楼", "大厦",
)
_PURE_TYPE_WORDS = {
    "房产", "住宅", "住宅房产", "商业", "商业用房", "工业", "工业厂房",
    "土地", "厂房", "写字楼", "商铺", "公寓", "别墅", "仓储", "办公",
    "门店", "车位", "抵押物", "不动产", "无", "—", "-", "其他",
}
_POSITION_DETAIL = (
    "路", "街", "大道", "巷", "弄", "小区", "苑", "花园", "幢", "栋",
    "层", "室", "镇", "村", "县", "乡",
    "高新区", "保税区", "开发区", "金融区",
)
_AREA_MARK = ("㎡", "平方米", "平米", "平方")
_CERT_MARK = ("权证", "房产证", "不动产权证", "登记证明", "产权证")
_DOOR_NUM_RE = re.compile(r"\d+\s*(号|幢|栋|室|层|单元)")


def is_valid_collateral(collateral: str, collateral_type: str = "") -> bool:
    """可尽调抵押物判定：房产类 + 描述具体（位置/面积/证号/门牌号 至少一项）。

    返回 False 的情况：抵押物缺失、纯类型词（如"住宅房产"）、非房产（设备/股权/车辆等）、
    描述只有大范围（如"青岛市黄岛区"）无具体位置信息。
    """
    text = (collateral or "").strip()
    ctype = (collateral_type or "").strip()
    if not text:
        return False
    if text in _PURE_TYPE_WORDS:
        return False
    combined = text + ctype
    # ① 必须是房产/不动产类（排除机器设备/股权/应收账款/车辆/存货等）
    if not any(k in combined for k in _REAL_ESTATE_TYPES):
        return False
    # ② 描述必须具体：位置细节 / 面积 / 证号 / 门牌号模式，至少一项
    if any(k in text for k in _POSITION_DETAIL):
        return True
    if any(k in text for k in _AREA_MARK):
        return True
    if any(k in text for k in _CERT_MARK):
        return True
    return bool(_DOOR_NUM_RE.search(text))


def evaluate_completeness(fields: dict[str, Any]) -> tuple[str, list[str]]:
    """返回 (等级, 缺失字段列表)。

    规则（产品确认）：
    - 关键字段（债务人/本金/抵押物）任一缺失 → red，不可勾选尽调；
    - 抵押物必须合格（is_valid_collateral：房产类+描述具体），否则视为缺失；
    - 关键字段齐备：次要字段（利息/担保类型/司法状态）缺失 ≤1 → green，否则 yellow。
    """
    missing: list[str] = []
    for k in KEY_FIELDS:
        v = fields.get(k)
        if k == "principal_cents":
            if v is None:
                missing.append(KEY_FIELD_LABELS[k])
        elif k == "collateral":
            extra = fields.get("extra_fields") or {}
            if not is_valid_collateral(v, extra.get("collateral_type")):
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
    # 扩展字段
    extra = fields.get("extra_fields") or {}
    if extra.get("region"):
        parts.append(f"地区：{extra['region']}")
    if extra.get("mortgagor"):
        parts.append(f"抵押人：{extra['mortgagor']}")
    if extra.get("collateral_type"):
        parts.append(f"抵押物类型：{extra['collateral_type']}")
    if extra.get("loan_bank"):
        parts.append(f"贷款行：{extra['loan_bank']}")
    if extra.get("batch"):
        parts.append(f"批次：{extra['batch']}")
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
        # 扩展字段（存入 extra_fields，见字段设计文档；2026-09-02 扩房产证/抵押物明细）
        extra = {
            "collateral_type": clean_empty(d.get("collateral_type")),
            "land_area_sqm": _fmt_num(_to_num(d.get("land_area_sqm"))),
            "building_area_sqm": _fmt_num(_to_num(d.get("building_area_sqm"))),
            "build_year": _fmt_num(_to_num(d.get("build_year"))),
            "structure_type": clean_empty(d.get("structure_type")),
            "property_cert_no": clean_empty(d.get("property_cert_no")),
            "property_owner": clean_empty(d.get("property_owner")),
            "property_use": clean_empty(d.get("property_use")),
            "mortgage_reg_no": clean_empty(d.get("mortgage_reg_no")),
            "mortgagor": clean_empty(d.get("mortgagor")),
            "region": clean_empty(d.get("region")),
            "batch": clean_empty(d.get("batch")),
            "loan_bank": clean_empty(d.get("loan_bank")),
            "mortgage_amount": clean_empty(d.get("mortgage_amount")),
            "mortgage_rank": clean_empty(d.get("mortgage_rank")),
            "seizure": clean_empty(d.get("seizure")),
            "collateral_status": clean_empty(d.get("collateral_status")),
            "interest_base_date": normalize_date(d.get("interest_base_date")),
            "case_number": clean_empty(d.get("case_number")),
            "case_cause": clean_empty(d.get("case_cause")),
        }
        fields["extra_fields"] = {k: v for k, v in extra.items() if v}
        completeness, missing = evaluate_completeness(fields)
        fields["completeness"] = completeness
        fields["missing_fields"] = missing
        fields["synthesized_description"] = synthesize_description(fields)
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
    # 扩展字段（Excel 列映射；2026-09-02 扩房产证/抵押物明细）
    extra = {}
    for k in ("collateral_type", "land_area_sqm", "building_area_sqm", "build_year", "structure_type",
              "property_cert_no", "property_owner", "property_use", "mortgage_reg_no",
              "mortgagor", "region", "batch", "loan_bank",
              "mortgage_amount", "mortgage_rank", "seizure", "collateral_status",
              "interest_base_date", "case_number", "case_cause"):
        v = row.get(k)
        if v is None or str(v).strip() == "":
            continue
        if k in ("land_area_sqm", "building_area_sqm", "build_year"):
            nv = _fmt_num(_to_num(v))
            if nv is not None:
                extra[k] = nv
        elif k == "interest_base_date":
            nd = normalize_date(str(v))
            if nd:
                extra[k] = nd
        else:
            extra[k] = clean_empty(str(v))
    fields["extra_fields"] = extra
    completeness, missing = evaluate_completeness(fields)
    fields["completeness"] = completeness
    fields["missing_fields"] = missing
    # 自动补全描述文本（description 缺失时供尽调上下文使用）
    fields["synthesized_description"] = synthesize_description(fields)
    return fields
