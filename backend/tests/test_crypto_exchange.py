"""Crypto.com Exchange journal connector tests.

The exchange export is a double-entry journal: each trade appears as two or
more ``TRADING`` rows (one per matched leg) plus optional ``TRADE_FEE`` rows,
all sharing the same ``Order ID``. The connector groups by order, converts
USD stablecoin amounts to EUR, and emits a single canonical BUY/SELL per
trade.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from app.models import (
    Account,
    AccountPlatform,
    Disposal,
    Taxpayer,
    Transaction,
    TransactionType,
)
from app.services.exchange_rate_provider import _RATE_CACHE
from app.services.import_service import import_excel

REAL_CSV = (
    Path(__file__).resolve().parents[2]
    / "informes"
    / "OEX_TRANSACTION_CRYPTO_COM_EXCHANGE.csv"
)

HEADER = (
    "Journal ID,Time (UTC),Event Date,Journal Type,Instrument,Taker Side,Side,"
    "Transaction Quantity,Transaction Cost,Realized PNL,Order ID,Trade ID,"
    "Trade Match ID,Client Order Id"
)


def _taxpayer(db) -> Taxpayer:
    taxpayer = Taxpayer(name="CDC Exchange Test", tax_id="77777777C")
    db.add(taxpayer)
    db.commit()
    db.refresh(taxpayer)
    return taxpayer


def _account(db, taxpayer_id: int) -> Account:
    acc = Account(
        name="Crypto.com Exchange", taxpayer_id=taxpayer_id,
        platform=AccountPlatform.CRYPTO_EXCHANGE, is_abroad=True,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


PREAMBLE = (
    "You understand and agree that...",
    "Export contains maximum 65,000 data...",
    "Export Date: 2026-04-16T19:52:30.789259Z[UTC]",
)


def _csv(*rows: str) -> bytes:
    return ("\n".join([*PREAMBLE, HEADER, *rows]) + "\n").encode("utf-8")


def test_eur_buy_crypto_with_crypto_fee(db, monkeypatch):
    """EUR -> SOL buy with fee charged in the received crypto."""
    _RATE_CACHE.clear()
    monkeypatch.setattr(
        "app.connectors.crypto_exchange.fetch_usd_eur_rate",
        lambda on: Decimal("0.92"),
    )

    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)
    content = _csv(
        # Order 1: buy 0.386 SOL for 48.8869 EUR, fee 0.0000036 SOL.
        "1,2025-06-13 13:49:03.614,2025-06-13,TRADING,EUR,,SELL,-48.8869,-48.8869,0,100,1,1,client-1",
        "2,2025-06-13 13:49:03.614,2025-06-13,TRADING,SOL,,BUY,0.386,0.386,0,100,1,1,client-1",
        "3,2025-06-13 13:49:03.614,2025-06-13,TRADE_FEE,SOL,,NULL_VAL,-0.0000036,-0.0000036,0,100,1,1,client-1",
    )
    batch = import_excel(
        db, connector_name="CRYPTO_EXCHANGE", taxpayer_id=taxpayer.id,
        account_id=acc.id, filename="exchange.csv", content=content,
    )
    assert batch.inserted_count == 1
    assert batch.errors_json is None

    tx = db.scalar(select(Transaction))
    assert tx.type == TransactionType.BUY
    assert tx.asset_in.symbol == "SOL"
    assert tx.amount_in == Decimal("0.3859964")  # 0.386 - 0.0000036
    assert tx.asset_out.symbol == "EUR"
    assert tx.amount_out == Decimal("48.89")
    assert tx.eur_value == Decimal("48.89")
    assert tx.fee_asset_id is None
    assert tx.fee_amount is None


def test_usd_stable_buy_crypto_with_usd_fee(db, monkeypatch):
    """USD_Stable_Coin -> XRP buy with fee in USD stablecoin."""
    _RATE_CACHE.clear()
    monkeypatch.setattr(
        "app.connectors.crypto_exchange.fetch_usd_eur_rate",
        lambda on: Decimal("0.92"),
    )

    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)
    content = _csv(
        # Order 2: buy 176 XRP for 487.36512 USD, fee 0.88 USD.
        "4,2025-07-11 16:28:08.818,2025-07-11,TRADING,USD_Stable_Coin,,SELL,-487.36512,-487.36512,0,200,2,2,client-2",
        "5,2025-07-11 16:28:08.818,2025-07-11,TRADING,XRP,,BUY,176,176,0,200,2,2,client-2",
        "6,2025-07-11 16:28:08.818,2025-07-11,TRADE_FEE,USD_Stable_Coin,,NULL_VAL,-0.88,-0.88,0,200,2,2,client-2",
    )
    batch = import_excel(
        db, connector_name="CRYPTO_EXCHANGE", taxpayer_id=taxpayer.id,
        account_id=acc.id, filename="exchange.csv", content=content,
    )
    assert batch.inserted_count == 1
    assert batch.errors_json is None

    tx = db.scalar(select(Transaction))
    assert tx.type == TransactionType.BUY
    assert tx.asset_in.symbol == "XRP"
    assert tx.amount_in == Decimal("176")
    assert tx.asset_out.symbol == "EUR"
    # (487.36512 + 0.88) USD * 0.92 = 449.1855104 -> 449.19 EUR
    assert tx.amount_out == Decimal("449.19")
    assert tx.eur_value == Decimal("449.19")
    # Fiat fee is included in the EUR cost; not emitted as a separate fee asset.
    assert tx.fee_asset_id is None
    assert tx.fee_amount is None


def test_sell_crypto_for_usd_stable_with_crypto_fee(db, monkeypatch):
    """SOL -> USD_Stable_Coin sell with fee charged in SOL."""
    _RATE_CACHE.clear()
    monkeypatch.setattr(
        "app.connectors.crypto_exchange.fetch_usd_eur_rate",
        lambda on: Decimal("0.92"),
    )

    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)
    content = _csv(
        # Order 3: sell 3.579 SOL for 643.32525 USD, fee 0.2573301 USD + 0.001 SOL fee.
        "7,2025-05-14 03:06:51.001,2025-05-14,TRADING,USD_Stable_Coin,,BUY,643.32525,643.32525,0,300,3,3,client-3",
        "8,2025-05-14 03:06:51.001,2025-05-14,TRADING,SOL,,SELL,-3.579,-3.579,0,300,3,3,client-3",
        "9,2025-05-14 03:06:51.001,2025-05-14,TRADE_FEE,USD_Stable_Coin,,NULL_VAL,-0.2573301,-0.2573301,0,300,3,3,client-3",
        "10,2025-05-14 03:06:51.001,2025-05-14,TRADE_FEE,SOL,,NULL_VAL,-0.001,-0.001,0,300,3,3,client-3",
    )
    batch = import_excel(
        db, connector_name="CRYPTO_EXCHANGE", taxpayer_id=taxpayer.id,
        account_id=acc.id, filename="exchange.csv", content=content,
    )
    assert batch.inserted_count == 1
    assert batch.errors_json is None

    tx = db.scalar(select(Transaction))
    assert tx.type == TransactionType.SELL
    assert tx.asset_in.symbol == "EUR"
    # (643.32525 - 0.2573301) USD * 0.92 = 591.622486308 -> 591.62 EUR
    assert tx.amount_in == Decimal("591.62")
    assert tx.asset_out.symbol == "SOL"
    # gross 3.579 + crypto fee 0.001
    assert tx.amount_out == Decimal("3.580")
    assert tx.eur_value == Decimal("591.62")
    # Fiat fee is netted from proceeds; not emitted as a separate fee asset.
    assert tx.fee_asset_id is None
    assert tx.fee_amount is None


def test_multi_fill_order_is_aggregated(db, monkeypatch):
    """A market order with several fills is collapsed into one trade."""
    _RATE_CACHE.clear()
    monkeypatch.setattr(
        "app.connectors.crypto_exchange.fetch_usd_eur_rate",
        lambda on: Decimal("0.92"),
    )

    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)
    content = _csv(
        # Order 4: four USD sell legs + four SOL buy legs (same parent order).
        "11,2025-07-16 18:31:38.339,2025-07-16,TRADING,USD_Stable_Coin,,SELL,-59.03846,-59.03846,0,400,4,4,client-4",
        "12,2025-07-16 18:31:38.339,2025-07-16,TRADING,SOL,,BUY,0.338,0.338,0,400,4,4,client-4",
        "13,2025-07-16 18:31:38.339,2025-07-16,TRADING,USD_Stable_Coin,,SELL,-87.16033,-87.16033,0,400,5,5,client-4",
        "14,2025-07-16 18:31:38.339,2025-07-16,TRADING,SOL,,BUY,0.499,0.499,0,400,5,5,client-4",
        "15,2025-07-16 18:31:09.595,2025-07-16,TRADING,USD_Stable_Coin,,SELL,-87.335,-87.335,0,400,6,6,client-4",
        "16,2025-07-16 18:31:09.595,2025-07-16,TRADING,SOL,,BUY,0.5,0.5,0,400,6,6,client-4",
        "17,2025-07-16 18:31:08.414,2025-07-16,TRADING,USD_Stable_Coin,,SELL,-65.32658,-65.32658,0,400,7,7,client-4",
        "18,2025-07-16 18:31:08.414,2025-07-16,TRADING,SOL,,BUY,0.374,0.374,0,400,7,7,client-4",
    )
    batch = import_excel(
        db, connector_name="CRYPTO_EXCHANGE", taxpayer_id=taxpayer.id,
        account_id=acc.id, filename="exchange.csv", content=content,
    )
    assert batch.inserted_count == 1
    assert batch.errors_json is None

    tx = db.scalar(select(Transaction))
    assert tx.type == TransactionType.BUY
    assert tx.asset_in.symbol == "SOL"
    assert tx.amount_in == Decimal("1.711")  # 0.338 + 0.499 + 0.5 + 0.374
    assert tx.asset_out.symbol == "EUR"
    # (59.03846 + 87.16033 + 87.335 + 65.32658) USD * 0.92 = 274.9515404 -> 274.95 EUR
    assert tx.amount_out == Decimal("274.95")


def test_fiat_deposit_creates_deposit(db):
    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)
    content = _csv(
        "19,2025-06-13 13:43:55.137,2025-06-13,FIAT_OPENPAYD_DEPOSIT,EUR,,NULL_VAL,50,50,0,0,0,0,deposit-1",
    )
    batch = import_excel(
        db, connector_name="CRYPTO_EXCHANGE", taxpayer_id=taxpayer.id,
        account_id=acc.id, filename="exchange.csv", content=content,
    )
    assert batch.inserted_count == 1
    assert batch.errors_json is None

    tx = db.scalar(select(Transaction))
    assert tx.type == TransactionType.DEPOSIT
    assert tx.asset_in.symbol == "EUR"
    assert tx.amount_in == Decimal("50")
    assert tx.eur_value == Decimal("50")


def test_buy_precedes_sell_for_equal_timestamp(db, monkeypatch):
    """For orders at the exact same timestamp, BUY must be emitted before SELL
    so the FIFO engine sees the acquisition first."""
    _RATE_CACHE.clear()
    monkeypatch.setattr(
        "app.connectors.crypto_exchange.fetch_usd_eur_rate",
        lambda on: Decimal("0.92"),
    )

    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)
    content = _csv(
        # Sell SOL for USD at 10:00:00.000
        "20,2025-05-14 10:00:00.000,2025-05-14,TRADING,USD_Stable_Coin,,BUY,100,100,0,500,10,10,client-5",
        "21,2025-05-14 10:00:00.000,2025-05-14,TRADING,SOL,,SELL,-0.5,-0.5,0,500,10,10,client-5",
        # Buy SOL for USD at 10:00:00.000 (same second as the sell above).
        "22,2025-05-14 10:00:00.000,2025-05-14,TRADING,USD_Stable_Coin,,SELL,-100,-100,0,600,11,11,client-6",
        "23,2025-05-14 10:00:00.000,2025-05-14,TRADING,SOL,,BUY,0.5,0.5,0,600,11,11,client-6",
    )
    batch = import_excel(
        db, connector_name="CRYPTO_EXCHANGE", taxpayer_id=taxpayer.id,
        account_id=acc.id, filename="exchange.csv", content=content,
    )
    assert batch.inserted_count == 2

    txs = list(db.scalars(select(Transaction).order_by(Transaction.timestamp)))
    assert txs[0].type == TransactionType.BUY
    assert txs[1].type == TransactionType.SELL


def test_real_exchange_export_imports_cleanly():
    """The actual Crypto.com Exchange journal must import without row errors."""
    import pytest

    if not REAL_CSV.exists():
        pytest.skip(f"sample export not present: {REAL_CSV}")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.db import Base
    from app.core.seed import seed_all
    import app.models  # noqa: F401

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True, expire_on_commit=False)()
    seed_all(session)

    taxpayer = Taxpayer(name="CDC Exchange Real", tax_id="88888888D")
    session.add(taxpayer)
    session.commit()
    session.refresh(taxpayer)

    acc = Account(
        name="Crypto.com Exchange", taxpayer_id=taxpayer.id,
        platform=AccountPlatform.CRYPTO_EXCHANGE, is_abroad=True,
    )
    session.add(acc)
    session.commit()
    session.refresh(acc)

    batch = import_excel(
        session, connector_name="CRYPTO_EXCHANGE", taxpayer_id=taxpayer.id,
        account_id=acc.id, filename=REAL_CSV.name, content=REAL_CSV.read_bytes(),
    )
    assert batch.errors_json is None, batch.errors_json
    assert batch.status.value == "OK"
    assert batch.inserted_count == 223

    # The demo export contains both buys and sells, so there must be disposals.
    assert session.scalar(select(func.count()).select_from(Disposal)) > 0

    session.close()
