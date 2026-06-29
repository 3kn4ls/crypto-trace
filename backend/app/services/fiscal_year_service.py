"""Per-year fiscal computation, year closing/carry-forward and manual summaries."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import ZERO
from app.models import (
    Account,
    AccountPlatform,
    Asset,
    Disposal,
    FiscalYear,
    FiscalYearStatus,
    FiscalYearSummary,
    IncomeCategory,
    IncomeEvent,
    SummarySource,
    TaxBracket,
    Taxpayer,
    Transaction,
    TransactionType,
)
from app.services.recompute import recompute_all
from app.services.tax_calculator import TaxResult, compute_tax


def get_brackets(db: Session, year: int) -> list[tuple[Decimal, Decimal | None, Decimal]]:
    rows = list(
        db.scalars(select(TaxBracket).where(TaxBracket.year == year).order_by(TaxBracket.from_eur))
    )
    if not rows:
        years = sorted(set(db.scalars(select(TaxBracket.year))))
        earlier = [y for y in years if y <= year]
        use = max(earlier) if earlier else (max(years) if years else None)
        if use is not None:
            rows = list(
                db.scalars(
                    select(TaxBracket).where(TaxBracket.year == use).order_by(TaxBracket.from_eur)
                )
            )
    return [(r.from_eur, r.to_eur, r.rate) for r in rows]


def _default_taxpayer_id(db: Session) -> int:
    taxpayer = db.scalar(select(Taxpayer).order_by(Taxpayer.id))
    if taxpayer is None:
        taxpayer = Taxpayer(name="Principal")
        db.add(taxpayer)
        db.commit()
        db.refresh(taxpayer)
    return taxpayer.id


def is_year_closed(db: Session, taxpayer_id: int, year: int) -> bool:
    """True if the taxpayer's fiscal year is CLOSED (read-only).

    Closing a year is a write-lock: edits/deletes of its transactions and
    resolutions that would change its derived state are rejected until the year
    is reopened. This keeps the frozen FiscalYearSummary and the live
    computation from diverging.
    """
    fy = db.scalar(
        select(FiscalYear).where(
            FiscalYear.taxpayer_id == taxpayer_id, FiscalYear.year == year
        )
    )
    return fy is not None and fy.status == FiscalYearStatus.CLOSED


def compute_year(db: Session, year: int, taxpayer_ids: list[int] | None = None) -> TaxResult:
    q_disposals = select(Disposal.gain_loss_eur).where(Disposal.fiscal_year == year)
    q_incomes = select(IncomeEvent).where(IncomeEvent.fiscal_year == year)
    if taxpayer_ids:
        q_disposals = q_disposals.where(Disposal.taxpayer_id.in_(taxpayer_ids))
        q_incomes = q_incomes.where(IncomeEvent.taxpayer_id.in_(taxpayer_ids))

    gains = list(db.scalars(q_disposals))
    incomes = list(db.scalars(q_incomes))
    rcm = sum((i.eur_value for i in incomes if i.category == IncomeCategory.RCM), ZERO)
    ganancia = sum((i.eur_value for i in incomes if i.category == IncomeCategory.GANANCIA), ZERO)
    actividad = sum((i.eur_value for i in incomes if i.category == IncomeCategory.ACTIVIDAD), ZERO)
    return compute_tax(
        year, gains, rcm_income=rcm, ganancia_income=ganancia,
        actividad_income=actividad, brackets=get_brackets(db, year),
    )


def _result_to_summary(taxpayer_id: int, year: int, r: TaxResult, source: SummarySource) -> dict:
    return dict(
        taxpayer_id=taxpayer_id,
        year=year,
        net_gain_eur=r.net_capital_gain,
        total_gains=r.total_gains,
        total_losses=r.total_losses,
        income_total=r.rcm_income + r.actividad_income,
        savings_base=r.savings_base,
        tax_due_eur=r.tax_due,
        source=source,
        detail_json=json.dumps(
            {
                "effective_rate": str(r.effective_rate),
                "brackets": [
                    {"from": str(b.from_eur), "to": (str(b.to_eur) if b.to_eur else None),
                     "rate": str(b.rate), "tax": str(b.tax)}
                    for b in r.bracket_breakdown
                ],
                "notes": r.notes,
            },
            ensure_ascii=False,
        ),
    )


def _upsert_summary(db: Session, data: dict) -> FiscalYearSummary:
    existing = db.scalar(
        select(FiscalYearSummary).where(
            FiscalYearSummary.taxpayer_id == data["taxpayer_id"],
            FiscalYearSummary.year == data["year"],
        )
    )
    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        db.commit()
        return existing
    s = FiscalYearSummary(**data)
    db.add(s)
    db.commit()
    return s


def _get_or_create_fiscal_year(db: Session, taxpayer_id: int, year: int) -> FiscalYear:
    fy = db.scalar(
        select(FiscalYear).where(
            FiscalYear.taxpayer_id == taxpayer_id, FiscalYear.year == year
        )
    )
    if fy is None:
        fy = FiscalYear(taxpayer_id=taxpayer_id, year=year, status=FiscalYearStatus.OPEN)
        db.add(fy)
        db.flush()
    return fy


def close_year(db: Session, year: int, taxpayer_id: int) -> FiscalYearSummary:
    """Freeze the computed result for one taxpayer and lock their year."""
    result = compute_year(db, year, [taxpayer_id])
    summary = _upsert_summary(
        db, _result_to_summary(taxpayer_id, year, result, SummarySource.COMPUTED)
    )
    fy = _get_or_create_fiscal_year(db, taxpayer_id, year)
    fy.status = FiscalYearStatus.CLOSED
    fy.closed_at = datetime.utcnow()
    db.add(fy)
    db.commit()
    return summary


def reopen_year(db: Session, year: int, taxpayer_id: int) -> FiscalYear:
    fy = db.scalar(
        select(FiscalYear).where(
            FiscalYear.taxpayer_id == taxpayer_id, FiscalYear.year == year
        )
    )
    if fy:
        fy.status = FiscalYearStatus.OPEN
        fy.closed_at = None
        db.commit()
    return fy


def load_manual_summary(
    db: Session, *, taxpayer_id: int, year: int, net_gain_eur: Decimal, income_total: Decimal,
    savings_base: Decimal, tax_due_eur: Decimal,
) -> FiscalYearSummary:
    """Load a summary for a past year for which detailed transactions are absent."""
    data = dict(
        taxpayer_id=taxpayer_id,
        year=year, net_gain_eur=net_gain_eur, total_gains=net_gain_eur, total_losses=ZERO,
        income_total=income_total, savings_base=savings_base, tax_due_eur=tax_due_eur,
        source=SummarySource.MANUAL_SUMMARY, detail_json=None,
    )
    summary = _upsert_summary(db, data)
    fy = _get_or_create_fiscal_year(db, taxpayer_id, year)
    fy.status = FiscalYearStatus.CLOSED
    fy.closed_at = datetime.utcnow()
    db.add(fy)
    db.commit()
    return summary


def _opening_account(db: Session, taxpayer_id: int) -> Account:
    acc = db.scalar(
        select(Account).where(
            Account.taxpayer_id == taxpayer_id, Account.name == "Apertura"
        )
    )
    if acc is None:
        acc = Account(
            name="Apertura", taxpayer_id=taxpayer_id, platform=AccountPlatform.MANUAL
        )
        db.add(acc)
        db.commit()
        db.refresh(acc)
    return acc


def add_opening_position(
    db: Session, *, taxpayer_id: int, asset_symbol: str, quantity: Decimal,
    cost_basis_eur: Decimal, acquired_at: datetime
) -> Transaction:
    """Register an opening lot (a DEPOSIT carrying its EUR cost basis) and recompute."""
    if is_year_closed(db, taxpayer_id, acquired_at.year):
        raise ValueError(
            f"El año {acquired_at.year} está cerrado; reábrelo para añadir posiciones de apertura."
        )
    asset = db.scalar(select(Asset).where(Asset.symbol == asset_symbol.upper()))
    if asset is None:
        raise ValueError(f"Activo desconocido: {asset_symbol}")
    acc = _opening_account(db, taxpayer_id)
    tx = Transaction(
        taxpayer_id=taxpayer_id,
        account_id=acc.id, timestamp=acquired_at, type=TransactionType.DEPOSIT,
        asset_in_id=asset.id, amount_in=quantity, eur_value=cost_basis_eur,
        cost_basis_eur=cost_basis_eur,
        price_source="opening", fiscal_year=acquired_at.year, notes="Posición de apertura",
        external_id=f"opening-{taxpayer_id}-{asset.symbol}-{acquired_at.date()}",
    )
    db.add(tx)
    db.commit()
    recompute_all(db)
    return tx
