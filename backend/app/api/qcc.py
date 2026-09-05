"""企查查企业尽调接口（网站自有缓存版）

前端 /api/qcc/query -> 本服务 -> 企查查 Agent MCP（无需独立 node 服务）
- 缓存：同一企业 **1 年**内重复查询直接返回缓存（零调用、零积分），所有用户共享；
  有补充按补充当日续 1 年；无补充满 1 年强制更新（2026-08-31 用户确认）
- 流程：工商核心工具 + 35 维风险扫描（明细仅钻取型工作流按命中调用）
- 更名处理：财产线索查询按 USCC 优先 → 名称比对 → get_company_by_query 定位现名
- **先扫后钻铁律（2026-08-31 用户强调，全平台适用）**：任何外部数据接口一律
  先低成本概览/扫描（如 get_company_risk_scan）拿到命中清单，只对命中且有价值的
  维度钻取明细工具；禁止无差别全量调用。配套：工具级共享缓存（同主体同工具
  1 年内只实查一次）、失败不缓存（防投毒）、查无此名负缓存、大额消耗先确认预算。
  未来接入其他 API 同样遵循此原则。
- **只扫不钻（2026-09-04 用户拍板）**：债权尽调、债务人画像两类工作流只调 risk_scan
  （命中维度/条数进报告概要 risk.hits），不主动钻明细工具；明细工具仅在「财产线索/深挖」
  等钻取型工作流按命中调用。案号/示例只复用共享缓存已有的明细结果（零积分）。
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..database import SessionLocal
from ..models.qcc_cache import QccCache
from .deps import get_current_user, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(tags=["qcc-demo"])

# 企查查 MCP 凭证：优先 .env 的 QCC_TOKEN（2026-09-04 用户换新 key），空则回退下方默认
from ..config import get_settings  # noqa: E402

_QCC_SETTINGS = get_settings()
QCC_TOKEN = _QCC_SETTINGS.qcc_token or "MfGkGeWEtgQLxS7J43UwHW3fWtElI10hhnEPzo4NySnm3LtX"
QCC_HOST = "agent.qcc.com"
# 共享缓存 TTL：1 年（用户确认 2026-08-31：基本信息变化小，更名/注销/吊销不影响债权尽调；
# 利息每天变化走"旧报告+新算"，不靠刷新缓存）。负缓存保持 1h 防积分浪费。
CACHE_TTL = timedelta(days=365)
NEG_TTL = timedelta(hours=1)

# 工商核心工具（始终查询）
COMPANY_TOOLS = [
    ("get_company_registration_info", "工商登记"),
    ("get_shareholder_info", "股东信息"),
    ("get_actual_controller", "实际控制人"),
    ("get_beneficial_owners", "受益所有人"),
    ("get_key_personnel", "主要人员"),
    ("get_branches", "分支机构"),
    ("get_change_records", "变更记录"),
    ("get_annual_reports", "企业年报"),
    ("get_financial_data", "财务数据"),
    ("get_contact_info", "联系方式"),
    ("get_external_investments", "对外投资"),
    ("get_listing_info", "上市信息"),
]


# ================= 自研工作流工具链（2026-09-01 用户确认，09-04 只扫不钻） =================
# 官方 SKILL(企业画像速览/诉讼风险评估/债务清偿能力评估)是全量豪华版太贵(全钻 91-211 积分)，
# 自研精简版只调需要的接口；多工作流共享工具级缓存(tool:{tool}:{company})不重复扣费。
# 单价：1元=10积分；同一主体月封顶 100 积分=10 元。
# 只扫不钻（2026-09-04 用户拍板）：①尽调/④画像 = 只调 risk_scan（risk.hits 命中清单，
# 明细不主动钻）；②财产线索/③深挖 = 先扫后钻（命中才钻，供案号/详情）。

# --- ① 债权尽调工作流（≈4-6 元一次性含股东+变更，三功能共享缓存复用）---
# 司法风险 = 只扫不钻（2026-09-04）：risk_scan 命中清单进报告；要案号/明细走财产线索/深挖
DD_BASE_TOOLS = [
    ("get_company_registration_info", "工商登记", 3),
    # 2026-09-04 用户确认：尽调主动查股东+变更，数据进共享缓存 → 债务人画像/财产线索复用，
    # 同一企业三功能总成本 ≈ 一次查透
    ("get_shareholder_info", "股东信息", 20),
    ("get_change_records", "变更记录(法人/股东/注册资本变动轨迹)", 5),
]
# 尽调的高危司法因子名册（2026-09-04 只扫不钻后不再钻取；保留作工具清单/缓存审计参考，
# 明细展示改由 risk.hits 命中清单 + 复用已有缓存示例，不再主动调用）
DD_RISK_TOOLS = {
    "get_case_filing_info": "立案信息",          # 案号/案由（涉案简述核心）
    "get_judicial_documents": "裁判文书",        # 案由/裁判结果/涉案金额
    "get_judgment_debtor_info": "被执行人",
    "get_dishonest_info": "失信信息",
    "get_high_consumption_restriction": "限制高消费",
    "get_terminated_cases": "终本案件",
    "get_equity_freeze": "股权冻结",
}

# --- ② 财产线索工作流（≈4-8 元）：工商+股东+知产+涉案(重点原告未来债权)+权益类 ---
CLUES_COMPANY_TOOLS = [
    ("get_company_registration_info", "工商登记", 3),
    ("get_shareholder_info", "股东信息", 20),
    ("get_external_investments", "对外投资", 5),
    ("get_branches", "分支机构", 5),
]
# 2026-09-04 审计：企查查 MCP(company/risk 两路 tools/list)不提供以下接口，
# 原 CLUES_IPR_TOOLS(专利/商标/软著/版权/IC/知产出质) 与 CLUES_ASSET_TOOLS
# (行政许可/资质/产权交易/土地出让/土地转让/融资租赁) 全部移除——此前一直在无效调用(0 产出)。
# 如企查查后续开放知产/资质类接口再补回。
# 风险路由财产工具（抵押/拍卖，risk_mcp）
RISK_PROPERTY_TOOLS = [
    ("get_chattel_mortgage_info", "动产抵押", 3),
    ("get_land_mortgage_info", "土地抵押", 3),
    ("get_judicial_auction", "司法拍卖", 3),
]
# 财产线索的司法因子（先扫后钻；重点：裁判文书判原告→未来债权；财产悬赏→未履行金额）
CLUES_RISK_TOOLS = {
    "get_judicial_documents": "裁判文书(原告身份→未来债权)",
    "get_case_filing_info": "立案信息",
    "get_property_asset_announcement": "财产悬赏公告(未履行金额)",
    "get_judgment_debtor_info": "被执行人",
    "get_dishonest_info": "失信信息",
    "get_high_consumption_restriction": "限制高消费",
    "get_terminated_cases": "终本案件",
    "get_equity_freeze": "股权冻结",
    "get_bankruptcy_reorganization": "破产重整",
    "get_valuation_inquiry": "询价评估(资产)",
    # 2026-09-04 实测补充（先扫后钻，命中才钻）：
    "get_court_notice": "法院公告(涉诉/失联信号)",
    "get_service_notice": "送达公告(逃避送达/失联)",
    "get_public_exhortation": "公示催告",
    "get_service_announcement": "劳动仲裁(欠薪/劳资纠纷)",
    "get_default_info": "违约事项",
    "get_disciplinary_list": "惩戒名单",
    "get_liquidation_info": "清算信息",
    "get_exit_restriction": "限制出境",
    "get_tax_abnormal": "税务非正常户",
    "get_tax_arrears_notice": "欠税公告",
}

# --- ③ 深挖工作流（≈6-12 元）：关联企业+财产转移痕迹+隐藏实控人+实缴 ---
DEEP_COMPANY_TOOLS = [
    ("get_company_registration_info", "工商登记", 3),
    ("get_shareholder_info", "股东信息", 20),
    ("get_actual_controller", "实际控制人", 5),
    ("get_beneficial_owners", "受益所有人(隐藏实控人)", 5),
    ("get_change_records", "变更记录(股权变动轨迹)", 5),
    ("get_annual_reports", "企业年报(实缴/股东变动)", 3),
    ("get_financial_data", "财务数据(实缴/负债)", 3),
    ("get_external_investments", "对外投资", 5),
    ("get_tax_invoice_info", "发票信息(经营活跃)", 3),
]
# 深挖司法/资产因子（有记录才拉明细；动产/土地抵押、司法拍卖已在 clues 基底中）
DEEP_RISK_FACTOR_TOOLS = {
    "get_judicial_documents": "裁判文书",
    "get_case_filing_info": "立案信息",
    "get_hearing_notice": "开庭公告",
    "get_valuation_inquiry": "询价评估",
    "get_property_asset_announcement": "财产悬赏公告",
    "get_equity_freeze": "股权冻结",
    "get_equity_pledge_info": "股权出质",
    "get_stock_pledge_info": "股权质押",
    "get_guarantee_info": "担保信息",
    "get_terminated_cases": "终本案件",
}


class McpClient:
    """企查查 Agent MCP 客户端（streamable HTTP + SSE）"""

    def __init__(self, server: str):
        self.server = server  # e.g. '/mcp/company/stream'
        self.session_id: str | None = None

    async def _post(self, client: httpx.AsyncClient, payload: dict) -> httpx.Response:
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "authorization": "Bearer " + QCC_TOKEN,
            "user-agent": "Mozilla/5.0",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        resp = await client.post(
            f"https://{QCC_HOST}{self.server}", json=payload, headers=headers, timeout=60
        )
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        return resp

    async def init(self, client: httpx.AsyncClient) -> None:
        await self._post(client, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "zichanxianfeng", "version": "1.0"},
            },
        })
        await self._post(client, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def call(self, client: httpx.AsyncClient, tool: str, args: dict) -> dict:
        resp = await self._post(client, {
            "jsonrpc": "2.0", "id": int(datetime.now().timestamp() * 1000) % 100000000,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        })
        for line in resp.text.splitlines():
            if not line.startswith("data: "):
                continue
            try:
                msg = json.loads(line[6:])
            except Exception:
                continue
            if "result" in msg:
                content = msg["result"].get("content") or []
                text = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
                try:
                    return {"ok": True, "data": json.loads(text)}
                except Exception:
                    return {"ok": True, "data": text}
            if "error" in msg:
                return {"ok": False, "error": msg["error"].get("message") or str(msg["error"])}
        return {"ok": False, "error": "企查查无有效响应"}


async def query_full(company: str) -> dict:
    """工商全套 + 35维扫描 + 有记录维度明细"""
    async with httpx.AsyncClient() as client:
        company_mcp = McpClient("/mcp/company/stream")
        risk_mcp = McpClient("/mcp/risk/stream")
        await asyncio.gather(company_mcp.init(client), risk_mcp.init(client))

        biz: dict = {}
        for tool, label in COMPANY_TOOLS:
            r = await _call_company_tool(client, company_mcp, tool, company)
            biz[tool] = {"label": label, **r}

        scan = await _call_risk_tool(client, risk_mcp, "get_company_risk_scan", company)

        details: dict = {}
        if scan.get("ok") and isinstance(scan.get("data"), dict):
            for f in scan["data"].get("风险因子扫描") or []:
                if (f.get("条目数") or 0) > 0 and f.get("明细工具"):
                    r = await _call_risk_tool(client, risk_mcp, f["明细工具"], company)
                    details[f["明细工具"]] = {
                        "label": f["风险因子"],
                        "factor": f["风险因子"],
                        "count": f["条目数"],
                        **r,
                    }

        return {"company": company, "biz": biz, "risk": {"scan": scan, "details": details}}


# 更名探测辅助：从 get_company_by_query 返回中提取企业名称（返回结构未知，宽松解析）
def _extract_company_name(fuzzy: dict) -> str | None:
    """从模糊搜索结果中提取候选企业名称；data 可能是 list（候选清单）或 dict"""
    if not fuzzy.get("ok"):
        return None
    data = fuzzy.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            for k in ("企业名称", "公司名称", "name", "companyName", "名称"):
                if first.get(k):
                    return str(first[k])
        elif isinstance(first, str):
            return first
    elif isinstance(data, dict):
        for k in ("企业名称", "公司名称", "name", "companyName", "名称"):
            if data.get(k):
                return str(data[k])
        # data 可能是 {"list": [...]} 包装
        lst = data.get("list") or data.get("data") or data.get("items")
        if isinstance(lst, list) and lst:
            first = lst[0]
            if isinstance(first, dict):
                for k in ("企业名称", "公司名称", "name", "companyName", "名称"):
                    if first.get(k):
                        return str(first[k])
    return None


async def query_property_clues(company: str) -> dict:
    """财产线索页用：工商登记 + 4 个公司工具 + 3 个风险路由财产工具 + 风险扫描（约 8 次调用/企业）

    更名处理（2026-08-31 用户确认）：① 先查工商登记，返回的企业名称与输入不一致 →
    说明已更名，后续工具用"现名"查询；② 登记查无此名 → 调 get_company_by_query
    (1 积分) 模糊搜索定位现名，命中后用现名重查。结果同时写入"输入名"与"现名"两个
    缓存键，两名字下次查询都能命中。
    """
    cached = cache_get(f"clues:{company}")
    if cached:
        return cached
    async with httpx.AsyncClient() as client:
        company_mcp = McpClient("/mcp/company/stream")
        risk_mcp = McpClient("/mcp/risk/stream")
        await asyncio.gather(company_mcp.init(client), risk_mcp.init(client))

        # ① 先查工商登记（同时用于更名探测）
        reg = await _call_company_tool(client, company_mcp, "get_company_registration_info", company)
        search_name = company  # 后续工具实际查询用的名称（更名后为现名）
        renamed: dict | None = None

        reg_ok = reg.get("ok") and isinstance(reg.get("data"), dict)
        if reg_ok and reg["data"].get("企业名称") and reg["data"]["企业名称"] != company:
            # 名称比对：输入名 vs 登记现名不一致 → 已更名，用现名查其余工具
            search_name = reg["data"]["企业名称"]
            renamed = {"old_name": company, "new_name": search_name}
        elif not reg_ok or not (reg.get("data") or {}).get("企业名称"):
            # ② 登记查无此名（可能已更名/曾用名）→ 模糊搜索定位现名（1 积分）
            fuzzy = await _call_company_tool(client, company_mcp, "get_company_by_query", company)
            candidate = _extract_company_name(fuzzy)
            if candidate and candidate != company:
                search_name = candidate
                renamed = {"old_name": company, "new_name": search_name}
                reg = await _call_company_tool(client, company_mcp, "get_company_registration_info", search_name)

        biz: dict = {"get_company_registration_info": {"label": "工商登记", **reg}}
        # 工商+股东+投资+分支（公司路由）
        for tool, label, _price in CLUES_COMPANY_TOOLS[1:]:
            r = await _call_company_tool(client, company_mcp, tool, search_name)
            biz[tool] = {"label": label, **r}
        # 风险抵押/拍卖财产工具：动产抵押/土地抵押/司法拍卖
        for tool, label, _price in RISK_PROPERTY_TOOLS:
            r = await _call_risk_tool(client, risk_mcp, tool, search_name)
            biz[tool] = {"label": label, **r}

        # 风险扫描（先扫后钻分诊）
        scan = await _call_risk_tool(client, risk_mcp, "get_company_risk_scan", search_name)

        # 涉案明细（先扫后钻）：只钻 CLUES_RISK_TOOLS 中的命中维度
        # 重点：裁判文书→识别企业作为原告可能胜诉产生的未来债权；财产悬赏→未履行金额
        details: dict = {}
        if scan.get("ok") and isinstance(scan.get("data"), dict):
            for f in scan["data"].get("风险因子扫描") or []:
                t = f.get("明细工具")
                if (f.get("条目数") or 0) > 0 and t in CLUES_RISK_TOOLS:
                    r = await _call_risk_tool(client, risk_mcp, t, search_name)
                    details[t] = {
                        "label": CLUES_RISK_TOOLS[t],
                        "factor": f["风险因子"],
                        "count": f["条目数"],
                        **r,
                    }

    result = {
        "company": company,          # 用户输入的原始名称
        "search_name": search_name,  # 实际查询的现用名称（更名后 ≠ company）
        "renamed": renamed,          # {old_name, new_name} 或 None
        "biz": biz,
        "risk": {"scan": scan, "details": details},
    }
    # 失败不缓存（防止缓存投毒）；工商登记或风险扫描任一成功即视为可缓存
    reg_ok = biz.get("get_company_registration_info", {}).get("ok")
    scan_ok = scan.get("ok")
    if reg_ok or scan_ok:
        cache_set(f"clues:{company}", result)
        if renamed:
            # 现名键也写一份：换用现名查询同样直接命中（零新增调用）
            result["company"] = search_name
            cache_set(f"clues:{search_name}", result)
    else:
        # 全部失败 → 查无此名/积分耗尽等，写入短时负缓存，避免 1h 内重复消耗积分
        neg_cache_set(company)
    return result


# ---------- 深度调查（深挖工作流，复用 clues 基底 + 增量工具） ----------

def deep_credit_estimate(scan_data: dict | None) -> int:
    """深挖积分预估：基底（未缓存时）+ 公司增量 + 有记录因子明细数"""
    extra = 0
    if scan_data and isinstance(scan_data, dict):
        for f in scan_data.get("风险因子扫描") or []:
            if (f.get("条目数") or 0) > 0 and f.get("明细工具") in DEEP_RISK_FACTOR_TOOLS:
                extra += 1
    return len(DEEP_COMPANY_TOOLS) + len(RISK_PROPERTY_TOOLS) + extra


async def query_deep_investigation(company: str) -> dict:
    """深挖工作流（2026-09-01 用户确认）：关联企业+财产转移痕迹+隐藏实控人+实缴

    工具链（DEEP_COMPANY_TOOLS）：工商/股东/实控人/受益所有人/历史股东(隐藏实控人)/
    变更记录(股权变动)/年报+财务(实缴)/对外投资/历史对外投资(退出=转移痕迹)。
    司法因子：risk_scan 先扫 → 命中才钻 DEEP_RISK_FACTOR_TOOLS 明细。
    关联风险：company_related_risk_scan 先扫关联方风险面 → 有风险关联方单点钻。
    基底复用 clues 缓存（财产线索查过的 工商/股东/抵押/拍卖/知产 零重复扣费）。
    """
    cached = cache_get(f"deep:{company}")
    if cached:
        return cached
    # 1. 基底：clues 缓存优先（含 工商/股东/知产/权益/抵押/拍卖/扫描），缺则实查财产线索
    base = cache_get(f"clues:{company}")
    async with httpx.AsyncClient() as client:
        company_mcp = McpClient("/mcp/company/stream")
        risk_mcp = McpClient("/mcp/risk/stream")
        await asyncio.gather(company_mcp.init(client), risk_mcp.init(client))

        if base is None:
            base = await query_property_clues(company)
        search_name = base.get("search_name") or company

        # 2. 深挖工商增量（关联/实控/实缴/转移痕迹；工具级缓存复用）
        extra_biz: dict = {}
        for tool, label, _price in DEEP_COMPANY_TOOLS:
            # 股东信息等在财产线索已查过 → 工具缓存直接命中，零新增扣费
            r = await _call_company_tool(client, company_mcp, tool, search_name)
            extra_biz[tool] = {"label": label, **r}

        # 3. 关联方风险（先扫后钻）：company_related_risk_scan 一次拿关联方风险面
        related = await _call_risk_tool(client, risk_mcp, "get_company_related_risk_scan", search_name)
        extra_biz["get_company_related_risk_scan"] = {"label": "关联方风险扫描", **related}

        # 4. 司法因子明细（先扫后钻）：只钻 DEEP_RISK_FACTOR_TOOLS 命中维度
        scan = base.get("risk", {}).get("scan") or {}
        details: dict = {}
        if scan.get("ok") and isinstance(scan.get("data"), dict):
            for f in scan["data"].get("风险因子扫描") or []:
                t = f.get("明细工具")
                if (f.get("条目数") or 0) > 0 and t in DEEP_RISK_FACTOR_TOOLS:
                    r = await _call_risk_tool(client, risk_mcp, t, search_name)
                    details[t] = {"label": f["风险因子"], "count": f["条目数"], **r}

    result = {
        "company": company,
        "search_name": search_name,
        "renamed": base.get("renamed"),
        "base": base,               # 财产线索基底（工商/股东/知产/权益/抵押/拍卖/扫描）
        "extra_biz": extra_biz,     # 深挖工商增量（关联/实控/实缴/转移痕迹）
        "risk_details": details,    # 深挖司法因子明细
        "related_scan": related,    # 关联方风险面（有风险关联方→提示钻取）
    }
    reg_ok = (base.get("biz", {}).get("get_company_registration_info") or {}).get("ok") or (
        extra_biz.get("get_company_registration_info") or {}).get("ok")
    if reg_ok:
        cache_set(f"deep:{company}", result)
    return result


# ================= ④ 债务人画像工作流（2026-09-04 用户确认新增） =================
# 定位：输入债务人企业 → 出"XXX企业速览"PDF。所有工具走共享缓存——尽调/财产线索查过的
# 维度零新增积分；反之画像查全后，对该企业尽调也基本零新增。新企业首次≈股东20+实控/受益/主要
# 人员/变更/投资/分支/年报/财务 ≈ 40-50 积分(4-5元) + scan 5 分（司法只扫不钻），月封顶100积分。
PROFILE_BASE_TOOLS = [
    ("get_company_registration_info", "工商登记", 3),
    ("get_shareholder_info", "股东信息", 20),
    ("get_actual_controller", "实际控制人", 5),
    ("get_beneficial_owners", "受益所有人", 5),
    ("get_key_personnel", "主要人员", 3),
    ("get_change_records", "变更记录", 5),
    ("get_external_investments", "对外投资", 5),
    ("get_branches", "分支机构", 5),
    ("get_annual_reports", "企业年报", 3),
    ("get_financial_data", "财务数据", 3),
]
PROFILE_QUAL_TOOLS = []  # 2026-09-04 审计：MCP 无 行政许可/资质 接口，移除(原含 get_administrative_license/get_qualifications)
# 画像司法因子名册（2026-09-04 只扫不钻后不再钻取；保留作工具清单/缓存审计参考，
# 明细展示改由 risk.hits 命中清单 + 复用已有缓存示例）
# 2026-09-04 实测补充（蓝图无记录亦接口有效，返回文案确认真实库）：
#   court_notice=法院公告 / service_notice=送达公告 / public_exhortation=公示催告 /
#   service_announcement=劳动仲裁(名字与内容不符!) / default_info=违约事项 / disciplinary_list=惩戒名单
PROFILE_RISK_TOOLS = {
    "get_dishonest_info": "失信被执行人",
    "get_judgment_debtor_info": "被执行人",
    "get_high_consumption_restriction": "限制高消费",
    "get_terminated_cases": "终本案件",
    "get_business_exception": "经营异常",
    "get_administrative_penalty": "行政处罚",
    "get_serious_violation": "严重违法失信",
    "get_equity_freeze": "股权冻结",
    "get_equity_pledge_info": "股权出质",
    "get_case_filing_info": "立案信息",
    "get_judicial_documents": "裁判文书",
    "get_hearing_notice": "开庭公告",
    "get_bankruptcy_reorganization": "破产重整",
    "get_court_notice": "法院公告",
    "get_service_notice": "送达公告",
    "get_public_exhortation": "公示催告",
    "get_service_announcement": "劳动仲裁",
    "get_default_info": "违约事项",
    "get_disciplinary_list": "惩戒名单",
    "get_liquidation_info": "清算信息",
    "get_exit_restriction": "限制出境",
    "get_tax_abnormal": "税务非正常户",
    "get_tax_arrears_notice": "欠税公告",
    "get_stock_pledge_info": "股权质押",
    "get_guarantee_info": "对外担保",
    "get_chattel_mortgage_info": "动产抵押",
    "get_land_mortgage_info": "土地抵押",
}


async def query_debtor_profile(company: str) -> dict:
    """④ 债务人画像工作流（2026-09-04）：全维度企业速览数据（供 PDF 报告）

    双向复用（用户 2026-09-04 确认）：本工作流与 尽调/财产线索/深挖 共享工具级缓存——
    先尽调后画像 / 先画像后尽调，同一企业维度只实查一次，后续功能零新增积分。
    更名处理：同 clues（工商现名比对 → 用现名查其余维度）。
    司法风险 = 只扫不钻（2026-09-04 用户拍板）：risk_scan 命中清单（hits）+ 缓存已有明细的
    示例（零积分）；不主动钻取明细工具，避免无谓积分。
    返回结构 {company, search_name, renamed, biz{tool:{label,data}}, risk{scan,hits},
    queried_at}；biz/risk 为 PDF 渲染与摘要的数据源。
    """
    cached = cache_get(f"profile:{company}")
    if cached:
        return cached
    async with httpx.AsyncClient() as client:
        company_mcp = McpClient("/mcp/company/stream")
        risk_mcp = McpClient("/mcp/risk/stream")
        await asyncio.gather(company_mcp.init(client), risk_mcp.init(client))

        reg = await _call_company_tool(client, company_mcp, "get_company_registration_info", company)
        search_name = company
        renamed: dict | None = None
        reg_ok = reg.get("ok") and isinstance(reg.get("data"), dict)
        if reg_ok and reg["data"].get("企业名称") and reg["data"]["企业名称"] != company:
            search_name = reg["data"]["企业名称"]
            renamed = {"old_name": company, "new_name": search_name}
        elif not reg_ok or not (reg.get("data") or {}).get("企业名称"):
            fuzzy = await _call_company_tool(client, company_mcp, "get_company_by_query", company)
            candidate = _extract_company_name(fuzzy)
            if candidate and candidate != company:
                search_name = candidate
                renamed = {"old_name": company, "new_name": search_name}
                reg = await _call_company_tool(client, company_mcp, "get_company_registration_info", search_name)

        biz: dict = {"get_company_registration_info": {"label": "工商登记", **reg}}
        # 2026-09-04：基础工具与风险扫描 并行调用（首次查询降到几十秒）
        jobs = []
        job_meta = []
        for tool, label, _p in PROFILE_BASE_TOOLS[1:]:
            jobs.append(_call_company_tool(client, company_mcp, tool, search_name))
            job_meta.append((tool, label, "company"))
        jobs.append(_call_risk_tool(client, risk_mcp, "get_company_risk_scan", search_name))
        job_meta.append(("__scan__", "", "risk"))
        results = await asyncio.gather(*jobs, return_exceptions=True)

        for (tool, label, _kind), r in zip(job_meta, results):
            if isinstance(r, Exception):
                biz[tool] = {"label": label, "ok": False, "error": str(r)[:120]}
                continue
            if tool == "__scan__":
                continue
            biz[tool] = {"label": label, **r}
        scan = results[-1] if not isinstance(results[-1], Exception) else {"ok": False, "error": str(results[-1])[:120]}
        # 只扫不钻（2026-09-04）：命中清单来自 scan；sample 仅复用已有缓存（零积分）
        hits = _scan_hits(scan, search_name)

    result = {
        "company": company,
        "search_name": search_name,
        "renamed": renamed,
        "biz": biz,
        "risk": {"scan": scan, "hits": hits},
    }
    if biz.get("get_company_registration_info", {}).get("ok") or scan.get("ok"):
        cache_set(f"profile:{company}", result)
        if renamed:
            result["company"] = search_name
            cache_set(f"profile:{search_name}", result)
    else:
        neg_cache_set(company)
    return result


async def query_engine_summary(company: str) -> dict:
    """① 债权尽调工作流（2026-09-01 用户确认，2026-09-04 只扫不钻）：债务人基本信息 + 股东/变更 + 涉案

    工具链（DD_BASE_TOOLS + risk_scan）：
    - 工商登记(3) 主体核验 + 股东信息(20) + 变更记录(5) —— 用户 2026-09-04 确认主动查，
      数据进共享工具缓存，债务人画像/财产线索直接复用（三功能同企业≈一次查透）
    - risk_scan(5) 先扫分诊 —— 只扫不钻（2026-09-04 用户拍板）：概要展示命中维度/条数
      （hits），不主动调用各明细工具；案号示例仅当明细工具结果已在共享缓存时附带（零积分）。
      需要明细/案号的完整场景走「财产线索/深挖」（先扫后钻）。
    同一主体月封顶 100 积分=10 元；工具级缓存 1 年复用（后续功能零新增）。
    """
    cached = cache_get(f"eng:{company}")
    if cached:
        return cached
    async with httpx.AsyncClient() as client:
        company_mcp = McpClient("/mcp/company/stream")
        risk_mcp = McpClient("/mcp/risk/stream")
        await asyncio.gather(company_mcp.init(client), risk_mcp.init(client))

        # 工商/股东/变更（2026-09-04：股东与变更主动查，供画像/线索复用）
        reg = await _call_company_tool(client, company_mcp, "get_company_registration_info", company)
        shr = await _call_company_tool(client, company_mcp, "get_shareholder_info", company)
        chg = await _call_company_tool(client, company_mcp, "get_change_records", company)
        scan = await _call_risk_tool(client, risk_mcp, "get_company_risk_scan", company)

        # 只扫不钻（2026-09-04）：命中清单来自 scan；sample 仅复用已有缓存（零积分）
        hits = _scan_hits(scan, company)

    result = {
        "company": company,
        "reg": reg,
        "shareholders": shr,
        "change_records": chg,
        "risk": {"scan": scan, "hits": hits},
    }
    cache_set(f"eng:{company}", result)
    return result


# ---------- 缓存（网站自有，所有用户共享） ----------
def cache_get(company: str) -> dict | None:
    db = SessionLocal()
    try:
        row = db.get(QccCache, company)
        if row and row.created_at and datetime.now() - row.created_at < CACHE_TTL:
            return json.loads(row.payload)
    except Exception:
        logger.exception("qcc cache read failed")
    finally:
        db.close()
    return None


def cache_set(company: str, payload: dict) -> None:
    db = SessionLocal()
    try:
        # 记录查询时间（数据截至），供报告/页面标注"数据截至 2026 年"；缓存过期 1 年强制更新
        payload.setdefault("queried_at", datetime.now().strftime("%Y-%m-%d"))
        row = db.get(QccCache, company)
        if row:
            row.payload = json.dumps(payload, ensure_ascii=False)
            row.created_at = datetime.now()
        else:
            db.add(QccCache(company=company, payload=json.dumps(payload, ensure_ascii=False)))
        db.commit()
    except Exception:
        logger.exception("qcc cache write failed")
        db.rollback()
    finally:
        db.close()


# ---------- 工具级共享缓存（2026-08-31：同一企业同一工具 24h 内全站共享，省积分） ----------
# 背景：get_shareholder_info 等在 尽调/财产线索/深度调查 三个功能各自独立调用（各消耗一次积分）。
# 现按 "tool:{tool}:{company}" 做共享缓存，任一功能查询后其他功能 24h 内直接复用（零积分）。

def _tool_cache_get(tool: str, company: str) -> dict | None:
    """工具级缓存读取；命中返回 payload，未命中/过期返回 None"""
    key = f"tool:{tool}:{company}"
    db = SessionLocal()
    try:
        row = db.get(QccCache, key)
        if row and row.created_at and datetime.now() - row.created_at < CACHE_TTL:
            return json.loads(row.payload)
    except Exception:
        logger.exception("qcc tool cache read failed")
    finally:
        db.close()
    return None


def _tool_cache_set(tool: str, company: str, payload: dict) -> None:
    """工具级缓存写入（仅成功结果可缓存，失败不缓存防投毒）"""
    if not payload.get("ok"):
        return
    key = f"tool:{tool}:{company}"
    db = SessionLocal()
    try:
        payload.setdefault("queried_at", datetime.now().strftime("%Y-%m-%d"))
        row = db.get(QccCache, key)
        if row:
            row.payload = json.dumps(payload, ensure_ascii=False)
            row.created_at = datetime.now()
        else:
            db.add(QccCache(company=key, payload=json.dumps(payload, ensure_ascii=False)))
        db.commit()
    except Exception:
        logger.exception("qcc tool cache write failed")
        db.rollback()
    finally:
        db.close()


async def _call_company_tool(client: httpx.AsyncClient, mcp: McpClient, tool: str, company: str) -> dict:
    """调公司工具：共享缓存优先（同一企业 1 年内只实查一次）。
    2026-09-04：失败不写缓存（防失败结果污染缓存永久命中）。"""
    hit = _tool_cache_get(tool, company)
    if hit is not None:
        return hit
    r = await mcp.call(client, tool, {"searchKey": company})
    if r.get("ok"):
        _tool_cache_set(tool, company, r)
    return r


async def _call_risk_tool(client: httpx.AsyncClient, mcp: McpClient, tool: str, company: str) -> dict:
    """调风险工具：共享缓存优先；失败不写缓存。"""
    hit = _tool_cache_get(tool, company)
    if hit is not None:
        return hit
    r = await mcp.call(client, tool, {"searchKey": company})
    if r.get("ok"):
        _tool_cache_set(tool, company, r)
    return r


# ---------- 只扫不钻：命中清单（2026-09-04 用户拍板） ----------
# 债权尽调、债务人画像 = 只扫（risk_scan）不钻：概要只展示"扫"到的命中维度与条数；
# 案号/示例仅在缓存已有该明细工具结果时附带（零积分），绝不为凑示例主动钻取。
def _detail_sample(payload: dict | None, n: int = 150) -> str:
    """从明细工具结果里抽一段示例文本（首条记录的前几个标量字段），供报告'示例'列展示"""
    if not payload or not payload.get("ok"):
        return ""
    data = payload.get("data")
    lst = data if isinstance(data, list) else None
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v:
                lst = v
                break
    if isinstance(lst, list) and lst:
        first = lst[0]
        if isinstance(first, dict):
            parts = []
            for v in first.values():
                if isinstance(v, (dict, list)):
                    continue
                s = str(v).strip()
                if s and s != "[]":
                    parts.append(s)
                if len(parts) >= 3:
                    break
            return "；".join(parts)[:n] if parts else ""
        return str(first)[:n]
    if isinstance(data, dict):
        for k in ("摘要", "说明", "搜索结果"):
            if isinstance(data.get(k), str) and data[k].strip():
                return data[k][:n]
    return ""


def _scan_hits(scan: dict, company: str) -> list:
    """从 risk_scan 结果生成命中清单（只扫不钻）：
    [{label, count, tool, sample?}]——label/count 来自扫描本身；
    sample 仅当明细工具结果已在共享缓存（tool:{tool}:{company}）时附上（零积分），否则不附、不钻取。
    """
    hits: list = []
    if not (scan.get("ok") and isinstance(scan.get("data"), dict)):
        return hits
    for f in scan["data"].get("风险因子扫描") or []:
        if not isinstance(f, dict):
            continue
        cnt = f.get("条目数") or 0
        if cnt <= 0:
            continue
        t = f.get("明细工具") or ""
        item: dict = {"label": f.get("风险因子") or "", "count": cnt, "tool": t}
        if t:
            cached = _tool_cache_get(t, company)
            sample = _detail_sample(cached) if cached else ""
            if sample:
                item["sample"] = sample
        hits.append(item)
    return hits


# ---------- 负缓存（查无此名，短 TTL，防积分浪费） ----------
def neg_cache_get(company: str) -> bool:
    """该名称是否在负缓存中（1h 内查过且查无此名）"""
    db = SessionLocal()
    try:
        row = db.get(QccCache, f"neg:{company}")
        if row and row.created_at and datetime.now() - row.created_at < NEG_TTL:
            return True
    except Exception:
        logger.exception("qcc neg-cache read failed")
    finally:
        db.close()
    return False


def neg_cache_set(company: str) -> None:
    db = SessionLocal()
    try:
        row = db.get(QccCache, f"neg:{company}")
        if row:
            row.payload = json.dumps({"negative": True}, ensure_ascii=False)
            row.created_at = datetime.now()
        else:
            db.add(QccCache(company=f"neg:{company}", payload=json.dumps({"negative": True}, ensure_ascii=False)))
        db.commit()
    except Exception:
        logger.exception("qcc neg-cache write failed")
        db.rollback()
    finally:
        db.close()


class QccQueryRequest(BaseModel):
    company: str
    mode: str = "full"  # full=全量(演示页) / eng=债权尽调 / clues=财产线索 / deep=深挖 / profile=债务人画像


@router.get("/qcc/history")
async def qcc_history():
    """查询记录：列出缓存中的全部企业（所有用户共享）"""
    db = SessionLocal()
    try:
        rows = db.query(QccCache).order_by(QccCache.created_at.desc()).limit(200).all()
        items = []
        for r in rows:
            try:
                if r.company.startswith("eng:") or r.company.startswith("neg:"):  # 内部缓存键，不展示
                    continue
                p = json.loads(r.payload)
                biz = p.get("biz", {})
                risk = p.get("risk", {})
                risk_hits = risk.get("hits") or []
                risk_details = risk.get("details") or {}
                # 只扫工作流(eng/profile)记录 hits 命中维度数；钻取工作流(clues/deep)记明细 ok 数
                risk_records = len(risk_hits) if risk_hits else sum(
                    1 for v in risk_details.values() if v.get("ok"))
                items.append({
                    "company": r.company,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "biz_count": sum(1 for v in biz.values() if v.get("ok")),
                    "risk_records": risk_records,
                })
            except Exception:
                continue
        return {"ok": True, "list": items}
    finally:
        db.close()


@router.post("/qcc/query")
async def qcc_query(payload: QccQueryRequest, user=Depends(get_current_user)):
    """企查查查询：需登录（财产线索/演示页查询前须登录，保护企查查积分成本）"""
    company = payload.company.strip()
    if not company:
        return {"ok": False, "error": "请输入企业名称"}

    def _annotate(result: dict) -> dict:
        """检测'查无此名'：工商登记为空 → 提示名称可能已变更（曾用名/简称）；
        更名处理（2026-08-31）：clues 结果已自动用现名重查，这里仅提示更名事实"""
        reg = result.get("biz", {}).get("get_company_registration_info") or {}
        data = reg.get("data") if reg.get("ok") else None
        name_ok = bool(data and data.get("企业名称"))
        result["name_ok"] = name_ok
        renamed = result.get("renamed")
        if renamed and isinstance(renamed, dict):
            result["name_warning"] = (
                f"该企业可能已由「{renamed.get('old_name')}」更名为「{renamed.get('new_name')}」，"
                "已按现名查询财产线索。"
            )
        elif not name_ok:
            result["name_warning"] = (
                "该名称可能已变更或与工商登记不符（如判决书使用的曾用名/简称）。"
                "查询结果可能为空/无效，建议核对准确工商名称后重查（可尝试'名称变体解析'）。"
            )
        return result

    if payload.mode == "eng":
        # ① 债权尽调工作流：工商+股东+变更 + 涉案案号/简述（先扫后钻）
        try:
            result = await query_engine_summary(company)
            return {"ok": True, "cached": False, "data": result}
        except Exception as e:
            logger.exception("QCC dd query failed for %s", company)
            return {"ok": False, "error": str(e)}

    if payload.mode == "profile":
        # ④ 债务人画像工作流：全维度速览（供 PDF "XXX企业速览"）
        try:
            result = await query_debtor_profile(company)
            return {"ok": True, "cached": False, "data": result}
        except Exception as e:
            logger.exception("QCC profile query failed for %s", company)
            return {"ok": False, "error": str(e)}

    if payload.mode == "clues":
        # 轻量缓存优先，全量缓存兜底（结构兼容，省积分）
        cached = cache_get(f"clues:{company}") or cache_get(company)
        if cached:
            return {"ok": True, "cached": True, **_annotate(dict(cached))}
        if neg_cache_get(company):
            # 1h 内查过且查无此名：不再重复调用，直接返回"名称不符"提示
            empty = {"company": company, "biz": {}, "risk": {"scan": {"ok": False}, "details": {}}}
            return {"ok": True, "cached": False, "negative": True, **_annotate(empty)}
        try:
            result = await query_property_clues(company)
        except Exception as e:
            logger.exception("QCC clues query failed for %s", company)
            return {"ok": False, "error": str(e)}
        return {"ok": True, "cached": False, **_annotate(result)}

    if payload.mode == "deep":
        # ③ 深挖工作流：关联企业/转移痕迹/隐藏实控人/实缴（复用 clues 基底）
        try:
            result = await query_deep_investigation(company)
            return {"ok": True, "cached": False, "data": result}
        except Exception as e:
            logger.exception("QCC deep query failed for %s", company)
            return {"ok": False, "error": str(e)}

    cached = cache_get(company)
    if cached:
        return {"ok": True, "cached": True, **_annotate(dict(cached))}

    try:
        result = await query_full(company)
    except Exception as e:
        logger.exception("QCC query failed for %s", company)
        return {"ok": False, "error": str(e)}

    cache_set(company, result)
    return {"ok": True, "cached": False, **_annotate(result)}


# ---------- 单条强制刷新（2026-08-31 用户确认：只做单条，不做全量，防误点） ----------
def _cache_keys_for(company: str) -> list[str]:
    """该债务人在缓存中的全部键：全量键、eng/clues/deep/neg 前缀键、工具级 tool:* 键"""
    keys = [company, f"eng:{company}", f"clues:{company}", f"deep:{company}", f"profile:{company}", f"neg:{company}"]
    db = SessionLocal()
    try:
        prefix = "tool:"
        suffix = f":{company}"
        rows = db.query(QccCache.company).filter(QccCache.company.like(f"{prefix}%")).all()
        for (k,) in rows:
            if k.endswith(suffix) and k.count(":") == 2:
                keys.append(k)
    except Exception:
        logger.exception("qcc list tool cache keys failed")
    finally:
        db.close()
    return keys


def _cache_delete(company: str) -> int:
    """删除该债务人的全部缓存键（含工具级），返回删除条数"""
    keys = _cache_keys_for(company)
    db = SessionLocal()
    n = 0
    try:
        for k in keys:
            row = db.get(QccCache, k)
            if row:
                db.delete(row)
                n += 1
        db.commit()
    except Exception:
        logger.exception("qcc cache delete failed")
        db.rollback()
    finally:
        db.close()
    return n


class QccRefreshRequest(BaseModel):
    company: str
    mode: str = "clues"  # clues=财产线索 / full=全量 / eng=债权尽调 / deep=深挖


@router.post("/qcc/refresh")
async def qcc_refresh(payload: QccRefreshRequest, user=Depends(require_admin)):
    """单条强制刷新：删除该债务人全部缓存键后重新实查（扣积分），仅影响该债务人，不影响其他企业缓存

    仅管理员可用（2026-08-31 用户确认：员工/普通用户无此权限，防误点消耗积分）。
    """
    company = payload.company.strip()
    if not company:
        return {"ok": False, "error": "请输入企业名称"}
    deleted = _cache_delete(company)
    try:
        if payload.mode == "eng":
            result = await query_engine_summary(company)
            return {"ok": True, "deleted": deleted, "cached": False, "data": result}
        if payload.mode == "clues":
            result = await query_property_clues(company)
            return {"ok": True, "deleted": deleted, "cached": False, "data": result}
        if payload.mode == "deep":
            result = await query_deep_investigation(company)
            return {"ok": True, "deleted": deleted, "cached": False, "data": result}
        if payload.mode == "profile":
            result = await query_debtor_profile(company)
            return {"ok": True, "deleted": deleted, "cached": False, "data": result}
        result = await query_full(company)
        cache_set(company, result)
        return {"ok": True, "deleted": deleted, "cached": False, "data": result}
    except Exception as e:
        logger.exception("QCC refresh failed for %s", company)
        return {"ok": False, "error": str(e)}
