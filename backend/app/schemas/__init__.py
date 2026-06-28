"""Pydantic request/response schemas for the API."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import AccountPlatform, AccountType


class TaxpayerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    tax_id: str | None = Field(None, max_length=32)


class TaxpayerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    tax_id: str | None = Field(None, max_length=32)


class TaxpayerOut(BaseModel):
    id: int
    name: str
    tax_id: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class AccountCreate(BaseModel):
    taxpayer_id: int
    name: str
    platform: AccountPlatform = AccountPlatform.MANUAL
    type: AccountType = AccountType.EXCHANGE
    is_abroad: bool = False
    country: str | None = None


class AccountOut(BaseModel):
    id: int
    taxpayer_id: int
    name: str
    platform: AccountPlatform
    type: AccountType
    is_abroad: bool
    country: str | None = None

    model_config = {"from_attributes": True}


class OpeningPositionIn(BaseModel):
    asset_symbol: str
    quantity: Decimal
    cost_basis_eur: Decimal
    acquired_at: datetime


class ManualSummaryIn(BaseModel):
    year: int
    net_gain_eur: Decimal = Field(default=Decimal("0"))
    income_total: Decimal = Field(default=Decimal("0"))
    savings_base: Decimal = Field(default=Decimal("0"))
    tax_due_eur: Decimal = Field(default=Decimal("0"))


class PriceQuoteIn(BaseModel):
    asset_symbol: str
    date: datetime
    price_eur: Decimal
    source: str = "manual"
