"""京东债权招商抓取器（精选债权数据源）

来源：京东拍卖 pmsearch.jd.com 债权/金融资产类目
接口：api.m.jd.com/api?appid=paimai&functionId=paimai_unifiedSearch
      labelSet=1033(金融资产) + publishSourceStr=['0','9'] + childrenCateId=109(债权)
策略：Playwright(系统Chrome) 预热一次拿 cookie → httpx 带 cookie 直连接口（h5st 可省略）
      实测：cookie 足够通过风控，无需每次启动浏览器
落地：写入 feed_items（section='featured' 精选债权），source=京东拍卖，source_url=标的详情页，
      detail 按京东字段映射（价格/地区/状态/来源/评估价）。
注意：低频抓取、遵守站点协议；仅供信息聚合与展示，交易仍跳转源页面。
"""
import json
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

JD_SEARCH_PARAMS = {
    "investmentType": "", "apiType": 12, "page": 1, "pageSize": 40, "keyword": "",
    "provinceId": "", "cityId": "", "countyId": "",
    "multiPaimaiStatus": "", "multiDisplayStatus": "", "multiPaimaiTimes": "",
    "childrenCateId": "109",  # 债权类目
    "currentPriceRangeStart": "", "currentPriceRangeEnd": "",
    "timeRangeTime": "endTime", "timeRangeStart": "", "timeRangeEnd": "",
    "loan": "", "purchaseRestriction": "", "liupaiBuyAgain": "",
    "orgId": "", "orgType": "", "sortField": 8, "projectType": 1, "reqSource": 0,
    "labelSet": "1033",  # 金融资产
    "publishSource": "", "publishSourceStr": ["0", "9"], "defaultLabelSet": "",
}

WARM_URL = "https://pmsearch.jd.com/?publishSource=9&childrenCateId=12767"
API_URL = "https://api.m.jd.com/api"

# 模块级 cookie 缓存（进程内；过期后重新预热）
_cookie_cache: str = ""


def _warm_cookie() -> str:
    """Playwright(系统Chrome) 访问京东页拿 cookie"""
    global _cookie_cache
    if _cookie_cache:
        return _cookie_cache
    from playwright.sync_api import sync_playwright
    from .browser import launch_chromium
    with sync_playwright() as p:
        browser = launch_chromium(p, headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            page.goto(WARM_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)
            cookies = ctx.cookies("https://api.m.jd.com")
            _cookie_cache = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        finally:
            browser.close()
    return _cookie_cache


def fetch_jd_claim_amount(paimai_id: str | int) -> int | None:
    """调京东详情接口 getProductBasicInfo，返回债权本金（元，extendInfoMap.claimsMoney）；失败返回 None"""
    import httpx
    from urllib.parse import quote

    cookie = _warm_cookie()
    if not cookie:
        return None
    url = (
        f"{API_URL}?appid=paimai&functionId=getProductBasicInfo&t={int(datetime.now().timestamp() * 1000)}&body="
        + quote(json.dumps({"paimaiId": int(paimai_id), "ismobile": False}))
    )
    try:
        r = httpx.get(url, headers={"Referer": f"https://paimai.jd.com/{paimai_id}", "Cookie": cookie,
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}, timeout=20)
        j = r.json()
        if j.get("code") != 0:
            return None
        data = j.get("data") or {}
        em = data.get("extendInfoMap")
        if isinstance(em, str):
            try:
                em = json.loads(em)
            except (TypeError, ValueError):
                em = None
        claims = (em or {}).get("claimsMoney") if isinstance(em, dict) else None
        if claims is None:
            return None
        try:
            return int(float(claims))
        except (TypeError, ValueError):
            return None
    except Exception as e:  # noqa: BLE001
        logger.debug("京东详情接口失败 %s: %s", paimai_id, e)
        return None


def fetch_jd_detail_money(paimai_id: str | int) -> dict:
    """调京东公告接口 queryProductDescription，解析竞买公告表格 → {principal_wan, interest_wan, penalty_wan, other_fees_wan, total_wan, debtors, collateral, guaranty, raw_text}

    - 金额单位万元；debtors=债务人名单；collateral=抵押物描述（表格"抵押情况"列优先）
    - raw_text=公告清洗文本（剔除表格块，表格已自建 announce_table）
    - 修复（2026-09-01 用户反馈）：此前要求 row[0].isdigit() 导致含"项目"列名的
      金额表整表被跳过，利息/费用/抵押物从未提取；现按表头定位列、不依赖首列类型，
      并优先取"合计"行（整包汇总），无合计则对多行数值求和。
    """
    import httpx
    from urllib.parse import quote
    from .text_extract import normalize_money

    cookie = _warm_cookie()
    if not cookie:
        return {}
    url = (
        f"{API_URL}?appid=paimai&functionId=queryProductDescription&loginType=3&t={int(datetime.now().timestamp() * 1000)}&body="
        + quote(json.dumps({"paimaiId": int(paimai_id)}))
    )
    try:
        r = httpx.get(url, headers={"Referer": f"https://paimai.jd.com/{paimai_id}", "Cookie": cookie,
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}, timeout=20)
        j = r.json()
        html = j.get("data") or ""
        if not html or not isinstance(html, str):
            return {}
        result: dict = {}
        # 公告清洗文本（供"招商信息原文"文字部分）：剔除表格块（表格已自建为 announce_table），只保留表格外文字介绍
        text = re.sub(r'<table.*?</table>', '\n', html, flags=re.S)
        text = re.sub(r'<style.*?</style>', ' ', text, flags=re.S)
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.I)
        text = re.sub(r'</p>|</tr>|</div>', '\n', text, flags=re.I)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'[ \t\u3000]+', ' ', text)
        text = re.sub(r'\n\s*\n+', '\n', text).strip()
        result["raw_text"] = text[:8000]
        # 自建表格：解析 HTML 表格 → {headers, rows}（供详情页用 AntD Table 渲染，可读且与原文一致）
        tables = re.findall(r'<table.*?</table>', html, re.S)
        for t in tables:
            trs = re.findall(r'<tr.*?</tr>', t, re.S)
            if not trs:
                continue
            def _cells(row_html):
                return [re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.S)]
            headers = _cells(trs[0])
            rows = [_cells(r) for r in trs[1:] if _cells(r) and any(_cells(r))]
            rows = [r for r in rows if any(c for c in r)]  # 去全空行
            if headers:
                result["announce_table"] = {"headers": headers, "rows": rows}
            # 金额列定位：按表头关键词（不再要求首列为数字——首列常是"项目/债务人"名）
            def _col_index(*keys):
                for i, h in enumerate(headers):
                    if any(k in h for k in keys):
                        return i
                return None
            p_i = _col_index("贷款本金余额", "本金余额", "本金")
            i_i = _col_index("利息余额", "欠息", "利息")      # 利息（排除罚息列）
            penalty_i = _col_index("罚息")
            fee_i = _col_index("代垫费用", "垫付费用", "其他费用", "律师费", "诉讼费", "费用")
            total_i = _col_index("本息及费用合计", "本息费用合计", "本息合计", "合计", "债权总额")
            coll_i = _col_index("抵押情况", "抵押物", "担保物", "抵质押", "担保情况", "担保详情", "担保措施", "押品地址", "押品")
            guar_i = _col_index("保证情况", "保证人", "担保人", "担保详情")
            # 2026-09-02：担保方式/司法状态 列（如"担保方式:抵押+保证"、"诉讼状况:执行终本"）
            gtype_i = _col_index("担保方式", "担保类型")
            jud_i = _col_index("诉讼状况", "诉讼状态", "涉诉情况", "司法状态", "执行状态", "案件状态", "诉讼及执行情况")
            debtor_i = _col_index("项目", "债务人", "借款企业", "借款人", "单位名称", "企业名称")

            # 列单位推断（2026-09-01 修复：表格单元格单位不统一，须按表头判断）
            # 表头含"（元）/单位：元" → 元；含"万元" → 万；无单位按值量级猜测（≥1万视为元，否则视为万）
            def _col_unit(idx):
                if idx is None:
                    return None
                h = headers[idx]
                if "万元" in h or "（万）" in h:
                    return "万"
                if "元" in h and "万元" not in h:
                    return "元"
                return None  # 未知，按值量级

            # 数值提取：逐列对数值行求和（跳过含"合计"的行）。
            # 2026-09-01 修复：合计行常因合并单元格（如"合计"跨列）导致列错位，
            # 取合计行值会张冠李戴（把"其他债权"当"利息"）；逐列求和不受错位影响，
            # 且与合计行结果一致（已对多个整包表格验证）。
            def _num(v):
                try:
                    return _to_float(v)
                except (TypeError, ValueError):
                    return None

            def _is_summary_row(row) -> bool:
                """合计/总计/小计 行（表头文字可能含空格，如"合 计"）。
                2026-09-02 修复：只查前2列——之前查前3列会把"担保情况"描述里的
                "…房产合计25,661.01平方米"（第3列）误判为合计行（448 案例）。"""
                if not row:
                    return False
                for c in row[:2]:
                    if not c:
                        continue
                    s = str(c).replace(" ", "").replace("\u3000", "")
                    if any(k in s for k in ("合计", "总计", "小计")):
                        return True
                return False

            def _pick(idx):
                if idx is None:
                    return None
                total = 0.0
                hit = False
                for row in rows:
                    if _is_summary_row(row):
                        continue
                    v = _num(row[idx]) if len(row) > idx else None
                    if v is not None:
                        total += v
                        hit = True
                return total if hit else None

            def _pick_total(idx):
                """整包合计列（债权合计/本息合计）取值：合计行的值优先（官方整包汇总）。
                2026-09-02 修复 448：3户资产包的合计行常因合并单元格**列错位**（行列数 < 表头列数，
                如 ['合计', 本金, 利息, 费用, 总额] 5列 vs 表头7列），取 r[idx] 会错位。
                正确做法：合计行的**最后一个数字**即整包总额（汇总列在最右）。
                合计行无值/为0才逐列求和。"""
                if idx is None:
                    return None
                for row in rows:
                    if not _is_summary_row(row):
                        continue
                    last = None
                    for cell in row:
                        nv = _num(cell)
                        if nv is not None:
                            last = nv
                    if last is not None and last > 0:
                        return last
                return _pick(idx)

            # 全表最大数值（用于无单位列的量级推断；跳过合计/总计行）
            _all_max = 0.0
            for row in rows:
                if row and any(k in (c or "") for c in row[:3] for k in ("合计", "总计", "小计")):
                    continue
                for cell in row:
                    nv = _num(cell)
                    if nv is not None and nv > _all_max:
                        _all_max = nv

            def _pick_std_fmt(v, idx):
                """数值+单位 → 标准金额字符串（处理单位）"""
                if v is None:
                    return None
                unit = _col_unit(idx)
                if unit is None:
                    # 无单位按全表数量级猜：全表最大值 <10万 → 万元表；否则 → 元表
                    # （同表各列单位一致，2026-09-01 修正：用全表极值而非单列）
                    unit = "万" if _all_max < 100_000 else "元"
                return normalize_money(f"{v}{unit}")

            for label, idx, key in (
                ("principal", p_i, "principal_std"),
                ("interest", i_i, "interest_std"),
                ("penalty", penalty_i, "penalty_std"),
                ("fee", fee_i, "other_fees_std"),
                ("total", total_i, "total_std"),
            ):
                # 2026-09-02：债权合计列优先取合计行（整包汇总，见 _pick_total）；其余列逐列求和
                v = _pick_total(idx) if label == "total" else _pick(idx)
                s = _pick_std_fmt(v, idx)
                if s:
                    result[key] = s

            # 债务人名单（"项目"列，跳过合计行）
            if debtor_i is not None:
                names = []
                for row in rows:
                    if not row or any("合计" in (c or "") for c in row[:3]):
                        continue
                    if len(row) > debtor_i and row[debtor_i]:
                        names.append(row[debtor_i].strip())
                if names:
                    result["debtors"] = names[:50]

            # 抵押物/保证人（"抵押情况/押品地址/保证情况"列，跳过合计/子表头行）
            for col_idx, key in ((coll_i, "collateral"), (guar_i, "guaranty")):
                if col_idx is None:
                    continue
                parts = []
                for row in rows:
                    if not row:
                        continue
                    first = str(row[0]).strip().replace(" ", "").replace("\u3000", "")
                    # 跳过 合计/总计/小计 行 与 子表头行（如 ['本金余额','利息','小计']）
                    if first in ("合计", "总计", "小计"):
                        continue
                    if _is_summary_row(row):
                        continue
                    if len(row) > col_idx and row[col_idx] and row[col_idx] not in ("—", "-", "无"):
                        parts.append(row[col_idx].strip())
                if parts:
                    result[key] = "；".join(parts)[:2000]

            # 2026-09-02：担保方式/司法状态（取首个非"无/-/—"值，多为"抵押+保证"/"执行终本"）
            for col_idx, key in ((gtype_i, "guaranty_type"), (jud_i, "judicial_status")):
                if col_idx is None:
                    continue
                for row in rows:
                    if len(row) > col_idx and row[col_idx] and row[col_idx].strip() not in ("—", "-", "无", ""):
                        result[key] = row[col_idx].strip()[:200]
                        break

            # ---- 竖排键值表（2026-09-01 补充）----
            # 形态：表头全空/无意义，行形如 ['', '本金', '750000元', '利息、罚息', '435783.44元', ...]
            # （京东个人债权"债权标的情况表"等；此前只处理横表导致这类字段从未提取）
            kv = _parse_kv_table(headers, rows)
            if kv:
                result["kv"] = kv
            break  # 只取第一个表
        return result
    except Exception as e:  # noqa: BLE001
        logger.debug("京东公告解析失败 %s: %s", paimai_id, e)
        return {}


def _to_float(s) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


_GUARANTOR_RE = re.compile(r'(?:连带责任)?保证人\s*[：:]\s*([^。；;]+)')


def _extract_guarantors_from_text(text: str) -> str | None:
    """从抵押/担保描述文本提取保证人名单（如'连带责任保证人：杨振军、张慧、杨振龙'）"""
    m = _GUARANTOR_RE.search(text or "")
    if not m:
        return None
    names = m.group(1).strip()
    # 过滤杂质：只保留到句号/分号前的人名串
    names = names.split("。")[0].split("；")[0].split(";")[0].strip()
    return names[:500] or None


def _parse_kv_table(headers: list, rows: list) -> dict | None:
    """竖排键值表解析：兼容三种形态（2026-09-01 扩展）：
      A. ['', '键', '值', '键2', '值2', ...]      —— 行首有空单元格（安徽新安银行）
      B. ['键', '值', '键2', '值2', '']           —— 无空单元格（威海银行）
      C. ['键', '值']                              —— 两列式
    返回 {键: 值}；非键值表返回 None。
    """
    if not rows:
        return None
    # 表头有多个非空 → 横表，不进入
    if headers and len([h for h in headers if h]) > 1:
        return None
    # 检测是否为键值形态：至少一行存在 键(非数字/金额) + 值
    has_kv = False
    for r in rows:
        if len(r) < 2:
            continue
        for start in (0, 1):
            if len(r) <= start:
                continue
            k = str(r[start]).strip()
            v = str(r[start + 1]).strip() if start + 1 < len(r) else ""
            if k and v and not re.match(r'^[\d,\.]+(元|万|万元|亿|亿元)?$', k):
                has_kv = True
                break
        if has_kv:
            break
    if not has_kv:
        return None
    kv: dict = {}
    for r in rows:
        if not r:
            continue
        # 自动探测本行起始：index0 或 index1 哪个更像键（index0 空 → 从 1 开始）
        start = 1 if (len(r) >= 2 and not str(r[0]).strip()) else 0
        if start == 1 and len(r) == 2 and str(r[1]).strip() and not str(r[0]).strip():
            # 行首空 + 单键值（['', '键'] 或 ['', '标题']）→ 跳过标题行
            kv.setdefault(str(r[1]).strip(), "")
            continue
        # 2026-09-02 修复：3 列行 ["组名","键","值"]（如 ["债权基本情况","贷款发放金额","10000000.00 元"]、
        # ["抵、质押及担保情况","抵、质押及保证担保人","陈大光"]）——原逻辑当 [键,值,键2] 错位解析，
        # 导致金额/担保人被张冠李戴（453 案例本金抓成贷款发放金额）。此处直接取 (row[1], row[2])。
        if (len(r) >= 3 and str(r[0]).strip() and str(r[1]).strip() and str(r[2]).strip()
                and not re.match(r'^[\d,\.]+(元|万|万元|亿|亿元)?$', str(r[1]).strip())):
            kv[str(r[1]).strip()] = str(r[2]).strip()
            continue
        for i in range(start, len(r), 2):
            k = str(r[i]).strip()
            v = str(r[i + 1]).strip() if i + 1 < len(r) else ""
            if k:
                kv[k] = v
    # 剔除纯标题键（值空且键含"表"）
    for k in list(kv.keys()):
        if not kv[k] and ("表" in k or "情况" in k):
            kv.pop(k, None)
    return kv or None


def _map_item(d: dict) -> dict:
    """京东返回 → feed_items 结构"""
    title = d.get("title") or ""
    item_id = d.get("auctionId") or d.get("id") or d.get("paimaiId") or ""
    # 正确详情页链接：paimai.jd.com/{auctionId}（pmsearch?auctionId 是列表页，用户无法比对）
    source_url = f"https://paimai.jd.com/{item_id}" if item_id else ""
    price_cn = d.get("currentPriceCN") or d.get("currentPriceStr") or ""
    assessment = d.get("assessmentPriceCN") or ""
    if assessment in ("0", "0万", "0.0", "0元"):
        assessment = ""
    city = d.get("city") or d.get("courtCityName") or ""
    province = d.get("province") or ""
    status = {1: "进行中", 2: "已结束", 3: "即将开始"}.get(d.get("auctionStatus"), "—")
    # 转让方：优先机构名 shopName，其次标题开头的机构名
    transferor = (d.get("shopName") or "").strip() or ""
    if not transferor:
        m = re.match(r'^(.{2,20}?(?:分行|支行|总行|分公司|有限公司|公司|事务所))', title)
        if m:
            transferor = m.group(1)
    region = city or province
    discount_rate = ""
    try:
        dr = float(d.get("discountRate") or 0)
        if dr > 0:
            discount_rate = f"{dr}折"
    except (TypeError, ValueError):
        pass
    # 精简标题 + 债务人（统一解析模块）
    from .text_extract import normalize_money, shorten_title, extract_debtor
    short_title = shorten_title(title)
    debtor = extract_debtor(title)
    price_std = normalize_money(price_cn)  # 起拍价/当前价
    assessment_std = normalize_money(assessment)
    # 本金：只从标题提取明确的"本金/债权总额/债权金额"值；提取不到留空（绝不拿起拍价冒充本金）
    claim_total = ""
    mc = re.search(r'(本金|债权总额|债权金额|债权本金)\s*[：:为是]?\s*([\d,]+\.?\d*)\s*(亿元|万元|万|元)', title)
    if mc:
        claim_total = normalize_money(f"{mc.group(2)}{mc.group(3)}")
    detail = {
        "region": region,
        "claim_total": claim_total,
        "listing_price": price_std or "",
        "current_price": price_std or "",
        "assessment_price": assessment_std or "",
        "auction_status": status,
        "transferor": transferor or "京东拍卖",
        "discount_rate": discount_rate,
        "source_label": "京东拍卖",
        "source_url": source_url,
        "short_title": short_title,
        "debtor_name": debtor,
        "_price_yuan": _price_cn_to_yuan(price_cn) or 0,  # 内部字段：当前价（元），供自动分类后删除
        "_discount_num": (float(d.get("discountRate") or 99) if d.get("discountRate") not in (None, "", 0) else 99),  # 折扣数值（8.0=8折），供自动分类后删除
        "_paimai_id": item_id,  # 内部字段：用于调详情接口补本金
    }
    tags = ["债权招商", "京东拍卖"]
    if region:
        tags.append(region)
    if discount_rate:
        tags.append(discount_rate)
    # 摘要自然化
    parts = []
    if debtor:
        parts.append(f"债务人 {debtor}")
    if claim_total:
        parts.append(f"债权本金 {claim_total}")
    if price_std:
        parts.append(f"起拍价 {price_std}")
    if discount_rate:
        parts.append(f"折扣 {discount_rate}")
    parts.append(f"当前{status}")
    summary = "，".join(parts) + "。"
    return {
        "title": title[:200],
        "summary": summary,
        "tags": tags,
        "source": "京东拍卖",
        "source_url": source_url,
        "detail": detail,
    }


def _is_bankrupt(d: dict) -> bool:
    """破产相关判定：标题含 破产/（破）/管理人（破产债权归捡漏版块，精选债权过滤）"""
    title = d.get("title") or ""
    return any(k in title for k in ("破产", "（破）", "(破)", "管理人"))


def _price_cn_to_yuan(price_cn: str) -> int | None:
    """'2.47312万'/'8748'/'1' → 元"""
    if not price_cn:
        return None
    s = str(price_cn).strip().replace(",", "")
    m = re.match(r'^([\d.]+)\s*(万|万元|亿|亿元|元)?$', s)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2) or ""
    if unit in ("万", "万元"):
        num *= 10_000
    elif unit in ("亿", "亿元"):
        num *= 100_000_000
    return int(num)


# 捡漏起拍价上限（元）——适合个人投资者的低价捡漏，排除几百几千万大额
BARGAIN_MAX_PRICE = 1_000_000  # 100 万（可调）


def _jd_request(params: dict) -> list[dict]:
    """执行京东 paimai_unifiedSearch 请求，返回原始条目列表"""
    import httpx

    cookie = _warm_cookie()
    if not cookie:
        logger.warning("京东预热失败：无 cookie")
        return []
    from urllib.parse import quote
    url = (
        f"{API_URL}?appid=paimai&functionId=paimai_unifiedSearch&body="
        + quote(json.dumps(params, ensure_ascii=False))
        + f"&clientVersion=paimai-h5-1.0.0&client=paimai-h5&t={int(datetime.now().timestamp() * 1000)}"
    )
    try:
        r = httpx.get(url, headers={"Referer": "https://pmsearch.jd.com/", "Cookie": cookie,
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}, timeout=20)
        j = r.json()
        datas = j.get("datas") if isinstance(j, dict) else None
        if j.get("code") != 0 or not datas:
            if j.get("code") in (400, 401, 403):
                global _cookie_cache
                _cookie_cache = ""
            logger.warning("京东接口返回异常: %s", str(j)[:200])
            return []
        return datas
    except Exception as e:  # noqa: BLE001
        logger.exception("京东请求失败: %s", e)
        return []


def fetch_jd_credit_list(page: int = 1, page_size: int = 40) -> list[dict]:
    """httpx + cookie 调京东接口，返回债权招商列表（只含进行中/即将开始，过滤破产）"""
    params = dict(JD_SEARCH_PARAMS)
    params["page"] = page
    params["pageSize"] = page_size
    datas = _jd_request(params)
    # 只保留 进行中(1)/即将开始(3)，过滤破产相关
    kept = [d for d in datas if d.get("auctionStatus") in (1, 3) and not _is_bankrupt(d)]
    return [_map_item(d) for d in kept]


def fetch_jd_bargain_list(max_price: int = BARGAIN_MAX_PRICE) -> list[dict]:
    """京东破产专区捡漏：keyword=破产 + 全类目 + 进行中/即将开始 → 低价标的（适合个人投资者）"""
    params = dict(JD_SEARCH_PARAMS)
    params["keyword"] = "破产"
    params["childrenCateId"] = ""
    params["labelSet"] = ""
    params["multiPaimaiStatus"] = "0,1"  # 进行中+即将开始
    params["page"] = 1
    params["pageSize"] = 40
    datas = _jd_request(params)
    out: list[dict] = []
    seen_urls: set[str] = set()
    for d in datas:
        title = d.get("title") or ""
        # 只保留破产相关标题（关键词"破产"可能匹配到无关条目）
        if not any(k in title for k in ("破产", "（破产）", "(破产)", "破产清算", "管理人")):
            continue
        price_cn = d.get("currentPriceCN") or ""
        price = _price_cn_to_yuan(price_cn)
        if price is None or price > max_price:
            continue  # 无价格或大额排除
        item = _map_item(d)
        item_id = d.get("auctionId") or d.get("id") or ""
        url = item["source_url"]
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        # 覆盖为捡漏形态
        item["tags"] = ["破产捡漏", "京东拍卖"]
        if price >= 10_000:
            item["tags"].append(f"起拍{price / 10000:.1f}万")
        else:
            item["tags"].append(f"起拍{price:,}元")
        detail = dict(item["detail"])
        detail.pop("_price_yuan", None)  # 清理内部字段
        detail.pop("_discount_num", None)
        # 2026-09-02：保留 _paimai_id（sync 详情补全需要，不再 pop）
        detail["auction_status"] = {1: "进行中", 3: "即将开始"}.get(d.get("auctionStatus"), "—")
        detail["listing_price"] = detail["current_price"]
        detail["bargain_note"] = "破产处置资产，起拍价远低于市场价，适合个人投资者低价参与；请自行核实权属、占用、税费等风险。"
        item["detail"] = detail
        item["summary"] = f"{detail.get('region', '')}·{detail['auction_status']}·起拍{detail.get('listing_price', '')} 破产处置，低价捡漏。"
        out.append(item)
    return out


def _upsert_feed(db, item: dict, section: str = "featured") -> None:
    """写入 feed_items：按 (section, title, source_url) 去重；已存在则刷新摘要/标签/详情。

    2026-09-02 修复：详情合并采用"非空覆盖，空值保留库内旧值"（与阿里版一致）——
    原整体覆盖会在重新同步时清掉 enrich-jd/手动补的字段（如 457/459/460 破产车位地址）。
    """
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


def _enrich_jd_detail(d: dict, paimai_id: str) -> None:
    """京东债权详情补全（2026-09-02 提取公共函数，精选与捡漏共用）：
    公告表格/kv/原文解析 → 回填 本金/利息/费用/合计/抵押物/担保/保证人/司法/announce_table。

    背景：捡漏(fetch_jd_bargain_list 破产搜索)此前不走详情解析，原文表格/利息/抵押物
    未抓取（465 案例：详情页没有原文表格）。
    """
    from .text_extract import normalize_money, extract_money_from_text, extract_collateral_from_text

    money = fetch_jd_detail_money(paimai_id)
    raw_text = money.get("raw_text") or ""
    if raw_text:
        d["raw_text"] = raw_text
    # 竖排键值表(kv)金额优先（2026-09-02 修复 453 案例：键别名+包含匹配）
    kv = money.get("kv") or {}

    def _kv_first(*keys):
        for k, v in kv.items():
            if not v or str(v).strip() in ("无", "", "—", "-"):
                continue
            if any(key in k for key in keys):
                return str(v).strip()
        return None

    if not d.get("claim_total"):
        v = _kv_first("本金余额", "债权本金余额", "本金")
        if v:
            d["claim_total"] = normalize_money(v)
    if not d.get("interest"):
        v = _kv_first("结欠利息", "利息余额", "利息、罚息", "欠息", "利息")
        if v:
            d["interest"] = normalize_money(v)
    if not d.get("other_fees"):
        v = _kv_first("代垫费用", "垫付费用")
        if v:
            d["other_fees"] = normalize_money(v)
    if not d.get("total_claims"):
        v = _kv_first("债权合计", "本息合计", "债权总额", "本息及费用合计")
        if v:
            d["total_claims"] = normalize_money(v)
    # 表格横表解析（含单位推断，最准）；文本正则兜底
    for src, dst in (("interest_std", "interest"), ("penalty_std", "penalty"),
                     ("other_fees_std", "other_fees"), ("total_std", "total_claims"),
                     ("principal_std", "claim_total")):
        if money.get(src) and not d.get(dst):
            d[dst] = money[src]
    # 京东接口 claimsMoney 兜底（2026-09-02：该接口返回"贷款发放金额"=原贷额，非当前本金余额）
    if not d.get("claim_total"):
        claims = fetch_jd_claim_amount(paimai_id)
        if claims and claims > 0:
            d["claim_total"] = normalize_money(f"{claims}元")
    # 文本正则兜底（东方资产模板等无表格场景；含【】金额格式）
    extracted = extract_money_from_text(raw_text)
    for src, dst in (("interest", "interest"), ("penalty", "penalty"),
                     ("other_fees", "other_fees")):
        if extracted.get(src) and not d.get(dst):
            d[dst] = extracted[src]
    if money.get("debtors"):
        d["debtor_count"] = len(money["debtors"])
        d["debtor_names"] = money["debtors"][:50]  # 多债务人名单（最多存50个）
    if money.get("announce_table"):
        d["announce_table"] = money["announce_table"]  # 自建表格（headers+rows）
    # 抵押物：表格"抵押情况"列优先；公告文本兜底
    if money.get("collateral"):
        d["collateral_desc"] = money["collateral"][:500]
        from .text_extract import classify_collateral
        ct = classify_collateral(money["collateral"])
        if ct:
            d["collateral_type"] = ct
    if not d.get("collateral_type") and raw_text:
        ctype, cdesc = extract_collateral_from_text(raw_text)
        if ctype:
            d["collateral_type"] = ctype
        if cdesc and not d.get("collateral_desc"):
            d["collateral_desc"] = cdesc
    # 保证人（表格"保证情况"列）
    if money.get("guaranty"):
        d["guarantor_names"] = money["guaranty"][:500]
        if not d.get("guaranty_type"):
            d["guaranty_type"] = "保证担保"
    # 2026-09-02：担保方式/司法状态 列（"担保方式:抵押+保证"、"诉讼状况:执行终本"）
    if money.get("guaranty_type") and not d.get("guaranty_type"):
        d["guaranty_type"] = money["guaranty_type"][:100]
    if money.get("judicial_status") and not d.get("judicial_status"):
        d["judicial_status"] = money["judicial_status"][:100]
    # 保证人兜底：无"保证人"列时，从抵押描述里提取"连带责任保证人：杨振军、张慧…"
    if not d.get("guarantor_names"):
        g = _extract_guarantors_from_text(money.get("collateral") or "")
        if g:
            d["guarantor_names"] = g
    # 竖排键值表其余映射（2026-09-01：京东个人债权"债权标的情况表"等；金额映射已在前置完成）
    if kv:
        # 潍坊银行形态：本金金额/利息金额/垫付费用金额（取首个非"无"值，kv 可能被后区块覆盖）
        table_rows = (money.get("announce_table") or {}).get("rows") or []
        for k, dst in (("本金金额", "claim_total"), ("利息金额", "interest"), ("垫付费用金额", "other_fees")):
            if d.get(dst):
                continue
            for r in table_rows:
                for i in range(len(r) - 1):
                    if str(r[i]).strip() == k and str(r[i + 1]).strip() not in ("无", "", "—"):
                        d[dst] = normalize_money(str(r[i + 1]).strip())
                        break
                if d.get(dst):
                    break
        # 威海银行"债权本息"长文本（含 本金余额/利息罚息合计/诉讼费用）
        zh = str(kv.get("债权本息") or kv.get("债权信息") or "")
        if zh and (not d.get("claim_total") or not d.get("interest") or not d.get("other_fees")):
            m = re.search(r'本金余额\s*([\d,]+\.?\d*)\s*元', zh)
            if m and not d.get("claim_total"):
                d["claim_total"] = normalize_money(f"{m.group(1)}元")
            m = re.search(r'利息[、，,，和]*罚息[^，。]*?合计\s*金额?\s*([\d,]+\.?\d*)\s*元', zh)
            if m and not d.get("interest"):
                d["interest"] = normalize_money(f"{m.group(1)}元")
            m = re.search(r'(?:诉讼费用|代垫费用)\s*([\d,]+\.?\d*)\s*元', zh)
            if m and not d.get("other_fees"):
                d["other_fees"] = normalize_money(f"{m.group(1)}元")
        if kv.get("担保方式") and not d.get("guaranty_type"):
            d["guaranty_type"] = kv["担保方式"]
        # 2026-09-02 修复(453)：担保人/抵押物支持"抵、质押及保证担保人""抵、质押物：（产权号…）"键
        if not d.get("guarantor_names"):
            gv = _kv_first("抵、质押及保证担保人", "保证担保人", "保证人", "担保人")
            if gv:
                d["guarantor_names"] = gv[:500]
        kv_coll = _kv_first("抵、质押物", "抵质押物", "抵押物", "抵押情况")
        # 抵押物：资产类型 + 抵质押物地址
        coll_parts = []
        if kv.get("资产类型"):
            coll_parts.append(f"{kv['资产类型']}")
        if kv_coll and kv_coll != "抵押物地址":
            coll_parts.append(kv_coll)
        if coll_parts and not d.get("collateral_desc"):
            d["collateral_desc"] = "；".join(coll_parts)[:500]
        if kv.get("资产类型") and not d.get("collateral_type"):
            from .text_extract import classify_collateral
            ct = classify_collateral(f"{kv['资产类型']} {kv_coll or ''}")
            if ct:
                d["collateral_type"] = ct
        if kv.get("诉讼情况") and not d.get("execution"):
            d["execution"] = kv["诉讼情况"]
        if kv.get("地区") and not d.get("region"):
            d["region"] = kv["地区"]
    __import__("time").sleep(0.3)  # 接口限速


def sync_jd_credit_to_feed() -> dict:
    """主入口：抓京东债权招商 → 精选债权 + 破产低价标的 → 捡漏。返回统计。"""
    from ..database import SessionLocal

    featured: list[dict] = []
    bargain: list[dict] = []
    bargain_raw: list[dict] = []
    try:
        featured_raw: list[dict] = []
        for pg in (1, 2):
            got = fetch_jd_credit_list(pg, 40)
            if got:
                featured_raw.extend(got)
        bargain_raw = fetch_jd_bargain_list()
    except Exception as e:  # noqa: BLE001
        logger.exception("京东同步失败: %s", e)
        featured_raw = []
    # 自动分类：起拍价 < 10000 元 或 折扣 < 1 折（discountRate 语义：8.0=8折）→ 归捡漏（用户规则 2026-08-31）
    # 同时调详情接口补债权本金（extendInfoMap.claimsMoney）+ 公告表格补利息/罚息
    for it in featured_raw:
        d = it["detail"]
        price = d.pop("_price_yuan", 0) or 0
        disc = d.pop("_discount_num", 99) or 99
        paimai_id = d.pop("_paimai_id", "") or ""
        if paimai_id:
            _enrich_jd_detail(d, paimai_id)  # 2026-09-02：详情补全（表格/kv/原文）提取为公共函数
        if (0 < price < 10000) or disc < 1:
            d["bargain_note"] = "低价捡漏：起拍价低于 1 万元或折扣低于 1 折，适合个人投资者低价参与；请自行核实权属、占用、税费等风险。"
            it["tags"] = [t for t in (it.get("tags") or []) if t not in ("债权招商", "京东拍卖")] + ["低价捡漏", "京东拍卖"]
            bargain.append(it)
        else:
            featured.append(it)

    # 破产搜索捡漏（2026-09-02 修复：此前不走详情解析，原文表格/利息/抵押物未抓——465 案例）
    for it in bargain_raw:
        d = it["detail"]
        paimai_id = d.pop("_paimai_id", "") or ""
        if paimai_id:
            _enrich_jd_detail(d, paimai_id)
        bargain.append(it)

    db = SessionLocal()
    try:
        for it in featured:
            _upsert_feed(db, it, section="featured")
        for it in bargain:
            _upsert_feed(db, it, section="bargain")
        db.commit()
        from ..models import FeedItem
        feat_total = db.query(FeedItem).filter(FeedItem.section == "featured").count()
        bargain_total = db.query(FeedItem).filter(FeedItem.section == "bargain").count()
    finally:
        db.close()
    logger.info("京东同步完成: 精选 %d 条, 捡漏 %d 条", len(featured), len(bargain))
    return {"fetched_featured": len(featured), "fetched_bargain": len(bargain),
            "featured_total": feat_total, "bargain_total": bargain_total}
