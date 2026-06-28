"""Taxpayer management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Taxpayer, Transaction
from app.schemas import TaxpayerCreate, TaxpayerOut, TaxpayerUpdate

router = APIRouter()


@router.get("", response_model=list[TaxpayerOut])
def list_taxpayers(db: Session = Depends(get_db)):
    return list(db.scalars(select(Taxpayer).order_by(Taxpayer.name)))


@router.post("", response_model=TaxpayerOut)
def create_taxpayer(payload: TaxpayerCreate, db: Session = Depends(get_db)):
    taxpayer = Taxpayer(name=payload.name, tax_id=payload.tax_id)
    db.add(taxpayer)
    db.commit()
    db.refresh(taxpayer)
    return taxpayer


@router.get("/{taxpayer_id}", response_model=TaxpayerOut)
def get_taxpayer(taxpayer_id: int, db: Session = Depends(get_db)):
    taxpayer = db.get(Taxpayer, taxpayer_id)
    if taxpayer is None:
        raise HTTPException(404, "Contribuyente no encontrado")
    return taxpayer


@router.put("/{taxpayer_id}", response_model=TaxpayerOut)
def update_taxpayer(taxpayer_id: int, payload: TaxpayerUpdate, db: Session = Depends(get_db)):
    taxpayer = db.get(Taxpayer, taxpayer_id)
    if taxpayer is None:
        raise HTTPException(404, "Contribuyente no encontrado")
    if payload.name is not None:
        taxpayer.name = payload.name
    if payload.tax_id is not None:
        taxpayer.tax_id = payload.tax_id
    db.commit()
    db.refresh(taxpayer)
    return taxpayer


@router.delete("/{taxpayer_id}")
def delete_taxpayer(taxpayer_id: int, db: Session = Depends(get_db)):
    taxpayer = db.get(Taxpayer, taxpayer_id)
    if taxpayer is None:
        raise HTTPException(404, "Contribuyente no encontrado")
    # Prevent deletion if any transactions belong to this taxpayer.
    has_tx = db.scalar(
        select(Transaction.id).where(Transaction.taxpayer_id == taxpayer_id).limit(1)
    )
    if has_tx:
        raise HTTPException(409, "No se puede borrar un contribuyente con transacciones asociadas")
    db.delete(taxpayer)
    db.commit()
    return {"deleted": True}
