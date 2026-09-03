"""京东债权附件服务（2026-09-01）

流程：渲染页面 → 提取 标的物属性 + 附件链接 → 下载信息类附件到服务器 →
      解析资产清单(表格)回填字段 → 与 feed_items 债权关联（detail.attachments）
"""
import json
import logging
import os
import re

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _attachments_dir(feed_id: int) -> str:
    """附件存储目录：{upload_dir}/feed_attachments/{feed_id}/"""
    base = os.path.join(settings.upload_dir, "feed_attachments", str(feed_id))
    os.makedirs(base, exist_ok=True)
    return base


def _clean_collateral_guarantor(text: str) -> dict:
    """从混杂文本中分离 抵押物描述 / 保证人名单（2026-09-01 用户要求：不粗糙堆放）

    源文本常形如（表格"担保措施/担保详情"列、kv 长文本）：
      "1.王胜标、刘竹保证担保；2.王胜标、刘竹持有的…股权质押担保；3.王胜标、刘竹名下位于…房产抵押担保。"
    按编号分句：保证担保句→保证人名单；抵押/质押/房产句→抵押物描述。
    """
    if not text:
        return {}
    s = str(text)
    out: dict = {}

    # 前置分支：带"抵押物信息/保证人信息/抵押物：/保证人："标记的长文本（如文本型公告）
    # 直接按标记切段，避免编号分离把"债权评估价"等误当保证人
    has_marker = re.search(r'(抵押物信息|保证人信息|抵押物[：:]|抵质押物[：:]|保证人[：:]|担保人[：:])', s)
    if has_marker:
        # 抵押物段：抵押物信息/抵押物： 到 保证人/担保人 前
        m = re.search(r'(?:抵押物信息|抵押物|抵质押物)[：:]?\s*(.+?)(?=保证人|担保人|查封物|$)', s)
        if m and m.group(1):
            desc = re.sub(r'（[^）]*）', '', m.group(1)).strip('：:，。；;、 \t\n')
            if desc and len(desc) > 2:
                out["collateral_desc"] = desc[:400]
        # 保证人段
        g = re.search(r'(?:保证人信息|保证人|担保人)[：:]?\s*(.+?)(?=抵押物|查封物|$)', s)
        if g and g.group(1):
            raw = re.sub(r'^\d+[.、]?\s*', '', g.group(1)).strip('：:，。；;、 ')
            raw = re.sub(r'(提供|承担).*(连带|保证|担保).*$', '', raw).strip('，。；;、 ')
            names = re.split(r'[、，,;；\s]+', raw)
            names = [n.strip('，。；;、') for n in names if n.strip() and n.strip() not in ("无", "—", "-", "提供")]
            names = [n for n in names if not re.search(r'(?:提供的|持有的|名下)', n)]
            if names:
                out["guarantor_names"] = "、".join(dict.fromkeys(names))[:300]
        return out

    # 按编号分句（担保措施列等）：编号如 "1.王胜标"、"2、钟斌"，且编号后跟中文
    # （负向后顾避免切 "139.3平方米" 这类小数）
    clauses = re.split(r'(?<![.\d])\d+[.、](?=\s*[\u4e00-\u9fa5])', s)
    coll_parts: list[str] = []
    guar_names: list[str] = []
    for c in clauses:
        c = c.strip()
        if not c:
            continue
        if re.search(r'保证担保|连带清偿|承担连带|保证责任', c):
            m = re.search(r'([^。；;]+?)(?:提供)?保证担保|承担连带清偿责任', c)
            if m and m.group(1):
                raw = m.group(1)
                raw = re.sub(r'^\d+[.、]?\s*', '', raw).strip()
                raw = re.sub(r'(保证|担保|连带).*$', '', raw).strip()
                raw = re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9·、，,]+', '', raw).strip('、，,')
                raw = re.sub(r'^(并由|并|由)', '', raw).strip('、，,')  # "并由马志祥…承担连带" → 马志祥…
                for n in re.split(r'[、，,]+', raw):
                    n = n.strip('、，, ')
                    # 过滤：纯数字/金额片段、单字、代词、公司后缀但含"等"的汇总
                    if not n or len(n) < 2:
                        continue
                    if re.fullmatch(r'[\d\.,]+(元|万|万元|亿|亿元)?', n):
                        continue
                    if re.search(r'(?:持有的|名下|提供|等$)', n):
                        continue
                    guar_names.append(n)
        elif re.search(r'抵押|质押|房产|住宅|商铺|土地|厂房|车位|商业|房屋', c):
            c2 = re.sub(r'^\d+[.、]?\s*', '', c)
            c2 = re.sub(r'（[^）]*）', '', c2).strip('。；;、 ')
            # 去"抵押物X：/该笔贷款抵押物为：/抵质押物："等前缀 与 残留编号
            c2 = re.sub(r'^(?:该笔贷款)?抵押物\d*[：:为]?|抵质押物\d*[：:为]?|质押物\d*[：:]?|抵押物信息[：:]?', '', c2).strip('：:，。；;、 ')
            c2 = re.sub(r'^\d+[.、：:]?\s*', '', c2).strip('：:，。；;、 ')
            if not re.match(r'^[^，。]*?(保证担保|承担连带)', c2) and c2 and len(c2) > 3:
                coll_parts.append(c2)
    seen: list[str] = []
    for n in guar_names:
        if n not in seen:
            seen.append(n)
    out: dict = {}
    if coll_parts:
        out["collateral_desc"] = "；".join(coll_parts)[:400]
    if seen:
        out["guarantor_names"] = "、".join(seen)[:300]
    return out


def _parse_asset_list(docx_path: str) -> dict:
    """解析"资产清单"docx/xlsx 表格 → 提取 本金/利息/抵押物/保证人等字段（供回填）

    原文附件 word/excel/pdf 混合（2026-09-01 用户提示）；按扩展名分流解析。
    """
    import os as _os
    from ..scrapers.jd_page import extract_docx_tables, extract_excel_tables

    ext = _os.path.splitext(docx_path)[1].lower()
    if ext in (".xlsx", ".xls"):
        tables = extract_excel_tables(docx_path)
    else:
        tables = extract_docx_tables(docx_path)
    out: dict = {}
    for t in tables:
        headers = t.get("headers") or []
        rows = t.get("rows") or []
        if not headers:
            continue
        # 列定位
        def col(*keys):
            for i, h in enumerate(headers):
                if any(k in h for k in keys):
                    return i
            return None

        p_i = col("本金", "贷款本金")
        i_i = col("利息", "欠息")
        fee_i = col("代垫费用", "垫付费用", "费用")
        # 债权总额列：排除"利息合计/利息及孳息"等含"利息"的列（避免误配）
        total_i = None
        for i, h in enumerate(headers):
            if "利息" in h:
                continue
            if any(k in h for k in ("本息及费用合计", "本息合计", "债权总额", "债权合计", "合计", "小计")):
                total_i = i
                break
        coll_i = col("抵押物", "抵押情况", "担保物", "抵质押", "押品")
        guar_i = col("保证人", "担保人", "保证情况")
        debtor_i = col("债务人", "借款企业", "借款人", "单位名称")

        # 求和(跳过合计行,去空格)
        def is_sum(r):
            for c in r[:3]:
                s = str(c or "").replace(" ", "").replace("\u3000", "")
                if any(k in s for k in ("合计", "总计", "小计")):
                    return True
            return False

        def num(v):
            try:
                return float(str(v).replace(",", "").strip())
            except (TypeError, ValueError):
                return None

        def pick(idx):
            if idx is None:
                return None
            total = 0.0
            hit = False
            for r in rows:
                if is_sum(r) or not r:
                    continue
                v = num(r[idx]) if len(r) > idx else None
                if v is not None:
                    total += v
                    hit = True
            return total if hit else None

        # 单位：表头含"（元）"→元,含"万元"→万,否则按值量级
        def unit(idx):
            if idx is None:
                return None
            h = headers[idx]
            if "万元" in h or "（万）" in h:
                return "万"
            if "元" in h and "万元" not in h:
                return "元"
            return None

        def std(idx):
            v = pick(idx)
            if v is None:
                return None
            u = unit(idx)
            if u is None:
                # 全表极值判断
                mx = 0.0
                for r in rows:
                    if is_sum(r) or not r:
                        continue
                    for c in r:
                        n = num(c)
                        if n is not None and n > mx:
                            mx = n
                u = "万" if mx < 100_000 else "元"
            from ..scrapers.text_extract import normalize_money
            return normalize_money(f"{v}{u}")

        for key, idx, dst in (("principal", p_i, "claim_total"),
                              ("interest", i_i, "interest"),
                              ("fee", fee_i, "other_fees"),
                              ("total", total_i, "total_claims")):
            s = std(idx)
            if s:
                out[dst] = s

        # 抵押物/保证人：逐行收集非空
        if coll_i is not None:
            parts = [r[coll_i].strip() for r in rows
                     if not is_sum(r) and len(r) > coll_i and r[coll_i] and r[coll_i] not in ("—", "-", "无")]
            if parts:
                out["collateral_desc"] = "；".join(parts)[:500]
                from ..scrapers.text_extract import classify_collateral
                ct = classify_collateral(out["collateral_desc"])
                if ct:
                    out["collateral_type"] = ct
        if guar_i is not None:
            parts = [r[guar_i].strip() for r in rows
                     if not is_sum(r) and len(r) > guar_i and r[guar_i] and r[guar_i] not in ("—", "-", "无")]
            if parts:
                out["guarantor_names"] = "；".join(parts)[:500]
        if debtor_i is not None:
            names = [r[debtor_i].strip() for r in rows
                     if not is_sum(r) and len(r) > debtor_i and r[debtor_i]]
            if names:
                out["debtor_names"] = names[:50]
                out["debtor_count"] = len(names)
    return out


def _parse_valuation_report(file_path: str) -> dict:
    """解析评估报告 → {year, value_text, value_cents, source}

    评估报告是抵押物价值的最权威参考（2026-09-01 用户规则）：
      - 评估年份在 2 年内 → 估值直接采用（房产近年降价大，2年内可信）
      - 超过 2 年 → 仅作参考，估值走成本法；报告仍展示供下载
    从文本中提取：评估基准日/评估日期（年份）、评估价值（元/万元/亿元）。
    """
    import re as _re
    from ..scrapers.jd_page import extract_text_from_any

    text = extract_text_from_any(file_path) or ""
    out: dict = {}
    if not text:
        return out

    # 年份：评估基准日/评估日期/评估时点 或 文件名年份
    year = None
    m = _re.search(r'(?:评估基准日|评估日期|评估时点|评估日|基准日)[：:为]?\s*(\d{4})\s*年', text)
    if not m:
        m = _re.search(r'(?:20\d{2})\s*年?\s*(?:评估|估价)', text)
    if not m:
        m = _re.search(r'\b(20\d{2})\s*年', text)
    if m:
        year = int(m.group(1))
    out["year"] = year

    # 评估价值：多种写法
    val_text = None
    val_cents = None
    for pat in (
        r'评估价值[^，。；\n]{0,20}?([\d,]+\.?\d*)\s*(亿元|万元|万|元)',
        r'评估总价[^，。；\n]{0,20}?([\d,]+\.?\d*)\s*(亿元|万元|万|元)',
        r'评估价[^，。；\n]{0,20}?([\d,]+\.?\d*)\s*(亿元|万元|万|元)',
        r'市场价值[^，。；\n]{0,20}?([\d,]+\.?\d*)\s*(亿元|万元|万|元)',
        r'总值[^，。；\n]{0,10}?([\d,]+\.?\d*)\s*(亿元|万元|万|元)',
    ):
        m = _re.search(pat, text)
        if m:
            val_text = f"{m.group(1)}{m.group(2)}"
            num = float(m.group(1).replace(",", ""))
            unit = m.group(2)
            if unit in ("亿元", "亿"):
                val_cents = int(num * 100_000_000 * 100)
            elif unit in ("万元", "万"):
                val_cents = int(num * 10_000 * 100)
            elif unit == "元":
                val_cents = int(num * 100)
            break
    out["value_text"] = val_text
    out["value_cents"] = val_cents
    return out


def enrich_jd_claim(feed_id: int, source_url: str, detail: dict) -> dict:
    """对京东债权做页面增强：属性回填 + 附件下载关联。返回更新后的 detail。

    - 从 source_url 提取 paimai_id
    - 属性区块(债权本金/抵质押物/担保方式等)回填 detail 空缺字段
    - 信息类附件下载到服务器,记录 attachments 列表
    - 资产清单 docx 解析回填 本金/利息/抵押物/保证人
    """
    from ..scrapers.jd_page import fetch_jd_page_data, download_attachment

    m = re.search(r'paimai\.jd\.com/(\d+)', source_url or "")
    if not m:
        return detail
    paimai_id = m.group(1)

    page = fetch_jd_page_data(paimai_id)
    props = page.get("properties") or {}
    changed = False

    # 1. 属性回填（只填空缺；2026-09-02 加"抵保方式"变体与"抵质押物地址"→抵押物描述）
    prop_map = {
        "债权本金": "claim_total",
        "有无抵质押物": None,  # 有→有抵押,无→无；用于抵押物提示
        "担保方式": "guaranty_type",
        "抵保方式": "guaranty_type",  # 京东变体（453 案例"标的物详情"表用"抵保方式"）
        "抵质押物类型": "collateral_type",
        "抵质押物地址": "collateral_desc",  # 标的物详情表→抵押物描述（2026-09-02）
        "标的物所在地": "region",
    }
    for k, dst in prop_map.items():
        v = props.get(k)
        if not v:
            continue
        if dst == "claim_total" and not detail.get("claim_total"):
            v2 = re.sub(r'[¥￥]', '', v)
            from ..scrapers.text_extract import normalize_money
            detail["claim_total"] = normalize_money(v2)
            changed = True
        elif dst == "guaranty_type" and not detail.get("guaranty_type"):
            detail["guaranty_type"] = v
            changed = True
        elif dst == "collateral_type" and not detail.get("collateral_type"):
            detail["collateral_type"] = v
            changed = True
        elif dst == "collateral_desc" and not detail.get("collateral_desc"):
            detail["collateral_desc"] = v
            changed = True
        elif dst == "region" and not detail.get("region"):
            detail["region"] = v
            changed = True
    # 有无抵质押物 → 提示（有但无类型时不乱填类型）
    if props.get("有无抵质押物") == "有" and not (detail.get("collateral_type") or detail.get("collateral_desc")):
        detail["has_collateral"] = True
        changed = True

    # 1.5 页面债权表格回填（2026-09-02 修复：页面 <table> 此前漏抓——465 案例的
    # 债务人/债权合计/本金/利息/代垫/担保情况 表格；抓取核心要求：原文表格必须抓到并格式化）
    for t in page.get("tables") or []:
        headers = t.get("headers") or []
        rows = t.get("rows") or []
        if not headers:
            continue
        joined_h = "".join(headers)
        # 只处理债权类表格（含 债务人/债权本金/债权合计 等），跳过出价/竞买记录
        if not any(k in joined_h for k in ("债务人", "债权本金", "债权合计", "本金余额", "担保情况")):
            continue
        if "竞买" in joined_h or "出价" in joined_h:
            continue
        # 回填 announce_table（仅当库内无表格时，避免覆盖已有更全的公告表格）
        if not detail.get("announce_table"):
            detail["announce_table"] = {"headers": headers, "rows": rows}
            changed = True
        # 字段回填（只填空缺）
        def _col(*keys):
            for i, h in enumerate(headers):
                if any(k in h for k in keys):
                    return i
            return None
        from ..scrapers.text_extract import normalize_money as _nm, classify_collateral as _cc

        def _cell(idx):
            if idx is None:
                return None
            for r in rows:
                if len(r) > idx and r[idx] and r[idx].strip() not in ("—", "-", "无", ""):
                    return r[idx].strip()
            return None

        p_i = _col("债权本金", "本金余额", "本金")
        i_i = _col("债权利息", "利息余额", "利息")
        f_i = _col("代垫费用", "垫付费用", "费用")
        t_i = _col("债权合计", "债权总额", "合计")
        g_i = _col("担保情况", "担保措施", "抵押情况", "担保")
        d_i = _col("债务人", "借款企业", "借款人")
        if p_i is not None:
            v = _cell(p_i)
            if v and not detail.get("claim_total"):
                detail["claim_total"] = _nm(v)
                changed = True
        if i_i is not None:
            v = _cell(i_i)
            if v and not detail.get("interest"):
                detail["interest"] = _nm(v)
                changed = True
        if f_i is not None:
            v = _cell(f_i)
            if v and not detail.get("other_fees"):
                detail["other_fees"] = _nm(v)
                changed = True
        if t_i is not None:
            v = _cell(t_i)
            if v and not detail.get("total_claims"):
                detail["total_claims"] = _nm(v)
                changed = True
        if d_i is not None:
            # 2026-09-02 修复：提取**所有**债务人（资产包多户），不只第一行；
            # 旧杂质名（标题提取"…及临夏市济民药业…"）不含任一表格户名时用首户名
            names = []
            for r in rows:
                if len(r) > d_i and r[d_i] and r[d_i].strip() not in ("—", "-", "无", ""):
                    nm = r[d_i].strip()
                    if nm and nm not in names and not any(k in nm for k in ("序号", "合计", "总计", "小计")):
                        names.append(nm)
            if names:
                if len(names) > 1:
                    detail["debtor_names"] = names[:50]
                    detail["debtor_count"] = len(names)
                cur = detail.get("debtor_name") or ""
                # 当前名必须是表格中的**完整户名**才保留（旧杂质"…及临夏市济民药业…"含户2名但非完整户名 → 覆盖）
                if not cur or cur not in names:
                    detail["debtor_name"] = names[0][:100]
                    changed = True
        if g_i is not None:
            v = _cell(g_i)
            if v:
                if not detail.get("collateral_desc"):
                    detail["collateral_desc"] = v[:500]
                    changed = True
                # 担保类型识别
                gt = []
                for kw, label in (("抵押", "抵押"), ("保证", "保证"), ("质押", "质押")):
                    if kw in v and label not in gt:
                        gt.append(label)
                if gt and not detail.get("guaranty_type"):
                    detail["guaranty_type"] = "、".join(gt)
                    changed = True
                # 抵押物类型
                if not detail.get("collateral_type"):
                    ct = _cc(v)
                    if ct:
                        detail["collateral_type"] = ct
                        changed = True
        # 保证人/抵押物：遍历所有行所有列，提取"保证人：xxx"与"抵押物：xxx"
        #（2026-09-02 用户指出 452：表格有保证人信息但未填入 guarantor_names）
        guarantors: list[str] = []
        coll_parts: list[str] = []
        for r in rows:
            for c in r:
                c = str(c or "")
                if "保证人" in c and ("：" in c or ":" in c):
                    for part in re.split(r'保证人\s*[：:]', c)[1:]:
                        nm = part.split("。")[0].split("；")[0].split(";")[0].strip()
                        if nm and nm not in guarantors and len(nm) <= 200:
                            guarantors.append(nm)
                if "抵押物" in c and ("：" in c or ":" in c):
                    m2 = re.search(r'抵押物\s*[：:]\s*(.+)', c)
                    if m2:
                        cp = m2.group(1).strip()
                        if cp and cp not in coll_parts:
                            coll_parts.append(cp)
        if guarantors and not detail.get("guarantor_names"):
            detail["guarantor_names"] = "、".join(guarantors)[:500]
            changed = True
        if coll_parts and not detail.get("collateral_desc"):
            detail["collateral_desc"] = "；".join(coll_parts)[:500]
            changed = True
        break  # 只取第一个债权表格

    # 2. 附件下载（重要文件：房产/土地证明、判决/裁定书、清单、评估报告、声明/处置公告等；
    #    跳过竞买公告/成交确认书/转让协议/承诺书等交易规则类——2026-09-01 用户确认）
    from ..scrapers.jd_page import _classify_attachment as _reclassify
    save_dir = _attachments_dir(feed_id)
    attachments: list[dict] = detail.get("attachments") or []
    # 清理已下载的非重要文件（旧分类可能含 转让协议/登记表 等交易规则类）
    kept_attachments = []
    for a in attachments:
        new_type = _reclassify(a.get("name") or "")
        if new_type == "skip":
            lp = a.get("local_path")
            if lp and os.path.exists(lp):
                try:
                    os.remove(lp)
                except OSError:
                    pass
            logger.info("移除交易规则类附件: %s", a.get("name"))
            continue
        a["type"] = new_type
        kept_attachments.append(a)
        changed = True
    attachments = kept_attachments

    existing_names = {a.get("name") for a in attachments}
    for att in page.get("attachments") or []:
        if att.get("type") == "skip":
            continue
        if att["name"] in existing_names:
            continue
        local = download_attachment(att["url"], save_dir)
        if local:
            local = os.path.abspath(local)  # 存绝对路径，避免 cwd 变化导致找不到
            attachments.append({
                "name": att["name"],
                "url": att["url"],
                "local_path": local,
                "type": att["type"],
                "source": "京东公告附件",
            })
            existing_names.add(att["name"])
            changed = True

    if attachments:
        detail["attachments"] = attachments
    elif "attachments" in detail:
        detail.pop("attachments", None)
        changed = True

    # 2.5 评估报告解析（2026-09-01：抵押物参考价值；注意年份——2年内可直接参考，超2年走成本法）
    for att in attachments:
        if att.get("type") == "valuation":
            report = _parse_valuation_report(att["local_path"])
            if report.get("year") or report.get("value_text"):
                detail["valuation_report"] = report
                att["valuation"] = report  # 附件上也带解析结果，前端展示
                changed = True

    # 3. 资产清单解析回填（最权威：实际抵押物明细；覆盖页面属性的粗略类型）
    for att in attachments:
        if "资产清单" in att["name"] or "明细" in att["name"]:
            parsed = _parse_asset_list(att["local_path"])
            for k, v in parsed.items():
                if k == "claim_total" and not detail.get("claim_total"):
                    detail[k] = v
                    changed = True
                elif k in ("collateral_type", "collateral_desc", "total_claims") and v:
                    # 资产清单最具体：抵押物/债权总额 覆盖页面属性或旧错误值
                    detail[k] = v
                    changed = True
                elif k != "claim_total" and k not in ("collateral_type", "collateral_desc", "total_claims") and not detail.get(k):
                    detail[k] = v
                    changed = True
            # 精炼 抵押物/保证人（资产清单的担保措施列常混杂保证人+抵押物+查封物）
            raw_coll = str(detail.get("collateral_desc") or "")
            if raw_coll:
                cleaned = _clean_collateral_guarantor(raw_coll)
                if cleaned.get("collateral_desc") and cleaned["collateral_desc"] != raw_coll:
                    detail["collateral_desc"] = cleaned["collateral_desc"]
                    changed = True
                if cleaned.get("guarantor_names") and not detail.get("guarantor_names"):
                    detail["guarantor_names"] = cleaned["guarantor_names"]
                    changed = True
            break

    # 4. 竖排键值表(kv)里的抵押物/保证人：精炼（由 jd_credit 的 sync 写入 detail.collateral_desc，
    #    但 kv 表格"担保措施"等列常是混杂长文本）
    raw_coll = str(detail.get("collateral_desc") or "")
    if raw_coll and ("保证人" in raw_coll or "抵押物" in raw_coll and ("保证" in raw_coll or "查封" in raw_coll)):
        cleaned = _clean_collateral_guarantor(raw_coll)
        if cleaned.get("collateral_desc"):
            detail["collateral_desc"] = cleaned["collateral_desc"]
            changed = True
        if cleaned.get("guarantor_names") and not detail.get("guarantor_names"):
            detail["guarantor_names"] = cleaned["guarantor_names"]
            changed = True
    if changed:
        logger.info("京东债权 %s(pid=%s) 页面增强完成", feed_id, paimai_id)
    return detail
