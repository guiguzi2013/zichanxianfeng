"""统一响应格式与通用依赖"""
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel


class ApiResponse(BaseModel):
    code: int = 0
    data: Any | None = None
    message: str = "ok"


def ok(data: Any = None, message: str = "ok") -> ApiResponse:
    return ApiResponse(code=0, data=data, message=message)


def err(message: str, code: int = 1, http_status: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    """业务错误：返回统一结构（由异常处理器转为 ApiResponse）"""
    return HTTPException(status_code=http_status, detail={"code": code, "message": message})
