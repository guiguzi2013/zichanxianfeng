"""淘宝司法拍卖详情页适配器

目标：sf-item.taobao.com / item-paimai.taobao.com
策略：P1 骨架——httpx 直抓 HTML + 简单正则提取关键字段；反爬拦截时降级提示走文本通道。
注意：不绕过验证码/登录，遵守站点协议，低频率访问。
"""
import logging
import re

import httpx

from .base import ScrapeResult, SiteAdapter

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


class TaobaoAuctionAdapter(SiteAdapter):
    # 淘宝系拍卖/诉讼资产平台域名
    domains = [
        "sf-item.taobao.com",        # 司法拍卖详情
        "item-paimai.taobao.com",    # 拍卖商品
        "sf.taobao.com",             # 司法拍卖首页
        "susong-item.taobao.com",    # 诉讼资产详情
        "zc-paimai.taobao.com",      # 资产拍卖
    ]

    async def fetch_text(self, url: str) -> ScrapeResult:
        try:
            async with httpx.AsyncClient(headers=_HEADERS, timeout=15, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            logger.warning("taobao fetch failed: %s", e)
            return ScrapeResult(
                success=False,
                note="抓取失败（站点反爬或网络问题）。请复制拍卖页面文字，使用「粘贴文本」方式输入。",
            )

        html = resp.text
        # 页面可能含反爬占位/需要 JS 渲染
        if "滑块" in html or "验证" in html[:2000] or len(html) < 5000:
            return ScrapeResult(
                success=False,
                note="页面需要验证/JS渲染，无法自动抓取。请复制拍卖页面文字，使用「粘贴文本」方式输入。",
            )

        text = _extract_text(html)
        if len(text.strip()) < 30:
            return ScrapeResult(success=False, note="未能提取到有效内容，请改用「粘贴文本」方式输入。")

        return ScrapeResult(success=True, text=text, note="已抓取，请确认提取结果")


def _extract_text(html: str) -> str:
    """从拍卖详情页 HTML 提取可读文本（尽力而为，供 LLM 提取）"""
    parts = []

    # 标题
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.S)
    if m:
        parts.append(f"标题：{m.group(1).strip()}")

    # 常见字段（起拍价/保证金/评估价/加价幅度）
    for label, pattern in [
        ("起拍价", r"起拍价[^\d]{0,10}([\d,，.]+)\s*万元"),
        ("起拍价", r"起拍价[^\d]{0,10}([\d,，.]+)\s*元"),
        ("保证金", r"保证金[^\d]{0,10}([\d,，.]+)\s*万元"),
        ("保证金", r"保证金[^\d]{0,10}([\d,，.]+)\s*元"),
        ("评估价", r"评估价[^\d]{0,10}([\d,，.]+)\s*万元"),
        ("加价幅度", r"加价幅度[^\d]{0,10}([\d,，.]+)\s*元"),
    ]:
        m = re.search(pattern, html)
        if m:
            parts.append(f"{label}：{m.group(1)}")

    # 拍卖时间
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", html)
    if m:
        parts.append(f"时间：{m.group(1)}-{m.group(2)}-{m.group(3)}")

    # 标的描述区（去除标签后的文本，截取）
    m = re.search(r"标的物介绍(.{0,3000}?)(?:拍卖须知|竞买公告|出价记录)", html, re.S)
    if m:
        body = re.sub(r"<[^>]+>", " ", m.group(1))
        body = re.sub(r"\s+", " ", body).strip()
        parts.append(f"标的描述：{body[:1500]}")

    # 整体去标签文本（兜底，限制长度）
    whole = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    whole = re.sub(r"<[^>]+>", " ", whole)
    whole = re.sub(r"\s+", " ", whole).strip()
    parts.append(f"页面全文：{whole[:3000]}")

    return "\n".join(parts)
