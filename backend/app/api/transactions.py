"""Transaction listing."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Transaction
from app.schemas import TransactionUpdateIn
from app.services.recompute import recompute_all

router = APIRouter()


@router.get("")
def list_transactions(
    year: int | None = None,
    account_id: int | None = None,
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = Query(default=None),
    limit: int = 500,
    db: Session = Depends(get_db),
) -> list[dict]:
    q = select(Transaction).order_by(Transaction.timestamp.desc())
    if year is not None:
        q = q.where(Transaction.fiscal_year == year)
    if account_id is not None:
        q = q.where(Transaction.account_id == account_id)
    ids = taxpayer_ids if taxpayer_ids else ([taxpayer_id] if taxpayer_id is not None else None)
    if ids:
        q = q.where(Transaction.taxpayer_id.in_(ids))
    q = q.limit(limit)
    return [_tx_dict(t) for t in db.scalars(q)]


def _tx_dict(t: Transaction) -> dict:
    return {
        "id": t.id,
        "taxpayer_id": t.taxpayer_id,
        "timestamp": t.timestamp.isoformat(),
        "type": t.type.value if hasattr(t.type, "value") else t.type,
        "asset_in": t.asset_in.symbol if t.asset_in else None,
        "amount_in": str(t.amount_in) if t.amount_in is not None else None,
        "asset_out": t.asset_out.symbol if t.asset_out else None,
        "amount_out": str(t.amount_out) if t.amount_out is not None else None,
        "eur_value": str(t.eur_value) if t.eur_value is not None else None,
        "cost_basis_eur": str(t.cost_basis_eur) if t.cost_basis_eur is not None else None,
        "is_internal_transfer": t.is_internal_transfer,
        "fiscal_year": t.fiscal_year,
        "account_id": t.account_id,
        "source": t.source,
        "notes": t.notes,
    }


@router.patch("/{tx_id}")
def patch_transaction(
    tx_id: int,
    payload: TransactionUpdateIn,
    db: Session = Depends(get_db),
) -> dict:
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(404, "Transacción no encontrada")
    if payload.cost_basis_eur is not None:
        tx.cost_basis_eur = payload.cost_basis_eur
    if payload.is_internal_transfer is not None:
        tx.is_internal_transfer = payload.is_internal_transfer
    if payload.notes is not None:
        tx.notes = payload.notes
    db.commit()
    recompute_all(db)
    return _tx_dict(tx)
