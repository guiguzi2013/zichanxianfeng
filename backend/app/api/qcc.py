"""企查查企业尽调接口（网站自有缓存版）

前端 /api/qcc/query -> 本服务 -> 企查查 Agent MCP（无需独立 node 服务）
- 缓存：同一企业 **1 年**内重复查询直接返回缓存（零调用、零积分），所有用户共享；
  有补充按补充当日续 1 年；无补充满 1 年强制更新（2026-08-31 用户确认）
- 流程：工商核心工具 + 35 维风险扫描 + 有记录维度明细
- 更名处理：财产线索查询按 USCC 优先 → 名称比对 → get_company_by_query 定位现名
- **先扫后钻铁律（2026-08-31 用户强调，全平台适用）**：任何外部数据接口一律
  先低成本概览/扫描（如 get_company_risk_scan）拿到命中清单，只对命中且有价值的
  维度钻取明细工具；禁止无差别全量调用。配套：工具级共享缓存（同主体同工具
  1 年内只实查一次）、失败不缓存（防投毒）、查无此名负缓存、大额消耗先确认预算。
  未来接入其他 API 同样遵循此原则。
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

# 企查查 MCP 凭证：优先 .env 的 QCC_TOKEN，空则回退旧 token
# 2026-09-02 用户换新 token（积分更多）：MfGkGeWEtgQLxS7J43UwHW3fWtElI10hhnEPzo4NySnm3LtX
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


# ================= 自研三大工作流工具链（2026-09-01 用户确认） =================
# 官方 SKILL(企业画像速览/诉讼风险评估/债务清偿能力评估)是全量豪华版太贵(全钻 91-211 积分)，
# 自研精简版只调需要的接口；多工作流共享工具级缓存(tool:{tool}:{company})不重复扣费。
# 单价：1元=10积分；同一主体月封顶 100 积分=10 元。

# --- ① 债权尽调工作流（≈2-4 元）：工商 + 涉案(案号/简述) ---
# 涉案"只要案号+简述" → get_case_filing_info(立案信息:案号/案由/立案日期/原被告, 3积分) 最契合
DD_BASE_TOOLS = [
    ("get_company_registration_info", "工商登记", 3),
]
# 尽调的高危司法因子（先扫后钻，命中才钻；各 3 积分）
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
# 知产（可拍卖变现，各 1 积分）
CLUES_IPR_TOOLS = [
    ("get_patent_info", "专利", 1),
    ("get_trademark_info", "商标", 1),
    ("get_software_copyright_info", "软件著作权", 1),
    ("get_copyright_work_info", "作品著作权", 1),
    ("get_integrated_circuit_layout", "集成电路布图", 1),
    ("get_ipr_pledge", "知产出质", 1),
]
# 权益类可变现资产（无专门矿权/林权接口，用行政许可/资质/产权交易/土地/租赁替代）
CLUES_ASSET_TOOLS = [
    ("get_administrative_license", "行政许可(矿权/林权/经营权等登记)", 3),
    ("get_qualifications", "资质证书", 1),
    ("get_property_rights_transaction", "产权交易挂牌", 3),
    ("get_land_grant_info", "土地出让", 3),
    ("get_land_transfer_info", "土地转让", 3),
    ("get_financing_lease_info", "融资租赁", 5),
]
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
}

# --- ③ 深挖工作流（≈6-12 元）：关联企业+财产转移痕迹+隐藏实控人+实缴 ---
DEEP_COMPANY_TOOLS = [
    ("get_company_registration_info", "工商登记", 3),
    ("get_shareholder_info", "股东信息", 20),
    ("get_actual_controller", "实际控制人", 5),
    ("get_beneficial_owners", "受益所有人(隐藏实控人)", 5),
    ("get_historical_shareholders", "历史股东(隐藏实控人/退出痕迹)", 20),
    ("get_change_records", "变更记录(股权变动轨迹)", 5),
    ("get_annual_reports", "企业年报(实缴/股东变动)", 3),
    ("get_financial_data", "财务数据(实缴/负债)", 3),
    ("get_external_investments", "对外投资", 5),
    ("get_historical_investments", "历史对外投资(退出=转移痕迹)", 5),
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
        # 知产（可拍卖变现，各 1 积分）
        for tool, label, _price in CLUES_IPR_TOOLS:
            r = await _call_company_tool(client, company_mcp, tool, search_name)
            biz[tool] = {"label": label, **r}
        # 权益类可变现资产（行政许可/资质/产权交易/土地/租赁）
        for tool, label, _price in CLUES_ASSET_TOOLS:
            r = await _call_company_tool(client, company_mcp, tool, search_name)
            biz[tool] = {"label": label, **r}

        # 风险扫描（先扫后钻分诊）
        scan = await _call_risk_tool(client, risk_mcp, "get_company_risk_scan", search_name)

        # 风险路由的财产工具：动产抵押/土地抵押/司法拍卖
        for tool, label, _price in RISK_PROPERTY_TOOLS:
            r = await _call_risk_tool(client, risk_mcp, tool, search_name)
            biz[tool] = {"label": label, **r}

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


async def query_engine_summary(company: str) -> dict:
    """① 债权尽调工作流（2026-09-01 用户确认）：债务人基本信息 + 涉案情况(案号/简述即可)

    工具链（DD_BASE_TOOLS + DD_RISK_TOOLS）：
    - 工商登记(3) 做主体核验
    - risk_scan(5) 先扫分诊 → 命中才钻 立案信息(案号/案由/原被告=涉案简述核心)/裁判文书/被执行/失信/限高/终本/股权冻结(各3)
    股东信息不主动实查（20 积分/次，全站最贵）：仅在已有工具级共享缓存时附带
    （用户先用了财产线索功能则免费复用），未缓存则不查——需要股东信息时由
    财产线索功能触发（先扫后钻铁律，2026-08-31 用户确认）。
    ≈ 2-4 元/主体；同一主体月封顶 100 积分=10 元。
    """
    cached = cache_get(f"eng:{company}")
    if cached:
        # 缓存命中：若工具缓存已有股东信息（用户先用了财产线索功能），合并进结果，
        # 让"先财产线索、后尽调"也能免费复用，不额外扣积分
        if not (cached.get("shareholders") or {}).get("ok"):
            shr = _tool_cache_get("get_shareholder_info", company)
            if shr is not None:
                cached["shareholders"] = shr
        return cached
    async with httpx.AsyncClient() as client:
        company_mcp = McpClient("/mcp/company/stream")
        risk_mcp = McpClient("/mcp/risk/stream")
        await asyncio.gather(company_mcp.init(client), risk_mcp.init(client))

        reg = await _call_company_tool(client, company_mcp, "get_company_registration_info", company)
        scan = await _call_risk_tool(client, risk_mcp, "get_company_risk_scan", company)

        # 股东信息：仅复用已有工具级缓存（财产线索功能查过才有），不主动实查省 20 积分
        shr = _tool_cache_get("get_shareholder_info", company)
        if shr is None:
            shr = {"ok": False, "note": "股东信息未查询（可在财产线索功能查询）"}

        # 涉案明细（先扫后钻）：只钻 DD_RISK_TOOLS 命中维度（案号/案由/简述）
        details: dict = {}
        if scan.get("ok") and isinstance(scan.get("data"), dict):
            for f in scan["data"].get("风险因子扫描") or []:
                t = f.get("明细工具")
                if (f.get("条目数") or 0) > 0 and t in DD_RISK_TOOLS:
                    r = await _call_risk_tool(client, risk_mcp, t, company)
                    details[t] = {
                        "label": DD_RISK_TOOLS[t],
                        "factor": f["风险因子"],
                        "count": f["条目数"],
                        **r,
                    }

    result = {"company": company, "reg": reg, "shareholders": shr, "risk": {"scan": scan, "details": details}}
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
    """调公司工具：共享缓存优先（同一企业 24h 内只实查一次）"""
    hit = _tool_cache_get(tool, company)
    if hit is not None:
        return hit
    r = await mcp.call(client, tool, {"searchKey": company})
    _tool_cache_set(tool, company, r)
    return r


async def _call_risk_tool(client: httpx.AsyncClient, mcp: McpClient, tool: str, company: str) -> dict:
    """调风险工具：共享缓存优先"""
    hit = _tool_cache_get(tool, company)
    if hit is not None:
        return hit
    r = await mcp.call(client, tool, {"searchKey": company})
    _tool_cache_set(tool, company, r)
    return r


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
    mode: str = "full"  # full=全量(演示页) / eng=债权尽调 / clues=财产线索 / deep=深挖


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
                items.append({
                    "company": r.company,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "biz_count": sum(1 for v in biz.values() if v.get("ok")),
                    "risk_records": sum(1 for v in risk.get("details", {}).values() if v.get("ok")),
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
        # ① 债权尽调工作流：工商 + 涉案案号/简述（先扫后钻）
        try:
            result = await query_engine_summary(company)
            return {"ok": True, "cached": False, "data": result}
        except Exception as e:
            logger.exception("QCC dd query failed for %s", company)
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
    keys = [company, f"eng:{company}", f"clues:{company}", f"deep:{company}", f"neg:{company}"]
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
        result = await query_full(company)
        cache_set(company, result)
        return {"ok": True, "deleted": deleted, "cached": False, "data": result}
    except Exception as e:
        logger.exception("QCC refresh failed for %s", company)
        return {"ok": False, "error": str(e)}
