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
# 运营编辑（editor）可维护的栏目：精选债权 + 热门捡漏 + 债权公告（债权公告本质是业务版块以公告形式展示）
EDITOR_SECTIONS = ["featured", "bargain", "notice"]


def _check_editor_section(operator: User, section: str) -> None:
    """运营编辑只能操作精选债权/热门捡漏/债权公告；管理员不限"""
    if operator.role == "editor" and section not in EDITOR_SECTIONS:
        raise err(f"运营编辑仅可维护『精选债权/热门捡漏/债权公告』栏目，{section} 为抓取数据不可编辑")


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
        "is_active": item.is_active,
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


@router.get("/search", response_model=ApiResponse)
def search_feed(q: str = "", db: Session = Depends(get_db)):
    """站内搜索：模糊匹配精选债权/热门捡漏/债权公告（标题/简介/债务人/抵押物/地区/标签）

    返回按栏目分组的结果 + 命中信息；无结果时前端展示引导页。
    """
    q = (q or "").strip()
    if not q:
        return ok({"query": "", "groups": {}, "total": 0})
    items = db.scalars(
        select(FeedItem).where(FeedItem.is_active == 1, FeedItem.section.in_(["featured", "bargain", "notice"]))
    ).all()

    def _detail_text(it: FeedItem) -> str:
        d = json.loads(it.detail_json) if it.detail_json else {}
        parts = [it.title or "", it.summary or "", json.dumps(d, ensure_ascii=False)]
        try:
            tags = json.loads(it.tags) if it.tags else []
            parts.extend(tags)
        except Exception:
            pass
        return " ".join(parts)

    def _hit_score(it: FeedItem) -> tuple[int, int]:
        """返回 (标题是否命中, 综合分)：标题命中优先，其次简介/债务人/标签"""
        title = it.title or ""
        text = _detail_text(it)
        if q in title:
            return (1, 100)
        if q in text:
            return (0, 50)
        return (0, 0)

    groups: dict[str, list[dict]] = {}
    for it in items:
        head, score = _hit_score(it)
        if score == 0:
            continue
        d = _item_to_dict(it)
        d["_hit"] = {"head": bool(head), "score": score}
        groups.setdefault(it.section, []).append(d)
    # 每组内按命中度排序
    for sec in groups:
        groups[sec].sort(key=lambda x: (-x["_hit"]["head"], -x["_hit"]["score"]))
        for g in groups[sec]:
            g.pop("_hit", None)
    total = sum(len(v) for v in groups.values())
    return ok({"query": q, "groups": groups, "total": total})


@router.get("/feed/{item_id}", response_model=ApiResponse)
def get_feed_detail(item_id: int, db: Session = Depends(get_db)):
    item = db.get(FeedItem, item_id)
    if item is None or item.is_active != 1:
        raise err("内容不存在", http_status=404)
    return ok(_item_to_dict(item))


# ---- 管理后台（editor 及以上；editor 仅精选/捡漏栏目）----

@router.post("/admin/feed/sync-jd", response_model=ApiResponse)
def sync_jd_credit(operator: User = Depends(require_editor)):
    """手动触发京东债权招商 + 破产捡漏抓取 → 精选债权/捡漏（editor 及以上）"""
    from ..scrapers.jd_credit import sync_jd_credit_to_feed
    result = sync_jd_credit_to_feed()
    return ok(result, f"同步完成：精选新增 {result.get('fetched_featured', 0)} 条，捡漏新增 {result.get('fetched_bargain', 0)} 条")


@router.post("/admin/feed/sync-taobao", response_model=ApiResponse)
def sync_taobao_credit(operator: User = Depends(require_editor)):
    """阿里资产抓取已停用（2026-09-05 用户拍板：阿里精选整类删除，阿里详情仅列表级一句话内容，
    登录后仍无正文——宁缺毋滥；保留接口返回空统计，避免旧前端/脚本报错）"""
    return ok({"fetched_featured": 0, "fetched_bargain": 0, "dropped_incomplete": 0,
               "featured_total": 0, "bargain_total": 0}, "阿里资产数据源已停用")


@router.post("/admin/feed/sync-amc", response_model=ApiResponse)
def sync_amc_notices(operator: User = Depends(require_editor)):
    """手动触发五大 AMC（长城/中信金融/信达/东方）资产处置公告抓取 → 债权公告栏目（editor 及以上）"""
    from ..scrapers.amc_scraper import sync_amc_notices_to_feed
    result = sync_amc_notices_to_feed()
    amcs = result.get("amcs") or {}
    parts = [f"{name} 列表{k.get('list', 0)}条/新增{k.get('new', 0)}条" for name, k in amcs.items()]
    return ok(result, f"AMC 公告同步完成：{'；'.join(parts)}")


@router.post("/admin/feed/sync-all", response_model=ApiResponse)
def sync_all_credit(operator: User = Depends(require_editor)):
    """一键同步京东债权信息（精选 + 捡漏）→ 首页栏目（editor 及以上）。
    2026-09-05：阿里资产已整类停用（详情仅列表级一句话内容），不再并入 sync-all"""
    from ..scrapers.jd_credit import sync_jd_credit_to_feed
    r1 = sync_jd_credit_to_feed()
    feat = r1.get("fetched_featured", 0)
    bg = r1.get("fetched_bargain", 0)
    return ok(
        {"jd": r1, "fetched_featured": feat, "fetched_bargain": bg,
         "featured_total": r1.get("featured_total", 0),
         "bargain_total": r1.get("bargain_total", 0)},
        f"同步完成：精选债权新增 {feat} 条，捡漏新增 {bg} 条",
    )


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


@router.get("/admin/feed-items", response_model=ApiResponse)
def list_admin_feed_items(
    section: str | None = None,
    operator: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """管理后台栏目列表：按操作者角色过滤栏目（editor 仅 featured/bargain），包含已下架记录"""
    q = select(FeedItem)
    if operator.role == "editor":
        q = q.where(FeedItem.section.in_(EDITOR_SECTIONS))
    elif section and section in SECTIONS:
        q = q.where(FeedItem.section == section)
    q = q.order_by(FeedItem.id.desc())
    items = db.scalars(q).all()
    return ok({"items": [_item_to_dict(i) for i in items]})


@router.post("/admin/feed/{item_id}/toggle", response_model=ApiResponse)
def toggle_feed_item(item_id: int, operator: User = Depends(require_editor), db: Session = Depends(get_db)):
    """下架/上架切换：已上架→下架，已下架→上架"""
    item = db.get(FeedItem, item_id)
    if item is None:
        raise err("内容不存在", http_status=404)
    _check_editor_section(operator, item.section)
    item.is_active = 0 if item.is_active == 1 else 1
    db.commit()
    db.refresh(item)
    return ok(_item_to_dict(item), "已上架" if item.is_active == 1 else "已下架")


@router.delete("/admin/feed/{item_id}", response_model=ApiResponse)
def delete_feed_item(item_id: int, operator: User = Depends(require_editor), db: Session = Depends(get_db)):
    item = db.get(FeedItem, item_id)
    if item is None:
        raise err("内容不存在", http_status=404)
    _check_editor_section(operator, item.section)
    item.is_active = 0  # 软删除
    db.commit()
    return ok(None, "已下架")


# ---------- 京东债权页面增强：属性回填 + 附件下载关联（2026-09-01） ----------

@router.post("/admin/feed/{item_id}/enrich-jd", response_model=ApiResponse)
def enrich_jd_feed_item(item_id: int, operator: User = Depends(require_editor), db: Session = Depends(get_db)):
    """京东债权页面增强：渲染真实页面 → 提取「标的物属性」回填 + 下载信息类附件到服务器并关联。

    说明：queryProductDescription 接口的 HTML 常缺附件与属性，须渲染浏览器页面；
    附件（资产清单/判决书等）下载保存后与债权关联，尽调页可下载。
    """
    item = db.get(FeedItem, item_id)
    if item is None:
        raise err("内容不存在", http_status=404)
    if item.source != "京东拍卖":
        raise err("仅京东拍卖债权支持页面增强", http_status=400)

    detail = json.loads(item.detail_json) if item.detail_json else {}
    try:
        from ..services.jd_attachment import enrich_jd_claim
        new_detail = enrich_jd_claim(item.id, item.source_url or "", detail)
        item.detail_json = json.dumps(new_detail, ensure_ascii=False)
        db.commit()
        atts = new_detail.get("attachments") or []
        return ok({
            "attachments": [{"name": a.get("name"), "type": a.get("type"), "local": bool(a.get("local_path"))} for a in atts],
            "claim_total": new_detail.get("claim_total"),
            "collateral_type": new_detail.get("collateral_type"),
            "guaranty_type": new_detail.get("guaranty_type"),
            "has_collateral": new_detail.get("has_collateral"),
        }, f"页面增强完成：附件 {len(atts)} 个，属性已回填")
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("enrich-jd failed for %s", item_id)
        raise err(f"页面增强失败：{e}")


@router.get("/feed/{item_id}/attachments/{att_index}", response_model=ApiResponse)
def download_feed_attachment(item_id: int, att_index: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """下载债权关联附件（需登录）：按 detail.attachments 索引返回本地文件

    用 FileResponse 直接返回文件流；路径必须来自 detail.attachments 的 local_path（防目录穿越）。
    """
    import os
    from fastapi.responses import FileResponse

    item = db.get(FeedItem, item_id)
    if item is None or item.is_active != 1:
        raise err("内容不存在", http_status=404)
    detail = json.loads(item.detail_json) if item.detail_json else {}
    atts = detail.get("attachments") or []
    if att_index < 0 or att_index >= len(atts):
        raise err("附件不存在", http_status=404)
    att = atts[att_index]
    local = att.get("local_path")
    # 路径兜底：local_path 可能因 cwd 不同而前缀错位（如 Q:\deepseek\data 而非 backend\data），
    # 统一以 upload_dir 为基准解析（2026-09-01）
    if not local or not os.path.exists(local):
        from ..config import get_settings as _gs
        base = os.path.abspath(_gs().upload_dir)
        # 尝试从 upload_dir 下找 feed_attachments/{id}/<文件名>
        fname = os.path.basename(local) if local else ""
        if fname:
            candidate = os.path.join(base, "feed_attachments", str(item_id), fname)
            if os.path.exists(candidate):
                local = candidate
    if not local or not os.path.exists(local):
        raise err("附件文件不存在（可能已清理），请查看原始公告", http_status=404)
    return FileResponse(local, filename=att.get("name") or os.path.basename(local))
