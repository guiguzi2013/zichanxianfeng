"""站点适配器注册表：按域名分发"""
import logging
from urllib.parse import urlparse

from .base import ScrapeResult, SiteAdapter
from .jd_auction import JdAuctionAdapter
from .taobao_auction import TaobaoAuctionAdapter

logger = logging.getLogger(__name__)

_adapters: list[SiteAdapter] = [TaobaoAuctionAdapter(), JdAuctionAdapter()]


def get_adapter(url: str) -> SiteAdapter | None:
    """按 URL 域名查找适配器"""
    host = urlparse(url).netloc.lower()
    for adapter in _adapters:
        if any(host == d or host.endswith("." + d) for d in adapter.domains):
            return adapter
    return None


async def fetch_url_text(url: str) -> ScrapeResult:
    """统一抓取入口：找到适配器则抓取，否则提示不支持"""
    adapter = get_adapter(url)
    if adapter is None:
        return ScrapeResult(success=False, note=f"暂不支持该站点（{urlparse(url).netloc}）。请复制页面文字，使用「粘贴文本」方式输入。")
    return await adapter.fetch_text(url)
