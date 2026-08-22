"""京东拍卖详情页适配器

目标：paimai.jd.com（京东拍卖）
特点：反爬比淘宝弱，通常可直接 httpx 抓取；页面含 JSON 数据（__NEXT_DATA__ 或 window.pageData）。
策略：先尝试提取内嵌 JSON 数据，失败则用正则提取关键字段。
"""
import json
import logging
import re

import httpx

from .base import ScrapeResult, SiteAdapter

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://paimai.jd.com/",
}


class JdAuctionAdapter(SiteAdapter):
    domains = ["paimai.jd.com"]

    async def fetch_text(self, url: str) -> ScrapeResult:
        try:
            async with httpx.AsyncClient(headers=_HEADERS, timeout=15, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            logger.warning("jd fetch failed: %s", e)
            return ScrapeResult(
                success=False,
                note="抓取失败（网络或站点限制）。请复制拍卖页面文字，使用「粘贴文本」方式输入。",
            )

        html = resp.text
        if len(html) < 5000 or ("验证" in html[:2000] and "滑块" in html[:2000]):
            return ScrapeResult(
                success=False,
                note="页面需要验证，无法自动抓取。请复制拍卖页面文字，使用「粘贴文本」方式输入。",
            )

        text = _extract_text(html)
        if len(text.strip()) < 30:
            return ScrapeResult(success=False, note="未能提取到有效内容，请改用「粘贴文本」方式输入。")

        return ScrapeResult(success=True, text=text, note="已抓取京东拍卖页面，请确认提取结果")


def _extract_text(html: str) -> str:
    """提取可读文本（优先内嵌 JSON，其次正则）"""
    parts = []

    # 1. 尝试提取 JSON 数据（京东拍卖常见 window.pageData / __NEXT_DATA__）
    json_data = _try_extract_json(html)
    if json_data:
        parts.append(json.dumps(json_data, ensure_ascii=False)[:3000])
        return "\n".join(parts)

    # 2. 正则兜底
    # 标题
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.S)
    if m:
        parts.append(f"标题：{m.group(1).strip()}")

    # 价格类字段（起拍价/评估价/保证金/加价幅度）
    for label, pattern in [
        ("起拍价", r"(?:起拍价|起拍)[^\d]{0,10}([\d,，.]+)\s*(?:万)?\s*元"),
        ("评估价", r"(?:评估价|评估)[^\d]{0,10}([\d,，.]+)\s*(?:万)?\s*元"),
        ("保证金", r"保证金[^\d]{0,10}([\d,，.]+)\s*(?:万)?\s*元"),
        ("加价幅度", r"加价幅度[^\d]{0,10}([\d,，.]+)\s*元"),
    ]:
        m = re.search(pattern, html)
        if m:
            parts.append(f"{label}：{m.group(1)}")

    # 时间
    m = re.search(r"(\d{4})\s*[年/-]\s*(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*日", html)
    if m:
        parts.append(f"时间：{m.group(1)}-{m.group(2)}-{m.group(3)}")

    # 标的描述区
    m = re.search(r"(?:标的物|标的介绍|拍品详情)(.{0,3000}?)(?:拍卖须知|竞买公告|出价记录|免责声明)", html, re.S)
    if m:
        body = re.sub(r"<[^>]+>", " ", m.group(1))
        body = re.sub(r"\s+", " ", body).strip()
        parts.append(f"标的描述：{body[:1500]}")

    # 整体去标签文本（兜底）
    whole = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    whole = re.sub(r"<[^>]+>", " ", whole)
    whole = re.sub(r"\s+", " ", whole).strip()
    parts.append(f"页面全文：{whole[:3000]}")

    return "\n".join(parts)


def _try_extract_json(html: str) -> dict | None:
    """尝试提取页面内嵌 JSON（京东拍卖常见格式）"""
    patterns = [
        r"window\.pageData\s*=\s*(\{.*?\})\s*;?</script>",
        r"__NEXT_DATA__\s*=\s*(\{.*?\})\s*;?</script>",
        r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?</script>",
    ]
    for p in patterns:
        m = re.search(p, html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
    return None
