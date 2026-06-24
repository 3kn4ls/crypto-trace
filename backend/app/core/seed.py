"""Idempotent seeding of reference data (assets and default tax brackets)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, AssetKind, TaxBracket
from app.tax.brackets import DEFAULT_BRACKETS

# symbol, name, kind, coingecko_id, decimals
_DEFAULT_ASSETS = [
    ("EUR", "Euro", AssetKind.FIAT, None, 2),
    ("BTC", "Bitcoin", AssetKind.CRYPTO, "bitcoin", 8),
    ("ETH", "Ethereum", AssetKind.CRYPTO, "ethereum", 18),
    ("USDT", "Tether", AssetKind.STABLECOIN, "tether", 6),
    ("USDC", "USD Coin", AssetKind.STABLECOIN, "usd-coin", 6),
    ("CRO", "Cronos", AssetKind.CRYPTO, "crypto-com-chain", 8),
    ("ADA", "Cardano", AssetKind.CRYPTO, "cardano", 6),
    ("SOL", "Solana", AssetKind.CRYPTO, "solana", 9),
    ("DOGE", "Dogecoin", AssetKind.CRYPTO, "dogecoin", 8),
    ("XRP", "XRP", AssetKind.CRYPTO, "ripple", 6),
]


def seed_assets(db: Session) -> int:
    existing = {a.symbol for a in db.scalars(select(Asset))}
    added = 0
    for symbol, name, kind, cg, decimals in _DEFAULT_ASSETS:
        if symbol in existing:
            continue
        db.add(Asset(symbol=symbol, name=name, kind=kind, coingecko_id=cg, decimals=decimals))
        added += 1
    db.commit()
    return added


def seed_tax_brackets(db: Session) -> int:
    added = 0
    for year, brackets in DEFAULT_BRACKETS.items():
        has_year = db.scalar(select(TaxBracket).where(TaxBracket.year == year)) is not None
        if has_year:
            continue
        for from_eur, to_eur, rate in brackets:
            db.add(TaxBracket(year=year, from_eur=from_eur, to_eur=to_eur, rate=rate))
            added += 1
    db.commit()
    return added


def seed_all(db: Session) -> dict[str, int]:
    return {"assets": seed_assets(db), "tax_brackets": seed_tax_brackets(db)}
