"""土地价格库匹配服务：抵押物估值时查询参考价

匹配规则：
1. 优先精确匹配：省+市+土地性质 完全一致
2. 其次省市匹配（同市同性质，忽略区县）
3. 再次同省同性质
4. 都未命中 → 返回 None，由调用方回退默认档位
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LandPriceRef

logger = logging.getLogger(__name__)


def match_land_price(db: Session, region: str | None, land_type: str | None) -> dict | None:
    """按地区+土地性质匹配土地参考价。

    Args:
        region: 地区文本（如 山东-青岛 / 青岛 / 山东临沂）
        land_type: 土地性质（工业/商业/住宅...）

    Returns:
        {province, city, land_type, price_lo, price_hi, source, effective_date, match_level}
        未命中返回 None
    """
    if not land_type or land_type not in ("工业", "商业", "住宅", "综合", "仓储", "农业", "公共", "交通"):
        return None

    # 解析地区
    province, city, district = _split_region(region or "")

    rows = db.scalars(select(LandPriceRef)).all()

    def _to_dict(r: LandPriceRef, level: str) -> dict:
        return {
            "province": r.province,
            "city": r.city,
            "land_type": r.land_type,
            "price_lo": r.price_lo,
            "price_hi": r.price_hi,
            "source": r.source,
            "effective_date": r.effective_date,
            "match_level": level,
        }

    # 1) 精确：省+市+区县+性质
    if province and city and district:
        for r in rows:
            if (r.province == province and r.city == city and r.district == district
                    and r.land_type == land_type):
                return _to_dict(r, "exact")
    # 2) 省市+性质（忽略区县；库内城市级记录 province 可为空——城市名基本唯一）
    if province and city:
        for r in rows:
            if (r.city == city and r.land_type == land_type
                    and (not r.province or r.province == province)):
                return _to_dict(r, "city")
    # 2.5) 仅市+性质（用户只给了市名，未带省）
    if city and not province:
        for r in rows:
            if r.city == city and r.land_type == land_type:
                return _to_dict(r, "city")
    # 3) 省+性质
    if province:
        for r in rows:
            if r.province == province and r.land_type == land_type:
                return _to_dict(r, "province")
    # 4) 仅性质（全国平均：province 和 city 均为空的记录）
    for r in rows:
        if r.land_type == land_type and not r.province and not r.city:
            return _to_dict(r, "national")
    return None


def _split_region(region: str) -> tuple[str | None, str | None, str | None]:
    """把地区文本拆成 省/市/区县（尽力而为）

    支持：山东 / 山东省 / 山东-青岛 / 山东青岛 / 山东省青岛市 / 青岛市 / 青岛 / 北京
    """
    region = (region or "").strip()
    if not region:
        return None, None, None
    import re

    # 直辖市
    province = None
    for p in ["北京", "天津", "上海", "重庆"]:
        if region.startswith(p):
            province = p
            rest = region[len(p):]
            city = p  # 直辖市即市
            break
    else:
        rest = region
        # 省：『山东省』『山东省青岛市』『山东-青岛』『山东青岛』
        m = re.match(r"([\u4e00-\u9fff]{2}?省)", region)
        if m:
            province = m.group(1).rstrip("省")
            rest = region[m.end():]
        else:
            m2 = re.match(r"([\u4e00-\u9fff]{2}?)(?:-|—|·|\s)([\u4e00-\u9fff]{2,6})", region)
            if m2 and m2.group(1) in ("山东", "河北", "河南", "江苏", "浙江", "安徽", "福建", "江西", "湖北", "湖南",
                                      "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "辽宁",
                                      "吉林", "黑龙江", "山西", "内蒙古", "广西", "西藏", "宁夏", "新疆", "台湾"):
                province = m2.group(1)
                rest = m2.group(2)
            elif region[:2] in ("山东", "河北", "河南", "江苏", "浙江", "安徽", "福建", "江西", "湖北", "湖南",
                                "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "辽宁",
                                "吉林", "黑龙江", "山西", "内蒙古", "广西", "西藏", "宁夏", "新疆", "台湾"):
                province = region[:2]
                rest = region[2:]
            else:
                # 无省份，可能是『青岛市』『青岛』
                rest = region

    # 市
    city = None
    if province in ("北京", "天津", "上海", "重庆"):
        city = province
    m = re.search(r"([\u4e00-\u9fff]{2,10}?市(?!场|政|民|中|心))", rest)
    if m:
        city = m.group(1).rstrip("市")
    elif not city and rest:
        # 剩余部分去掉区县后视为市（如『临沂市兰山区』→ 临沂）
        m2 = re.match(r"([\u4e00-\u9fff]{2,8}?)(?:[\u4e00-\u9fff]{2,8}?(?:区|县))", rest)
        if m2:
            city = m2.group(1)
        else:
            cand = re.match(r"([\u4e00-\u9fff]{2,8}?)$", rest)
            if cand and not re.search(r"(?:区|县)$", cand.group(1)):
                city = cand.group(1)
    # 区县
    district = None
    m3 = re.search(r"([\u4e00-\u9fff]{2,8}?(?:区|县))", rest)
    if m3:
        district = m3.group(1)
    return province, city, district
