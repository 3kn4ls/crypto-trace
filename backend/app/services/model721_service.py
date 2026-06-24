"""Modelo 721 — informative declaration of crypto held abroad.

Computes year-end (31/12) balances per foreign account and asset, valued in EUR,
and flags whether the declaration threshold (50.000 €) is reached. Valuation
uses the latest :class:`PriceQuote` on or before 31/12; assets without a price
are reported with a null value and surfaced as a warning.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import ZERO, quantize_eur
from app.models import Account, Asset
from app.services.pricing_service import get_price
from app.services.reporting_service import account_balances

THRESHOLD_EUR = Decimal("50000")


def compute(db: Session, year: int) -> dict:
    as_of = date(year, 12, 31)
    balances = account_balances(db, as_of=as_of)
    accounts = {a.id: a for a in db.scalars(select(Account))}

    holdings: list[dict] = []
    warnings: list[str] = []
    total_abroad = ZERO

    for (account_id, asset_id), qty in balances.items():
        if qty <= ZERO:
            continue
        account = accounts.get(account_id)
        asset = db.get(Asset, asset_id)
        if asset is None or asset.is_fiat:
            continue
        price = get_price(db, asset_id, as_of)
        value = quantize_eur(qty * price) if price is not None else None
        if price is None:
            warnings.append(f"Sin precio a 31/12/{year} para {asset.symbol}; valor no calculado.")
        is_abroad = bool(account and account.is_abroad)
        if is_abroad and value is not None:
            total_abroad += value
        holdings.append({
            "account": account.name if account else str(account_id),
            "is_abroad": is_abroad,
            "asset": asset.symbol,
            "quantity": str(qty),
            "price_eur": str(price) if price is not None else None,
            "value_eur": str(value) if value is not None else None,
        })

    total_abroad = quantize_eur(total_abroad)
    return {
        "year": year,
        "threshold_eur": str(THRESHOLD_EUR),
        "total_abroad_eur": str(total_abroad),
        "obligated": total_abroad >= THRESHOLD_EUR,
        "holdings": sorted(holdings, key=lambda h: (h["account"], h["asset"])),
        "warnings": warnings,
    }
