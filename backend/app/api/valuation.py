"""土地厂房估价路由（独立工具，替换原债权对比入口）

成本法粗估：土地出让价 + 建筑建安造价×折旧（20年/残值5%）。
支持：粘贴抵押物描述自动提取 + 手工补充关键字段（面积/结构/建成年份/地区）+ 上传证件存档。
"""
import logging
import os
import re
from datetime import datetime

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import User
from ..schemas.common import ApiResponse, err, ok
from ..services.land_factory_valuation import estimate_land_factory
from .deps import get_current_user

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/valuation", tags=["valuation"])


class ValuationRequest(BaseModel):
    collateral_text: str = Field(..., description="抵押物描述（如：青岛市黄岛区XX路工业厂房，土地总面积4881平方米，厂房总面积5306平方米，建于2010年）")
    # 可选手工补充字段（描述提取不到时用）
    collateral_type: str | None = None
    region: str | None = None
    land_area_sqm: float | None = None
    building_area_sqm: float | None = None
    structure_type: str | None = None   # light_steel / heavy_steel / brick / unknown
    build_year: int | None = None


@router.post("/estimate", response_model=ApiResponse)
def estimate(
    req: ValuationRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """成本法估值：土地+厂房，输出三档（保守/中性/乐观）+ 计算明细"""
    if not req.collateral_text or len(req.collateral_text.strip()) < 5:
        raise err("请填写抵押物描述（至少包含抵押物类型与面积）")

    extra = {
        "collateral_type": req.collateral_type,
        "region": req.region,
        "land_area_sqm": req.land_area_sqm,
        "building_area_sqm": req.building_area_sqm,
        "structure_type": req.structure_type,
        "build_year": req.build_year,
    }
    extra = {k: v for k, v in extra.items() if v is not None}

    result = estimate_land_factory(req.collateral_text, extra)
    valuation = result.get("valuation")
    if not valuation or valuation.get("data_insufficient"):
        raise err(valuation.get("note", "无法估值，请补充抵押物信息") if valuation else "无法估值")

    # 活动留痕：记录到"我的任务-土地厂房估价"区块
    try:
        from ..services.activity import add_activity

        ref = valuation.get("reference_cents")
        ref_wan = f"{ref / 100 / 10000:.4f}万元" if ref else "—"
        add_activity(
            db, user.id, "valuation",
            title="土地厂房估价",
            summary=f"{valuation.get('collateral_type') or '抵押物'}：主参考 {ref_wan}（区间 {valuation.get('conservative_cents', 0) / 100 / 10000:.2f}~{valuation.get('optimistic_cents', 0) / 100 / 10000:.2f}万元）",
            detail={
                "collateral_text": req.collateral_text,
                "method": result.get("method"),
                "valuation": valuation,
                "notes": result.get("notes", []),
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("activity record failed: %s", e)

    return ok({
        "method": result.get("method"),
        "land": result.get("land"),
        "building": result.get("building"),
        "valuation": valuation,
        "notes": result.get("notes", []),
    }, "估值完成（成本法粗估，仅供参考）")


@router.post("/upload-docs", response_model=ApiResponse)
async def upload_docs(
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
):
    """上传房产证/土地证等证件（存档备查，供人工核对面积/建成年份）。

    仅做魔数校验 + 指纹去重 + 安全存档，不解析内容（P1 可扩展 OCR 提取关键字段）。
    """
    from ..services.file_validate import validate_upload

    os.makedirs(settings.upload_dir, exist_ok=True)
    saved = []
    skipped = []
    for f in files:
        data = await f.read()
        v = validate_upload(f.filename or "file", data, getattr(f, "last_modified", None))
        if not v.get("ok"):
            raise err(v.get("error", "文件校验失败"))
        fingerprint = v["fingerprint"]
        safe_name = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", f.filename or "file")
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        path = os.path.join(settings.upload_dir, f"valdoc_{user.id}_{stamp}_{fingerprint[:8]}_{safe_name}")
        if os.path.exists(path):
            skipped.append(f.filename)
            continue
        with open(path, "wb") as fp:
            fp.write(data)
        saved.append({"name": safe_name, "size": len(data), "path": path})
        logger.info("valuation doc uploaded: %s (user %s)", safe_name, user.id)
    return ok({"saved": saved, "skipped_duplicates": skipped}, f"已存档 {len(saved)} 份证件")
