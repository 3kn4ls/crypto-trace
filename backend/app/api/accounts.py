"""Account management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Account, Taxpayer
from app.schemas import AccountCreate, AccountOut

router = APIRouter()


def _default_taxpayer_id(db: Session) -> int:
    taxpayer = db.scalar(select(Taxpayer).order_by(Taxpayer.id))
    if taxpayer is None:
        raise HTTPException(500, "No existe ningún contribuyente")
    return taxpayer.id


@router.get("", response_model=list[AccountOut])
def list_accounts(
    taxpayer_id: int | None = None,
    db: Session = Depends(get_db),
):
    q = select(Account).order_by(Account.name)
    if taxpayer_id is not None:
        q = q.where(Account.taxpayer_id == taxpayer_id)
    return list(db.scalars(q))


@router.post("", response_model=AccountOut)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    if db.get(Taxpayer, payload.taxpayer_id) is None:
        raise HTTPException(404, f"Contribuyente {payload.taxpayer_id} no existe")
    acc = Account(**payload.model_dump())
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc
