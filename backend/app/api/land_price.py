"""土地价格库路由（管理后台维护 + 估价引擎参考，前台不展示）

- GET    /admin/land-prices        列表
- POST   /admin/land-prices        手动新增
- PUT    /admin/land-prices/{id}   编辑
- DELETE /admin/land-prices/{id}   删除
- POST   /admin/land-prices/import 批量导入（Excel/Word/粘贴文本，自动解析归类）
- POST   /land-price/match         估价引擎调用：按地区+性质匹配参考价
"""
import json
import logging
import os
import re

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import LandPriceRef, User
from ..schemas.common import ApiResponse, err, ok
from ..services.land_price_matcher import match_land_price
from ..services.land_price_parser import (
    extract_text_from_docx,
    parse_excel_rows,
    parse_text_lines,
)
from .deps import (
    get_current_user,
    require_admin,
    require_land_price_admin,
    require_land_price_perm,
    require_editor,
)

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(tags=["land-price"])


# ---------- 数据模型 ----------

class LandPriceCreate(BaseModel):
    province: str | None = None
    city: str | None = None
    district: str | None = None
    land_type: str = Field(..., description="土地性质（工业/商业/住宅/综合/仓储/农业/公共/交通）")
    price_lo: int = Field(..., ge=0)
    price_hi: int = Field(..., ge=0)
    source: str | None = None
    effective_date: str | None = None
    note: str | None = None


class LandPriceUpdate(BaseModel):
    province: str | None = None
    city: str | None = None
    district: str | None = None
    land_type: str | None = None
    price_lo: int | None = None
    price_hi: int | None = None
    source: str | None = None
    effective_date: str | None = None
    note: str | None = None


class LandPriceMatchRequest(BaseModel):
    region: str | None = None
    land_type: str | None = None


def _to_dict(r: LandPriceRef) -> dict:
    return {
        "id": r.id,
        "province": r.province,
        "city": r.city,
        "district": r.district,
        "land_type": r.land_type,
        "price_lo": r.price_lo,
        "price_hi": r.price_hi,
        "source": r.source,
        "effective_date": r.effective_date,
        "note": r.note,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _normalize_land_type(t: str | None) -> str | None:
    """归一化土地性质"""
    if not t:
        return None
    t = t.strip()
    syn = {
        "工业": "工业", "工矿": "工业", "工业用地": "工业", "工矿仓储": "工业",
        "商业": "商业", "商服": "商业", "商业服务业": "商业", "商业用地": "商业",
        "住宅": "住宅", "居住": "住宅", "住宅用地": "住宅",
        "综合": "综合", "其他": "综合",
        "仓储": "仓储", "物流": "仓储",
        "农业": "农业", "农用地": "农业",
        "公共": "公共", "公共服务": "公共",
        "交通": "交通", "交通运输": "交通",
    }
    return syn.get(t, t)


# ---------- 管理后台 CRUD ----------

@router.get("/admin/land-prices", response_model=ApiResponse)
def list_land_prices(
    province: str | None = None,
    city: str | None = None,
    land_type: str | None = None,
    user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    q = select(LandPriceRef)
    if province:
        q = q.where(LandPriceRef.province == province)
    if city:
        q = q.where(LandPriceRef.city == city)
    if land_type:
        q = q.where(LandPriceRef.land_type == _normalize_land_type(land_type))
    q = q.order_by(LandPriceRef.province, LandPriceRef.city, LandPriceRef.land_type)
    rows = db.scalars(q).all()
    return ok({"records": [_to_dict(r) for r in rows], "count": len(rows)})


@router.post("/admin/land-prices", response_model=ApiResponse)
def create_land_price(req: LandPriceCreate, user: User = Depends(require_land_price_perm), db: Session = Depends(get_db)):
    if req.price_lo > req.price_hi:
        req.price_lo, req.price_hi = req.price_hi, req.price_lo
    r = LandPriceRef(
        province=req.province, city=req.city, district=req.district,
        land_type=_normalize_land_type(req.land_type),
        price_lo=req.price_lo, price_hi=req.price_hi,
        source=req.source or "人工录入", effective_date=req.effective_date, note=req.note,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return ok(_to_dict(r), "已新增")


@router.put("/admin/land-prices/{rid}", response_model=ApiResponse)
def update_land_price(rid: int, req: LandPriceUpdate, user: User = Depends(require_land_price_perm), db: Session = Depends(get_db)):
    r = db.get(LandPriceRef, rid)
    if r is None:
        raise err("记录不存在", http_status=404)
    data = req.model_dump(exclude_unset=True)
    for k, v in data.items():
        if k == "land_type" and v:
            v = _normalize_land_type(v)
        setattr(r, k, v)
    if r.price_lo and r.price_hi and r.price_lo > r.price_hi:
        r.price_lo, r.price_hi = r.price_hi, r.price_lo
    db.commit()
    db.refresh(r)
    return ok(_to_dict(r), "已更新")


@router.delete("/admin/land-prices/{rid}", response_model=ApiResponse)
def delete_land_price(rid: int, user: User = Depends(require_land_price_admin), db: Session = Depends(get_db)):
    r = db.get(LandPriceRef, rid)
    if r is None:
        raise err("记录不存在", http_status=404)
    db.delete(r)
    db.commit()
    return ok(None, "已删除")


# ---------- 批量导入 ----------

@router.post("/admin/land-prices/import", response_model=ApiResponse)
async def import_land_prices(
    text: str | None = None,
    files: list[UploadFile] = File(default=[]),
    user: User = Depends(require_land_price_perm),
    db: Session = Depends(get_db),
):
    """批量导入：粘贴文本（text 参数）或上传 Word/Excel/图片（files 参数），自动解析归类"""
    records: list[dict] = []
    parse_errors: list[str] = []

    # 1) 粘贴文本
    if text and text.strip():
        records.extend(parse_text_lines(text))

    # 2) 文件（Word/Excel/图片；PDF 暂不支持——用户确认去掉）
    for f in files:
        filename = f.filename or "upload"
        ext = os.path.splitext(filename)[1].lower()
        data = await f.read()
        if len(data) > 20 * 1024 * 1024:
            parse_errors.append(f"{filename}: 文件过大")
            continue
        os.makedirs(settings.upload_dir, exist_ok=True)
        safe = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", filename)
        path = os.path.join(settings.upload_dir, f"landprice_{safe}")
        with open(path, "wb") as fp:
            fp.write(data)
        try:
            if ext in (".xlsx", ".xls"):
                from ..services.excel_parser import parse_excel

                rows, mapping, unmapped = parse_excel(data, filename)
                recs = parse_excel_rows(rows)
                if not recs:
                    parse_errors.append(f"{filename}: 未解析到有效记录（需含 地区/土地性质/单价 列）")
                records.extend(recs)
            elif ext == ".docx":
                text_content = extract_text_from_docx(path)
                recs = parse_text_lines(text_content) if text_content else []
                if not recs:
                    parse_errors.append(f"{filename}: 未解析到有效记录")
                records.extend(recs)
            elif ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
                # 图片：OCR 提取文字后解析（RapidOCR 离线引擎）
                from ..services.supplement_parser import extract_text_from_file

                text_content = extract_text_from_file(path, "png") or ""
                recs = parse_text_lines(text_content) if text_content else []
                if not recs:
                    parse_errors.append(f"{filename}: 图片未识别到有效记录（请确保图片清晰）")
                records.extend(recs)
            elif ext in (".txt", ".md", ".csv"):
                content = data.decode("utf-8", errors="ignore")
                recs = parse_text_lines(content)
                if not recs:
                    parse_errors.append(f"{filename}: 未解析到有效记录")
                records.extend(recs)
            else:
                parse_errors.append(f"{filename}: 不支持的文件格式（支持 Excel/Word/图片/TXT）")
        except Exception as e:  # noqa: BLE001
            logger.exception("land price import failed: %s", filename)
            parse_errors.append(f"{filename}: 解析失败（{str(e)[:80]}）")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    # 3) 写入数据库
    saved = 0
    skipped = 0
    for rec in records:
        try:
            r = LandPriceRef(
                province=rec.get("province"), city=rec.get("city"), district=rec.get("district"),
                land_type=_normalize_land_type(rec["land_type"]),
                price_lo=rec["price_lo"], price_hi=rec["price_hi"],
                source=rec.get("source"), effective_date=rec.get("effective_date"),
                note=rec.get("note"),
            )
            db.add(r)
            saved += 1
        except Exception:  # noqa: BLE001
            skipped += 1
    db.commit()
    return ok({
        "saved": saved,
        "parsed": len(records),
        "skipped": skipped,
        "parse_errors": parse_errors[:20],
        "preview": records[:5],
    }, f"导入完成：成功 {saved} 条")


# ---------- 估价引擎匹配 ----------

@router.post("/land-price/match", response_model=ApiResponse)
def match_price(req: LandPriceMatchRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """估价引擎调用：按地区+土地性质匹配参考价（未命中返回 null）"""
    matched = match_land_price(db, req.region, req.land_type)
    return ok({"matched": matched})
