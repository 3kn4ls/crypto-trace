"""Health, connectors, assets and price quotes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors import list_connectors
from app.core.db import get_db
from app.models import Asset
from app.schemas import PriceQuoteIn
from app.services.pricing_service import upsert_price

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/connectors")
def connectors() -> list[dict]:
    return list_connectors()


@router.get("/assets")
def assets(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {"id": a.id, "symbol": a.symbol, "name": a.name, "kind": a.kind.value if hasattr(a.kind, "value") else a.kind}
        for a in db.scalars(select(Asset).order_by(Asset.symbol))
    ]


@router.post("/prices")
def add_price(payload: PriceQuoteIn, db: Session = Depends(get_db)) -> dict:
    asset = db.scalar(select(Asset).where(Asset.symbol == payload.asset_symbol.upper()))
    if asset is None:
        raise HTTPException(404, f"Activo desconocido: {payload.asset_symbol}")
    q = upsert_price(db, asset.id, payload.date.date(), payload.price_eur, payload.source)
    return {"asset": asset.symbol, "date": str(q.date), "price_eur": str(q.price_eur)}
