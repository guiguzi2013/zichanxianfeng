"""活动记录路由：我的任务-土地厂房估价/财产线索 分区块数据源"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas.common import ApiResponse, ok
from ..services.activity import list_activity
from .deps import get_current_user

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("", response_model=ApiResponse)
def get_activity(
    kind: str | None = None,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询活动记录（kind=valuation 土地厂房估价 / clue 财产线索）"""
    if kind not in (None, "valuation", "clue"):
        kind = None
    records = list_activity(db, user.id, kind=kind, limit=min(limit, 100))
    return ok({"records": records})
