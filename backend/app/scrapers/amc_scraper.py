# -*- coding: utf-8 -*-
"""五大 AMC 资产处置公告统一抓取器（2026-09-03）

来源与抓法（昨晚搜集接口 + 今晨逐源验证）：
  1. 长城资产  www.gwamcc.com
     列表：Ajax/GetArticleList.ashx?pIndex=&pSize=&liName=64 → JSON（ID/Title/ActionDate）
     详情：HiringDetail.aspx?ID=xxx（正文 JS 动态加载，Playwright 等待后仍无正文 → 待适配，
           先落列表信息 + 原文链接）
  2. 中信金融（原华融） www.famc.citic
     列表：/ywjs/ywdt/zcczxx/index.shtml SSR（标题+日期+详情链接）
     详情：/ywjs/ywdt/zcczxx/YYYY/NNNN.shtml SSR 全文 + 表格（正文容器 .blzcwz_text）✅
  3. 中国信达  www.cinda.com.cn
     列表：/home/pc/cn/xdjt/qykhpd/blzcjy/index.shtml（Playwright 渲染，旧 TLS）
     详情：zcggxq/index.shtml?bulletintno=xxx SSR 摘要（编号/资产总额/联系人）+ PDF 附件链接
  4. 东方资产  sales.coamc.com.cn（营销网，SSR）
     列表：首页 Playwright 提取 /html/ 详情链接
     详情：/html/{uuid}/{TYPE}/{date}/{uuid}.html SSR 全文 + 资产信息表（.notice-detail.clear）✅
  5. 华融 = 中信金融资产（已并入 2）

版权原则（用户 2026-09-02 定）：AMC 官网无版权声明 → 能抓尽抓全文（3 万字符），配原文链接。
落库：feed_items section=notice，按 (section, source_url) 去重；详情非空覆盖、空值保留旧。
"""
import json
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"

AMC_SOURCES = {
    "长城资产": {
        "website": "https://www.gwamcc.com",
        "notice_url": "https://www.gwamcc.com/Hiring.aspx?liName=64",
        "list_kind": "httpx_json",
    },
    "中信金融": {
        "website": "https://www.famc.citic",
        "notice_url": "https://www.famc.citic/ywjs/ywdt/zcczxx/index.shtml",
        "list_kind": "httpx_ssr",
    },
    "中国信达": {
        "website": "https://www.cinda.com.cn",
        "notice_url": "https://www.cinda.com.cn/home/pc/cn/xdjt/qykhpd/blzcjy/index.shtml",
        "list_kind": "playwright",
    },
    "东方资产": {
        "website": "https://sales.coamc.com.cn",
        "notice_url": "https://sales.coamc.com.cn/coamc/",
        "list_kind": "playwright",
    },
}

# 公告类型识别词（标题 → notice_type）
_TYPE_WORDS = [
    ("债权转让", "债权转让公告"),
    ("债权资产", "债权处置公告"),
    ("债权处置", "债权处置公告"),
    ("不良债权", "债权处置公告"),
    ("处置公告", "资产处置公告"),
    ("处置招商", "处置招商公告"),
    ("招商公告", "招商公告"),
    ("资产包", "资产包处置公告"),
    ("抵债", "抵债资产处置公告"),
    ("股权", "股权处置公告"),
    ("催收", "催收公告"),
]


def _notice_type(title: str) -> str:
    for word, typ in _TYPE_WORDS:
        if word in title:
            return typ
    return "资产处置公告"


def _clean_text(t: str) -> str:
    """压缩空白，去多余行"""
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    return "\n".join(lines)


# ---------------- 列表 ----------------

def fetch_amc_list(amc: str, limit: int = 10) -> list[dict]:
    """抓指定 AMC 资产处置公告列表 → [{title, date, detail_url}]"""
    src = AMC_SOURCES.get(amc)
    if not src:
        raise ValueError(f"未知 AMC 来源: {amc}")
    if src["list_kind"] == "httpx_json":
        return _list_gwamcc(limit)
    if src["list_kind"] == "httpx_ssr":
        return _list_famc(limit)
    if src["list_kind"] == "playwright":
        if amc == "中国信达":
            return _list_cinda(limit)
        return _list_dongfang(limit)
    return []


def _list_gwamcc(limit: int = 10) -> list[dict]:
    import httpx
    out: list[dict] = []
    try:
        r = httpx.get("https://www.gwamcc.com/Ajax/GetArticleList.ashx",
                      params={"pIndex": 1, "pSize": min(limit, 20), "liName": 64},
                      headers={"User-Agent": UA}, timeout=25, verify=False)
        data = r.json()
        for row in (data.get("ds") or []):
            out.append({
                "title": (row.get("Title") or "").strip(),
                "date": (row.get("ActionDate") or "").strip(),
                "detail_url": f"https://www.gwamcc.com/HiringDetail.aspx?ID={row.get('ID')}",
            })
    except Exception as e:  # noqa: BLE001
        logger.warning("长城列表抓取失败: %s", e)
    return out[:limit]


def _list_famc(limit: int = 10) -> list[dict]:
    import httpx
    out: list[dict] = []
    try:
        r = httpx.get("https://www.famc.citic/ywjs/ywdt/zcczxx/index.shtml",
                      headers={"User-Agent": UA}, timeout=25, verify=False)
        t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S)
        # 列表条目：<a href="/ywjs/ywdt/zcczxx/2026/96142.shtml">标题</a>
        for m in re.finditer(r'<a[^>]+href="([^"]*zcczxx/\d+/\d+\.shtml)"[^>]*>(.*?)</a>', t, re.S):
            href, anchor = m.group(1), m.group(2)
            title = re.sub(r"<[^>]+>", "", anchor).strip()
            if not title or "资产处置公告" == title:
                continue
            url = href if href.startswith("http") else f"https://www.famc.citic{href}"
            # 日期从 URL 年份 + 列表页附近文本难取，先留空，详情页再取
            out.append({"title": title, "date": "", "detail_url": url})
            if len(out) >= limit:
                break
    except Exception as e:  # noqa: BLE001
        logger.warning("中信金融列表抓取失败: %s", e)
    return out


def _list_cinda(limit: int = 10) -> list[dict]:
    """信达资产处置栏目（Playwright，Chrome 兼容旧 TLS）"""
    out: list[dict] = []
    from playwright.sync_api import sync_playwright
    from .browser import launch_chromium
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p, headless=True)
            page = browser.new_context(viewport={"width": 1440, "height": 2000}).new_page()
            page.goto("https://www.cinda.com.cn/home/pc/cn/xdjt/qykhpd/blzcjy/index.shtml",
                      wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(5000)
            links = page.eval_on_selector_all(
                "a",
                """els => els.map(e => ({href:e.href, text:(e.innerText||'').trim()}))
                             .filter(x => x.href.indexOf('zcggxq') >= 0 && x.text.length > 8)""",
            )
            # 去重（同一公告可能出现多次）
            seen: set[str] = set()
            for l in links:
                if l["href"] in seen:
                    continue
                seen.add(l["href"])
                out.append({"title": l["text"], "date": "", "detail_url": l["href"]})
                if len(out) >= limit:
                    break
            browser.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("信达列表抓取失败: %s", e)
    return out


def _list_dongfang(limit: int = 10) -> list[dict]:
    """东方营销网：首页 Playwright 提取 /html/ 详情链接（首页即最新公告）"""
    out: list[dict] = []
    from playwright.sync_api import sync_playwright
    from .browser import launch_chromium
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p, headless=True)
            page = browser.new_context(viewport={"width": 1440, "height": 2000}).new_page()
            page.goto("https://sales.coamc.com.cn/coamc/", wait_until="domcontentloaded", timeout=35000)
            page.wait_for_timeout(4000)
            hrefs = page.eval_on_selector_all(
                "a", "els => els.map(e => e.href).filter(h => h.indexOf('/html/') >= 0)")
            seen: set[str] = set()
            for href in hrefs:
                if href in seen:
                    continue
                seen.add(href)
                out.append({"title": "", "date": "", "detail_url": href})
                if len(out) >= limit:
                    break
            browser.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("东方列表抓取失败: %s", e)
    return out


# ---------------- 详情 ----------------

def fetch_amc_detail(amc: str, item: dict) -> dict:
    """抓 AMC 公告详情（无版权 → 抓全文 + 表格结构化）。

    返回：{title, date, body, tables, attachments, notice_type, transferor}
    """
    url = item.get("detail_url") or ""
    if amc == "中信金融":
        return _detail_famc(url, item.get("title") or "")
    if amc == "东方资产":
        return _detail_dongfang(url)
    if amc == "中国信达":
        return _detail_cinda(url, item.get("title") or "")
    if amc == "长城资产":
        return _detail_gwamcc(url, item.get("title") or "", item.get("date") or "")
    return {}


def _parse_tables(page) -> list[dict]:
    """提取页面所有 table → [{headers, rows}]"""
    tables = []
    for i in range(page.locator("table").count()):
        tbl = page.locator("table").nth(i)
        rows = []
        for tr in tbl.locator("tr").all():
            cells = [re.sub(r"\s+", " ", c.strip()) for c in tr.locator("td,th").all_inner_texts()]
            cells = [c for c in cells if c]
            if cells:
                rows.append(cells)
        if rows:
            tables.append({"headers": rows[0], "rows": rows[1:]})
    return tables


def _detail_famc(url: str, fallback_title: str) -> dict:
    """中信金融详情：SSR 全文（正文容器 .blzcwz_text）+ 表格"""
    import httpx
    out = {"title": fallback_title, "date": "", "body": "", "tables": [], "attachments": []}
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=25, verify=False)
        t = r.text
        # 标题：优先 h1（页面真标题）；<title> 会带 "_中国中信金融资产管理股份有限公司" 后缀需清洗
        m = re.search(r'<h1[^>]*>(.*?)</h1>', t, re.S) or re.search(r'<title>(.*?)</title>', t, re.S)
        if m:
            title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            title = re.sub(r"_(?:中国)?中信金融资产管理股份有限公司$", "", title)
            title = re.sub(r"中国中信金融资产管理股份有限公司$", "", title)
            out["title"] = title
        # 日期：页面常见 <span class="date">2026-09-02</span> 或 发布时间
        m = re.search(r'(\d{4}-\d{2}-\d{2})', t)
        if m:
            out["date"] = m.group(1)
        # 正文容器 .blzcwz_text
        m = re.search(r'<div[^>]+class="[^"]*blzcwz_text[^"]*"[^>]*>(.*?)</div>\s*</div>', t, re.S)
        body_html = m.group(1) if m else ""
        if not body_html:
            m = re.search(r'<div[^>]+class="[^"]*blzcwz_text[^"]*"[^>]*>(.*)', t, re.S)
            if m:
                body_html = m.group(1)
        if body_html:
            # 正文文本排除表格（原文表格由自建表格展示——用户 2026-09-03 修改1）
            body_no_table = re.sub(r"<table.*?</table>", " ", body_html, flags=re.S)
            body_txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", body_no_table, flags=re.S)
            body_txt = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", body_txt, flags=re.I)
            body_txt = re.sub(r"<[^>]+>", " ", body_txt)
            body_txt = re.sub(r"[ \t\u3000]+", " ", body_txt)
            body_txt = _clean_text(body_txt)
            out["body"] = body_txt[:30000]
            # 表格（容器内原文 HTML，用于自建表格）
            for tm in re.finditer(r'<table.*?</table>', body_html, re.S):
                rows = []
                for tr in re.finditer(r'<tr.*?</tr>', tm.group(0), re.S):
                    cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr.group(0), re.S)
                    cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
                    cells = [re.sub(r"\s+", " ", c) for c in cells if c.strip()]
                    if cells:
                        rows.append(cells)
                if rows:
                    out["tables"].append({"headers": rows[0], "rows": rows[1:]})
    except Exception as e:  # noqa: BLE001
        logger.warning("中信金融详情抓取失败 %s: %s", url, e)
    return out


def _detail_dongfang(url: str) -> dict:
    """东方营销网详情：Playwright 渲染（正文容器 .notice-detail.clear，含资产信息表）"""
    out = {"title": "", "date": "", "body": "", "tables": [], "attachments": []}
    # 日期优先从 URL 提取（/html/{uuid}/{TYPE}/{YYYYMMDD}/{uuid}.html）
    m = re.search(r"/(20\d{2})(\d{2})(\d{2})/", url)
    if m:
        out["date"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    from playwright.sync_api import sync_playwright
    from .browser import launch_chromium
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p, headless=True)
            page = browser.new_context(viewport={"width": 1440, "height": 2000}).new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=35000)
            page.wait_for_timeout(4000)
            # 正文容器：表格临时隐藏再取 innerText（保留段落结构，表格文字不进正文——
            # 原文表格由自建表格展示，用户 2026-09-03 修改1；detached clone 会丢段落换行，不可用）
            body = page.evaluate("""(sel) => {
                const el = document.querySelector(sel);
                if (!el) return '';
                const tables = [...el.querySelectorAll('table')];
                tables.forEach(t => { t.dataset.amcShow = t.style.display; t.style.display = 'none'; });
                const txt = el.innerText;
                tables.forEach(t => { t.style.display = t.dataset.amcShow || ''; });
                return txt;
            }""", ".notice-detail.clear")
            if not body or len(body.strip()) < 20:
                body = page.inner_text("body")
            body = _clean_text(body)
            out["body"] = body[:30000]
            # 标题：正文容器中第一个含"公告"的行（导航行"返回…首页"之前是机构名，跳过）
            lines = [ln for ln in body.splitlines() if ln.strip()]
            for ln in lines:
                if ("公告" in ln or "招商" in ln or "处置" in ln) and "返回" not in ln and len(ln) > 10:
                    out["title"] = re.sub(r"\s+", " ", ln).strip()
                    break
            if not out["date"]:
                m = re.search(r"(\d{4})-(\d{2})-(\d{2})", body)
                if m:
                    out["date"] = m.group(0)
            out["tables"] = _parse_tables(page)
            browser.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("东方详情抓取失败 %s: %s", url, e)
    return out


def _detail_cinda(url: str, fallback_title: str) -> dict:
    """信达详情：SSR 摘要（编号/资产总额/联系人）+ PDF 附件链接"""
    out = {"title": fallback_title, "date": "", "body": "", "tables": [], "attachments": []}
    from playwright.sync_api import sync_playwright
    from .browser import launch_chromium
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p, headless=True)
            page = browser.new_context(viewport={"width": 1440, "height": 2000}).new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(5000)
            # 正文：表格临时隐藏再取 innerText（保留段落结构，表格文字不进正文——2026-09-03）
            body = page.evaluate("""() => {
                const tables = [...document.querySelectorAll('table')];
                tables.forEach(t => { t.dataset.amcShow = t.style.display; t.style.display = 'none'; });
                const txt = document.body.innerText;
                tables.forEach(t => { t.style.display = t.dataset.amcShow || ''; });
                return txt;
            }""")
            # 从"编号"开始截正文
            idx = body.find("编号：")
            txt = body[idx:] if idx >= 0 else body
            # 截到"相关资产信息"（页脚前）
            end = txt.find("相关资产信息")
            if end > 0:
                txt = txt[:end]
            out["body"] = _clean_text(txt)[:10000]
            m = re.search(r'(\d{4}-\d{2}-\d{2})', out["body"])
            if m:
                out["date"] = m.group(1)
            # 标题：优先列表标题；否则取"发布时间"后第一个非空行（公告名称）
            if not fallback_title:
                m = re.search(r'发布时间[：:]\s*\S+[^\n]*\n([^\n]{8,60})', out["body"])
                if m:
                    out["title"] = m.group(1).strip()
            # PDF 附件
            pdfs = page.eval_on_selector_all(
                "a", "els => els.map(e => ({text:(e.innerText||'').trim(), href:e.href})).filter(x => x.href.toLowerCase().endsWith('.pdf'))")
            for pdf in pdfs:
                if pdf["text"]:
                    out["attachments"].append({"name": pdf["text"], "url": pdf["href"]})
            browser.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("信达详情抓取失败 %s: %s", url, e)
    return out


def _detail_gwamcc(url: str, fallback_title: str, fallback_date: str) -> dict:
    """长城详情：静态页无正文（正文 JS 动态加载，待适配）→ 先落列表信息 + 原文链接"""
    out = {"title": fallback_title, "date": fallback_date, "body": "", "tables": [], "attachments": []}
    try:
        import httpx
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=25, verify=False)
        t = r.text
        m = re.search(r'<title>(.*?)</title>', t, re.S)
        if m and not out["title"]:
            out["title"] = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        # 静态页正文区（若有）
        m = re.search(r'<div[^>]+class="[^"]*article[^"]*"[^>]*>(.*?)</div>', t, re.S)
        if m:
            body_txt = re.sub(r"<[^>]+>", " ", m.group(1))
            body_txt = re.sub(r"\s+", " ", body_txt).strip()
            if len(body_txt) > 50:
                out["body"] = body_txt[:30000]
    except Exception as e:  # noqa: BLE001
        logger.warning("长城详情抓取失败 %s: %s", url, e)
    return out


# ---------------- 落库 ----------------

def _extract_transferor(title: str) -> str:
    """从标题提取公告发布方（AMC 分公司/公司名）"""
    m = re.search(r'(中国(?:长城|信达|东方|中信金融)资产管理股份有限公司[^\s，,（(]{0,15}?分公司)', title)
    if m:
        return m.group(1)
    m = re.search(r'([^\s，,]{2,30}?资产管理股份有限公司)', title)
    if m:
        return m.group(1)
    return ""


def _extract_debtors(tables: list[dict]) -> list[str]:
    """从表格提取债务人名称列（有表抓表规则：债务人列 → 名单）

    跳过合计行（前2列含合计/总计/小计）与金额型占位（列错位时合计行把金额排到
    债务人列，514 案例：'33,798,972.66' 被当债务人）。
    """
    names: list[str] = []
    for tb in tables:
        headers = tb.get("headers") or []
        for ci, h in enumerate(headers):
            if ("债务人" in h and "名称" in h) or "债务人" == h or "借款人" in h:
                for row in tb.get("rows") or []:
                    first2 = "".join(str(c) for c in (row or [])[:2])
                    if re.search(r"合计|总计|小计", first2):
                        continue
                    val = str(row[ci]).strip() if ci < len(row) else ""
                    if not val or re.match(r"^[\d,，.]+(?:元|万元|港元|美元)?$", val):
                        continue  # 金额/纯数字不当债务人
                    if val not in names:
                        names.append(val)
    return names


def _extract_transferor_from_body(body: str) -> str:
    """正文首行机构名（东方等公告正文第一行是分公司名，标题不含）"""
    m = re.search(r'(中国(?:长城|信达|东方|中信金融)资产管理股份有限公司[^\n，,（(]{0,15}?分公司)', body or "")
    return m.group(1) if m else ""


def _calc_claim_text(tables: list[dict], body: str) -> str:
    """从表格/正文计算债权金额文本（用于指标卡）。

    优先级：信达"资产总额(亿元/万元)" → 明确人民币元单位（正文"人民币元"或表头含"（元）"）
    的本金列加总 → 空（单位不明/外币不加总，避免 元/万/美元 混淆）。
    """
    body = body or ""
    m = re.search(r'资产总额[（(]单位[：:]\s*(亿元|万元)[）)]\s*[：:]\s*人民币[:：]?\s*([\d.]+)', body)
    if m:
        return f"{m.group(2)}{m.group(1)}"
    has_yuan = "人民币元" in body
    if not has_yuan:
        # 表头列名带"（元）"也算明确元单位（514：本金余额（元））
        for tb in tables:
            for h in tb.get("headers") or []:
                if re.search(r"[（(]元[）)]", re.sub(r"\s", "", h or "")):
                    has_yuan = True
                    break
            if has_yuan:
                break
    if not has_yuan:
        return ""
    # 防外币：表格有"币种"列且含外币 → 不加总（516：美元/港元表）
    for tb in tables:
        headers = tb.get("headers") or []
        for ci, h in enumerate(headers):
            if "币种" in re.sub(r"\s", "", h or ""):
                for row in tb.get("rows") or []:
                    if ci < len(row) and re.search(r"美元|港元|港币|欧元|日元", str(row[ci])):
                        return ""
    total = 0.0
    for tb in tables:
        headers = tb.get("headers") or []
        for ci, h in enumerate(headers):
            hc = re.sub(r"\s", "", h or "")  # 表头可能带空格（"本 金"）
            if re.search(r"本金", hc) and not re.search(r"利息|违约", hc):
                for row in tb.get("rows") or []:
                    if ci < len(row):
                        mm = re.search(r"([\d,]+\.?\d*)", str(row[ci]))
                        if mm:
                            total += float(mm.group(1).replace(",", ""))
    if not total:
        return ""
    if total >= 100_000_000:
        return f"{total / 100_000_000:.2f}亿元"
    return f"{total / 10_000:.2f}万元"


def _upsert_notice(db, amc: str, item: dict, detail: dict) -> bool:
    """按 (section, source_url) 去重写入 feed_items；返回是否新增。

    详情合并：非空覆盖、空值保留旧（防抓取失败清字段）。
    """
    from sqlalchemy import select
    from ..models import FeedItem

    url = item.get("detail_url") or ""
    title = detail.get("title") or item.get("title") or ""
    if not title or not url:
        return False
    existing = db.scalar(
        select(FeedItem).where(FeedItem.section == "notice", FeedItem.source_url == url)
    )
    body = detail.get("body") or ""
    tables = detail.get("tables") or []
    # 排版（2026-09-03 用户规则：抓取内容排版再发布，正文段落化/去重复头/表格文字已排除）
    from ..scrapers.text_extract import extract_notice_metrics, layout_notice_body
    paras = layout_notice_body(body, title)
    met = extract_notice_metrics(body)
    display_body = "\n".join(paras) if paras else body
    # 摘要：正文排版后引言（首段）；无正文用标题+日期
    if paras:
        summary = paras[0][:180] + "…" if len(paras[0]) > 180 else paras[0]
    elif body:
        summary = " ".join(body.split())[:180] + "…" if len(body) > 180 else body
    else:
        parts = [title]
        if detail.get("date"):
            parts.append(f"{detail['date']}发布")
        summary = "，".join(parts) + "。"
    transferor = (detail.get("transferor") or _extract_transferor(title)
                  or _extract_transferor_from_body(body))
    debtors = _extract_debtors(tables)
    claim_total = _calc_claim_text(tables, body) or met.get("claim_total") or ""
    detail_json = {
        "notice_type": detail.get("notice_type") or _notice_type(title),
        "publish_date": detail.get("date") or item.get("date") or "",
        "transferor": transferor,
        "debtor_names": "; ".join(debtors),
        # 户数：表格债务人去重优先（精确）；无表格/无债务人列用正文"N户"
        "households": (len(debtors) if debtors else None) or met.get("households"),
        "claim_total": claim_total,
        "principal": met.get("principal") or "",
        "interest": met.get("interest") or "",
        "other_fees": met.get("other_fees") or "",
        "deadline": met.get("deadline") or "",
        "asset_pkg_no": met.get("asset_pkg_no") or "",
        "body_text": display_body,          # 排版后全文（段落 \n 分隔）
        "body_paragraphs": paras,           # 段落数组（前端逐段渲染）
        "tables": tables,
        "attachments": detail.get("attachments") or [],
        "paper_url": url,  # 原文链接（AMC 官网详情页）
    }
    new_raw = json.dumps(detail_json, ensure_ascii=False)
    if existing:
        old = json.loads(existing.detail_json) if existing.detail_json else {}
        merged = {**old, **{k: v for k, v in detail_json.items() if v}}
        new_raw = json.dumps(merged, ensure_ascii=False)
        if existing.detail_json != new_raw or (existing.summary or "") != summary:
            existing.summary = summary
            existing.detail_json = new_raw
            existing.title = title
        return False
    db.add(FeedItem(
        section="notice",
        title=title,
        summary=summary,
        tags=json.dumps([amc, detail_json.get("notice_type") or ""], ensure_ascii=False),
        source=amc,
        source_url=url,
        detail_json=new_raw,
        is_active=1,
    ))
    return True


def sync_amc_notices_to_feed(amcs: list[str] | None = None, limit_each: int = 8) -> dict:
    """主入口：抓各 AMC 列表 → 详情 → 落库 notice 栏目。返回统计。"""
    from ..database import SessionLocal

    targets = amcs or list(AMC_SOURCES.keys())
    db = SessionLocal()
    result: dict[str, int] = {}
    total_new = 0
    try:
        for amc in targets:
            items = fetch_amc_list(amc, limit=limit_each)
            new = 0
            for it in items:
                try:
                    detail = fetch_amc_detail(amc, it)
                except Exception as e:  # noqa: BLE001
                    logger.warning("AMC %s 详情失败 %s: %s", amc, it.get("detail_url"), e)
                    detail = {}
                if _upsert_notice(db, amc, it, detail):
                    new += 1
                db.commit()
            result[amc] = {"list": len(items), "new": new}
            total_new += new
    finally:
        db.close()
    logger.info("AMC 公告同步完成: %s", result)
    return {"amcs": result, "total_new": total_new}


if __name__ == "__main__":
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    r = sync_amc_notices_to_feed(limit_each=3)
    print(json.dumps(r, ensure_ascii=False, indent=1))
