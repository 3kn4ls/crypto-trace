"""Fiscal year endpoints: status, compute, close/reopen, manual summary, opening lots."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import FiscalYear, FiscalYearSummary
from app.schemas import ManualSummaryIn, OpeningPositionIn
from app.services import fiscal_year_service as fys

router = APIRouter()


@router.get("")
def list_years(db: Session = Depends(get_db)) -> list[dict]:
    summaries = {s.year: s for s in db.scalars(select(FiscalYearSummary))}
    out = []
    for fy in db.scalars(select(FiscalYear).order_by(FiscalYear.year.desc())):
        s = summaries.get(fy.year)
        out.append({
            "year": fy.year,
            "status": fy.status.value if hasattr(fy.status, "value") else fy.status,
            "closed_at": fy.closed_at.isoformat() if fy.closed_at else None,
            "tax_due_eur": str(s.tax_due_eur) if s else None,
            "net_gain_eur": str(s.net_gain_eur) if s else None,
            "source": (s.source.value if hasattr(s.source, "value") else s.source) if s else None,
        })
    return out


@router.get("/{year}/tax")
def compute(year: int, db: Session = Depends(get_db)) -> dict:
    r = fys.compute_year(db, year)
    data = asdict(r)
    return _stringify(data)


@router.post("/{year}/close")
def close(year: int, db: Session = Depends(get_db)) -> dict:
    s = fys.close_year(db, year)
    return {"year": s.year, "tax_due_eur": str(s.tax_due_eur), "status": "CLOSED"}


@router.post("/{year}/reopen")
def reopen(year: int, db: Session = Depends(get_db)) -> dict:
    fy = fys.reopen_year(db, year)
    if fy is None:
        raise HTTPException(404, f"Año {year} no existe")
    return {"year": year, "status": "OPEN"}


@router.post("/manual-summary")
def manual_summary(payload: ManualSummaryIn, db: Session = Depends(get_db)) -> dict:
    s = fys.load_manual_summary(
        db, year=payload.year, net_gain_eur=payload.net_gain_eur,
        income_total=payload.income_total, savings_base=payload.savings_base,
        tax_due_eur=payload.tax_due_eur,
    )
    return {"year": s.year, "source": "MANUAL_SUMMARY", "tax_due_eur": str(s.tax_due_eur)}


@router.post("/opening-position")
def opening_position(payload: OpeningPositionIn, db: Session = Depends(get_db)) -> dict:
    try:
        tx = fys.add_opening_position(
            db, asset_symbol=payload.asset_symbol, quantity=payload.quantity,
            cost_basis_eur=payload.cost_basis_eur, acquired_at=payload.acquired_at,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"transaction_id": tx.id, "asset": payload.asset_symbol.upper()}


def _stringify(data: dict) -> dict:
    """Recursively turn Decimals into strings for JSON."""
    from decimal import Decimal

    def conv(v):
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, list):
            return [conv(x) for x in v]
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        return v

    return conv(data)
