# -*- coding: utf-8 -*-
"""智收云(debtop.com)公告抓取器（2026-09-02）

来源链：报纸（法定公告渠道）→ 报纸官网文字版(gsjb.com 等) / 报纸数字报(szb.gansudaily.com.cn) / 智收云聚合
策略（用户确认）：
  1. 智收云列表做索引（标题/权利人/金额/债务人/报纸/日期/类型）
  2. 溯源到报纸官网抓文字正文（事实信息合规）；已知报纸入口记录缓存，同源复用不再重复溯源
  3. 完整版面图不存站内（版权），链接跳转来源/智收云原页
robots：debtop.com Allow /notice（智收云允许抓公告）
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

# 已知来源 → 官网入口缓存（2026-09-02：溯源一次记录，同源复用不再重新溯源）
# copyright: False=无版权声明(AMC官网,可抓全文) / True=有版权声明(报纸数字报等,只摘要+链接)
# 抓取原则（用户 2026-09-02 定）：能抓尽抓；无版权抓全文，有版权回填摘要；都配原文链接。
KNOWN_PAPER_SOURCES: dict[str, dict] = {
    "甘肃经济日报": {"website": "https://www.gsjb.com", "notice_url": "https://www.gsjb.com", "copyright": True},
    "长城资产": {"website": "https://www.gwamcc.com", "notice_url": "https://www.gwamcc.com/Hiring.aspx?liName=64", "copyright": False},
    "中国长城资产管理股份有限公司": {"website": "https://www.gwamcc.com", "notice_url": "https://www.gwamcc.com/Hiring.aspx?liName=64", "copyright": False},
    "中国信达资产管理股份有限公司": {"website": "https://www.cinda.com.cn", "notice_url": "https://www.cinda.com.cn", "copyright": False},
    "中国信达": {"website": "https://www.cinda.com.cn", "notice_url": "https://www.cinda.com.cn", "copyright": False},
    "中国东方资产管理股份有限公司": {"website": "https://www.coamc.com.cn", "notice_url": "https://www.coamc.com.cn", "copyright": False},
    "中国东方资产": {"website": "https://www.coamc.com.cn", "notice_url": "https://www.coamc.com.cn", "copyright": False},
    "中国中信金融资产管理股份有限公司": {"website": "https://www.famc.citic", "notice_url": "https://www.famc.citic", "copyright": False},
    "中信金融": {"website": "https://www.famc.citic", "notice_url": "https://www.famc.citic", "copyright": False},
}


def trace_to_paper(paper_name: str, title: str) -> dict:
    """溯源：按来源名找官网 → 必应搜索「标题 site:官网」→ 提取原文 URL → 抓正文文字。

    已知入口（KNOWN_PAPER_SOURCES）直接复用域名；未知来源返回待收录。
    返回：{found, url, body, note}；正文=官网网页文字（事实信息，合规）。
    """
    import httpx

    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    src = KNOWN_PAPER_SOURCES.get(paper_name)
    if not src or not src.get("website"):
        return {"found": False, "url": "", "body": "", "note": f"来源「{paper_name}」官网入口未收录，待人工确认后记录"}
    site = src["website"].replace("https://", "").replace("http://", "").rstrip("/")
    # 必应搜索：标题 + site:域名
    query = f'"{title[:30]}" site:{site}'
    try:
        r = httpx.get("https://www.bing.com/search", params={"q": query},
                      headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
        links = re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', r.text, re.S)
        for href, anchor in links:
            # 过滤必应跳转壳/导航
            if "bing.com" in href or "microsoft" in href or "go.micro" in href:
                continue
            txt = re.sub(r'<[^>]+>', '', anchor).strip()
            if site.split("/")[0] in href and title[:8] in txt:
                copyright_flag = src.get("copyright", True)
                body = _fetch_origin_body(href, full=not copyright_flag)  # 无版权抓全文
                return {"found": True, "url": href, "body": body, "note": "", "copyright": copyright_flag}
    except Exception as e:
        return {"found": False, "url": src.get("notice_url") or "", "body": "",
                "note": f"溯源失败: {e}", "is_fallback": True}
    # 未命中原文网页 → 兜底跳来源官网公告栏目（不跳智收云，竞对）
    return {"found": False, "url": src.get("notice_url") or "", "body": "",
            "note": "未搜到独立原文网页，跳来源官网公告栏目", "is_fallback": True,
            "copyright": src.get("copyright", True)}


def _fetch_origin_body(url: str, full: bool = True) -> str:
    """抓溯源原文网页正文文字。
    full=True：无版权来源（AMC 官网）抓全文；full=False：有版权来源不抓正文（只摘要+链接）。"""
    import httpx
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=25)
        t = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', r.text, flags=re.S)
        t = re.sub(r'<[^>]+>', ' ', t)
        t = re.sub(r'\s+', ' ', t).strip()
        return t[:30000] if full else ""  # 无版权抓全文(3万字符上限)
    except Exception:
        return ""


def fetch_notice_detail(notice_id: int | str) -> dict:
    """Playwright 渲染智收云公告详情页，拦截 detail API（结构化）+ 提取报纸版面主图 URL。

    返回：{id, title, paper, day, notice_type_name, transferor, transferee,
           amount_text, principal_text, debtor_num, sub_title, img_url, source_url}
    """
    from playwright.sync_api import sync_playwright
    from .browser import launch_chromium

    captured: dict = {}
    source_url = f"https://www.debtop.com/notice/{notice_id}"
    with sync_playwright() as p:
        browser = launch_chromium(p, headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 2000}).new_page()

        def on_resp(resp):
            if "paper/paper/detail" in resp.url:
                try:
                    captured["detail"] = resp.json()
                except Exception:
                    pass
        page.on("response", on_resp)
        page.goto(source_url, wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(6000)
        # 主图（报纸版面原图）
        imgs = page.eval_on_selector_all(
            "img",
            """els => els.map(e => e.src).filter(s => s && s.indexOf('res.debtop.com') >= 0 && s.indexOf('paper/') >= 0)""",
        )
        captured["imgs"] = imgs
        browser.close()

    val = (captured.get("detail") or {}).get("value") or {}
    if not val:
        return {"source_url": source_url, "error": "detail 未捕获"}
    amount = val.get("amount_final") or val.get("total_amount") or 0
    principal = val.get("total_amount") or 0
    out = {
        "id": val.get("id"),
        "title": val.get("title") or "",
        "paper": val.get("paper") or "",
        "day": val.get("day") or "",
        "notice_type_name": val.get("notice_type_name") or "",
        "transferor": val.get("transferor") or "",
        "transferee": val.get("transferee") or "",
        "amount_text": f"{amount / 10000:.2f}万" if isinstance(amount, (int, float)) and amount else "",
        "principal_text": f"{principal / 10000:.2f}万" if isinstance(principal, (int, float)) and principal else "",
        "debtor_num": val.get("debtor_num_final") or val.get("item_num") or 0,
        "sub_title": val.get("sub_title") or "",
        "img_url": (captured.get("imgs") or [None])[0] or "",
        "source_url": source_url,
    }
    return out


if __name__ == "__main__":
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    d = fetch_notice_detail(118498350681344)
    print(json.dumps(d, ensure_ascii=False, indent=1))
