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


def compute_year(db: Session, year: int) -> TaxResult:
    gains = list(db.scalars(select(Disposal.gain_loss_eur).where(Disposal.fiscal_year == year)))
    incomes = list(db.scalars(select(IncomeEvent).where(IncomeEvent.fiscal_year == year)))
    rcm = sum((i.eur_value for i in incomes if i.category == IncomeCategory.RCM), ZERO)
    ganancia = sum((i.eur_value for i in incomes if i.category == IncomeCategory.GANANCIA), ZERO)
    actividad = sum((i.eur_value for i in incomes if i.category == IncomeCategory.ACTIVIDAD), ZERO)
    return compute_tax(
        year, gains, rcm_income=rcm, ganancia_income=ganancia,
        actividad_income=actividad, brackets=get_brackets(db, year),
    )


def _result_to_summary(year: int, r: TaxResult, source: SummarySource) -> dict:
    return dict(
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
    existing = db.scalar(select(FiscalYearSummary).where(FiscalYearSummary.year == data["year"]))
    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        db.commit()
        return existing
    s = FiscalYearSummary(**data)
    db.add(s)
    db.commit()
    return s


def close_year(db: Session, year: int) -> FiscalYearSummary:
    """Freeze the computed result and lock the year against further edits."""
    result = compute_year(db, year)
    summary = _upsert_summary(db, _result_to_summary(year, result, SummarySource.COMPUTED))
    fy = db.get(FiscalYear, year) or FiscalYear(year=year)
    fy.status = FiscalYearStatus.CLOSED
    fy.closed_at = datetime.utcnow()
    db.add(fy)
    db.commit()
    return summary


def reopen_year(db: Session, year: int) -> FiscalYear:
    fy = db.get(FiscalYear, year)
    if fy:
        fy.status = FiscalYearStatus.OPEN
        fy.closed_at = None
        db.commit()
    return fy


def load_manual_summary(
    db: Session, *, year: int, net_gain_eur: Decimal, income_total: Decimal,
    savings_base: Decimal, tax_due_eur: Decimal,
) -> FiscalYearSummary:
    """Load a summary for a past year for which detailed transactions are absent."""
    data = dict(
        year=year, net_gain_eur=net_gain_eur, total_gains=net_gain_eur, total_losses=ZERO,
        income_total=income_total, savings_base=savings_base, tax_due_eur=tax_due_eur,
        source=SummarySource.MANUAL_SUMMARY, detail_json=None,
    )
    summary = _upsert_summary(db, data)
    fy = db.get(FiscalYear, year) or FiscalYear(year=year)
    fy.status = FiscalYearStatus.CLOSED
    fy.closed_at = datetime.utcnow()
    db.add(fy)
    db.commit()
    return summary


def _opening_account(db: Session) -> Account:
    acc = db.scalar(select(Account).where(Account.name == "Apertura"))
    if acc is None:
        acc = Account(name="Apertura", platform=AccountPlatform.MANUAL)
        db.add(acc)
        db.commit()
    return acc


def add_opening_position(
    db: Session, *, asset_symbol: str, quantity: Decimal, cost_basis_eur: Decimal, acquired_at: datetime
) -> Transaction:
    """Register an opening lot (a DEPOSIT carrying its EUR cost basis) and recompute."""
    asset = db.scalar(select(Asset).where(Asset.symbol == asset_symbol.upper()))
    if asset is None:
        raise ValueError(f"Activo desconocido: {asset_symbol}")
    acc = _opening_account(db)
    tx = Transaction(
        account_id=acc.id, timestamp=acquired_at, type=TransactionType.DEPOSIT,
        asset_in_id=asset.id, amount_in=quantity, eur_value=cost_basis_eur,
        price_source="opening", fiscal_year=acquired_at.year, notes="Posición de apertura",
        external_id=f"opening-{asset.symbol}-{acquired_at.date()}",
    )
    db.add(tx)
    db.commit()
    recompute_all(db)
    return tx
