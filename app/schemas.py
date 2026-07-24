from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models import (
    InstitutionType,
    QuoteStatus,
    TradeDirection,
    TradeStatus,
    TradeType,
)


class InstitutionCreate(BaseModel):
    code: str = Field(..., max_length=20)
    name: str = Field(..., max_length=100)
    inst_type: InstitutionType
    country: str = Field(..., max_length=50)
    is_active: bool = True


class InstitutionOut(BaseModel):
    id: int
    code: str
    name: str
    inst_type: InstitutionType
    country: str
    is_active: bool

    model_config = {"from_attributes": True}


class CurrencyPairCreate(BaseModel):
    symbol: str = Field(..., max_length=20)
    base_currency: str = Field(..., max_length=3)
    quote_currency: str = Field(..., max_length=3)
    is_active: bool = True


class CurrencyPairOut(BaseModel):
    id: int
    symbol: str
    base_currency: str
    quote_currency: str
    is_active: bool

    model_config = {"from_attributes": True}


class InstitutionLimitCreate(BaseModel):
    institution_id: int
    currency_pair_id: int
    credit_limit: Decimal = Field(..., gt=0)
    exposure_limit: Decimal = Field(..., gt=0)


class InstitutionLimitOut(BaseModel):
    id: int
    institution_id: int
    currency_pair_id: int
    credit_limit: Decimal
    exposure_limit: Decimal
    used_credit: Decimal
    net_exposure: Decimal

    model_config = {"from_attributes": True}


class QuoteCreate(BaseModel):
    institution_id: int
    currency_pair_id: int
    bid_price: Decimal = Field(..., gt=0)
    ask_price: Decimal = Field(..., gt=0)
    bid_amount: Decimal = Field(..., gt=0)
    ask_amount: Decimal = Field(..., gt=0)
    valid_minutes: int = Field(60, gt=0)


class QuoteOut(BaseModel):
    id: int
    institution_id: int
    currency_pair_id: int
    bid_price: Decimal
    ask_price: Decimal
    bid_original: Decimal
    ask_original: Decimal
    bid_available: Decimal
    ask_available: Decimal
    valid_until: datetime
    status: QuoteStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class TradeCreate(BaseModel):
    quote_id: int
    initiator_id: int
    direction: TradeDirection
    trade_type: TradeType
    amount: Decimal = Field(..., gt=0)
    forward_date: Optional[date] = None


class TradeOut(BaseModel):
    id: int
    quote_id: int
    initiator_id: int
    counterparty_id: int
    currency_pair_id: int
    direction: TradeDirection
    trade_type: TradeType
    trade_date: date
    forward_date: Optional[date]
    amount: Decimal
    price: Decimal
    status: TradeStatus
    reject_reason: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClearingReportOut(BaseModel):
    id: int
    trade_date: date
    institution_id: int
    currency_pair_id: int
    buy_volume: Decimal
    sell_volume: Decimal
    net_volume: Decimal
    trade_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class RejectReasonDistribution(BaseModel):
    reject_reason: str
    count: int


class TradeStatistics(BaseModel):
    institution_id: Optional[int] = None
    currency_pair_id: Optional[int] = None
    total_trades: int
    executed_trades: int
    cancelled_trades: int
    total_volume: Decimal
    reject_reasons: list[RejectReasonDistribution]
