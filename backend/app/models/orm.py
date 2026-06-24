"""SQLAlchemy ORM entities for Crypto-Trace.

Money is stored via :class:`DecimalText` (exact Decimal on SQLite). Quantities,
EUR amounts and per-unit prices all use it; the distinction is purely semantic.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import (
    AccountPlatform,
    AccountType,
    AssetKind,
    DisposalKind,
    FiscalYearStatus,
    ImportStatus,
    IncomeCategory,
    SummarySource,
    TransactionType,
)
from app.models.types import DecimalText


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[AssetKind] = mapped_column(String(16), default=AssetKind.CRYPTO)
    coingecko_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decimals: Mapped[int] = mapped_column(Integer, default=18)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def is_fiat(self) -> bool:
        return self.kind == AssetKind.FIAT


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    platform: Mapped[AccountPlatform] = mapped_column(String(32), default=AccountPlatform.MANUAL)
    type: Mapped[AccountType] = mapped_column(String(16), default=AccountType.EXCHANGE)
    is_abroad: Mapped[bool] = mapped_column(Boolean, default=False)  # for Modelo 721
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    connector: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(256))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[ImportStatus] = mapped_column(String(16), default=ImportStatus.OK)
    errors_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class Transaction(Base):
    """Atomic, normalised (canonical) movement. The single entry point into the
    fiscal engine — exchange specifics never reach this far."""

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("account_id", "external_id", name="uq_tx_account_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    type: Mapped[TransactionType] = mapped_column(String(24), index=True)

    asset_in_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    amount_in: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    asset_out_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    amount_out: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    fee_asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    fee_amount: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)

    # Best-known EUR value of the operation at the time (for valuing swaps/income).
    eur_value: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)
    price_source: Mapped[str | None] = mapped_column(String(64), nullable=True)

    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    notes: Mapped[str | None] = mapped_column(String(256), nullable=True)

    asset_in: Mapped[Asset | None] = relationship(foreign_keys=[asset_in_id])
    asset_out: Mapped[Asset | None] = relationship(foreign_keys=[asset_out_id])
    fee_asset: Mapped[Asset | None] = relationship(foreign_keys=[fee_asset_id])


class Lot(Base):
    """An acquisition lot for FIFO matching (a slice of the portfolio)."""

    __tablename__ = "lots"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    qty_original: Mapped[Decimal] = mapped_column(DecimalText)
    qty_remaining: Mapped[Decimal] = mapped_column(DecimalText)
    unit_cost_eur: Mapped[Decimal] = mapped_column(DecimalText)  # EUR per unit
    source_tx_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    fiscal_year_acquired: Mapped[int] = mapped_column(Integer, index=True)
    is_carryforward: Mapped[bool] = mapped_column(Boolean, default=False)
    is_opening: Mapped[bool] = mapped_column(Boolean, default=False)  # manual opening position

    asset: Mapped[Asset] = relationship()


class Disposal(Base):
    """A taxable disposal (enajenación). Consumes one or more lots via FIFO."""

    __tablename__ = "disposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    tx_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    disposed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    quantity: Mapped[Decimal] = mapped_column(DecimalText)
    proceeds_eur: Mapped[Decimal] = mapped_column(DecimalText)  # transfer value net of fees
    cost_basis_eur: Mapped[Decimal] = mapped_column(DecimalText)
    gain_loss_eur: Mapped[Decimal] = mapped_column(DecimalText)
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    disposal_kind: Mapped[DisposalKind] = mapped_column(String(16))

    asset: Mapped[Asset] = relationship()
    consumptions: Mapped[list["LotConsumption"]] = relationship(
        back_populates="disposal", cascade="all, delete-orphan"
    )


class LotConsumption(Base):
    """FIFO match line: how much of a lot a disposal consumed and its result."""

    __tablename__ = "lot_consumptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    disposal_id: Mapped[int] = mapped_column(ForeignKey("disposals.id"), index=True)
    # Null when the disposal had no recorded acquisition basis (shortfall, base=0).
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots.id"), index=True, nullable=True)
    qty_consumed: Mapped[Decimal] = mapped_column(DecimalText)
    cost_basis_eur: Mapped[Decimal] = mapped_column(DecimalText)
    proceeds_eur: Mapped[Decimal] = mapped_column(DecimalText)
    gain_loss_eur: Mapped[Decimal] = mapped_column(DecimalText)
    holding_days: Mapped[int] = mapped_column(Integer)
    acquired_at: Mapped[datetime] = mapped_column(DateTime)
    disposed_at: Mapped[datetime] = mapped_column(DateTime)

    disposal: Mapped[Disposal] = relationship(back_populates="consumptions")


class IncomeEvent(Base):
    """Income at fair market value when received (staking/airdrop/referral)."""

    __tablename__ = "income_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    tx_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    quantity: Mapped[Decimal] = mapped_column(DecimalText)
    eur_value: Mapped[Decimal] = mapped_column(DecimalText)
    category: Mapped[IncomeCategory] = mapped_column(String(16))
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)

    asset: Mapped[Asset] = relationship()


class FiscalYear(Base):
    __tablename__ = "fiscal_years"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[FiscalYearStatus] = mapped_column(String(16), default=FiscalYearStatus.OPEN)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(256), nullable=True)


class FiscalYearSummary(Base):
    """Immutable snapshot of a year's fiscal result (computed or manually loaded)."""

    __tablename__ = "fiscal_year_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    net_gain_eur: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal("0"))
    total_gains: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal("0"))
    total_losses: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal("0"))
    income_total: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal("0"))
    savings_base: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal("0"))
    tax_due_eur: Mapped[Decimal] = mapped_column(DecimalText, default=Decimal("0"))
    source: Mapped[SummarySource] = mapped_column(String(16), default=SummarySource.COMPUTED)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TaxBracket(Base):
    """A savings-base tax bracket for a given year (editable; rates change)."""

    __tablename__ = "tax_brackets"
    __table_args__ = (UniqueConstraint("year", "from_eur", name="uq_bracket_year_from"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    from_eur: Mapped[Decimal] = mapped_column(DecimalText)
    to_eur: Mapped[Decimal | None] = mapped_column(DecimalText, nullable=True)  # None = top bracket
    rate: Mapped[Decimal] = mapped_column(DecimalText)  # e.g. 0.19


class PriceQuote(Base):
    """Historical EUR price for valuing swaps and income at fair market value."""

    __tablename__ = "price_quotes"
    __table_args__ = (
        UniqueConstraint("asset_id", "date", "source", name="uq_price_asset_date_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    price_eur: Mapped[Decimal] = mapped_column(DecimalText)
    source: Mapped[str] = mapped_column(String(64), default="manual")
