# -*- coding: utf-8 -*-
"""Playwright 浏览器启动公共封装（2026-09-03，Docker/Linux 部署适配）

背景：资产先锋需部署到预装 Docker 的香港服务器（临时）并日后迁回国内。
原代码 8 处硬编码 `p.chromium.launch(channel="chrome")` —— 依赖 Windows 系统 Chrome，
Linux 容器无系统 Chrome 会直接失败。

策略：优先系统 Chrome（Windows 本机/装了 Chrome 的机器，渲染旧 TLS 站点如信达更稳），
找不到/启动失败则自动回退 Playwright 自带 chromium（容器 `playwright install chromium`）。
调用方统一 `from .browser import launch_chromium`，不再各自 hardcode。
"""
import logging

logger = logging.getLogger(__name__)


def launch_chromium(p, **kwargs):
    """启动 Chromium：优先系统 Chrome，失败回退 Playwright 自带 chromium。

    用法：with sync_playwright() as p: browser = launch_chromium(p, headless=True)
    额外 kwargs（viewport 等在 context 上配，此处仅 launch 参数）原样传给两次尝试。
    """
    headless = kwargs.pop("headless", True)
    attempts = [("系统 Chrome", {"channel": "chrome", "headless": headless})]
    if "channel" not in kwargs:
        attempts.append(("自带 Chromium", {"headless": headless}))
    last_err = None
    for name, opts in attempts:
        try:
            b = p.chromium.launch(**opts)
            logger.info("浏览器启动成功（%s）", name)
            return b
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("浏览器启动失败（%s）: %s", name, str(e)[:160])
    raise RuntimeError(f"无法启动浏览器（系统 Chrome 与自带 Chromium 均失败）: {last_err}")
