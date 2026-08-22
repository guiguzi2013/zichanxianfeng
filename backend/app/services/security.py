"""安全工具：密码哈希（bcrypt 直接调用，替代已停维护的 passlib）+ JWT"""
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from ..config import get_settings

settings = get_settings()


def hash_password(password: str) -> str:
    """bcrypt 哈希（passlib 与新版 bcrypt 不兼容，改用直接调用）"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "username": username, "role": role, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
