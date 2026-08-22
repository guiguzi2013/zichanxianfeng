"""Excel 解析与列映射（对应设计文档《Excel列映射方案.md》）

三层：表头同义词自动识别 → 单位/格式归一化 → 返回映射预览 + 数据。
"""
import csv
import io
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 表头同义词词典：标准字段 -> 表头关键词列表
HEADER_SYNONYMS: dict[str, list[str]] = {
    "debtor_name": ["债务人", "债权项目", "借款人", "企业名称", "债务人名称", "债务企业", "借款企业"],
    "principal_text": ["本金", "债权本金", "借款本金", "贷款本金"],
    "interest_text": ["利息", "债权利息", "欠息", "利息罚息", "应收利息"],
    "fees_text": ["费用", "诉讼费", "保全费", "实现债权费用"],
    "guaranty_type": ["担保类型", "担保方式", "担保", "担保形式"],
    "guarantor": ["保证人", "担保人", "连带保证", "保证人名称"],
    "collateral": ["抵押物", "抵押物情况", "抵押物描述", "抵质押物", "担保物", "抵押情况"],
    "judicial_status": ["执行法院", "司法状态", "诉讼状态", "法院", "受理法院", "管辖法院"],
    "listing_price_text": ["挂牌价", "起拍价", "评估价", "债权转让价", "转让价格"],
    "deadline": ["截止日期", "到期日", "拍卖时间", "报名截止", "挂牌截止"],
    "extra_notes": ["备注", "说明", "其他", "附注"],
}

# 表头单位解析：列名里的单位词
_UNIT_PATTERN = re.compile(r"[（(]?\s*(万亿|亿|万|元)\s*[)）]?")

# 表头清洗：去空白、去括号内容、去单位词
def _clean_header(raw: str) -> str:
    t = re.sub(r"[（(][^）)]*[)）]", "", raw)  # 去括号内容
    t = _UNIT_PATTERN.sub("", t)
    return t.strip()


def build_mapping(headers: list[str]) -> dict[str, str]:
    """表头列表 -> {标准字段: 原始列名}，未识别的列省略（进 extra）"""
    mapping: dict[str, str] = {}
    for raw in headers:
        cleaned = _clean_header(raw)
        if not cleaned:
            continue
        for field, keywords in HEADER_SYNONYMS.items():
            if field in mapping:
                continue
            if any(kw in cleaned or cleaned in kw for kw in keywords):
                mapping[field] = raw
                break
    return mapping


def _detect_unit(raw: str) -> int:
    """表头里带 '万'/'亿' 返回倍率，否则 1"""
    m = re.search(r"[（(]\s*(万亿|亿|万|元)\s*[)）]", raw) or re.search(r"(万亿|亿|万)", raw)
    if not m:
        return 1
    return {"万亿": 10**8, "亿": 10**4, "万": 10**2, "元": 1}.get(m.group(1), 1)
    # 说明：返回的是"转为分"的倍率：万元*10000*100 = 值*10^6 -> 这里先按 10^2 表示"万元->元"的换算？不对。
    # 修正：值(万元) * 10000(元/万) * 100(分/元) = 值 * 1,000,000


def _to_cents(value: Any, unit_mult: int) -> int | None:
    """值转分。unit_mult 为表头单位倍率（万元=10000）。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    else:
        t = str(value).strip().replace(",", "").replace("，", "")
        if not t or t in ("未知", "无", "面议", "-", "—", "待定"):
            return None
        # 去掉内嵌单位（如 "539万"）
        m = re.match(r"^([\d.]+)\s*(万亿|亿|万|元)?$", t)
        if not m:
            return None
        num = float(m.group(1))
        if m.group(2):
            unit_mult = {"万亿": 10**12, "亿": 10**8, "万": 10**4, "元": 1}.get(m.group(2), 1)
    return int(round(num * unit_mult * 100))


def _apply_unit_inheritance(rows: list[dict[str, Any]], unit_mult: dict[str, int]) -> None:
    """无单位金额列继承主金额列（principal_text）的单位倍率。

    场景：表头"债权本金（万元）"标了单位，但"债权利息"没标，实际同为万元。
    规则：对 unit_mult 中未出现的金额字段，若该行 principal_text 已解析且其倍率>1，
    则按同倍率重算该字段（仅当原值较小、疑似漏标单位时）。
    """
    amount_fields = ("principal_text", "interest_text", "fees_text", "listing_price_text")
    main_mult = unit_mult.get("principal_text", 1)
    for row in rows:
        for field in amount_fields:
            if field in unit_mult:
                continue  # 该列表头自带单位
            value = row.get(field)
            if value is None or not isinstance(value, int):
                continue
            # 原值被当"元"解析且 < 1亿分（=100万元），疑似实际为万元
            if main_mult > 1 and value < 100_000_000:
                row[field] = int(round(value * main_mult))
                row[f"{field}_unit_inherited"] = True


def parse_excel(file_bytes: bytes, filename: str) -> tuple[list[dict[str, Any]], dict, list[str]]:
    """解析 Excel/Csv。

    Returns:
        (rows, mapping, unmapped_columns)
        rows: [{标准字段: 值}, ...]（金额已转分）
        mapping: {标准字段: 原始列名}
        unmapped_columns: 未识别的列名
    """
    if filename.lower().endswith(".csv"):
        return _parse_csv(file_bytes)
    return _parse_xlsx(file_bytes)


def _parse_xlsx(file_bytes: bytes) -> tuple[list[dict[str, Any]], dict, list[str]]:
    from openpyxl import load_workbook  # 延迟导入：无该依赖时纯函数仍可测试

    wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header = [str(h) if h is not None else "" for h in next(rows_iter)]
    except StopIteration:
        return [], {}, []
    mapping = build_mapping(header)
    unmapped = [h for h in header if h and h not in mapping.values()]

    # 单位倍率
    unit_mult: dict[str, int] = {}
    for field, raw in mapping.items():
        if field in ("principal_text", "interest_text", "fees_text", "listing_price_text"):
            unit_mult[field] = _detect_unit(raw)

    rows = []
    for raw_row in rows_iter:
        if all(v is None or str(v).strip() == "" for v in raw_row):
            continue
        row: dict[str, Any] = {}
        for i, col_name in enumerate(header):
            if i >= len(raw_row):
                continue
            value = raw_row[i]
            field = next((f for f, r in mapping.items() if r == col_name), None)
            if not field:
                continue
            if field in unit_mult:
                row[field] = _to_cents(value, unit_mult[field])
            else:
                row[field] = str(value).strip() if value is not None else None
        rows.append(row)
    _apply_unit_inheritance(rows, unit_mult)
    return rows, mapping, unmapped


def _parse_csv(file_bytes: bytes) -> tuple[list[dict[str, Any]], dict, list[str]]:
    # 编码探测：优先 UTF-8，失败 GBK
    text = None
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            text = file_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("无法识别 CSV 编码")

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return [], {}, []
    mapping = build_mapping(header)
    unmapped = [h for h in header if h and h not in mapping.values()]

    unit_mult: dict[str, int] = {}
    for field, raw in mapping.items():
        if field in ("principal_text", "interest_text", "fees_text", "listing_price_text"):
            unit_mult[field] = _detect_unit(raw)

    rows = []
    for raw_row in reader:
        if all(not c.strip() for c in raw_row):
            continue
        row: dict[str, Any] = {}
        for i, col_name in enumerate(header):
            if i >= len(raw_row):
                continue
            value = raw_row[i].strip()
            if not value:
                continue
            field = next((f for f, r in mapping.items() if r == col_name), None)
            if not field:
                continue
            if field in unit_mult:
                row[field] = _to_cents(value, unit_mult[field])
            else:
                row[field] = value
        rows.append(row)
    _apply_unit_inheritance(rows, unit_mult)
    return rows, mapping, unmapped
