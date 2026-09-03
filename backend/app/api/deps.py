"""依赖：获取当前登录用户"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..services.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def require_editor(user: User = Depends(get_current_user)) -> User:
    """运营编辑（editor）或管理员（admin）可访问"""
    if user.role not in ("editor", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要运营编辑权限")
    return user


def require_land_price_perm(user: User = Depends(get_current_user)) -> User:
    """土地价格库录入权限：admin 或（editor 且 land_price_perm=True）"""
    if user.role == "admin":
        return user
    if user.role == "editor" and getattr(user, "land_price_perm", False):
        return user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无土地价格库录入权限（请联系管理员开通）")


def require_land_price_admin(user: User = Depends(get_current_user)) -> User:
    """土地价格库删除权限：仅 admin"""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可删除土地价格记录")
    return user
