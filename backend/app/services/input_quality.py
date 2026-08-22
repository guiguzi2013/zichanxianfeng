"""输入质量检查：在尽调前发现可疑输入，提醒用户核对，避免在错误路线上浪费资源

- analyze_text(text)：用户粘贴文本的体检（长度/关键要素/OCR乱码/金额矛盾/多主体）
- analyze_claims(fields_list)：提取后字段级体检（金额异常/折扣异常）
- analyze_excel_rows(rows)：Excel 行级体检（缺失/零值/异常）
"""
import re

W = list[dict[str, str]]  # [{level: info|warning|error, text}]


def analyze_text(text: str) -> W:
    """粘贴文本体检"""
    out: W = []
    t = (text or "").strip()
    if not t:
        return [{"level": "error", "text": "输入为空"}]

    if len(t) < 50:
        out.append({"level": "warning", "text": "文本较短（不足 50 字），信息可能不全，报告将较多标注「需人工补充」"})

    # 关键要素
    if not re.search(r"[\d,，.．]+[\s]*[万亿元]|本金|金额", t):
        out.append({"level": "warning", "text": "未识别到金额相关信息（本金/利息/挂牌价等）"})
    if not re.search(r"债务人|借款人|被告|贷款人|债权", t):
        out.append({"level": "warning", "text": "未识别到债务人相关表述，请确认文本为债权信息"})
    if not re.search(r"抵押|担保|保证|质押", t):
        out.append({"level": "warning", "text": "文本未提及抵押物/担保信息，尽调报告将缺少关键版块"})

    # 多主体
    if re.search(r"被告[一二三四五六七八九十\d]|保证人[一二三四五六七八九十\d]|多名|多位", t):
        out.append({"level": "info", "text": "文本疑似包含多个主体（被告/保证人多位），系统会尝试拆分，请在预处理页核对"})

    # OCR 乱码痕迹
    if "\ufffd" in t or re.search(r"口口|��|�{2,}", t) or re.search(r"[，,。；;]{2,}", t):
        out.append({"level": "warning", "text": "文本疑似含 OCR 乱码/重复标点，请检查粘贴内容是否完整准确"})

    # 金额矛盾：同一段话里出现明显不同的本金表述
    amounts = re.findall(r"(\d[\d,，.]*)\s*(万|亿)\s*元?(?!元)", t)
    if len(amounts) >= 2:
        vals = []
        for num, unit in amounts[:5]:
            n = float(num.replace(",", "").replace("，", ""))
            vals.append(n * (10**8 if unit == "亿" else 10**4))
        if max(vals) / min(vals) > 50 if vals else False:
            out.append({"level": "warning", "text": "文本中多处金额差异巨大（可能本金/利息/挂牌价混用或粘贴错误），请核对"})

    return out


def analyze_claims(fields_list: list[dict]) -> W:
    """提取后字段级体检"""
    out: W = []
    for i, f in enumerate(fields_list, start=1):
        tag = f"第{i}条"
        principal = f.get("principal_cents")
        if principal is not None and principal <= 0:
            out.append({"level": "warning", "text": f"{tag}（{f.get('debtor_name') or '未命名'}）本金为 0 或负数，请核对"})
        interest = f.get("interest_cents")
        if principal and interest and interest > principal * 10:
            out.append({"level": "info", "text": f"{tag}（{f.get('debtor_name') or '未命名'}）利息远高于本金（可能为长期罚息累计，请核对计算基准）"})
        listing = f.get("listing_price_cents")
        if principal and listing and listing > principal:
            out.append({"level": "warning", "text": f"{tag}（{f.get('debtor_name') or '未命名'}）挂牌价高于本金（折扣率异常），请核对"})
    return out


def analyze_excel_rows(rows: list[dict]) -> W:
    """Excel 行级体检（聚合）"""
    out: W = []
    total = len(rows)
    if total == 0:
        return [{"level": "error", "text": "未解析到有效数据行"}]

    no_name = sum(1 for r in rows if not (r.get("debtor_name") or "").strip())
    no_principal = sum(1 for r in rows if r.get("principal_text") in (None, "") and r.get("principal_cents") is None)
    zero_principal = sum(1 for r in rows if r.get("principal_cents") is not None and r.get("principal_cents") <= 0)
    no_collateral = sum(1 for r in rows if not (r.get("collateral") or "").strip())

    if no_name:
        out.append({"level": "error", "text": f"{no_name}/{total} 行缺少债务人名称（标红，无法尽调）"})
    if no_principal:
        out.append({"level": "error", "text": f"{no_principal}/{total} 行缺少本金（标红，无法尽调）"})
    if zero_principal:
        out.append({"level": "warning", "text": f"{zero_principal} 行本金为 0 或负值，请核对"})
    if no_collateral:
        out.append({"level": "warning", "text": f"{no_collateral}/{total} 行缺少抵押物（关键字段，补充后才能尽调）"})

    # 数值疑似单位错误：本金文本带"亿"且数字 < 1（如 0.5 亿=5000万 正常；0.05亿=500万 也正常）——不做误报，仅提示极端值
    big = sum(1 for r in rows if r.get("principal_cents") is not None and r["principal_cents"] >= 10**11)  # >=1亿元
    if big:
        out.append({"level": "info", "text": f"{big} 行本金 ≥1 亿元，请确认单位/金额无误"})

    return out
