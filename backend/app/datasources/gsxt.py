"""国家企业信用信息公示系统适配器（免费官方工商源）

网址：gsxt.gov.cn
P0 策略：公示系统滑块验证码较强，本适配器实现骨架 + 明确降级。
实际查询可对接第三方解析服务或爱企查免费额度（见 design doc 7.3），接口不变。
"""
import logging
from datetime import datetime

from ..config import get_settings
from .base import DataSourceResult, EnterpriseDataSource

logger = logging.getLogger(__name__)
settings = get_settings()


class GsxtDataSource(EnterpriseDataSource):
    name = "国家企业信用信息公示系统"

    def __init__(self) -> None:
        self.enabled = settings.gsxt_enabled

    def _unavailable(self, note: str) -> DataSourceResult:
        return DataSourceResult(
            success=False, source=self.name, fetch_time=datetime.now().isoformat(), note=note
        )

    async def get_basic_info(self, name: str) -> DataSourceResult:
        if not self.enabled:
            return self._unavailable("工商信息暂不可用")
        # P0 骨架：公示系统需滑块验证，返回降级结果，由报告标注"需人工核实"
        return self._unavailable("工商信息暂未获取到，建议人工核实")

    async def get_shareholders(self, name: str) -> DataSourceResult:
        return self._unavailable("股东信息暂未获取到，建议人工核实")
