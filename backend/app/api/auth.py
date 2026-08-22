"""认证路由：注册 / 登录 / 刷新 / me / 改密码"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas.auth import LoginRequest, RegisterRequest, TokenOut, UserOut
from ..schemas.common import ApiResponse, err, ok
from .deps import get_current_user
from ..services.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=ApiResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    exists = db.scalar(select(User).where(User.username == req.username))
    if exists:
        raise err("用户名已存在", http_status=status.HTTP_409_CONFLICT)
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        nickname=req.nickname or req.username,
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok(UserOut.model_validate(user), "注册成功")


@router.post("/login", response_model=ApiResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == req.username))
    if user is None or not verify_password(req.password, user.password_hash):
        raise err("用户名或密码错误", http_status=status.HTTP_401_UNAUTHORIZED)
    token = create_access_token(user.id, user.username, user.role)
    return ok(TokenOut(access_token=token, user=UserOut.model_validate(user)).model_dump(), "登录成功")


@router.get("/me", response_model=ApiResponse)
def me(user: User = Depends(get_current_user)):
    return ok(UserOut.model_validate(user))


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=6, max_length=100)
    new_password: str = Field(min_length=6, max_length=100)


@router.post("/change-password", response_model=ApiResponse)
def change_password(req: ChangePasswordRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """修改密码（用户中心）"""
    if not verify_password(req.old_password, user.password_hash):
        raise err("原密码不正确", http_status=status.HTTP_400_BAD_REQUEST)
    user.password_hash = hash_password(req.new_password)
    db.commit()
    return ok(None, "密码已修改，请重新登录")
