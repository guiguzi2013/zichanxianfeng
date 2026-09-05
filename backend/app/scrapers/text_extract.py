"""资产先锋 · 原文解析统一模块（必备技能库·方案B）

集中"读懂原文 → 提取结构化字段"的全部能力，京东/阿里/Excel 等来源全局复用。
方法论见 docs/必备技能库.md。
特殊功能/版块如有特殊提取需求，在此模块扩展针对性函数。

函数清单：
- normalize_money / fmt_yuan_to_cn：金额标准化
- shorten_title：标题精简（去【】营销前缀）
- extract_debtor：债务人提取（个人/公司/名下/等N户）
- extract_money_from_text：从公告文本提取 本金/利息/罚息
- extract_collateral_from_text：从公告文本提取 抵押物（大类+描述）
- classify_collateral：抵押物文本 → 大类（商业楼/土地厂房/住宅房产/仓储物流）
- extract_start_price_from_html：从公告详情页 HTML 提取起拍价（元）
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

# ==================== 金额标准化 ====================

def normalize_money(raw) -> str:
    """金额标准化：'5049222.62元'/'139109.0万'/'1亿余元'/'430.0万' → 统一『数值+标准单位』（元/万/亿，去尾零，原含约/余/近 标『约』）"""
    if not raw:
        return ""
    s = str(raw).strip()
    m = re.match(r'^([\d,]+\.?\d*)\s*(亿元|万元|万|亿|元)?', s)
    if not m:
        return s
    num = float(m.group(1).replace(",", ""))
    unit = m.group(2) or ""
    approx = "约" if re.search(r'余|约|左右|近', s) else ""

    def fmt(v):
        return f"{v:.2f}".rstrip("0").rstrip(".")

    if unit in ("亿元", "亿"):
        return f"{approx}{fmt(num)}亿"
    if unit in ("万元", "万"):
        if num >= 10000:
            return f"{approx}{fmt(num / 10000)}亿"
        return f"{approx}{fmt(num)}万"
    # 元 / 无单位
    if num >= 100_000_000:
        return f"{approx}{fmt(num / 100_000_000)}亿"
    if num >= 10_000:
        return f"{approx}{fmt(num / 10_000)}万"
    if num >= 1:
        return f"{approx}{int(num)}元" if num == int(num) else f"{approx}{fmt(num)}元"
    return s


def fmt_yuan_to_cn(yuan: int) -> str:
    """元 → 展示字符串（>=1亿用亿，>=1万用万，否则元）"""
    if yuan >= 100_000_000:
        return f"{yuan / 100_000_000:.2f}".rstrip("0").rstrip(".") + "亿"
    if yuan >= 10_000:
        return f"{yuan / 10_000:.2f}".rstrip("0").rstrip(".") + "万"
    return f"{yuan:,}元"


# ==================== 标题精简 ====================

def shorten_title(title: str, max_len: int = 34) -> str:
    """精简标题：去【】营销前缀，尽量保留『债务人+债权性质』核心；仍长则按关键词截断"""
    t = re.sub(r'^【[^】]*】', '', title or '').strip()
    m = re.search(r'^(.{4,40}?)(?:等\d+户|等\d+笔)?(债权|应收\w*|款项|股权)(?:转让|资产|包)?', t)
    if m:
        core = m.group(0)
        if 4 <= len(core) <= max_len:
            return core
    return t[:max_len]


# ==================== 债务人提取 ====================

def extract_debtor(title: str) -> str:
    """从标题提取债务人（公司名/个人名）；提取不到返回空
    2026-09-05 增强：①多家公司(和/、/,连接) ②更名括注清理 ③标题开头的个人名列表
    ④【】营销前缀/（破）前缀剥离后匹配
    """
    t = (title or '').strip()
    _work = re.sub(r'^【[^】]*】', '', t).strip()          # 去【营销词】
    _work = re.sub(r'^[（(]\s*破[）)]\s*', '', _work).strip()  # 去（破）
    # 杂质词：提取结果含这些视为无效（如"对法院已判决生效...的债权"、"对应的从权利"）
    # 2026-09-02 加"对应"：标题"…债权及对应的从权利…"的"对"被误当"对债务人"提取出垃圾（453 案例）
    BAD = re.compile(r'判决|执行|生效|未诉|余元|转让|线索|凭证|在业|注册|审计|法院|案件|拟将|公开竞价|公开处置|贷款|拟|对应|从权利|抵、质押|借款合同')
    patterns = [
        # 0) 标题开头的公司列表（可多家、带（更名）括注），到 债权/款项/竞买/等N户/资产 处截断（2026-09-05）
        r'^([\u4e00-\u9fa5A-Za-z0-9*·\d]{2,20}(?:公司|集团|银行|厂|店|学校|医院)(?:（[^）]{0,40}）)?(?:(?:、|和|,|，)[\u4e00-\u9fa5A-Za-z0-9*·\d]{2,20}(?:公司|集团|银行|厂|店|学校|医院)(?:（[^）]{0,40}）)?){0,3})(?=等?\d+户?|[,，]?\s*\d+户|(?:及|并)?(?:相关担保人|保证人)?等?\d+户|(?:不良)?(?:贷款|信用)?债权|应收\w*|款项|资产包|两户|单户|未实缴|未缴|出资|竞买)',
        # 0b) 多家/单家公司（和/、/, 连接），可带（现更名：XX）括注；后接 债权/应收/不良贷款/资产包/等N户/N户
        r'([\u4e00-\u9fa5A-Za-z0-9*·]{2,20}(?:公司|集团|银行|厂|店|学校|医院)(?:（[^）]{0,30}）)?(?:(?:、|和|,|，)[\u4e00-\u9fa5A-Za-z0-9*·]{2,20}(?:公司|集团|银行|厂|店|学校|医院)(?:（[^）]{0,30}）)?){0,3})(?=等?\d+户?|(?:不良)?(?:贷款|信用)?债权|应收\w*|款项|资产包|两户|单户|未实缴|未缴|出资)',
        # 等N户前的公司（债务人后常跟"等N户"，最可靠）
        r'([\u4e00-\u9fa5A-Za-z0-9*·]{2,18}?(?:公司|集团|银行|厂|店|学校|医院))等\d+户',
        # 对+完整公司（（破）应收/未实缴场景：对XX公司享有/应收…；2026-09-05 新增，防公司名被个人规则截断）
        r'对(?:股东)?([\u4e00-\u9fa5A-Za-z0-9*·]{2,25}(?:公司|集团|银行|厂|店|学校|医院))(?:享有|享|持有|所持|未实缴|未缴|其他应收|应收)?',
        # 个人债权：对XX / 对持有XX / 对债务人XX（遇"个人/有/享/出资"等停止；2026-09-05 修（破）应收类截断）
        r'对(?:股东|持有(?:的)?|债务人)?([^个人有享。；,;、未实缴未缴出资人民币元，\d]{2,6}(?:、[^个人有享。；,;、未实缴未缴出资人民币元，\d]{2,6}){0,3})(?:享有|享)?',
        # 公司债权：XX公司等N户/单户债权；XX公司债权（含"单户抵押担保类不良债权"等中间修饰）
        r'([\u4e00-\u9fa5A-Za-z0-9*·]{2,18}?(?:公司|集团|银行|厂|店|学校|医院))(?:等\d+户|单户)?(?:的)?(?:抵押\w*|担保\w*|质押\w*|信用)?(?:债权|应收\w*|款项|不良)',
        # XX名下/持有/所持…债权
        r'([\u4e00-\u9fa5A-Za-z0-9*·]{2,14}?)(?:名下|持有|所持)(?:的)?(?:债权|应收\w*|款项)',
        # 标题开头的个人（XX个人/XX名下/XX、YY债权，2-4字可多个，2026-09-05 加"XX、YY债权"）
        r'^([\u4e00-\u9fa5]{2,4}(?:、[\u4e00-\u9fa5]{2,4}){0,3})(?:个人|名下|所有|债权|的债权)',
    ]
    for p in patterns:
        m = re.search(p, _work)
        if not m:
            continue
        name = m.group(1).strip().strip('、，,')
        # 清理前置杂质段（"对民事判决已确认胜诉的青岛*钢结构…"→ 只留"青岛*钢结构…"；先于其他清洗）
        for cut in ('对民事判决已确认胜诉的', '对法院已判决的', '对相关凭证记载的', '对正常在业的', '对在业注资超1亿的',
                    '经审计对在业注资超1亿', '经审计对在业注册超1亿', '经审计对相关凭证记载', '对法院已判决名下有土地线索的',
                    '对民事判决已确认胜诉', '对持有', '对债务人',
                    # 破产捡漏标题杂质（2026-09-05：破产企业对XX的债权 / 破产企业持有的XX股权 / 产企业持有的…）
                    '破产企业对', '破产企业持有的', '破产企业所持有的', '破产企业名下', '破产企业拥有的',
                    '产企业持有的', '产企业所持有的', '产企业名下', '破产企业对日照'):
            if name.startswith(cut):
                name = name[len(cut):]
                break
        name = re.sub(r'^(对|债务人)', '', name)
        # 取"拟将/转让/应收"等后的最后一段（如"云南省分公司拟将石林万农园林绿化有限公司"→"石林万农园林绿化有限公司"）
        name = re.split(r'等\d+户|应收|款项|转让|拟将|拟', name)[-1].strip('、，,')
        name = re.sub(r'(的债权|的公开转让|的)$', '', name).strip('、，,')
        # 更名括注并入（如"万元实业集团有限公司（现更名：湖南芳清集团有限公司）"——保留原名即可，去掉括注更干净）
        name = re.sub(r'（现更名[^）]*）', '', name).strip()
        # 剥离公司名最前面的 数字日期前缀（如 20260518北方蓝天…）
        name = re.sub(r'^\d{6,8}', '', name).strip()
        if BAD.search(name):
            continue  # 含杂质词 → 试下一个模式
        if len(name) <= 1 or name in ("公司", "企业", "个人", "我方", "我司", "其"):
            continue  # 泛称无意义
        if 1 <= len(name) <= 40:
            return name
    return ""


# ==================== 抵押物 ====================

_COLLATERAL_RULES = [
    ("商业楼", re.compile(r'商业|商铺|写字楼|商服|综合体|商场|物业|底商')),
    ("土地厂房", re.compile(r'土地|厂房|工业|车间|园区|仓储|仓库|库房')),
    ("住宅房产", re.compile(r'住宅|公寓|住房|别墅|房产|房屋')),
]


def classify_collateral(text: str) -> str:
    """抵押物文本 → 大类（商业楼/土地厂房/住宅房产）；无匹配返回空"""
    if not text:
        return ""
    for label, re_ in _COLLATERAL_RULES:
        if re_.search(text):
            return label
    return ""


_GUARANTOR_RE = re.compile(r'(?:连带责任)?保证人\s*[：:]\s*([^。；;]+)')


def extract_guarantors_from_text(text: str) -> str | None:
    """从抵押/担保描述文本提取保证人名单（如'连带责任保证人：杨振军、张慧、杨振龙'）"""
    m = _GUARANTOR_RE.search(text or "")
    if not m:
        return None
    names = m.group(1).strip()
    # 过滤杂质：只保留到句号/分号前的人名串
    names = names.split("。")[0].split("；")[0].split(";")[0].strip()
    return names[:500] or None


def extract_property_metrics(text: str) -> dict:
    """从抵押物描述提取 土地面积/建筑面积/建成年份/建筑结构 → dict（2026-09-02 自动预填用）。

    面积提取规则：找所有"数值+㎡/平方米"，面积前 40 字符内含
    "土地/占地面积/土地使用权" → 土地面积；否则 → 建筑面积（取第一个非土地面积）。
    如"总面积为13425.19平方米及相应的土地使用权面积为1349.7平方米"
      → {"building_area_sqm": "13425.19", "land_area_sqm": "1349.7"}
    """
    result: dict = {}
    t = (text or "").replace("，", ",").replace("；", ";")
    # 1) 土地面积：明确前缀
    m = re.search(r'(?:土地使用权面积|土地面积|占地面积)\s*[为是]?\s*([\d,]+\.?\d*)\s*(?:㎡|平方米|平米|平方)', t)
    if m:
        result["land_area_sqm"] = m.group(1).replace(",", "")
    # 2) 全部面积出现 → 按上下文分类
    lands, builds = [], []
    for m in re.finditer(r'([\d,]+\.?\d*)\s*(?:㎡|平方米|平米)', t):
        num = m.group(1).replace(",", "")
        before = t[max(0, m.start() - 40):m.start()]
        after = t[m.end():m.end() + 20]
        if re.search(r'土地|占地面积|土地使用权', before) and not re.search(r'总|建筑|房产|房屋|大楼|大厦|酒店|厂房|办公', before):
            lands.append(num)
        else:
            builds.append(num)
    if not result.get("land_area_sqm") and lands:
        result["land_area_sqm"] = lands[0]
    if not result.get("building_area_sqm") and builds:
        result["building_area_sqm"] = builds[0]
    # 3) 建成年份
    m = re.search(r'(?:建成年份|建成于|建于|竣工于)\s*[为是]?\s*(\d{4})\s*年?', t)
    if m:
        result["build_year"] = m.group(1)
    # 4) 建筑结构
    for kw, label in (("轻钢结构", "light_steel"), ("重钢结构", "heavy_steel"),
                      ("钢结构", "light_steel"), ("框架结构", "brick"), ("砖混", "brick"), ("框架", "brick")):
        if kw in t:
            result["structure_type"] = label
            break
    return result


def extract_collateral_from_text(text: str) -> tuple[str, str]:
    """从公告文本提取抵押物信息 → (抵押物大类, 描述)。如"…天和家园住宅小区…60套6428.11平方米住宅提供抵押担保"→(住宅房产, …)
    2026-09-05 修复：优先锚定"抵押物位于/抵押物为/抵押物："等真描述，避免"单户抵押担保类不良债权招商"
    标题里的"抵押"二字抢先命中、把公告开头段当抵押物（长江银行询价公告形态，549 等案例）。"""
    if not text:
        return "", ""
    # 真锚点优先：抵押物位于/为/坐落/：……（描述性句式），取最靠前的一个
    idx = -1
    for anchor in ("抵押物位于", "抵押物为", "抵押物坐落", "抵押物：", "抵押物:", "抵押物地址", "抵押担保物位于", "担保物位于"):
        i = text.find(anchor)
        if i >= 0 and (idx < 0 or i < idx):
            idx = i
    # 备选：普通"抵押"（旧逻辑）
    if idx < 0:
        idx = text.find("抵押")
    if idx < 0:
        return "", ""
    scope = text[max(0, idx - 60):idx + 90].strip()
    scope = re.sub(r'\s+', ' ', scope)
    if not scope:
        return "", ""
    # 2026-09-02 修复(453)：免责/注释段落含"抵押"字样被误当抵押物描述
    # （如"…抵押房地产可能已被其他债权人通过法院查封…不承担任何法律责任"）
    if re.search(r'注[：:]|不承担任何|仅供参考|瑕疵|请竞买人|买受人|可能已被|查封|先租后抵|被占用|已停止经营|已丧失|免责|详见合同', scope):
        return "", ""
    # 2026-09-05：命中"抵押"但实为公告开头标题段（"…银行…单户抵押担保类不良债权招商…询价如下"）→ 非抵押物描述
    if idx == text.find("抵押") and re.search(r'不良债权|债权招商|询价|公开拍卖|市场询价|近日在京东', scope) and not re.search(r'位于|坐落|面积为|平方米|幢|栋|号|路', scope):
        return "", ""
    ctype = classify_collateral(scope)
    return ctype, scope[:120]


# ==================== 金额（本金/利息/罚息） ====================

def extract_money_from_text(text: str) -> dict:
    """从公告清洗文本正则提取金额：本金/利息（含欠息）/罚息/其他费用。返回 {'principal','interest','penalty','other_fees'}（标准化字符串）

    支持两种格式：普通文本（"利息余额 1234.56万元"）与东方资产模板（"未偿利息人民币【10,924.22】万元"）。
    """
    if not text:
        return {}
    result: dict = {}
    # 通用金额捕获组：支持【】包裹
    def _amt():
        return r'[【\[]?\s*([\d,]+\.?\d*)\s*[】\]]?\s*(亿元|万元|万|元)'
    # 本金：债权本金/主债权本金余额/本金余额/本金；东方模板"未偿本金人民币【X】万元"
    m = re.search(
        r'(?:未偿本金|债权本金|主债权本金余额|本金余额|本金)\s*(?:人民币)?\s*[为是]?\s*[:：]?\s*' + _amt(),
        text,
    )
    if m:
        result["principal"] = normalize_money(f"{m.group(1)}{m.group(2)}")
    # 利息：未偿利息/利息余额/欠息/利息（含…）/利息及孳息
    m = re.search(
        r'(?:未偿利息|利息余额|欠息|利息及孳息|利息)(?:（含[^）]*）)?\s*(?:人民币)?\s*(?:金额)?\s*[为是]?\s*[:：]?\s*' + _amt(),
        text,
    )
    if m:
        result["interest"] = normalize_money(f"{m.group(1)}{m.group(2)}")
    # 罚息：剩余罚息/罚息（含…）/罚息
    m = re.search(
        r'(?:剩余罚息|罚息)(?:（含[^）]*）)?\s*(?:人民币)?\s*(?:金额)?\s*[为是]?\s*[:：]?\s*' + _amt(),
        text,
    )
    if m:
        result["penalty"] = normalize_money(f"{m.group(1)}{m.group(2)}")
    # 其他费用：代垫费用/垫付费用/其他权利金额（东方模板把律师费等并入"其他权利金额"）
    m = re.search(
        r'(?:代垫费用|垫付费用|其他权利金额|其他费用|诉讼费|律师费)\s*(?:人民币)?\s*(?:金额)?\s*[为是]?\s*[:：]?\s*' + _amt(),
        text,
    )
    if m:
        result["other_fees"] = normalize_money(f"{m.group(1)}{m.group(2)}")
    return result


# ==================== 起拍价（HTML 详情页） ====================

_START_PRICE_RE = re.compile(r'起拍价[：:]\s*([\d,]+\.?\d*)\s*(元|万元|万|亿元|亿)')


def extract_start_price_from_html(html: str) -> int | None:
    """从公告详情页 HTML 提取起拍价（元）；失败返回 None"""
    if not html:
        return None
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


# ==================== 公告正文排版（2026-09-03 用户规则：抓取内容必须排版再发布，禁止文字堆砌） ====================

# 机构名行（开头重复头识别：519/520 "分公司名/标题/分公司名/副标题" 重复2遍）
_ORG_LINE_RE = re.compile(r'^(中国(?:长城|信达|东方|中信金融|华融晋商)资产管理股份有限公司[^\n，。]{0,30}(?:分公司|事业部|有限公司)?)$')
# 页脚/导航噪声行
_NOISE_LINE_RE = re.compile(r'^(收藏|打印内容|相关资产信息|提示：点击本页面|关于信达|网站地图|版权所有|Copyright|ICP|京公网安备|'
                            r'邮箱：\S+@|传真：[0-9-]|返回中国东方营销网站首页|金融超市|联系我们|加入收藏|网站地图|关于本站)')
# 字段行（键：值 短信息，如 联系人/电话/编号/公告有效期）
_FIELD_LINE_RE = re.compile(
    r'^(联\s*系\s*人|联系电话|联系\s*电话|电子邮件|通讯地址|邮编|举报电话|监督管理部门|'
    r'编\s*号|公告编号|发布时间|公告有效期|受理征询或异议有效期|公告有效期|征询或异议的有效期限|'
    r'联系地址|公司地址|传真|网址|网站|资产编号|项目编号)\s*[：:]')


def layout_notice_body(body: str, title: str = "") -> list[str]:
    """公告正文排版 → 段落列表（用户规则 2026-09-03：所有抓取内容排版再发布）。

    抓取阶段已排除表格节点（自建表格展示原文表格，正文不再重复表格文字——用户 2026-09-03 修改1）。
    处理：
    1. 拆行去空行，滤导航/页脚噪声行
    2. 去开头重复头：与公告标题相同/包含标题的行、开头重复的机构名单行（519/520 重复2遍）
    3. 每逻辑行一段（公告 <p> 段落经 inner_text 后基本一行一段；长句保持完整行）
    4. 相邻极短碎片（如标题行/机构名残留后跟正文）合入后续
    """
    if not body:
        return []
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    lines = [ln for ln in lines if not _NOISE_LINE_RE.match(ln)]
    # 去重复头
    t = re.sub(r'\s+', '', title or "")
    start = 0
    drop_head = 0
    while start < len(lines):
        ln = lines[start]
        lc = re.sub(r'\s+', '', ln)
        is_dup = False
        if t and len(t) > 10 and (lc == t or lc in t or t in lc):
            is_dup = True
        elif _ORG_LINE_RE.match(ln):
            # 机构名单行重复（下一行也以机构名或标题开头）
            nxt = re.sub(r'\s+', '', lines[start + 1]) if start + 1 < len(lines) else ""
            nxt2 = re.sub(r'\s+', '', lines[start + 2]) if start + 2 < len(lines) else ""
            if start < 3 and (not nxt or _ORG_LINE_RE.match(lines[start + 1]) if start + 1 < len(lines) else False
                              or (t and nxt and (nxt == t or t in nxt))):
                is_dup = True
        if is_dup and drop_head < 2:
            drop_head += 1
            start += 1
            continue
        break
    rest = lines[start:]
    # 组段：正文长句(>40字或含句读)独立成段；短行(字段行/机构名)如果跟正文段之间是换行则独立
    paras: list[str] = []
    for ln in rest:
        if _FIELD_LINE_RE.match(ln) or _ORG_LINE_RE.match(ln) or len(ln) > 20 or ln.endswith(("。", "；", "！", "？")):
            # 独立段（含字段行/机构名行/长句/以句读结尾的短句）
            if paras and _FIELD_LINE_RE.match(paras[-1]) and _FIELD_LINE_RE.match(ln):
                # 字段行连续（联系人→电话→邮箱）合并为一段更整洁
                paras[-1] += "\n" + ln
            else:
                paras.append(ln)
        else:
            # 短碎片：接到上一段末尾（语义连续），无则独立
            if paras:
                paras[-1] += ln
            else:
                paras.append(ln)
    return [p for p in paras if p]


def extract_notice_metrics(body: str) -> dict:
    """从公告正文提取汇总指标（519：'包含债权4户…总金额为9500.20万元…本金3754.02万元，利息5393.29万元…'）。

    返回 {households, claim_total, principal, interest, other_fees, asset_pkg_no, deadline}
    """
    body = body or ""
    out: dict = {}
    m = re.search(r'(?:包含|涉及|共|为)?(?:债权|标的)?(\d+)\s*户(?:债权|资产|不良)?', body)
    if m:
        out["households"] = int(m.group(1))
    m = re.search(r'(?:总金额|债权总额|合计金额|资产包金额)[为是]?\s*([\d,]+\.?\d*)\s*(万元|亿元|万|亿)', body)
    if m:
        out["claim_total"] = f"{m.group(1)}{'万' if m.group(2) in ('万元', '万') else '亿'}"
    for key, pat in (
        ("principal", r'本金(?:余额)?(?:为)?\s*([\d,]+\.?\d*)\s*(万元|亿元|万|亿)'),
        ("interest", r'利息(?:余额)?(?:为)?\s*([\d,]+\.?\d*)\s*(万元|亿元|万|亿)'),
        ("other_fees", r'其他费用(?:为)?\s*([\d,]+\.?\d*)\s*(万元|亿元|万|亿)'),
    ):
        m = re.search(pat, body)
        if m:
            out[key] = f"{m.group(1)}{'万' if m.group(2) in ('万元', '万') else '亿'}"
    m = re.search(r'编号[：:]?\s*[（(]?([A-Z]{2,4}\d{8,})', body)
    if m:
        out["asset_pkg_no"] = m.group(1)
    m = re.search(r'(?:截止日|基准日)[为是]?\s*(\d{4})年(\d{1,2})月(\d{1,2})日', body)
    if m:
        out["deadline"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    if not m:
        m = re.search(r'截至\s*(\d{4})年(\d{1,2})月(\d{1,2})日', body)
        if m:
            out["deadline"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return out
