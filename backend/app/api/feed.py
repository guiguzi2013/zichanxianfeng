"""首页栏目数据路由：公开查询 + 管理后台维护"""
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FeedItem, User
from ..schemas.common import ApiResponse, err, ok
from .deps import get_current_user, require_admin, require_editor

router = APIRouter(tags=["feed"])

# 栏目白名单
SECTIONS = ["featured", "bargain", "asset_revive", "amc", "auction", "notice"]
# 运营编辑（editor）可维护的栏目：仅精选债权 + 热门捡漏（其余为抓取数据，不动）
EDITOR_SECTIONS = ["featured", "bargain"]


def _check_editor_section(operator: User, section: str) -> None:
    """运营编辑只能操作精选债权/热门捡漏；管理员不限"""
    if operator.role == "editor" and section not in EDITOR_SECTIONS:
        raise err(f"运营编辑仅可维护『精选债权/热门捡漏』栏目，{section} 为抓取数据不可编辑")


class FeedItemCreate(BaseModel):
    section: str = Field(pattern="|".join(SECTIONS))
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = None
    tags: list[str] | None = None
    source: str | None = None
    source_url: str | None = None
    detail_json: dict | None = None


def _item_to_dict(item: FeedItem) -> dict:
    return {
        "id": item.id,
        "section": item.section,
        "title": item.title,
        "summary": item.summary,
        "tags": json.loads(item.tags) if item.tags else None,
        "source": item.source,
        "source_url": item.source_url,
        "detail": json.loads(item.detail_json) if item.detail_json else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("/feed", response_model=ApiResponse)
def get_feed(section: str | None = None, page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    """公开：首页栏目数据 + 分页（P1 前端接入）"""
    q = select(FeedItem).where(FeedItem.is_active == 1)
    if section:
        if section not in SECTIONS:
            raise err("未知栏目")
        q = q.where(FeedItem.section == section)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    items = db.scalars(
        q.order_by(FeedItem.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ok({
        "items": [_item_to_dict(i) for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    })


@router.get("/feed/{item_id}", response_model=ApiResponse)
def get_feed_detail(item_id: int, db: Session = Depends(get_db)):
    item = db.get(FeedItem, item_id)
    if item is None or item.is_active != 1:
        raise err("内容不存在", http_status=404)
    return ok(_item_to_dict(item))


# ---- 管理后台（editor 及以上；editor 仅精选/捡漏栏目）----

@router.post("/admin/feed", response_model=ApiResponse)
def create_feed_item(req: FeedItemCreate, operator: User = Depends(require_editor), db: Session = Depends(get_db)):
    _check_editor_section(operator, req.section)
    item = FeedItem(
        section=req.section,
        title=req.title,
        summary=req.summary,
        tags=json.dumps(req.tags, ensure_ascii=False) if req.tags else None,
        source=req.source,
        source_url=req.source_url,
        detail_json=json.dumps(req.detail_json, ensure_ascii=False) if req.detail_json else None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return ok(_item_to_dict(item), "已发布")


@router.put("/admin/feed/{item_id}", response_model=ApiResponse)
def update_feed_item(item_id: int, req: FeedItemCreate, operator: User = Depends(require_editor), db: Session = Depends(get_db)):
    item = db.get(FeedItem, item_id)
    if item is None:
        raise err("内容不存在", http_status=404)
    _check_editor_section(operator, item.section)
    item.section = req.section
    item.title = req.title
    item.summary = req.summary
    item.tags = json.dumps(req.tags, ensure_ascii=False) if req.tags else None
    item.source = req.source
    item.source_url = req.source_url
    item.detail_json = json.dumps(req.detail_json, ensure_ascii=False) if req.detail_json else None
    db.commit()
    db.refresh(item)
    return ok(_item_to_dict(item), "已更新")


@router.delete("/admin/feed/{item_id}", response_model=ApiResponse)
def delete_feed_item(item_id: int, operator: User = Depends(require_editor), db: Session = Depends(get_db)):
    item = db.get(FeedItem, item_id)
    if item is None:
        raise err("内容不存在", http_status=404)
    _check_editor_section(operator, item.section)
    item.is_active = 0  # 软删除
    db.commit()
    return ok(None, "已下架")
