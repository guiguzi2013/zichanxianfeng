"""页面抓取适配器（对应设计文档第10章）

原则：只抓好抓的；先 httpx 直抓 → 失败提示走"粘贴文本"通道。
站点适配器注册表：registry.py 按域名分发。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ScrapeResult:
    success: bool
    text: str = ""                # 提取后的纯文本（供 LLM 提取）
    structured: dict = field(default_factory=dict)  # 结构化字段（尽力而为）
    note: str = ""                # 失败/降级说明


class SiteAdapter(ABC):
    """站点适配器基类"""

    domains: list[str] = []

    @abstractmethod
    async def fetch_text(self, url: str) -> ScrapeResult:
        """抓取页面并返回可读文本（供 LLM 结构化提取）"""
