"""债权重复检测服务

用户需求（2026-08-25 确认）：
1. 重复上传同一债权表 → 提醒文件已存在，建议去我的任务查看
2. 同一表内债务人重名 → 提醒已有该条，建议去我的报告查看；同表重复只能勾选一个
3. 不同表之间债务人重名 → 允许上传，但只允许勾选第一次上传的那条
4. 不同方式（粘贴/链接/表）与任务/报告中的债务人重复 → 下一步时提醒；批量粘贴重复剔除

判定标准：债务人名称一致即视为重复（用户确认，不比较金额）。
"""
import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Claim, Report, Task

logger = logging.getLogger(__name__)


def _norm_name(name: str | None) -> str:
    """归一化债务人名称：去空白/全角空格，取主要部分"""
    if not name:
        return ""
    s = str(name).strip().replace("　", "").replace(" ", "")
    # 去掉常见的状态后缀（（在业）/（存续）等），避免误判
    s = re.sub(r"[（(].{1,6}[)）]", "", s)
    return s


def _names_match(a: str | None, b: str | None) -> bool:
    """两名称是否视为同一债务人"""
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # 包含关系（如 青岛XX公司 与 青岛XX公司（在业））
    if na in nb or nb in na:
        return True
    return False


def detect_duplicates(db: Session, user_id: int, incoming: list[dict]) -> dict:
    """检测本次导入债权与 同批/历史 的重复情况。

    Args:
        incoming: 本次导入的债权字段列表 [{id, debtor_name, ...}]（含已入库的 id）

    Returns:
        {
          "batch_dups": [{"id":.., "debtor_name":.., "dup_with":..}],  # 同批内重复（后出现的）
          "existing_dups": [{"id":.., "debtor_name":.., "first_source":..}],  # 与历史债权重复
          "file_duplicate": bool,  # 本次上传文件是否重复
        }
    """
    # 同批重复：按归一化名分组，保留第一条，其余标记
    batch_map: dict[str, list[dict]] = {}
    for c in incoming:
        key = _norm_name(c.get("debtor_name"))
        if key:
            batch_map.setdefault(key, []).append(c)
    batch_dups = []
    for key, items in batch_map.items():
        if len(items) > 1:
            for extra in items[1:]:
                batch_dups.append({
                    "id": extra.get("id"),
                    "debtor_name": extra.get("debtor_name"),
                    "dup_with": items[0].get("debtor_name"),
                    "first_id": items[0].get("id"),
                })

    # 与历史债权重复：查询该用户全部历史债权（排除本次入库的）
    incoming_ids = {c.get("id") for c in incoming if c.get("id")}
    history = db.scalars(
        select(Claim).where(Claim.user_id == user_id)
    ).all()
    existing_dups = []
    for c in incoming:
        if c.get("id") in incoming_ids and any(_names_match(c.get("debtor_name"), h.debtor_name) and h.id != c.get("id") for h in history if h.id not in incoming_ids):
            # 找首次来源（该同名债务人的最早债权在哪个任务/报告）
            first = None
            for h in history:
                if h.id in incoming_ids:
                    continue
                if _names_match(c.get("debtor_name"), h.debtor_name):
                    first = h
                    break
            src = _locate_claim_source(db, first) if first else "历史记录"
            existing_dups.append({
                "id": c.get("id"),
                "debtor_name": c.get("debtor_name"),
                "first_source": src,
                # 是否已真正发起过尽调（有任务/报告）——仅这类才拦截；只导入未尽调只是提示
                "started": bool(first and _claim_has_task_or_report(db, first)),
            })
        elif c.get("id") not in incoming_ids:
            # 纯文本粘贴（尚未入库）情况：与历史比较
            for h in history:
                if _names_match(c.get("debtor_name"), h.debtor_name):
                    src = _locate_claim_source(db, h)
                    existing_dups.append({
                        "id": c.get("id"),
                        "debtor_name": c.get("debtor_name"),
                        "first_source": src,
                        "started": bool(_claim_has_task_or_report(db, h)),
                    })
                    break

    return {"batch_dups": batch_dups, "existing_dups": existing_dups}


def _claim_has_task_or_report(db: Session, claim: Claim) -> bool:
    """该历史债权是否已发起过尽调（进入过任务或生成过报告）"""
    from ..models import Report, Task

    t = db.scalar(select(Task).where(Task.claim_ids.contains(f'"{claim.id}"')))
    if t:
        return True
    r = db.scalar(select(Report).where(Report.claim_id == claim.id))
    return r is not None


def _locate_claim_source(db: Session, claim: Claim) -> str:
    """定位债权首次出现的位置（任务/报告）"""
    from ..models import Task

    t = db.scalar(select(Task).where(Task.claim_ids.contains(f'"{claim.id}"')))
    if t:
        return f"任务#{t.id}"
    r = db.scalar(select(Report).where(Report.claim_id == claim.id))
    if r:
        return f"报告#{r.id}"
    return "历史记录"


def check_file_duplicate(db: Session, user_id: int, filename: str, fingerprint: str | None) -> bool:
    """检测该用户是否上传过相同文件（同名 + 同指纹）"""
    if not fingerprint:
        return False
    from ..models import Claim

    # 该用户是否存在 source_raw 同名 且 extra 指纹相同的债权
    claims = db.scalars(
        select(Claim).where(Claim.user_id == user_id, Claim.source_raw == filename)
    ).all()
    for c in claims:
        import json
        try:
            extra = json.loads(c.extra_fields) if c.extra_fields else {}
        except Exception:
            extra = {}
        if extra.get("file_fingerprint") == fingerprint:
            return True
    return False
