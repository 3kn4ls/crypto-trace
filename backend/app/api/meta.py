"""Health, connectors, assets and price quotes."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors import list_connectors
from app.core.db import get_db
from app.models import Asset, Disposal, IncomeEvent, Lot, PriceQuote
from app.schemas import PriceQuoteIn
from app.services.pricing_provider import coin_id_for, discover_coin_id, fetch_history_eur
from app.services.pricing_service import upsert_price

router = APIRouter()


class FetchHistoricalPricesIn(BaseModel):
    year: int | None = None
    taxpayer_id: int | None = None
    taxpayer_ids: list[int] | None = None


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


@router.post("/prices/fetch-historical")
def fetch_historical_prices(
    payload: FetchHistoricalPricesIn,
    db: Session = Depends(get_db),
) -> dict:
    """Fetch 31/12 EUR prices from CoinGecko for assets held by the taxpayer(s).

    If ``year`` is provided, only that year-end is filled; otherwise every
    fiscal year with disposals or income is processed.
    """
    ids = payload.taxpayer_ids if payload.taxpayer_ids else ([payload.taxpayer_id] if payload.taxpayer_id else None)

    q_disposals = select(Disposal.fiscal_year)
    q_incomes = select(IncomeEvent.fiscal_year)
    if ids:
        q_disposals = q_disposals.where(Disposal.taxpayer_id.in_(ids))
        q_incomes = q_incomes.where(IncomeEvent.taxpayer_id.in_(ids))
    years = sorted(set(db.scalars(q_disposals)) | set(db.scalars(q_incomes)))
    if payload.year is not None:
        years = [payload.year] if payload.year in years else []

    if not years:
        return {"fetched": [], "missing": [], "skipped": [], "errors": []}

    # Collect asset ids that appear in lots for these taxpayers.
    q_lots = select(Lot.asset_id).distinct()
    if ids:
        q_lots = q_lots.where(Lot.taxpayer_id.in_(ids))
    asset_ids = [aid for aid in db.scalars(q_lots) if aid is not None]
    assets = {a.id: a for a in db.scalars(select(Asset).where(Asset.id.in_(asset_ids))) if not a.is_fiat}

    fetched: list[dict] = []
    missing: list[dict] = []
    errors: list[str] = []
    skipped: list[dict] = []

    for y in years:
        target = date(y, 12, 31)
        for asset in assets.values():
            # First try the hardcoded map; if it fails, attempt dynamic discovery.
            coin_id = coin_id_for(asset.symbol) or discover_coin_id(asset.symbol)
            if not coin_id:
                missing.append({"asset": asset.symbol, "year": y, "reason": "sin_mapeo_coingecko"})
                continue

            # Skip if a manual price already exists for this date.
            already = db.scalar(
                select(PriceQuote).where(
                    PriceQuote.asset_id == asset.id,
                    PriceQuote.date == target,
                )
            )
            if already:
                skipped.append({"asset": asset.symbol, "year": y, "date": str(target)})
                continue

            price = fetch_history_eur(coin_id, target)
            if price is None:
                errors.append(f"No se pudo obtener precio para {asset.symbol} a {target}")
                missing.append({"asset": asset.symbol, "year": y, "reason": "fetch_error"})
                continue

            upsert_price(db, asset.id, target, price, source="coingecko")
            fetched.append({"asset": asset.symbol, "year": y, "date": str(target), "price_eur": str(price)})

    return {"fetched": fetched, "missing": missing, "skipped": skipped, "errors": errors}
