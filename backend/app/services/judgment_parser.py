"""判决书主体识别 + 名称校验服务

1. extract_entities(text)：从判决书/裁定书文本中识别 债务人/借款人/保证人/关联人 等主体
   - 有 LLM Key 时走 LLM（精确完整全称 + 角色 + 置信度）
   - 无 Key 时走规则提取（mock，尽力识别并标注低置信）
2. verify_names(names)：规则级名称校验（免费、离线），提示可疑名称，避免浪费企查查积分
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

# ---------- 主体提取 ----------

SYSTEM_PROMPT = """你是不良资产法律文书信息提取助手。从用户提供的判决书/裁定书/起诉状文本中，提取所有相关主体（企业法人与自然人）。

严格要求：
1. 只输出一个 JSON 对象：{"entities": [{"name": "主体完整名称", "role": "借款人|保证人|债务人|担保人|申请人|被申请人|其他", "type": "enterprise|person", "confidence": "high|medium|low"}]}
2. 企业名称必须使用完整全称（含"有限公司/股份有限公司/集团/中心/厂/银行"等后缀），不得缩写、不得拼接、不得加"被告一/原告"等角色前缀；
3. 同一主体多次出现时合并为一条，角色取最主要的一个；
4. 多个被告/保证人/担保人全部列出，不得遗漏；
5. confidence 判断：名称在原文完整出现且角色明确 → high；角色明确但名称可能被截断/不完整 → medium；模糊或疑似 → low；
6. 严禁编造：原文未出现的主体不得添加。"""


async def extract_entities(text: str) -> dict:
    """识别主体。返回 {"entities": [...], "method": "llm|rule", "note": "..."}"""
    if not text or len(text.strip()) < 10:
        return {"entities": [], "method": "none", "note": "文本过短，无法识别"}

    from .llm import chat_json  # 延迟导入

    try:
        result = await chat_json(
            SYSTEM_PROMPT,
            f"===== 法律文书文本开始 =====\n{text[:12000]}\n===== 法律文书文本结束 =====\n\n请提取全部相关主体。",
            temperature=0.1,
        )
        entities = result.get("entities", [])
        if entities:
            return {"entities": entities, "method": "llm", "note": ""}
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM 主体识别失败，回退规则提取: %s", e)

    return {"entities": rule_extract_entities(text), "method": "rule", "note": "使用规则提取（未配置 LLM Key），置信度仅供参考"}


# 企业名常见后缀
_COMPANY_SUFFIX = r"(?:股份有限公司|有限公司|有限责任公司|集团|中心|银行|支行|分行|事务所|厂|合作社|合伙企业|工作室)"

_ROLE_KEYWORDS = ["保证人", "担保人", "借款人", "债务人", "被告", "原告", "申请人", "被申请人", "连带"]

# 角色前缀（会从企业名里剥离）
_ROLE_PREFIX = re.compile(
    r"^(?:原告|被告[一二三四五六七八九十\d]*|连带责任保证人|法人保证人|自然人保证人|一般保证人|保证人|担保人|借款人|债务人|申请人|被申请人|连带保证人|关联人)[：:、]?"
)

# 文档常见词（合并结果以这些词开头时判定为误合并，如"项目基本情况"+"服务有限公司"）
_DOC_STOP = ("第三章", "第二章", "第一章", "项目", "基本", "情况", "说明", "要求", "内容",
             "采购", "如下", "本次", "服务", "本", "之", "的", "和", "与", "及", "对",
             "为", "在", "向", "由", "关于")

# 人名以这些词结尾 → 判定为企业简称（如"犇智汽车""顺翰汽车"），不作为自然人输出
_PERSON_COMPANY_TAIL = ("汽车", "公司", "集团", "中心", "银行", "实业", "科技", "贸易",
                        "投资", "建设", "房产", "担保", "机械", "材料", "销售", "服务",
                        "有限", "发展", "控股", "股份", "地产", "能源", "物流")

# 自然人姓名后的边界（法律文书常见词/标点），防止把名字尾巴或企业简称抓进人名
_PERSON_BOUNDARY = r"(?=提起诉讼|承担|保证|连带|担保|提供|支付|偿还|履行|到期|逾期|应|向|对|等|的|和|与|及|、|，|,|。|；|;|\s|$)"

# 贪婪匹配企业名（从最后一个合法后缀结束），避免拆出"股份有限公司"等碎片
_COMPANY_RE = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9]{2,40}" + _COMPANY_SUFFIX)

# 合并边界：只有"完整公司形态"后缀才视为另一个公司名的结束（集团/中心等可能是长名的一部分）
_MERGE_BOUNDARY = ("股份有限公司", "有限责任公司", "有限公司")

# 后缀被 OCR 断行拆开时，下一行以这些"后缀续接"开头则拼回（如 "服务有\n限公司" → "服务有限公司"）
_SUFFIX_CONT = r"(限公司|有限公司|股份有限公司|有限责任公司|公司|集团|中心|银行|支行|分行|事务所|厂|合作社|合伙企业)"

_SUFFIX_SPLIT_RE = re.compile(r"(?<=[\u4e00-\u9fa5])\n(?=" + _SUFFIX_CONT + r")")


def _join_suffix_splits(text: str) -> str:
    """修复 OCR 把公司后缀断行的情况：前一行以中文结尾、下一行以公司后缀续接 → 拼回一行。"""
    return _SUFFIX_SPLIT_RE.sub("", text)


def _merge_company_name(text: str, s: int, name: str) -> str:
    """OCR 断行把长企业名截断时，向前回溯补全名称。

    例如 OCR 输出"济南森智汽车"换行"销售服务有限公司"，后一段是碎片，
    回溯取回"济南森智汽车"拼成完整名称；若前文本身就是完整公司名则放弃合并。
    """
    prefix: list[str] = []
    p = s - 1
    while p >= 0 and len(prefix) < 25:
        c = text[p]
        if c in "\n\r \u3000\t":  # 允许跨行/空格合并
            p -= 1
            continue
        if not ("\u4e00" <= c <= "\u9fff"):  # 遇标点/符号停止
            break
        prefix.insert(0, c)
        acc = "".join(prefix)
        if any(acc.endswith(x) for x in _MERGE_BOUNDARY):
            # 前文已是完整公司名（如"……有限公司"），不合并
            prefix = []
            break
        p -= 1
    if not prefix:
        return name
    merged = _ROLE_PREFIX.sub("", "".join(prefix) + name)
    if merged != name and merged.endswith(_MERGE_BOUNDARY) and 5 <= len(merged) <= 45:
        return merged
    return name


def _extract_person_identity(text: str, start: int, end: int, name: str) -> dict:
    """从材料上下文提取自然人的身份锚点（用于重名消歧）。

    只取必要字段：性别 / 出生年月 / 住址 / 证件后4位 / 与企业关系绑定。
    身份证号仅保留后 4 位（隐私最小化）。
    """
    identity: dict = {}
    ctx = text[max(0, start - 30):end + 50]
    identity["context"] = ctx.strip()[:80]

    m = re.search(r"(男|女)", ctx[:25])
    if m:
        identity["gender"] = m.group(1)
    m = re.search(r"(\d{4})年(\d{1,2})月", ctx)
    if m:
        identity["birth"] = f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"住(?:址)?[:：]?([\u4e00-\u9fa5·]{4,28}?(?:号|室|楼|区|路|街|镇|村|县|市|花园|小区))", ctx)
    if m:
        identity["address"] = m.group(1)
    # 证件号仅保留后 4 位
    m = re.search(r"(?:身份证|证件)?号?码?[:：]?[\s]*\d{6}.*?(\d{4})\b", ctx)
    if m:
        identity["id_tail"] = m.group(1)
    # 与企业角色绑定
    for kw, label in (("法定代表人", "法定代表人"), ("实际控制人", "实际控制人"),
                      ("股东", "股东"), ("董事", "董事"), ("监事", "监事")):
        if kw in ctx[:35]:
            identity["binding"] = label
            break
    return identity


def rule_extract_entities(text: str) -> list[dict]:
    """规则提取：抓企业名 + 邻近角色词；自然人（无后缀）从'保证人：X'模式提取。"""
    text = _join_suffix_splits(text)  # 先修复 OCR 后缀断行
    raw: list[tuple[int, int, str, str]] = []
    for m in _COMPANY_RE.finditer(text):
        name = _ROLE_PREFIX.sub("", m.group(0))
        # "X有限公司向银行借款" → 去掉"向..."粘连（"向"是常见连接词）
        if "向" in name and name.count("向") <= 2:
            name = name.split("向")[0]
        if len(name) < 4:  # 剔除"股份有限公司"这类碎片
            continue
        ctx = text[max(0, m.start() - 20):m.start()]
        role = next((k for k in _ROLE_KEYWORDS if k in ctx), "其他")
        if role == "被告":
            role = "债务人"
        elif role == "原告":
            role = "申请人"
        raw.append((m.start(), m.end(), name, role))

    # 位置去重（保留最长非重叠片段）——此时不按名字去重，避免同名碎片被提前合并
    raw.sort(key=lambda t: (t[1] - t[0], t[0]), reverse=True)
    kept_pos: list[tuple[int, int, str, str]] = []
    for s, e, name, role in raw:
        if any(s >= ps and e <= pe for ps, pe, _, _ in kept_pos):
            continue
        kept_pos.append((s, e, name, role))

    # OCR 断行碎片合并 + 按合并后名称去重（优先保留带角色的一次出现）
    merged_map: dict[str, tuple[str, int]] = {}
    for s, e, name, role in kept_pos:
        full = _merge_company_name(text, s, name)
        prev = merged_map.get(full)
        if prev is None or (role != "其他" and prev[0] == "其他"):
            merged_map[full] = (role, s)

    entities: list[dict] = []
    for full, (role, s) in merged_map.items():
        # 误合并防护：以文档常见词开头的名称判定为 OCR 碎片误拼，丢弃（不输出垃圾主体）
        if full.startswith(_DOC_STOP):
            continue
        # 短尾碎片过滤：未成功合并、且核心名过短（≤3字，如"服务有限公司"）的多为截断碎片，丢弃
        core = re.sub(_COMPANY_SUFFIX, "", full)
        if len(core) <= 3:
            continue
        entities.append({
            "name": full, "role": role, "type": "enterprise",
            "confidence": "medium" if role != "其他" else "low",
        })

    # 自然人："保证人：张三" / "保证人林慧兵、洪燕提起诉讼" / "被告四：林慧兵" 等模式
    # 姓名 2-3 字（非贪婪，优先 2 字），后接法律文本边界词（提起诉讼/承担/、/，等），
    # 避免把"洪燕提"或企业简称"犇智汽车"误抓
    seen: set[str] = set(merged_map.keys())
    person_re = re.compile(
        r"(保证人|担保人|借款人|债务人|连带保证人|被告[一二三四五六七八九十\d]*)[：:、\s]*"
        r"([\u4e00-\u9fa5·]{2,3}?)" + _PERSON_BOUNDARY +
        r"(?:[、，,]([\u4e00-\u9fa5·]{2,3}?)" + _PERSON_BOUNDARY + r")*"
    )
    for m in person_re.finditer(text):
        role_kw = m.group(1)
        role = "保证人" if "保证" in role_kw or "担保" in role_kw else ("债务人" if "被告" in role_kw else role_kw)
        identity = _extract_person_identity(text, m.start(), m.end(), m.group(2))
        for name in [m.group(2)] + [g for g in m.groups()[2:] if g]:
            if name in seen:
                continue
            seen.add(name)
            entities.append({
                "name": name, "role": role, "type": "person", "confidence": "medium",
                "identity": identity,
            })

    # 清理 1：自然人名若是企业名的前缀（OCR 碎片，如"济南森智"是"济南森智汽车…"的头部），删除误判
    ent_names = [e["name"] for e in entities if e["type"] == "enterprise"]
    entities = [
        e for e in entities
        if e["type"] != "person"
        or not any(n.startswith(e["name"]) and n != e["name"] for n in ent_names)
    ]
    # 清理 2：人名以企业常见词结尾（如"犇智汽车""顺翰汽车"）→ 企业简称误判，删除
    entities = [
        e for e in entities
        if e["type"] != "person"
        or not e["name"].endswith(_PERSON_COMPANY_TAIL)
    ]

    return entities


# ---------- 名称校验（规则级，免费离线） ----------

def verify_names(names: list[str]) -> list[dict]:
    """逐名称校验，返回 [{name, ok, warnings: [..]}]。ok=False 表示疑似有误，建议核对后再查询。"""
    out: list[dict] = []
    seen: dict[str, int] = {}
    for raw in names:
        name = (raw or "").strip()
        if not name:
            continue
        warnings: list[str] = []

        # 长度异常
        if len(name) < 2 or len(name) > 60:
            warnings.append("名称长度异常（过短/过长），疑似识别错误")

        # OCR 残留字符
        if re.search(r"[，,。、；;（）()\d\.\-_]", name):
            warnings.append("含标点/数字/特殊符号，疑似 OCR 残留或截断")

        # 空格/英文夹杂（中文企业名不应有）
        if re.search(r"[A-Za-z]", name) and not re.search(r"(ATM|POS|ERP)", name):
            warnings.append("含英文字母，疑似识别错误")

        # 企业形态名称缺后缀
        if re.search(r"[\u4e00-\u9fa5]{2,}?(公司|集团|中心|银行|厂|事务所)$", name) is None and len(name) >= 4:
            # 可能是自然人，也可能是残缺企业名——不强制告警，仅提示
            warnings.append("未匹配企业常见后缀（若是企业，名称可能不完整）")

        # 重复主体
        key = re.sub(r"(省|市|县|自治|有限|股份|责任)", "", name)
        if key in seen:
            warnings.append(f"与第 {seen[key]} 项疑似重复（名称相近）")
        else:
            seen[key] = len(out) + 1

        out.append({"name": name, "ok": len(warnings) == 0, "warnings": warnings})
    return out
