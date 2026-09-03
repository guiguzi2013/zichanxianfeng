"""土地厂房成本法估值模块（估值口径经用户确认 2026-08-25）

口径：
1. 抵押物只有土地 → 只估土地；有土地+厂房 → 土地+厂房合计
2. 土地价值 = 土地面积 × 土地出让单价（按地区档位：沿海/内地/默认）
3. 厂房价值 = 厂房面积 × 建安造价（按结构：钢构/砖混，无描述取平均）× 折旧系数
4. 折旧：房屋建筑物折旧年限不低于 20 年、残值率 5%（直线折旧，年折旧率 4.75%）
   - 建成年份从描述提取（如"建于2010年"）；提取不到则不折旧并标注
5. 三档输出（保守/中性/乐观）= 面积 × 单价区间三档
6. 平台边界：成本法粗估仅供参考，不替代专业评估；非工业类（住宅/商铺/写字楼等）回退市场价区间法
"""
import json
import logging
import re
from datetime import date

logger = logging.getLogger(__name__)

# ---------- 参数表（来源：公开出让公告/建安造价参考，见 docs/债权尽调维度清单.md） ----------

# 工业用地出让单价区间（元/㎡）；1亩=666.67㎡
#   沿海/发达城市（青岛、烟台、威海、日照、大连、苏州、宁波等）：约 40~80 万/亩 → 600~1200 元/㎡
#   内地地级市/省会周边：约 30~50 万/亩 → 450~750 元/㎡
#   无地区信息：取全国中值 30~60 万/亩 → 450~900 元/㎡
LAND_PRICE_TIERS = {
    "coastal": (600, 1200),   # 沿海/发达
    "inland": (450, 750),     # 内地
    "default": (450, 900),    # 未知地区
}

_COASTAL_CITIES = (
    "青岛", "烟台", "威海", "日照", "大连", "苏州", "无锡", "南通", "连云港", "盐城",
    "宁波", "温州", "台州", "嘉兴", "绍兴", "舟山", "厦门", "福州", "泉州", "漳州",
    "珠海", "东莞", "中山", "惠州", "汕头", "湛江", "北海", "海口", "三亚", "天津",
    "上海", "广州", "深圳", "杭州", "南京", "唐山", "秦皇岛", "潍坊", "北京",
)
_INLAND_CITIES = (
    "济南", "郑州", "武汉", "长沙", "南昌", "合肥", "西安", "成都", "重庆",
    "昆明", "贵阳", "南宁", "兰州", "太原", "沈阳", "长春", "哈尔滨", "乌鲁木齐",
    "呼和浩特", "银川", "西宁", "拉萨", "石家庄",
)

# 厂房建安造价区间（元/㎡，单层工业厂房参考）
#   轻钢（门式刚架）：600~1000；重钢：1000~1500；砖混/框架：800~1200；未知结构：取 700~1100 平均档
BUILDING_COST = {
    "light_steel": (600, 1000),   # 轻钢/钢结构
    "heavy_steel": (1000, 1500),  # 重钢
    "brick": (800, 1200),         # 砖混/框架/混凝土
    "unknown": (700, 1100),       # 无结构描述，取平均档
}

# 折旧参数：房屋建筑物折旧年限 ≥20 年、残值率 5%（直线折旧）
DEPRECIATION_YEARS = 20
DEPRECIATION_RESIDUAL = 0.05
YEARLY_DEPRECIATION_RATE = (1 - DEPRECIATION_RESIDUAL) / DEPRECIATION_YEARS  # 4.75%/年

# 非工业类型回退市场价区间（元/㎡，维持原口径）
TYPE_PRICE_RANGE = {
    "住宅": (8000, 20000),
    "商铺": (15000, 50000),
    "商业": (15000, 50000),
    "写字楼": (10000, 30000),
    "别墅": (15000, 35000),
}


def _parse_json(text: str | None) -> dict:
    if not text:
        return {}
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _extract_area(text: str, keyword: str) -> float | None:
    """提取指定关键词附近的面积，支持多种写法：
    『土地总面积4881.36平方米』『土地面积5306.92㎡』『土地，总面积5000平方米』『土地5000平方米』
    """
    # 写法1：关键词紧跟（可含"总"）
    m = re.search(
        rf"{keyword}\s*(?:总)?面积\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:㎡|平方米|平米|平)?",
        text,
    )
    if m:
        return float(m.group(1))
    # 写法2：关键词 + 分隔符 + 总面积
    m2 = re.search(
        rf"{keyword}[，,、\s]*总?面积\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(?:㎡|平方米|平米|平)",
        text,
    )
    if m2:
        return float(m2.group(1))
    # 写法3：关键词后短距离内出现面积（如『土地5000平方米』）
    m3 = re.search(
        rf"{keyword}[^，。；\n]{{0,15}}?(\d+(?:\.\d+)?)\s*(?:㎡|平方米|平米|平)",
        text,
    )
    if m3:
        return float(m3.group(1))
    return None


def _extract_any_area(text: str) -> list[float]:
    """提取描述中所有面积数字（兜底：无明确土地/厂房标注时使用）"""
    return [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*(?:㎡|平方米|平米|平)", text)]


def _extract_build_year(text: str) -> int | None:
    """提取建成年份：『建于2010年』『2010年建成』『2010年建』等"""
    m = re.search(r"(?:建于|建成|建成年份|建设年份|建造年份|落成|竣工)\s*[:：]?\s*(\d{4})\s*年?", text)
    if m:
        return int(m.group(1))
    m2 = re.search(r"(\d{4})\s*年\s*(?:建成|建|竣工|落成)", text)
    if m2:
        return int(m2.group(1))
    return None


def _detect_structure(text: str) -> str:
    t = text
    if re.search(r"重钢|重型钢|门式刚架.*重", t):
        return "heavy_steel"
    if re.search(r"钢构|钢结构|轻钢|门式刚架|彩钢|钢架", t):
        return "light_steel"
    if re.search(r"砖混|框架|混凝土|钢混|混合结构|砖瓦|排架", t):
        return "brick"
    return "unknown"


def _detect_region(text: str) -> str:
    for c in _COASTAL_CITIES:
        if c in text:
            return "coastal"
    for c in _INLAND_CITIES:
        if c in text:
            return "inland"
    return "default"


def _is_industrial(text: str, ctype: str) -> bool:
    keywords = ("厂房", "工业", "土地", "厂区", "车间", "仓储", "仓库", "用地", "钢构", "钢结构")
    for kw in keywords:
        if kw in ctype or kw in text:
            return True
    return False


def _lookup_land_price(text: str, extra: dict) -> dict | None:
    """查土地价格库：按地区+土地性质匹配参考单价（库内有数据则优先，未命中返回 None）

    返回 {price_lo, price_hi, source, match_level} 或 None
    """
    try:
        from ..database import SessionLocal
        from .land_price_matcher import match_land_price

        region = extra.get("region") or _detect_region_text(text)
        # 土地性质：工业抵押物 → 工业；商业类描述 → 商业
        land_type = "工业"
        if any(k in text or k in (extra.get("collateral_type") or "") for k in ("商业", "商铺", "写字楼", "商服")):
            land_type = "商业"
        db = SessionLocal()
        try:
            return match_land_price(db, region, land_type)
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        return None


def _detect_region_text(text: str) -> str | None:
    """从描述中提取地区文本（如 山东青岛 / 青岛市）"""
    import re
    for kw in ("青岛市", "济南市", "临沂市", "烟台市", "潍坊市", "淄博市", "济宁市", "威海市",
               "日照市", "泰安市", "德州市", "聊城市", "菏泽市", "滨州市", "东营市", "枣庄市",
               "北京市", "上海市", "天津市", "重庆市"):
        if kw in text:
            return kw.replace("市", "")
    m = re.search(r"([\u4e00-\u9fff]{2}?省[\u4e00-\u9fff]{2,6}?市)", text)
    if m:
        return m.group(1)
    return None


def estimate_land_factory(collateral_text: str, extra: dict | None = None) -> dict:
    """成本法估值主入口。

    Args:
        collateral_text: 抵押物描述原文
        extra: 可选结构化补充字段（用户手工录入）：
            {collateral_type, region, land_area_sqm, building_area_sqm,
             structure_type (light_steel/heavy_steel/brick/unknown), build_year}

    Returns:
        dict: 估值结果（含 land/building/total 三档 + notes）
    """
    extra = extra or {}
    text = collateral_text or ""
    ctype = extra.get("collateral_type") or ""

    # 非工业类（住宅/商铺/写字楼/别墅/商业）→ 回退市场价区间法
    if ctype in TYPE_PRICE_RANGE or any(k in ctype or k in text for k in ("住宅", "商铺", "写字楼", "别墅", "商业房产", "商业网点", "商业")):
        return _market_estimate(text, ctype, extra)

    if not _is_industrial(text, ctype):
        return {
            "method": "unsupported",
            "valuation": {"data_insufficient": True, "note": "无法识别抵押物类型，请补充抵押物描述或选择类型"},
            "notes": ["抵押物类型不明确，无法估值"],
        }

    region = extra.get("region") or _detect_region(text)
    tier = _detect_region(f"{text} {region or ''}")
    land_lo, land_hi = LAND_PRICE_TIERS.get(tier, LAND_PRICE_TIERS["default"])

    # 优先查土地价格库（管理员维护的真实参考价）
    price_note = ""
    land_ref = _lookup_land_price(text, extra)
    if land_ref and land_ref.get("price_lo"):
        land_lo = land_ref["price_lo"]
        land_hi = land_ref["price_hi"]
        price_note = f"（土地价格库匹配：{'省市' if land_ref.get('match_level') == 'city' else '省' if land_ref.get('match_level') == 'province' else '精确' if land_ref.get('match_level') == 'exact' else '全国'}级，来源{land_ref.get('source') or '人工维护'}）"

    # 面积：优先手工字段，其次从描述提取
    land_area = None
    building_area = None
    try:
        land_area = float(extra["land_area_sqm"]) if extra.get("land_area_sqm") else None
    except (TypeError, ValueError):
        land_area = None
    try:
        building_area = float(extra["building_area_sqm"]) if extra.get("building_area_sqm") else None
    except (TypeError, ValueError):
        building_area = None
    if land_area is None:
        land_area = _extract_area(text, "土地")
    if building_area is None:
        building_area = _extract_area(text, "厂房")
    if building_area is None:
        building_area = _extract_area(text, "建筑")

    # 兜底：没有明确土地/厂房标注时，把描述里的面积按类型关键词归位
    if land_area is None and building_area is None:
        areas = _extract_any_area(text)
        if areas:
            if "土地" in text and not re.search(r"厂房|车间|建筑|房屋|仓库", text):
                land_area = areas[0]  # 描述只有土地类关键词 → 视为土地面积
            else:
                building_area = areas[0]  # 工业场景常见"厂房X㎡"
    # 兜底2：有土地无厂房、但描述同时有未标注面积（如"土地X㎡，另有Y㎡建筑"）
    if land_area and building_area is None and "厂房" in text and "厂房" not in text.split("土地")[0]:
        bm = _extract_area(text.split("土地")[-1] if "土地" in text else text, "厂房")
        if bm:
            building_area = bm

    # 结构 + 建成年份
    structure = extra.get("structure_type") or _detect_structure(text)
    if structure not in BUILDING_COST:
        structure = "unknown"
    cost_lo, cost_hi = BUILDING_COST[structure]

    build_year = None
    if extra.get("build_year"):
        try:
            build_year = int(extra["build_year"])
        except (TypeError, ValueError):
            build_year = None
    if build_year is None:
        build_year = _extract_build_year(text)

    notes: list[str] = []
    land_part = None
    building_part = None

    # ---- 土地价值 ----
    if land_area and land_area > 0:
        land_part = {
            "area_sqm": round(land_area, 2),
            "unit_range": f"{land_lo}~{land_hi}元/㎡",
            "tier": tier,
            "conservative_cents": int(land_area * land_lo * 100),
            "neutral_cents": int(land_area * (land_lo + land_hi) / 2 * 100),
            "optimistic_cents": int(land_area * land_hi * 100),
        }
        notes.append(f"土地 {land_area:g}㎡ × 出让价 {land_lo}~{land_hi}元/㎡（{'土地价格库' if price_note else '沿海' if tier == 'coastal' else '内地' if tier == 'inland' else '全国中值'}档）{price_note}")
    else:
        notes.append("未提取到土地面积（如含土地请补充，或在描述中写明『土地总面积X平方米』）")

    # ---- 建筑价值（含折旧）----
    if building_area and building_area > 0:
        dep_factor = 1.0
        dep_note = ""
        if build_year:
            years = max(0, date.today().year - build_year)
            if years >= DEPRECIATION_YEARS:
                dep_factor = DEPRECIATION_RESIDUAL  # 超过折旧年限，按残值计
                dep_note = f"已使用{years}年（≥20年），按残值5%计"
            else:
                dep_factor = max(DEPRECIATION_RESIDUAL, 1 - YEARLY_DEPRECIATION_RATE * years)
                dep_note = f"建成于{build_year}年，已使用{years}年，直线折旧后按 {dep_factor*100:.1f}% 计"
        else:
            dep_note = "建成年份未知，未计折旧（可按房产证补充）"
        building_part = {
            "area_sqm": round(building_area, 2),
            "structure": structure,
            "cost_range": f"{cost_lo}~{cost_hi}元/㎡",
            "build_year": build_year,
            "depreciation_note": dep_note,
            "conservative_cents": int(building_area * cost_lo * dep_factor * 100),
            "neutral_cents": int(building_area * (cost_lo + cost_hi) / 2 * dep_factor * 100),
            "optimistic_cents": int(building_area * cost_hi * dep_factor * 100),
        }
        notes.append(f"建筑 {building_area:g}㎡ × 建安造价 {cost_lo}~{cost_hi}元/㎡（{_STRUCTURE_LABEL.get(structure, '平均档')}）；{dep_note}")
    else:
        notes.append("未提取到建筑面积（如含建筑请补充，或在描述中写明『建筑面积X平方米』）")

    # ---- 合计 ----
    if not land_part and not building_part:
        return {
            "method": "insufficient",
            "valuation": {"data_insufficient": True, "note": "未提取到土地/建筑面积，无法估值"},
            "notes": notes,
        }

    def _sum(part, key):
        return sum((p.get(key) or 0) for p in part if p)

    cons = _sum([land_part, building_part], "conservative_cents")
    neut = _sum([land_part, building_part], "neutral_cents")
    opti = _sum([land_part, building_part], "optimistic_cents")

    return {
        "method": "cost",
        "land": land_part,
        "building": building_part,
        "valuation": {
            "conservative_cents": cons,
            "neutral_cents": neut,
            "optimistic_cents": opti,
            "reference_cents": neut,  # 工业主参考值 = 中间值（成本法）
            "reference_label": "主参考估值（工业类取中间值）",
            "area_sqm": round((land_area or 0) + (building_area or 0), 2),
            "collateral_type": "工业（土地+建筑）" if (land_part and building_part) else "工业（土地）" if land_part else "工业（建筑）",
            "unit_price_range": "土地出让价 + 建筑建安造价（见成本法明细）",
            "estimate_note": "成本法粗估：土地按出让价、建筑按建安造价折旧，市场价波动大，不替代专业评估报告",
        },
        "notes": notes,
    }


_STRUCTURE_LABEL = {
    "light_steel": "轻钢结构",
    "heavy_steel": "重钢结构",
    "brick": "砖混/框架",
    "unknown": "平均档（结构未知）",
}


def _market_estimate(text: str, ctype: str, extra: dict) -> dict:
    """非工业类：维持原市场价区间法"""
    area = None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:㎡|平方米|平米|平)", text)
    if m:
        area = float(m.group(1))
    label = None
    for kw, rng in TYPE_PRICE_RANGE.items():
        if kw in ctype or kw in text:
            label = kw
            break
    if not label or not area:
        return {
            "method": "insufficient",
            "valuation": {"data_insufficient": True, "note": "缺少抵押物类型或面积，无法估值"},
            "notes": ["请补充抵押物类型与面积"],
        }
    lo, hi = TYPE_PRICE_RANGE[label]
    conservative = int(area * lo * 100)
    neutral = int(area * (lo + hi) / 2 * 100)
    optimistic = int(area * hi * 100)
    # 主参考值取档（经济下行口径，用户确认 2026-08-25）：
    #   商业/商铺/写字楼 → 保守（最低价）；住宅/别墅 → 中间值；工业（成本法）→ 中间值
    if label in ("商业", "商铺", "写字楼"):
        reference = conservative
        reference_label = "主参考估值（商业类取最低价）"
    else:
        reference = neutral
        reference_label = "主参考估值（住宅类取中间值）"
    return {
        "method": "market",
        "valuation": {
            "conservative_cents": conservative,
            "neutral_cents": neutral,
            "optimistic_cents": optimistic,
            "reference_cents": reference,
            "reference_label": reference_label,
            "area_sqm": round(area, 2),
            "collateral_type": label,
            "unit_price_range": f"{lo}~{hi}元/㎡",
            "estimate_note": "按同类型公开市场单价区间粗估，市场价格无法确定，不替代专业评估报告",
        },
        "notes": [f"{label} {area:g}㎡ × {lo}~{hi}元/㎡（市场价区间粗估；主参考值取{'最低价' if reference == conservative else '中间值'}）"],
    }
