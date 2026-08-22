# -*- coding: utf-8 -*-
"""企查查 MCP 实测脚本：验证深度数据链路（工商/股东/司法）

用法（在任意终端）：
  Q:\\deepseek\\zichanxianfeng\\backend\\.venv\\Scripts\\python.exe Q:\\deepseek\\zichanxianfeng\\backend\\scripts\\test_qcc_live.py

可传企业名：... test_qcc_live.py "青岛啤酒股份有限公司"
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.api.qcc import McpClient  # noqa: E402

COMPANY = sys.argv[1] if len(sys.argv) > 1 else "青岛啤酒股份有限公司"


async def main():
    out = {}
    async with httpx.AsyncClient(timeout=60) as client:
        comp = McpClient("/mcp/company/stream")
        await comp.init(client)
        # 1) 工商登记（核心）
        out["工商登记"] = await comp.call(client, "get_company_registration_info", {"searchKey": COMPANY})
        # 2) 股东信息
        out["股东信息"] = await comp.call(client, "get_shareholder_info", {"searchKey": COMPANY})

    print("=" * 60)
    print(f"查询企业：{COMPANY}")
    print("=" * 60)
    for name, result in out.items():
        print(f"\n【{name}】ok={result.get('ok')}")
        data = result.get("data")
        if isinstance(data, dict):
            # 只打印前若干关键字段，避免刷屏
            for k, v in list(data.items())[:8]:
                text = str(v)
                print(f"  {k}: {text[:150]}")
        else:
            print(f"  {data}")

    print("\n" + "=" * 60)
    print("提示：ok=True 表示链路正常；ok=False 请查看 note 字段（token 失效/积分不足/接口变化）")
    print("=" * 60)


asyncio.run(main())
