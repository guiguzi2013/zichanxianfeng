"""Pydantic schemas：任务与报告"""
from datetime import datetime

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    claim_ids: list[int] = Field(min_length=1, max_length=5)


class TaskOut(BaseModel):
    id: int
    claim_ids: list[int]
    status: str
    current_node: str | None
    progress: int
    points_est: int
    error: str | None
    created_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class ReportOut(BaseModel):
    id: int
    task_id: int
    claim_id: int
    version: int
    content: dict | None
    pdf_path: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SectionNoteRequest(BaseModel):
    section: str
    note: str
