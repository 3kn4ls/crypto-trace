"""Fiscal year endpoints: status, compute, close/reopen, manual summary, opening lots."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import FiscalYear, FiscalYearSummary, Taxpayer
from app.schemas import ManualSummaryIn, OpeningPositionIn
from app.services import fiscal_year_service as fys

router = APIRouter()


def _active_taxpayer_ids(
    db: Session, taxpayer_id: int | None = None, taxpayer_ids: list[int] | None = None
) -> list[int] | None:
    ids = taxpayer_ids if taxpayer_ids else ([taxpayer_id] if taxpayer_id is not None else None)
    if ids:
        existing = {tp.id for tp in db.scalars(select(Taxpayer).where(Taxpayer.id.in_(ids)))}
        if any(i not in existing for i in ids):
            raise HTTPException(404, "Algún contribuyente no existe")
    return ids


@router.get("")
def list_years(
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict]:
    ids = _active_taxpayer_ids(db, taxpayer_id, taxpayer_ids)
    q_fy = select(FiscalYear)
    q_summary = select(FiscalYearSummary)
    if ids:
        q_fy = q_fy.where(FiscalYear.taxpayer_id.in_(ids))
        q_summary = q_summary.where(FiscalYearSummary.taxpayer_id.in_(ids))

    summaries = {(s.taxpayer_id, s.year): s for s in db.scalars(q_summary)}
    out = []
    for fy in db.scalars(q_fy.order_by(FiscalYear.year.desc())):
        s = summaries.get((fy.taxpayer_id, fy.year))
        out.append({
            "taxpayer_id": fy.taxpayer_id,
            "year": fy.year,
            "status": fy.status.value if hasattr(fy.status, "value") else fy.status,
            "closed_at": fy.closed_at.isoformat() if fy.closed_at else None,
            "tax_due_eur": str(s.tax_due_eur) if s else None,
            "net_gain_eur": str(s.net_gain_eur) if s else None,
            "source": (s.source.value if hasattr(s.source, "value") else s.source) if s else None,
        })
    return out


@router.get("/{year}/tax")
def compute(
    year: int,
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    ids = _active_taxpayer_ids(db, taxpayer_id, taxpayer_ids)
    r = fys.compute_year(db, year, taxpayer_ids=ids)
    data = asdict(r)
    return _stringify(data)


@router.post("/{year}/close")
def close(
    year: int,
    taxpayer_id: int,
    db: Session = Depends(get_db),
) -> dict:
    _active_taxpayer_ids(db, taxpayer_id=taxpayer_id)
    s = fys.close_year(db, year, taxpayer_id)
    return {
        "taxpayer_id": s.taxpayer_id,
        "year": s.year,
        "tax_due_eur": str(s.tax_due_eur),
        "status": "CLOSED",
    }


@router.post("/{year}/reopen")
def reopen(
    year: int,
    taxpayer_id: int,
    db: Session = Depends(get_db),
) -> dict:
    _active_taxpayer_ids(db, taxpayer_id=taxpayer_id)
    fy = fys.reopen_year(db, year, taxpayer_id)
    if fy is None:
        raise HTTPException(404, f"Año {year} no existe para este contribuyente")
    return {"taxpayer_id": fy.taxpayer_id, "year": year, "status": "OPEN"}


@router.post("/manual-summary")
def manual_summary(
    taxpayer_id: int,
    payload: ManualSummaryIn,
    db: Session = Depends(get_db),
) -> dict:
    _active_taxpayer_ids(db, taxpayer_id=taxpayer_id)
    s = fys.load_manual_summary(
        db, taxpayer_id=taxpayer_id, year=payload.year, net_gain_eur=payload.net_gain_eur,
        income_total=payload.income_total, savings_base=payload.savings_base,
        tax_due_eur=payload.tax_due_eur,
    )
    return {
        "taxpayer_id": s.taxpayer_id,
        "year": s.year,
        "source": "MANUAL_SUMMARY",
        "tax_due_eur": str(s.tax_due_eur),
    }


@router.post("/opening-position")
def opening_position(
    taxpayer_id: int,
    payload: OpeningPositionIn,
    db: Session = Depends(get_db),
) -> dict:
    _active_taxpayer_ids(db, taxpayer_id=taxpayer_id)
    try:
        tx = fys.add_opening_position(
            db, taxpayer_id=taxpayer_id, asset_symbol=payload.asset_symbol,
            quantity=payload.quantity, cost_basis_eur=payload.cost_basis_eur,
            acquired_at=payload.acquired_at,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"transaction_id": tx.id, "taxpayer_id": taxpayer_id, "asset": payload.asset_symbol.upper()}


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
