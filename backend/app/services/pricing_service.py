"""Historical EUR pricing used to value swaps, income and year-end balances."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PriceQuote


def get_price(db: Session, asset_id: int, on: date) -> Decimal | None:
    """Latest known EUR price for an asset on or before ``on``."""
    row = db.scalars(
        select(PriceQuote)
        .where(PriceQuote.asset_id == asset_id, PriceQuote.date <= on)
        .order_by(PriceQuote.date.desc())
        .limit(1)
    ).first()
    return row.price_eur if row else None


def upsert_price(db: Session, asset_id: int, on: date, price_eur: Decimal, source: str = "manual") -> PriceQuote:
    existing = db.scalar(
        select(PriceQuote).where(
            PriceQuote.asset_id == asset_id, PriceQuote.date == on, PriceQuote.source == source
        )
    )
    if existing:
        existing.price_eur = price_eur
        db.commit()
        return existing
    quote = PriceQuote(asset_id=asset_id, date=on, price_eur=price_eur, source=source)
    db.add(quote)
    db.commit()
    return quote
