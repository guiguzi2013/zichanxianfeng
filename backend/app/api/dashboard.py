"""首页市场看板：公开查询 + 管理后台维护（拍卖平台 / AMC / 宏观KPI）

公开接口：
  GET /api/home/dashboard  → 宏观数据条 + KPI 卡片 + 拍卖平台表 + AMC 排行

管理接口（/api/admin/...，需管理员）：
  macro-kpis / auction-stats / amc-stats 三组 CRUD，全部写审计日志
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AmcStat, AuctionStat, MacroKpi, User
from ..schemas.common import ApiResponse, err, ok
from ..services.audit import write_audit_log
from .deps import require_admin

router = APIRouter(tags=["dashboard"])


# ---------- 请求模型 ----------

class MacroKpiCreate(BaseModel):
    category: str = Field(pattern="^(macro|kpi)$")
    label: str = Field(min_length=1, max_length=50)
    value: str = Field(min_length=1, max_length=30)
    unit: str = Field(default="", max_length=10)
    trend: str = Field(default="", max_length=50)
    trend_up: int = Field(default=1, ge=0, le=1)
    sort: int = Field(default=0)
    source: str = Field(default="", max_length=100)


class AuctionStatCreate(BaseModel):
    platform: str = Field(min_length=1, max_length=100)
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    on_auction: int = Field(default=0, ge=0)
    sold: int = Field(default=0, ge=0)
    amount: float = Field(default=0, ge=0)


class AmcStatCreate(BaseModel):
    org_name: str = Field(min_length=1, max_length=150)
    scope: str = Field(pattern="^(national|local)$")
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    listed_count: int = Field(default=0, ge=0)
    market_share: float = Field(default=0, ge=0)
    trend: str = Field(default="flat", pattern="^(up|down|flat)$")


# ---------- 序列化 ----------

def _macro_to_dict(m: MacroKpi) -> dict:
    return {
        "id": m.id, "category": m.category, "label": m.label, "value": m.value,
        "unit": m.unit, "trend": m.trend, "trend_up": bool(m.trend_up),
        "sort": m.sort, "source": m.source,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def _auction_to_dict(a: AuctionStat) -> dict:
    return {
        "id": a.id, "platform": a.platform, "period": a.period,
        "on_auction": a.on_auction, "sold": a.sold, "amount": a.amount,
        "sold_rate": round(a.sold / a.on_auction * 100, 1) if a.on_auction else 0,
    }


def _amc_to_dict(a: AmcStat) -> dict:
    return {
        "id": a.id, "org_name": a.org_name, "scope": a.scope, "period": a.period,
        "listed_count": a.listed_count, "market_share": a.market_share, "trend": a.trend,
    }


# ---------- 公开看板 ----------

@router.get("/home/dashboard", response_model=ApiResponse)
def get_dashboard(db: Session = Depends(get_db)):
    """首页看板：宏观数据条 + KPI + 拍卖平台 + AMC 排行（无数据时返回空列表，前端回退演示数据）"""
    macro = db.scalars(
        select(MacroKpi).where(MacroKpi.category == "macro").order_by(MacroKpi.sort, MacroKpi.id)
    ).all()
    kpis = db.scalars(
        select(MacroKpi).where(MacroKpi.category == "kpi").order_by(MacroKpi.sort, MacroKpi.id)
    ).all()

    # 拍卖平台：取最新统计周期的数据
    latest_period = db.scalar(select(func.max(AuctionStat.period)))
    auction = []
    if latest_period:
        auction = db.scalars(
            select(AuctionStat).where(AuctionStat.period == latest_period).order_by(AuctionStat.amount.desc())
        ).all()

    # AMC：取最新周期，按 全国/地方 分组
    amc_period = db.scalar(select(func.max(AmcStat.period)))
    amc = {"national": [], "local": []}
    if amc_period:
        rows = db.scalars(
            select(AmcStat).where(AmcStat.period == amc_period).order_by(AmcStat.market_share.desc())
        ).all()
        for r in rows:
            amc[r.scope if r.scope in amc else "national"].append(_amc_to_dict(r))

    return ok({
        "macro": [_macro_to_dict(m) for m in macro],
        "kpis": [_macro_to_dict(k) for k in kpis],
        "auction": [_auction_to_dict(a) for a in auction],
        "amc": amc,
        "latest_period": latest_period or amc_period,
    })


# ---------- 管理后台 CRUD ----------

@router.get("/admin/macro-kpis", response_model=ApiResponse)
def list_macro_kpis(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    items = db.scalars(select(MacroKpi).order_by(MacroKpi.category, MacroKpi.sort, MacroKpi.id)).all()
    return ok({"items": [_macro_to_dict(m) for m in items]})


@router.post("/admin/macro-kpis", response_model=ApiResponse)
def create_macro_kpi(req: MacroKpiCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = MacroKpi(**req.model_dump())
    db.add(item)
    write_audit_log(db, admin.id, "macro_kpi", "create", change_summary={"label": req.label, "value": req.value})
    db.commit()
    db.refresh(item)
    return ok(_macro_to_dict(item), "已保存")


@router.put("/admin/macro-kpis/{item_id}", response_model=ApiResponse)
def update_macro_kpi(item_id: int, req: MacroKpiCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(MacroKpi, item_id)
    if item is None:
        raise err("记录不存在", http_status=404)
    for field, value in req.model_dump().items():
        setattr(item, field, value)
    write_audit_log(db, admin.id, "macro_kpi", "update", entity_id=item_id, change_summary={"label": req.label})
    db.commit()
    db.refresh(item)
    return ok(_macro_to_dict(item), "已更新")


@router.delete("/admin/macro-kpis/{item_id}", response_model=ApiResponse)
def delete_macro_kpi(item_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(MacroKpi, item_id)
    if item is None:
        raise err("记录不存在", http_status=404)
    write_audit_log(db, admin.id, "macro_kpi", "delete", entity_id=item_id, change_summary={"label": item.label})
    db.delete(item)
    db.commit()
    return ok(None, "已删除")


@router.get("/admin/auction-stats", response_model=ApiResponse)
def list_auction_stats(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    items = db.scalars(select(AuctionStat).order_by(AuctionStat.period.desc(), AuctionStat.id)).all()
    return ok({"items": [_auction_to_dict(a) for a in items]})


@router.post("/admin/auction-stats", response_model=ApiResponse)
def create_auction_stat(req: AuctionStatCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = AuctionStat(**req.model_dump())
    db.add(item)
    write_audit_log(db, admin.id, "auction_stat", "create", change_summary={"platform": req.platform, "period": req.period})
    db.commit()
    db.refresh(item)
    return ok(_auction_to_dict(item), "已保存")


@router.put("/admin/auction-stats/{item_id}", response_model=ApiResponse)
def update_auction_stat(item_id: int, req: AuctionStatCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(AuctionStat, item_id)
    if item is None:
        raise err("记录不存在", http_status=404)
    for field, value in req.model_dump().items():
        setattr(item, field, value)
    write_audit_log(db, admin.id, "auction_stat", "update", entity_id=item_id, change_summary={"platform": req.platform})
    db.commit()
    db.refresh(item)
    return ok(_auction_to_dict(item), "已更新")


@router.delete("/admin/auction-stats/{item_id}", response_model=ApiResponse)
def delete_auction_stat(item_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(AuctionStat, item_id)
    if item is None:
        raise err("记录不存在", http_status=404)
    write_audit_log(db, admin.id, "auction_stat", "delete", entity_id=item_id, change_summary={"platform": item.platform})
    db.delete(item)
    db.commit()
    return ok(None, "已删除")


@router.get("/admin/amc-stats", response_model=ApiResponse)
def list_amc_stats(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    items = db.scalars(select(AmcStat).order_by(AmcStat.period.desc(), AmcStat.scope, AmcStat.market_share.desc())).all()
    return ok({"items": [_amc_to_dict(a) for a in items]})


@router.post("/admin/amc-stats", response_model=ApiResponse)
def create_amc_stat(req: AmcStatCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = AmcStat(**req.model_dump())
    db.add(item)
    write_audit_log(db, admin.id, "amc_stat", "create", change_summary={"org_name": req.org_name, "scope": req.scope})
    db.commit()
    db.refresh(item)
    return ok(_amc_to_dict(item), "已保存")


@router.put("/admin/amc-stats/{item_id}", response_model=ApiResponse)
def update_amc_stat(item_id: int, req: AmcStatCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(AmcStat, item_id)
    if item is None:
        raise err("记录不存在", http_status=404)
    for field, value in req.model_dump().items():
        setattr(item, field, value)
    write_audit_log(db, admin.id, "amc_stat", "update", entity_id=item_id, change_summary={"org_name": req.org_name})
    db.commit()
    db.refresh(item)
    return ok(_amc_to_dict(item), "已更新")


@router.delete("/admin/amc-stats/{item_id}", response_model=ApiResponse)
def delete_amc_stat(item_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(AmcStat, item_id)
    if item is None:
        raise err("记录不存在", http_status=404)
    write_audit_log(db, admin.id, "amc_stat", "delete", entity_id=item_id, change_summary={"org_name": item.org_name})
    db.delete(item)
    db.commit()
    return ok(None, "已删除")
