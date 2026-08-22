"""Pydantic schemas：债权"""
from datetime import date

from pydantic import BaseModel, Field


class ClaimCreate(BaseModel):
    source_type: str = Field(pattern="^(text|link|excel)$")
    source_raw: str | None = None
    source_url: str | None = None
    debtor_name: str | None = None
    principal_cents: int | None = None
    interest_cents: int | None = None
    fees_cents: int | None = None
    guaranty_type: str | None = None
    guarantor: str | None = None
    collateral: str | None = None
    judicial_status: str | None = None
    listing_price_cents: int | None = None
    deadline: str | None = None


class ClaimUpdate(BaseModel):
    """预处理确认页内联编辑"""

    debtor_name: str | None = None
    principal_cents: int | None = None
    interest_cents: int | None = None
    fees_cents: int | None = None
    guaranty_type: str | None = None
    guarantor: str | None = None
    collateral: str | None = None
    judicial_status: str | None = None
    listing_price_cents: int | None = None
    deadline: str | None = None


class ClaimOut(BaseModel):
    id: int
    source_type: str
    debtor_name: str | None
    principal_cents: int | None
    interest_cents: int | None
    fees_cents: int | None
    guaranty_type: str | None
    guarantor: str | None
    collateral: str | None
    judicial_status: str | None
    listing_price_cents: int | None
    deadline: str | None
    debtor_type: str | None
    completeness: str | None
    missing_fields: list | None = None
    extra_fields: dict | None = None

    model_config = {"from_attributes": True}


class ImportTextRequest(BaseModel):
    text: str = Field(min_length=10)


class ImportLinkRequest(BaseModel):
    url: str = Field(min_length=8)


class ImportExcelResponse(BaseModel):
    claims: list[ClaimOut]
    column_mapping: dict | None = None
    unmapped_columns: list[str] | None = None
