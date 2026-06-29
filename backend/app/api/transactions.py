"""Transaction listing."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Transaction, TransactionType
from app.schemas import TransactionUpdateIn
from app.services.fiscal_year_service import is_year_closed
from app.services.recompute import recompute_all

router = APIRouter()

# Reclassifying a transaction's type must stay coherent with the legs (assets)
# it already carries — PATCH cannot add a missing leg. Acquisition-like types
# need an incoming crypto asset; disposal-like types need an outgoing one.
_NEEDS_CRYPTO_IN = {
    TransactionType.BUY,
    TransactionType.DEPOSIT,
    TransactionType.STAKING_REWARD,
    TransactionType.AIRDROP,
    TransactionType.REFERRAL,
}
_NEEDS_CRYPTO_OUT = {
    TransactionType.SELL,
    TransactionType.SPEND,
    TransactionType.WITHDRAWAL,
    TransactionType.REVERSAL,
}


def _validate_type(tx: Transaction, new_type: TransactionType) -> None:
    """Reject a reclassification incoherent with the transaction's existing legs."""
    has_crypto_in = tx.asset_in is not None and not tx.asset_in.is_fiat
    has_crypto_out = tx.asset_out is not None and not tx.asset_out.is_fiat
    if new_type in _NEEDS_CRYPTO_IN and not has_crypto_in:
        raise HTTPException(
            400, f"{new_type.value} requiere un activo cripto de entrada del que esta transacción carece."
        )
    if new_type in _NEEDS_CRYPTO_OUT and not has_crypto_out:
        raise HTTPException(
            400, f"{new_type.value} requiere un activo cripto de salida del que esta transacción carece."
        )
    if new_type == TransactionType.SWAP and not (has_crypto_in and has_crypto_out):
        raise HTTPException(400, "SWAP requiere un activo cripto de entrada y otro de salida.")
    if new_type == TransactionType.TRANSFER and not (has_crypto_in or has_crypto_out):
        raise HTTPException(400, "TRANSFER requiere al menos un activo cripto (entrada o salida).")


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
    if is_year_closed(db, tx.taxpayer_id, tx.fiscal_year):
        raise HTTPException(
            409, f"El año {tx.fiscal_year} está cerrado; reábrelo para editar sus transacciones."
        )
    if payload.type is not None and payload.type != tx.type:
        _validate_type(tx, payload.type)
        tx.type = payload.type
    if payload.cost_basis_eur is not None:
        tx.cost_basis_eur = payload.cost_basis_eur
    if payload.is_internal_transfer is not None:
        tx.is_internal_transfer = payload.is_internal_transfer
    if payload.notes is not None:
        tx.notes = payload.notes
    db.commit()
    recompute_all(db)
    return _tx_dict(tx)
