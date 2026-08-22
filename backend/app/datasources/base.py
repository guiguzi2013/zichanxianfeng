"""数据源适配层（可插拔）

P0 免费源：gsxt（工商公示）、zxgk（执行信息网）、valuation（公开搜索估值）
后期可换付费源（爱企查/企查查/威科）而不改业务代码：新增实现类并在工厂注册即可。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class DataSourceResult:
    """统一数据源返回结构。success=False 时 data=None，调用方标注'需人工核实'。"""
    success: bool
    data: dict | list | None = None
    source: str = ""
    fetch_time: str = ""
    note: str = ""  # 失败/降级原因


class EnterpriseDataSource(ABC):
    """工商信息源"""

    @abstractmethod
    async def get_basic_info(self, name: str) -> DataSourceResult:
        """工商基本信息：注册号/法人/注册资本/状态/成立日期"""

    @abstractmethod
    async def get_shareholders(self, name: str) -> DataSourceResult:
        """股东及实控人"""


class JudicialDataSource(ABC):
    """司法风险源（被执行/失信/限高）"""

    @abstractmethod
    async def search_execution(self, keyword: str) -> DataSourceResult:
        """被执行人查询"""

    @abstractmethod
    async def search_dishonest(self, keyword: str) -> DataSourceResult:
        """失信被执行人查询"""

    @abstractmethod
    async def search_restricted(self, keyword: str) -> DataSourceResult:
        """限制消费人员查询"""


class LegalDataSource(ABC):
    """法律文书与法规源"""

    @abstractmethod
    async def search_documents(self, keyword: str) -> DataSourceResult:
        """裁判文书检索"""

    @abstractmethod
    async def get_statutes(self, questions: list[str]) -> DataSourceResult:
        """法规依据检索"""
