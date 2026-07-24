import enum
from datetime import date, datetime
from decimal import Decimal

from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class InstitutionType(str, enum.Enum):
    DOMESTIC_BANK = "DOMESTIC_BANK"
    FOREIGN_BANK = "FOREIGN_BANK"
    MARKET_MAKER = "MARKET_MAKER"


class QuoteStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class TradeStatus(str, enum.Enum):
    QUOTED = "QUOTED"
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    CLEARED = "CLEARED"
    CANCELLED = "CANCELLED"


class TradeType(str, enum.Enum):
    SPOT = "SPOT"
    FORWARD = "FORWARD"


class TradeDirection(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    inst_type: Mapped[InstitutionType] = mapped_column(
        Enum(InstitutionType), nullable=False
    )
    country: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    limits: Mapped[list["InstitutionLimit"]] = relationship(
        back_populates="institution", cascade="all, delete-orphan"
    )


class CurrencyPair(Base):
    __tablename__ = "currency_pairs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    limits: Mapped[list["InstitutionLimit"]] = relationship(back_populates="currency_pair")


class InstitutionLimit(Base):
    __tablename__ = "institution_limits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    institution_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("institutions.id"), nullable=False
    )
    currency_pair_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("currency_pairs.id"), nullable=False
    )
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    exposure_limit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    used_credit: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=Decimal("0"), nullable=False
    )
    net_exposure: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), default=Decimal("0"), nullable=False
    )

    institution: Mapped["Institution"] = relationship(back_populates="limits")
    currency_pair: Mapped["CurrencyPair"] = relationship(back_populates="limits")


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    institution_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("institutions.id"), nullable=False
    )
    currency_pair_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("currency_pairs.id"), nullable=False
    )
    bid_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    ask_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    bid_original: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    ask_original: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    bid_available: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    ask_available: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[QuoteStatus] = mapped_column(
        Enum(QuoteStatus), default=QuoteStatus.ACTIVE, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    institution: Mapped["Institution"] = relationship()
    currency_pair: Mapped["CurrencyPair"] = relationship()


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quote_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quotes.id"), nullable=False
    )
    initiator_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("institutions.id"), nullable=False
    )
    counterparty_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("institutions.id"), nullable=False
    )
    currency_pair_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("currency_pairs.id"), nullable=False
    )
    direction: Mapped[TradeDirection] = mapped_column(
        Enum(TradeDirection), nullable=False
    )
    trade_type: Mapped[TradeType] = mapped_column(Enum(TradeType), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    forward_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    status: Mapped[TradeStatus] = mapped_column(
        Enum(TradeStatus), default=TradeStatus.QUOTED, nullable=False
    )
    reject_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    quote: Mapped["Quote"] = relationship()
    initiator: Mapped["Institution"] = relationship(foreign_keys=[initiator_id])
    counterparty: Mapped["Institution"] = relationship(foreign_keys=[counterparty_id])
    currency_pair: Mapped["CurrencyPair"] = relationship()


class ClearingReport(Base):
    __tablename__ = "clearing_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    institution_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("institutions.id"), nullable=False
    )
    currency_pair_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("currency_pairs.id"), nullable=False
    )
    buy_volume: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    sell_volume: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    net_volume: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    trade_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    institution: Mapped["Institution"] = relationship()
    currency_pair: Mapped["CurrencyPair"] = relationship()
