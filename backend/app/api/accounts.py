"""Account management."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Account
from app.schemas import AccountCreate, AccountOut

router = APIRouter()


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)):
    return list(db.scalars(select(Account).order_by(Account.name)))


@router.post("", response_model=AccountOut)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    acc = Account(**payload.model_dump())
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc
