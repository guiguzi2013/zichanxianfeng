"""数据源工厂：按配置返回实现实例（可插拔切换付费源）"""
from .gsxt import GsxtDataSource
from .zxgk import ZxgkDataSource

_instances: dict = {}


def get_enterprise_source():
    """P0 返回 Gsxt；P2 可按配置切爱企查等"""
    if "enterprise" not in _instances:
        _instances["enterprise"] = GsxtDataSource()
    return _instances["enterprise"]


def get_judicial_source():
    if "judicial" not in _instances:
        _instances["judicial"] = ZxgkDataSource()
    return _instances["judicial"]
