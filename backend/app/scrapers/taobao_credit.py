"""阿里资产（淘宝）债权信息抓取器（精选债权 + 捡漏数据源）

来源：
  1. 债权专区列表（主力，2026-09-02 起）：阿里 H5 网关 h5api.m.taobao.com 直连，
     mtop.taobao.datafront.invoke.auctionwalle + dfApiName=auctionwalle.datou.getPageModulesData，
     _m_h5_tk cookie + MD5 签名（参考 github.com/dayicorp/auction-mcp 的 ali_h5_client.py 签名算法），
     无需浏览器/登录，返回 schemeList 自带 auctionBenefits（本金/利息/抵押物）。
  2. 资产交易公告列表（SSR 渲染，httpx 直连）：zc-paimai.taobao.com/zc/notice_list.htm
     - item_biz_type=7 金融资产类公告：银行/AMC/信达等机构的债权转让、资产包处置公告 → 精选债权
     - item_biz_type=8 破产资产类公告：破产管理人处置（商铺/应收款/股权等） → 捡漏候选
        （用户规则：破产相关债权进『捡漏』版块；标题带（破）、详情出现『管理人』『破产管理人』）
规则：
  - 精选债权：债权类目 206067301，只留 进行中/即将开始；过滤破产相关（（破）/破产/管理人）
  - 捡漏：破产资产公告（zcBizTypes=8），只保留小额（默认 ≤100 万），适合个人投资者低价捡漏
  - 债权公告栏目（AMC/金融机构处置公告）暂不采集，等用户确定信息源
落地：feed_items（featured=精选债权 / bargain=捡漏），source=阿里资产，source_url=公告详情页。
"""
import hashlib
import json
import logging
import random
import re
import time
import urllib.parse

import httpx

from .text_extract import (  # noqa: F401  统一解析模块（必备技能库）
    normalize_money,
    fmt_yuan_to_cn as _fmt_yuan_to_cn,
    shorten_title,
    extract_debtor,
    classify_collateral as _classify_collateral,
)

logger = logging.getLogger(__name__)

NOTICE_URL = "https://zc-paimai.taobao.com/zc/notice_list.htm"
DETAIL_URL = "https://zc-paimai.taobao.com/zc/notice_detail.htm"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Referer": "https://zc-paimai.taobao.com/",
}
MAX_PAGES = 3  # 每次同步最多翻页数（每页约 20 条）

_ITEM_RE = re.compile(
    r'<h2><a href="([^"]+)"[^>]*title="([^"]+)">.*?</a></h2>\s*'
    r'<p class="item-desc">\s*<span>([^<]*)</span>',
    re.S,
)
_AUTHOR_RE = re.compile(
    r'zc_item\.htm\?user_id=\d+[^>]*title="([^"]+)">([^<]+)</a>.*?class="date">([\d-]+)',
    re.S,
)
_NEXT_RE = re.compile(r'notice_list\.htm\?[^"]*cursor=([\d.]+-\d+)')

# 标题→户数/金额 提取
_HOUSEHOLD_RE = re.compile(r'(\d+)\s*户')
_AMOUNT_RE = re.compile(r'([\d,]+\.?\d*)\s*(万|万元|亿|亿元)')
# 详情页起拍价
_START_PRICE_RE = re.compile(r'起拍价[：:]\s*([\d,]+\.?\d*)\s*(元|万元|万|亿元|亿)')

# 捡漏起拍价上限（元）——适合个人投资者的低价捡漏，排除几百几千万大债权
BARGAIN_MAX_PRICE = 1_000_000  # 100 万（可调）


def _fetch_page(biz_type: int, cursor: str | None = None) -> tuple[list[dict], str | None]:
    """抓一页公告列表，返回 (条目列表, 下一页 cursor 或 None)"""
    params = {"item_biz_type": biz_type}
    if cursor:
        params["cursor"] = cursor
    r = httpx.get(NOTICE_URL, params=params, headers=HEADERS, timeout=30, follow_redirects=True)
    r.raise_for_status()
    html = r.text
    items = []
    for m in _ITEM_RE.finditer(html):
        href = m.group(1).replace("&amp;", "&")
        items.append({
            "href": href,
            "title": m.group(2).strip(),
            "desc": m.group(3).strip(),
        })
    authors = _AUTHOR_RE.findall(html)
    for it, (author_title, author_name, date) in zip(items, authors):
        it["author"] = author_name.strip()
        it["date"] = date
    m = _NEXT_RE.search(html)
    next_cursor = m.group(1) if m else None
    return items, next_cursor


def _is_bankrupt_title(title: str) -> bool:
    """破产相关标题判定：含 （破）/(破)/破产/管理人"""
    return any(k in title for k in ("（破）", "(破)", "破产", "管理人"))


def _extract_start_price(href: str) -> int | None:
    """抓公告详情页提取起拍价（元）；失败返回 None"""
    try:
        r = httpx.get(href, headers=HEADERS, timeout=25, follow_redirects=True)
        r.raise_for_status()
        html = r.text
        m = _START_PRICE_RE.search(html)
        if not m:
            return None
        num = float(m.group(1).replace(",", ""))
        unit = m.group(2)
        if unit in ("万元", "万"):
            num *= 10_000
        elif unit in ("亿元", "亿"):
            num *= 100_000_000
        return int(num)
    except Exception as e:  # noqa: BLE001
        logger.debug("详情页起拍价提取失败 %s: %s", href[:90], e)
        return None


# 详情页补全：金额/抵押物关键词（金额优先真实本金类，起拍价仅兜底）
_AMOUNT_KEY_RE = re.compile(
    r'(代偿金额|债权总额|本息合计|债权本金|债权金额|本息|本金)\s*[：:为是]?\s*([\d,]+\.?\d*)\s*(亿元|万元|万|元)'
)
_START_PRICE_IN_DETAIL_RE = re.compile(r'(起拍价)\s*[：:]\s*([\d,]+\.?\d*)\s*(亿元|万元|万|元)')
_COLLATERAL_RE = re.compile(r'【?抵押物】?[^【\n]{0,60}')


def _fetch_detail_text(href: str) -> str:
    """抓公告详情页，返回清洗后的文本（去掉标签）；失败/验证页返回空（含多次重试）"""
    for attempt in range(3):
        try:
            r = httpx.get(href, headers=HEADERS, timeout=25, follow_redirects=True)
            r.raise_for_status()
            html = r.text
            text = re.sub(r'<script.*?</script>', ' ', html, flags=re.S)
            text = re.sub(r'<style.*?</style>', ' ', text, flags=re.S)
            text = re.sub(r'<[^>]+>', ' ', text)
            cleaned = re.sub(r'\s+', ' ', text)
            # 滑块/验证页判定（此类页面无公告正文；注意正常页导航也含"亲，请登录"，不能用）
            if any(k in cleaned for k in ("拖动滑块", "拖动下方滑块", "通过验证以确保", "nocaptcha", "安全验证")):
                logger.debug("详情页触发验证(第%d次) %s", attempt + 1, href[:90])
            elif cleaned.strip():
                return cleaned
        except Exception as e:  # noqa: BLE001
            logger.debug("详情页抓取失败(第%d次) %s: %s", attempt + 1, href[:90], e)
        if attempt < 2:
            __import__("time").sleep(1.5 * (attempt + 1))  # 递增等待，规避限流
    return ""


def _enrich_ali_detail(item: dict) -> dict:
    """抓公告详情页补全金额/抵押物（详情页公开可抓）。返回补全后的 item"""
    href = item.get("source_url") or ""
    if not href or href.startswith("https://susong"):
        return item  # susong 详情有滑块，跳过
    text = _fetch_detail_text(href)
    if not text:
        return item
    d = dict(item["detail"])
    # 金额：优先"代偿金额/债权总额/本息合计/本金"等，其次起拍价
    if not d.get("claim_total"):
        m = _AMOUNT_KEY_RE.search(text)
        if not m:
            m = _START_PRICE_IN_DETAIL_RE.search(text)
        if m:
            num = m.group(2).replace(",", "")
            unit = m.group(3)
            val = num + ("亿" if unit == "亿元" else "万" if unit in ("万元", "万") else "元")
            d["claim_total"] = val
    # 抵押物：提取"抵押物"上下文 → 大类
    if not d.get("collateral_type"):
        mc = _COLLATERAL_RE.search(text)
        scope = mc.group(0) if mc else text[:400]
        ctype = _classify_collateral(scope)
        if ctype:
            d["collateral_type"] = ctype
            d["collateral_desc"] = scope.strip()[:80]
    item["detail"] = d
    return item


def _map_item(it: dict, section: str, start_price: int | None = None) -> dict:
    """公告条目 → feed_items 结构"""
    title = it["title"]
    href = it["href"]
    if href.startswith("//"):
        href = "https:" + href
    desc = it.get("desc") or ""
    author = it.get("author") or ""
    # 地区：优先标题内【省市】标记，其次省级行政区白名单匹配机构名
    region = ""
    mb = re.search(r'【([\u4e00-\u9fa5]{2,6}?)】', title)
    if mb:
        region = mb.group(1)
    else:
        prov = re.findall(
            r'(北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|台湾|内蒙古|广西|西藏|宁夏|新疆)'
            r'(?:省|市|自治区)?',
            author,
        )
        if prov:
            region = prov[-1]
    # 户数 / 金额（标题内）
    households = ""
    mh = _HOUSEHOLD_RE.search(title)
    if mh:
        households = mh.group(1) + "户"
    amount = ""
    ma = _AMOUNT_RE.search(title)
    if ma:
        amount = ma.group(1) + ("万" if ma.group(2) in ("万", "万元") else "亿")
    # 起拍价展示
    listing_price = ""
    if start_price:
        if start_price >= 10_000:
            listing_price = f"{start_price / 10000:.1f}万"
        else:
            listing_price = f"{start_price:,}元"

    if section == "bargain":
        tags = ["破产捡漏", "阿里资产"]
        if listing_price:
            tags.append(f"起拍{listing_price}")
        summary = desc[:500] or title
        detail = {
            "region": region,
            "claim_total": amount or "",
            "households": households,
            "listing_price": listing_price,
            "current_price": listing_price,
            "assessment_price": "",
            "auction_status": "公告中",
            "transferor": author or "破产管理人",
            "notice_date": it.get("date") or "",
            "source_label": "阿里资产·破产专区",
            "source_url": href,
            "bargain_note": "破产处置资产，起拍价远低于市场价，适合个人投资者低价参与；请自行核实权属、占用、税费等风险。",
        }
    else:  # featured
        tags = ["债权转让", "阿里资产"]
        if households:
            tags.append(households)
        if author:
            tags.append(author[:20])
        summary = desc[:500] or title
        detail = {
            "region": region,
            "claim_total": amount,
            "households": households,
            "listing_price": "",
            "current_price": "",
            "assessment_price": "",
            "auction_status": "公告中",
            "transferor": author,
            "notice_date": it.get("date") or "",
            "source_label": "阿里资产",
            "source_url": href,
        }
    return {
        "title": title[:200],
        "summary": summary,
        "tags": tags,
        "source": "阿里资产",
        "source_url": href,
        "detail": detail,
    }


def fetch_taobao_credit_list(max_pages: int = MAX_PAGES) -> list[dict]:
    """阿里金融资产类公告 → 精选债权列表（过滤破产）"""
    out: list[dict] = []
    cursor: str | None = None
    for _ in range(max_pages):
        items, cursor = _fetch_page(7, cursor)
        for it in items:
            title = it["title"]
            if "债权" not in title and "不良" not in title:
                continue
            if _is_bankrupt_title(title):
                continue  # 破产相关 → 归捡漏（见 fetch_taobao_bargain_mtop）
            out.append(_enrich_ali_detail(_map_item(it, "featured")))
            __import__("time").sleep(2 + (id(it) % 3))  # 随机间隔 2-4s，规避详情页风控
        if not cursor:
            break
    return out


# ==================== 阿里 H5 网关直连（2026-09-02 主力数据源，替代 Playwright） ====================
# 参考 github.com/dayicorp/auction-mcp 的 ali_h5_client.py：移动 H5 网关 h5api.m.taobao.com，
# 签名=MD5(token & t & appKey & data)，token 取自 _m_h5_tk cookie 前 32 字符（普通 GET 即下发），
# 完全绕过 app 端 unifiedSign/wua/sgext anti-tamper，无需登录。
# 关键参数（PC 版 zichansearch 页面实测抓包）：
#   dfApiName=auctionwalle.datou.getPageModulesData
#   moduleIds="2004318340:items,2068791300:recommend"（:items 后缀才返回列表）
#   context["_b_2004318340:items"] = {"fcatV4Ids":[...], "page":"1", "userInfo":{}, "appendMap":{"sid":"随机数_毫秒"}}
#   返回 data.data.GQL_getPageModulesData["2004318340"].items.schemeList（带 auctionBenefits 本金/利息/抵押物）
H5_GATEWAY = "https://h5api.m.taobao.com"
H5_APPKEY = "12574478"
H5_MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
_H5_SCENE_CODE = "20210823QCG72BUD"
_H5_PAGE_ID = 1910955
_H5_MODULE_IDS = "2004318340:items,2068791300:recommend"
_H5_API = "mtop.taobao.datafront.invoke.auctionwalle"

# 债权类目（阿里资产列表筛选）：fcatV4Ids 编码
FCAT_CREDIT = "206067301"
# 拍卖状态：0 进行中 / 1 即将开始 / 2 已结束 / 4 中止 / 5 撤回
STATUS_ING = "0"
STATUS_UPCOMING = "1"
STATUS_END = "2"
# 资产类型 zcBizTypes：4 涉刑 / 6 诉讼 / 8 破产 / 10 自行处置
BIZ_BANKRUPT = "8"

_client_lock = __import__("threading").Lock()
_client_state: dict = {"token": None, "session": None}


def _h5_bootstrap() -> httpx.Client:
    """确保 _m_h5_tk cookie 就绪，返回共享 httpx.Client（线程安全）"""
    with _client_lock:
        if _client_state.get("session") is None or _client_state.get("token") is None:
            s = httpx.Client(headers={"User-Agent": H5_MOBILE_UA, "Accept": "application/json"},
                             follow_redirects=True, timeout=20)
            # 碰任意 mtop 端点即可让服务端下发 _m_h5_tk（即使返回 TOKEN_EMPTY）
            params = {
                "jsv": "2.7.5", "appKey": H5_APPKEY, "t": str(int(time.time() * 1000)),
                "sign": "0" * 32, "api": _H5_API, "v": "1.0",
                "type": "originaljson", "dataType": "json",
            }
            try:
                s.get(f"{H5_GATEWAY}/h5/{_H5_API}/1.0/", params=params)
            except Exception:  # noqa: BLE001
                pass
            tk = s.cookies.get("_m_h5_tk")
            if not tk or "_" not in tk:
                try:
                    s.get("https://sf.taobao.com/")
                except Exception:  # noqa: BLE001
                    pass
                tk = s.cookies.get("_m_h5_tk")
            if not tk or "_" not in tk:
                raise RuntimeError("阿里 H5 无法获取 _m_h5_tk cookie")
            _client_state["token"] = tk.split("_", 1)[0]
            _client_state["session"] = s
        return _client_state["session"]


def _h5_sign(t_ms: str, data_str: str) -> str:
    raw = f"{_client_state['token']}&{t_ms}&{H5_APPKEY}&{data_str}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _h5_call(data: dict, method: str = "POST") -> dict:
    """单次 mtop 调用；token 失效（TOKEN_EMPTY/EXPIRED/Sign Error）时清缓存重 bootstrap 重试一次"""
    s = _h5_bootstrap()
    data_str = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    t = str(int(time.time() * 1000))
    url = f"{H5_GATEWAY}/h5/{_H5_API}/1.0/"
    params = {
        "jsv": "2.6.1", "appKey": H5_APPKEY, "t": t, "sign": _h5_sign(t, data_str),
        "bxPageId": str(_H5_PAGE_ID), "api": _H5_API, "v": "1.0",
        "type": "originaljson", "dataType": "json",
        "requiredParams": "dfApiName,dfUniqueId",
    }
    try:
        if method == "POST":
            r = s.post(url, params=params, data={"data": data_str})
        else:
            params["data"] = data_str
            r = s.get(url, params=params)
        out = r.json()
    except Exception:  # noqa: BLE001 非 JSON（风控页/网关异常）
        return {"ret": ["LOCAL_NON_JSON"]}
    ret0 = ""
    try:
        ret0 = (out.get("ret") or [""])[0]
    except Exception:  # noqa: BLE001
        pass
    if any(m in ret0 for m in ("TOKEN_EMPTY", "TOKEN_EXPIRED", "ILLEGAL_ACCESS::Sign Error!", "ILLEGAL_REQUEST")):
        with _client_lock:
            _client_state["token"] = None
            _client_state["session"] = None
        try:
            s2 = _h5_bootstrap()
            data_str2 = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
            t2 = str(int(time.time() * 1000))
            params2 = dict(params, t=t2, sign=_h5_sign(t2, data_str2))
            if method == "POST":
                r2 = s2.post(url, params=params2, data={"data": data_str2})
            else:
                params2["data"] = data_str2
                r2 = s2.get(url, params=params2)
            out = r2.json()
        except Exception:  # noqa: BLE001
            pass
    return out


def _h5_list_items(fcat: str = FCAT_CREDIT, page: int = 1,
                   status_orders: list[str] | None = None,
                   zc_biz_types: list[str] | None = None) -> list[dict]:
    """阿里债权专区列表直连 → schemeList 条目列表（字段同 Playwright 版，含 auctionBenefits）"""
    ts = str(int(time.time() * 1000))
    sid = f"{random.randint(10**9, 10**10 - 1)}_{ts}"
    flt: dict = {"fcatV4Ids": [fcat], "page": str(page), "userInfo": {}}
    if status_orders:
        flt["statusOrders"] = status_orders
    if zc_biz_types:
        flt["zcBizTypes"] = zc_biz_types
    flt["appendMap"] = {"sid": sid}
    df_vars = {
        "pageId": _H5_PAGE_ID,
        "moduleIds": _H5_MODULE_IDS,
        "context": {
            f"_b_2004318340:items": json.dumps(flt, separators=(",", ":"), ensure_ascii=False),
            "userInfo": "{}",
            "device": "pc",
            "sceneCode": _H5_SCENE_CODE,
            "appendMap": json.dumps({"isAutoSelect": True}),
        },
    }
    data = {
        "dfApp": "auctionwalle",
        "dfApiName": "auctionwalle.datou.getPageModulesData",
        "dfVariables": json.dumps(df_vars, separators=(",", ":"), ensure_ascii=False),
        "dfUniqueId": f"{_H5_PAGE_ID}.{_H5_MODULE_IDS}",
        "dfVariablesRecover": "{}",
    }
    out = _h5_call(data)
    mods = ((out.get("data") or {}).get("data") or {}).get("GQL_getPageModulesData") or {}
    ib = mods.get("2004318340", {}).get("items", {})
    return ib.get("schemeList") or []


def _h5_fetch(fcat: str, max_pages: int = 1,
              status_orders: list[str] | None = None,
              zc_biz_types: list[str] | None = None) -> list[dict]:
    """H5 直连翻页抓取，返回合并后的 schemeList 条目（去重）"""
    out: list[dict] = []
    seen_ids: set = set()
    for page in range(1, max_pages + 1):
        try:
            sl = _h5_list_items(fcat, page, status_orders, zc_biz_types)
        except Exception as e:  # noqa: BLE001
            logger.warning("阿里 H5 直连第%d页失败: %s", page, e)
            break
        if not sl:
            break
        added = 0
        for s in sl:
            iid = s.get("itemId")
            if iid in seen_ids:
                continue
            seen_ids.add(iid)
            out.append(s)
            added += 1
        logger.debug("阿里 H5 直连第%d页: %d 条(新增 %d)", page, len(sl), added)
        if len(sl) < 40 or added == 0:
            break
    return out


def _apply_list_extra(s: dict, detail: dict) -> None:
    """列表接口附加字段最大化填充（2026-09-02，H5 直连后列表字段很全，能填的都填上）：
    精确本金 crPrincipal(元)/抵押物分类 crCoCat/折扣率 tagArray/拍卖时间/围观·出价·订阅热度"""
    from .text_extract import normalize_money as _nm, classify_collateral as _cc
    em = s.get("auctionExtraMap") or {}
    # 1) 精确本金：crPrincipal 单位=元（如 199592.05=19.96万），比 auctionBenefits 展示值更精确，存在即覆盖
    crp = em.get("crPrincipal")
    if isinstance(crp, (int, float)) and crp > 0:
        detail["claim_total"] = _nm(f"{crp}元")
    # 2) 抵押物分类：crCoCat（如"房产"）
    ccat = em.get("crCoCat")
    if ccat and not detail.get("collateral_type"):
        detail["collateral_type"] = _cc(str(ccat)) or str(ccat)[:20]
    # 3) 折扣率：tagArray 中 alias 含"折"（如"本息5.1折"=债权起拍价对比本息总额的折扣）
    for tag in (s.get("tagArray") or []):
        alias = str(tag.get("alias") or "")
        if "折" in alias and not detail.get("discount"):
            detail["discount"] = alias
    # 4) 拍卖时间：timeCentre+timeSuffix（如"09月08日10:00开始"）
    tc = s.get("timeCentre") or ""
    if tc and not detail.get("auction_time"):
        detail["auction_time"] = f"{tc}{s.get('timeSuffix') or ''}"
    # 5) 热度：围观 pv / 出价 bidCnt / 订阅 subscribeCnt
    if not detail.get("watch_count"):
        detail["watch_count"] = s.get("pv") or 0
    if not detail.get("bid_count"):
        detail["bid_count"] = s.get("bidCnt") or 0
    if not detail.get("subscribe_count"):
        detail["subscribe_count"] = s.get("subscribeCnt") or 0


# ==================== 阿里破产专区（Playwright 渲染 + mtop 拦截，兜底） ====================
# 专区地址（用户指定）：zichansearch?fcatV4Ids=["206067301"]&zcBizTypes=["8"]
# 页面 JS 渲染后调用 mtop.taobao.datafront.invoke.auctionwalle 返回 items（schemeList）。
# 2026-09-02 起 H5 网关直连（见上方 _h5_fetch）已可复现该接口，Playwright 仅作直连失败时的兜底。
_MT_API_MARK = "mtop.taobao.datafront.invoke.auctionwalle"


def _mt_items_to_entry(s: dict) -> dict | None:
    """阿里破产专区 schemeList 条目 → feed_items 结构（破产捡漏）

    2026-09-02 规范统一：复用精选解析（_mt_items_to_featured allow_bankrupt=True）——
    benefits 本金/利息/抵押物、精确本金 crPrincipal、折扣、时间、热度、摘要自然化，
    与精选债权同一内容规范；仅破产过滤保留、来源标签与价格上限不同。
    """
    title = s.get("auctionTitle") or ""
    if not title:
        return None
    # 破产相关判定（捡漏只收破产）
    shop = s.get("shopName") or ""
    if not (any(k in title for k in ("（破）", "(破)", "破产", "管理人")) or "管理人" in shop):
        return None
    e = _mt_items_to_featured(s, allow_bankrupt=True)
    if not e:
        return None
    price = (e.get("detail") or {}).get("_price_yuan") or 0
    if price <= 0 or price > BARGAIN_MAX_PRICE:
        return None  # 排除大额
    d = e["detail"]
    d.pop("_price_yuan", None)
    d["source_label"] = "阿里资产·破产专区"
    d["bargain_note"] = "破产处置资产，起拍价远低于市场价，适合个人投资者低价参与；请自行核实权属、占用、税费等风险。"
    tags = ["破产捡漏", "阿里资产"]
    if d.get("listing_price"):
        tags.append(f"起拍{d['listing_price']}")
    region = d.get("region") or ""
    summary = f"{region}·{d.get('auction_status') or ''}·起拍{d.get('listing_price') or ''} 破产处置，低价捡漏。" if region \
        else f"{d.get('auction_status') or ''}·起拍{d.get('listing_price') or ''} 破产处置，低价捡漏。"
    return {
        "title": title[:200],
        "summary": summary,
        "tags": tags,
        "source": "阿里资产",
        "source_url": e["source_url"],
        "detail": d,
    }


# ==================== 阿里破产专区（Playwright 渲染 + mtop 拦截） ====================
# 专区地址（用户指定）：zichansearch?fcatV4Ids=["206067301"]&zcBizTypes=["8"]
# 页面 JS 渲染后调用 mtop.taobao.datafront.invoke.auctionwalle 返回 items（schemeList）。
# 实测 httpx 直接复现参数不生效（返回综合推荐），必须 Playwright 渲染页面并拦截响应。
_POCHAN_URL = ("https://zc-paimai.taobao.com/wow/pm/default/pc/zichansearch?"
               "fcatV4Ids=%5B%22206067301%22%5D&zcBizTypes=%5B%228%22%5D&page=1")
# 阿里资产-债权专区（确定信息源，2026-08-30）：债权类目 206067301，不带破产筛选
_ZQ_URL = ("https://zc-paimai.taobao.com/wow/pm/default/pc/zichansearch?"
           "fcatV4Ids=%5B%22206067301%22%5D&page=1")
_MT_API_MARK = "mtop.taobao.datafront.invoke.auctionwalle"


def _render_zichansearch(url: str) -> list[list[dict]]:
    """Playwright 渲染 zichansearch 页并拦截 auctionwalle 响应，返回所有 schemeList"""
    from playwright.sync_api import sync_playwright
    from .browser import launch_chromium

    scheme_lists: list[list[dict]] = []
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p, headless=True)
            page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
            def on_response(resp):
                if _MT_API_MARK in resp.url:
                    try:
                        j = resp.json()
                        mods = j.get("data", {}).get("data", {}).get("GQL_getPageModulesData", {})
                        ib = mods.get("2004318340", {}).get("items", {})
                        sl = ib.get("schemeList")
                        if sl:
                            scheme_lists.append(sl)
                    except Exception:  # noqa: BLE001
                        pass
            page.on("response", on_response)
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(5000)
            except Exception as e:  # noqa: BLE001
                logger.warning("阿里专区渲染失败 %s: %s", url[:80], e)
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001
        logger.exception("Playwright 启动失败: %s", e)
    return scheme_lists


def fetch_taobao_bargain_mtop(max_pages: int = 2) -> list[dict]:
    """阿里破产专区（H5 直连，失败降级 Playwright）→ 捡漏列表：破产债权 + 小额"""
    out: list[dict] = []
    seen_urls: set[str] = set()
    items: list[dict] = []
    try:
        items = _h5_fetch(FCAT_CREDIT, max_pages=max_pages, zc_biz_types=[BIZ_BANKRUPT])
    except Exception as e:  # noqa: BLE001
        logger.warning("阿里 H5 直连失败，降级 Playwright 破产专区: %s", e)
    if not items:
        for sl in _render_zichansearch(_POCHAN_URL):
            items.extend(sl)
    for s in items:
        e = _mt_items_to_entry(s)
        if not e:
            continue
        url = e["source_url"]
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        out.append(e)
        if len(out) >= 40:
            break
    return out


def _mt_items_to_featured(s: dict, allow_bankrupt: bool = False) -> dict | None:
    """阿里债权专区 schemeList 条目 → feed_items 结构（精选债权）。

    2026-09-02：allow_bankrupt=True 供捡漏复用（破产处置资产也走同一解析规范——
    benefits 本金/利息/抵押物、折扣、时间、热度、摘要自然化），仅破产过滤与来源标签不同。
    """
    title = s.get("auctionTitle") or ""
    if not title:
        return None
    # 只留 进行中/即将开始；已结束排除
    status_key = s.get("status") or ""
    if status_key not in ("ing", "before", "upcoming"):
        return None
    status = {"ing": "进行中", "before": "即将开始", "upcoming": "即将开始"}.get(status_key, "—")
    # 破产相关 → 归捡漏（精选过滤；捡漏 allow_bankrupt=True 保留）
    if any(k in title for k in ("（破）", "(破)", "破产", "管理人")) and not allow_bankrupt:
        return None
    shop = s.get("shopName") or ""
    # 起拍价 → 元
    price_int = 0
    try:
        price = float(s.get("displayInitialPrice") or s.get("price") or 0)
        unit = s.get("displayInitialPriceUnit") or s.get("priceUnit") or "元"
        if unit in ("万", "万元"):
            price *= 10_000
        elif unit in ("亿", "亿元"):
            price *= 100_000_000
        price_int = int(price)
    except (TypeError, ValueError):
        pass
    listing_price = ""
    if price_int > 0:
        listing_price = _fmt_yuan_to_cn(price_int)
    link = s.get("auctionLink") or ""
    if link.startswith("//"):
        link = "https:" + link
    # benefits 字段（2026-09-01 关键发现）：阿里列表接口自带结构化信息！
    # 例：['抵押物:房产', '本金:1026.86万元', '利息:8406.27万元'] / ['本金:1亿元'] / ['抵押物:房产，土地等']
    benefits = s.get("auctionBenefits") or []
    # 从 benefits 提取 本金/利息/抵押物（比标题提取更准，权威优先）
    b_principal = ""
    b_interest = ""
    b_collateral = ""
    region = ""
    for b in benefits:
        b = str(b).strip()
        if not b:
            continue
        # 本金:XX 万元/亿元
        m = re.match(r'^本金[：:]\s*(.+)$', b)
        if m:
            b_principal = normalize_money(m.group(1))
            continue
        m = re.match(r'^利息[：:]\s*(.+)$', b)
        if m:
            b_interest = normalize_money(m.group(1))
            continue
        m = re.match(r'^抵押物[：:]\s*(.+)$', b)
        if m:
            b_collateral = m.group(1).strip()
            continue
        # 纯地区词（如"青岛市"）
        if re.match(r'^[\u4e00-\u9fa5]{2,8}(?:省|市|区|县)$', b):
            region = b
    # 地区兜底：从标题提取（如"青岛市黄岛区房抵债权转让"→青岛市黄岛区，2026-09-01）
    if not region:
        m = re.search(r'([\u4e00-\u9fa5]{2,3}省)?([\u4e00-\u9fa5]{2,10}市)([\u4e00-\u9fa5]{2,10}(?:区|县))?', title)
        if m:
            region = "".join(g for g in m.groups() if g)
    # 本金：benefits 权威优先，标题兜底（2026-09-01）
    amount = b_principal or ""
    if not amount:
        ma = re.search(r'([\d,]+\.?\d*)\s*(亿元|万元|亿|万|元)', title)
        if ma:
            amount = normalize_money(ma.group(0))
        else:
            mb = re.search(r'([\d,]+\.?\d*)\s*元', title)
            if mb:
                amount = normalize_money(f"{mb.group(1)}元")
            else:
                mc = re.search(r'([\d,]{4,}\.?\d*)', title)  # 大额裸数字（如 1,776,333.5 债权）
                if mc:
                    amount = normalize_money(f"{mc.group(1)}元")
    # 抵押物：benefits 权威优先（"抵押物:房产"），标题线索兜底（2026-09-01）
    from .text_extract import classify_collateral as _cc
    collateral_type = ""
    if b_collateral:
        collateral_type = _cc(b_collateral) or (b_collateral[:20] if len(b_collateral) <= 20 else "")
        # 描述：保留原始（如"房产，土地等"）
        collateral_desc = b_collateral[:100]
    else:
        collateral_desc = ""
        coll_text = title
        if re.search(r'有土地线索|名下有土地|土地线索|查封.*土地', coll_text):
            collateral_type = "土地厂房"
        elif re.search(r'房抵|房产抵押|房屋抵押|小区|花苑|府邸|社区', coll_text):
            collateral_type = "住宅房产"
        elif re.search(r'厂房|工业|仓储|仓库', coll_text):
            collateral_type = "土地厂房"
        else:
            cm = re.search(r'抵押[^，。；,;]{0,30}', coll_text)
            if cm:
                collateral_type = _cc(cm.group(0))
    # 精简标题 + 债务人（卡片/列表展示用，完整标题在详情页）
    short_title = shorten_title(title)
    debtor = extract_debtor(title)
    # 2026-09-02：破产标题（"（破）XXX的对外债权"）extract_debtor 提取不到 → 直接取括号后的主体
    #（圈1 债务主体，如 466 "（破）安徽南方煤矿机械有限公司的对外债权转让"→安徽南方煤矿机械有限公司）
    if not debtor and ("（破）" in title or "(破)" in title or "（破产）" in title or "(破产)" in title):
        mb = re.search(r'[（(]?(?:破|破产)[)）]\s*([\u4e00-\u9fa5A-Za-z0-9*·]{2,18}?(?:公司|集团|银行|厂|店|学校|医院|事务所))', title)
        if mb:
            debtor = mb.group(1)
    detail = {
        "region": region,
        "claim_total": amount,
        "interest": b_interest or "",   # benefits 利息（2026-09-01）
        "households": "",
        "listing_price": listing_price,
        "current_price": listing_price,
        "assessment_price": "",
        "auction_status": status,
        "transferor": shop,
        "notice_date": "",
        "source_label": "阿里资产·债权专区",
        "source_url": link,
        "_price_yuan": price_int,  # 内部字段：起拍价（元），供自动分类（归捡漏）后删除
        "short_title": short_title,
        "debtor_name": debtor,
        "collateral_type": collateral_type,
        "collateral_desc": collateral_desc,
    }
    _apply_list_extra(s, detail)  # 2026-09-02：精确本金/折扣/时间/热度最大化填充
    tags = ["债权转让", "阿里资产"]
    if region:
        tags.append(region)
    # 摘要自然化：债务人 + 本金 + 利息 + 抵押物 + 折扣 + 转让方 + 状态（2026-09-02 加折扣）
    parts = []
    if debtor:
        parts.append(f"债务人 {debtor}")
    if amount:
        parts.append(f"本金 {amount}")
    if b_interest:
        parts.append(f"利息 {b_interest}")
    if collateral_type:
        parts.append(f"抵押物 {collateral_type}")
    if detail.get("discount"):
        parts.append(f"折扣 {detail['discount']}")
    if listing_price:
        parts.append(f"起拍 {listing_price}")
    if shop:
        parts.append(f"转让方 {shop}")
    parts.append(f"当前{status}")
    summary = "，".join(parts) + "。"
    return {
        "title": title[:200],
        "summary": summary,
        "tags": tags,
        "source": "阿里资产",
        "source_url": link,
        "detail": detail,
    }


def fetch_taobao_credit_mtop(max_pages: int = 2) -> list[dict]:
    """阿里资产-债权专区（H5 直连，失败降级 Playwright）→ 精选债权列表（进行中/即将开始，滤破产）"""
    out: list[dict] = []
    seen_urls: set[str] = set()
    items: list[dict] = []
    try:
        items = _h5_fetch(FCAT_CREDIT, max_pages=max_pages,
                          status_orders=[STATUS_ING, STATUS_UPCOMING])
    except Exception as e:  # noqa: BLE001
        logger.warning("阿里 H5 直连失败，降级 Playwright 债权专区: %s", e)
    if not items:
        for sl in _render_zichansearch(_ZQ_URL):
            items.extend(sl)
    for s in items:
        e = _mt_items_to_featured(s)
        if not e:
            continue
        url = e["source_url"]
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        out.append(e)
        if len(out) >= 40:
            break
    return out


def _upsert_feed(db, item: dict, section: str) -> None:
    """写入 feed_items：按 (section, title, source_url) 去重；已存在则刷新摘要/标签/详情。
    详情合并：新 detail 的空字段保留库内旧值（避免抓取失败清空已有本金/抵押物）"""
    from sqlalchemy import select
    from ..models import FeedItem

    existing = db.scalar(
        select(FeedItem).where(
            FeedItem.section == section,
            FeedItem.title == item["title"],
            FeedItem.source_url == (item.get("source_url") or ""),
        )
    )
    new_detail_raw = json.dumps(item.get("detail") or {}, ensure_ascii=False)
    if existing:
        new_d = json.loads(new_detail_raw)
        old_d = json.loads(existing.detail_json) if existing.detail_json else {}
        merged = {**old_d, **{k: v for k, v in new_d.items() if v}}  # 非空覆盖，空值保留旧
        new_detail = json.dumps(merged, ensure_ascii=False)
        if existing.detail_json != new_detail or existing.summary != item.get("summary"):
            existing.summary = item.get("summary")
            existing.tags = json.dumps(item.get("tags") or [], ensure_ascii=False)
            existing.detail_json = new_detail
        return
    db.add(FeedItem(
        section=section,
        title=item["title"],
        summary=item.get("summary"),
        tags=json.dumps(item.get("tags") or [], ensure_ascii=False),
        source=item.get("source"),
        source_url=item.get("source_url"),
        detail_json=new_detail_raw,
        is_active=1,
    ))


def sync_taobao_credit_to_feed() -> dict:
    """主入口：阿里资产-债权专区 → 精选债权 + 破产专区小额 → 捡漏。返回统计。"""
    from ..database import SessionLocal
    from ..models import FeedItem

    featured: list[dict] = []
    bargain: list[dict] = []
    try:
        featured_raw = fetch_taobao_credit_mtop()  # 债权专区（确定信息源）
        # 2026-09-05 用户确认（B）：捡漏只保留京东来源；阿里捡漏整类放弃——
        # 阿里破产专区多为"一句话/打码"条目（详情无正文），宁缺毋滥，不再抓取
        # bargain = fetch_taobao_bargain_mtop()  # 已停用
    except Exception as e:  # noqa: BLE001
        logger.exception("阿里资产同步失败: %s", e)
        featured_raw = []
    # 自动分类：起拍价 < 10000 元的极低标的自动归捡漏（用户规则 2026-08-31）
    # 2026-09-05 停用降级：捡漏只要京东，阿里低价条目不再降级（信息普遍不全，直接按精选门槛过滤）
    featured: list[dict] = []
    for it in featured_raw:
        d = it["detail"]
        d.pop("_price_yuan", None)
        featured.append(it)

    db = SessionLocal()
    dropped = 0
    try:
        from .quality import is_complete
        for it in featured:
            if not is_complete(it, section="featured"):
                dropped += 1
                continue
            _upsert_feed(db, it, section="featured")
        for it in bargain:
            if not is_complete(it, section="bargain"):
                dropped += 1
                continue
            _upsert_feed(db, it, section="bargain")
        db.commit()
        feat_total = db.query(FeedItem).filter(FeedItem.section == "featured").count()
        bargain_total = db.query(FeedItem).filter(FeedItem.section == "bargain").count()
    finally:
        db.close()
    logger.info("阿里资产同步完成: 精选 %d 条, 捡漏 %d 条, 因信息不全放弃 %d 条", len(featured), len(bargain), dropped)
    return {"fetched_featured": len(featured), "fetched_bargain": len(bargain),
            "dropped_incomplete": dropped,
            "featured_total": feat_total, "bargain_total": bargain_total}
