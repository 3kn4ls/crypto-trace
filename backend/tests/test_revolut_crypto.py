"""Tests for the Revolut crypto *account statement* connector.

This is the per-operation export (es-ES): one row per movement, monetary cells
carrying a currency suffix and Spanish formatting, Spanish dates and a mix of
EUR/USD rows. The connector must:

* parse Spanish numbers and dates, stripping the currency symbol;
* convert ``$`` rows to EUR at the date's rate and pass ``€`` rows through;
* drop pure-fiat funding rows (Symbol EUR/USD);
* preserve open positions so current holdings are non-zero.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from app.models import (
    Account,
    AccountPlatform,
    Lot,
    Taxpayer,
    Transaction,
    TransactionType,
)
from app.services.exchange_rate_provider import _RATE_CACHE
from app.services.import_service import import_excel

HEADER = "Symbol,Type,Quantity,Price,Value,Fees,Date"

REAL_CSV = (
    Path(__file__).resolve().parents[2]
    / "informes"
    / "reales"
    / "REVOLUT"
    / "crypto-account-statement_2025-01-01_2025-12-31_es-es_279bf9_EDU_TOTAL.csv"
)


def _taxpayer(db) -> Taxpayer:
    taxpayer = Taxpayer(name="Revolut Crypto", tax_id="66666666P")
    db.add(taxpayer)
    db.commit()
    db.refresh(taxpayer)
    return taxpayer


def _account(db, taxpayer_id: int) -> Account:
    acc = Account(
        name="Revolut", taxpayer_id=taxpayer_id,
        platform=AccountPlatform.REVOLUT, is_abroad=True,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def _csv(*rows: str) -> bytes:
    return ("\r\n".join([HEADER, *rows]) + "\r\n").encode("utf-8")


def _fix_rate(monkeypatch, rate: str = "0.90") -> None:
    _RATE_CACHE.clear()
    monkeypatch.setattr(
        "app.connectors.revolut_crypto.fetch_usd_eur_rate",
        lambda on: Decimal(rate),
    )


def test_buy_sell_reward_and_fiat_skip(db, monkeypatch):
    _fix_rate(monkeypatch, "0.90")
    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)

    content = _csv(
        # Fiat funding row -> skipped (no crypto, no fiscal effect).
        'EUR,Recepción,,,"100,00€","0,00€","9 abr 2025, 23:27:47"',
        # BUY in EUR: value passes through, fee kept in EUR.
        'BTC,Comprar - Revolut X,"0,002","76.080,34€","100,00€","0,10€","9 abr 2025, 23:27:47"',
        # SELL in USD: 60,00$ * 0.90 = 54,00 EUR proceeds.
        'BTC,Vender - Revolut X,"0,001","78.000,00$","60,00$","0,00$","10 abr 2025, 8:44:00"',
        # Learn & Earn reward (no fiat leg) -> AIRDROP acquisition.
        'MEW,Recompensa de Aprende,"50,5",,,,"7 abr 2025, 11:30:29"',
        # Pure-fiat USD "Otro" funding row -> skipped.
        'USD,Otro,,,"200,00$","0,00€","13 nov 2025, 23:00:22"',
    )
    batch = import_excel(
        db, connector_name="REVOLUT_CRYPTO", taxpayer_id=taxpayer.id, account_id=acc.id,
        filename="revolut_crypto.csv", content=content,
    )

    assert batch.errors_json is None, batch.errors_json
    # 2 fiat rows skipped -> 3 canonical transactions persisted.
    assert batch.inserted_count == 3

    txs = {t.type: t for t in db.scalars(select(Transaction))}

    buy = txs[TransactionType.BUY]
    assert buy.asset_in.symbol == "BTC"
    assert buy.amount_in == Decimal("0.002")
    assert buy.eur_value == Decimal("100.00")
    assert buy.fee_amount == Decimal("0.10")
    assert buy.fee_asset.symbol == "EUR"
    assert (buy.timestamp.year, buy.timestamp.month, buy.timestamp.day) == (2025, 4, 9)

    sell = txs[TransactionType.SELL]
    assert sell.asset_out.symbol == "BTC"
    assert sell.amount_out == Decimal("0.001")
    assert sell.eur_value == Decimal("54.00")  # 60 USD * 0.90
    assert sell.fee_amount is None  # 0 fee -> no fee asset

    reward = txs[TransactionType.AIRDROP]
    assert reward.asset_in.symbol == "MEW"
    assert reward.amount_in == Decimal("50.5")
    assert (reward.timestamp.year, reward.timestamp.month, reward.timestamp.day) == (2025, 4, 7)


def test_holdings_are_not_zeroed(db, monkeypatch):
    """Open positions must survive: 0.001 BTC remains after a 0.002/0.001 trade."""
    _fix_rate(monkeypatch, "0.90")
    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)

    content = _csv(
        'BTC,Comprar - Revolut X,"0,002","76.080,34€","100,00€","0,10€","9 abr 2025, 23:27:47"',
        'BTC,Vender - Revolut X,"0,001","78.000,00€","80,00€","0,00€","10 abr 2025, 8:44:00"',
        'MEW,Recompensa de Aprende,"50,5",,,,"7 abr 2025, 11:30:29"',
    )
    import_excel(
        db, connector_name="REVOLUT_CRYPTO", taxpayer_id=taxpayer.id, account_id=acc.id,
        filename="revolut_crypto.csv", content=content,
    )

    remaining = {
        lot.asset.symbol: lot.qty_remaining
        for lot in db.scalars(select(Lot).where(Lot.qty_remaining > 0))
    }
    assert remaining.get("BTC") == Decimal("0.001")
    assert remaining.get("MEW") == Decimal("50.5")


def test_spanish_september_abbreviation(db, monkeypatch):
    """Revolut writes September as 'sept' (4 letters), not the locale 'sep'."""
    _fix_rate(monkeypatch, "0.90")
    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)

    content = _csv(
        'ALGO,Comprar - Revolut X,"1.005","0,23$","234,70$","0,00$","15 sept 2025, 16:47:42"',
    )
    import_excel(
        db, connector_name="REVOLUT_CRYPTO", taxpayer_id=taxpayer.id, account_id=acc.id,
        filename="revolut_crypto.csv", content=content,
    )
    buy = db.scalar(select(Transaction).where(Transaction.type == TransactionType.BUY))
    assert (buy.timestamp.year, buy.timestamp.month, buy.timestamp.day) == (2025, 9, 15)
    assert buy.asset_in.symbol == "ALGO"
    assert buy.amount_in == Decimal("1005")  # '1.005' is 1005 (thousands sep)


def test_real_statement_imports_without_row_errors(db, monkeypatch):
    """The real export must parse cleanly and leave a non-empty portfolio."""
    import pytest

    if not REAL_CSV.exists():
        pytest.skip(f"sample export not present: {REAL_CSV}")

    _fix_rate(monkeypatch, "0.92")
    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)

    batch = import_excel(
        db, connector_name="REVOLUT_CRYPTO", taxpayer_id=taxpayer.id, account_id=acc.id,
        filename=REAL_CSV.name, content=REAL_CSV.read_bytes(),
    )

    assert batch.errors_json is None, batch.errors_json
    assert batch.inserted_count > 0
    # Current holdings must NOT be zero: several positions stay open.
    held = db.scalar(select(func.count()).select_from(Lot).where(Lot.qty_remaining > 0))
    assert held > 0
