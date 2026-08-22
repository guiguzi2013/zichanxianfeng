"""中国执行信息公开网适配器（免费官方司法风险源）

网址：zxgk.court.gov.cn
P0 策略：
- 使用 async httpx（避免同步 client 阻塞 FastAPI 事件循环）
- 短超时（8s）+ 快速降级：失败返回 success=False + note，报告标注"需人工核实"
- 后续可接入打码平台/半自动验证增强
"""
import logging
from datetime import datetime

import httpx

from ..config import get_settings
from .base import DataSourceResult, JudicialDataSource

logger = logging.getLogger(__name__)
settings = get_settings()

EXECUTION_API = "https://zxgk.court.gov.cn/api/execution"
DISHONEST_API = "https://zxgk.court.gov.cn/api/dishonest"
LIMIT_API = "https://zxgk.court.gov.cn/api/limit"

_TIMEOUT = 8  # 秒，快速失败不拖慢尽调


class ZxgkDataSource(JudicialDataSource):
    name = "中国执行信息公开网"

    def __init__(self) -> None:
        self.enabled = settings.zxgk_enabled

    def _unavailable(self, note: str) -> DataSourceResult:
        return DataSourceResult(
            success=False, source=self.name, fetch_time=datetime.now().isoformat(), note=note
        )

    async def _post(self, url: str, keyword: str) -> DataSourceResult:
        if not self.enabled:
            return self._unavailable("执行信息网未启用")
        try:
            async with httpx.AsyncClient(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://zxgk.court.gov.cn/",
                },
                timeout=_TIMEOUT,
            ) as client:
                resp = await client.post(url, json={"pName": keyword, "pCardNum": "", "pCode": ""})
                resp.raise_for_status()
                return DataSourceResult(success=True, data=resp.json(), source=self.name, fetch_time=datetime.now().isoformat())
        except Exception as e:  # noqa: BLE001
            logger.warning("zxgk %s failed for %s: %s", url.split("/")[-1], keyword, e)
            return self._unavailable(f"查询失败（{e.__class__.__name__}），建议人工核实")

    async def search_execution(self, keyword: str) -> DataSourceResult:
        return await self._post(EXECUTION_API, keyword)

    async def search_dishonest(self, keyword: str) -> DataSourceResult:
        return await self._post(DISHONEST_API, keyword)

    async def search_restricted(self, keyword: str) -> DataSourceResult:
        return await self._post(LIMIT_API, keyword)
