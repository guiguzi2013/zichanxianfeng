# -*- coding: utf-8 -*-
"""在线心跳活跃表(2026-09-08 用户批准, 内存版零磁盘开销)

单进程部署: 用进程内存 dict 存 {user_id: 最近心跳时间戳}; 前端可见时每 5 分钟上报一次。
判定: 10 分钟内无心跳 → 视为离线(页面切后台/关闭/人离开即停发)。
重启丢失的只是"最近几分钟活跃态", 无副作用。
"""
import threading
import time
from datetime import datetime

_ACTIVE: dict[int, float] = {}
_LOCK = threading.Lock()
# 10 分钟内无心跳判离线(心跳间隔 5 分钟, 留一倍余量)
ACTIVE_TTL = 600


def mark_active(user_id: int) -> None:
    """上报活跃(登录与心跳共用入口)"""
    with _LOCK:
        _ACTIVE[user_id] = time.time()


def clear_active(user_id: int) -> None:
    """登出/注销时清除活跃标记"""
    with _LOCK:
        _ACTIVE.pop(user_id, None)


def last_active_ts(user_id: int) -> float | None:
    with _LOCK:
        return _ACTIVE.get(user_id)


def last_active_dt(user_id: int) -> datetime | None:
    ts = last_active_ts(user_id)
    return datetime.fromtimestamp(ts) if ts else None


def is_online(user_id: int) -> bool:
    """最近 10 分钟内有心跳 → 在线"""
    ts = last_active_ts(user_id)
    return bool(ts) and (time.time() - ts) <= ACTIVE_TTL
