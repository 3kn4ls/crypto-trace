"""Revolut "Gains / Losses" connector tests.

Each CSV row describes a completed round-trip trade. The connector must emit a
BUY on the acquisition date and a SELL on the disposal date, applying the
configurable USD→EUR rate to the reported USD values.
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
from app.services.import_service import import_excel

REAL_CSV = (
    Path(__file__).resolve().parents[2]
    / "informes"
    / "REVOLUT_DEMO.csv"
)

HEADER = (
    "Date acquired,Date sold,Symbol,Quantity,Cost basis,Gross proceeds,"
    "Gross PnL,Fees,Net PnL,Currency"
)


def _taxpayer(db) -> Taxpayer:
    taxpayer = Taxpayer(name="Revolut Test", tax_id="44444444A")
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
    return ("\n".join([HEADER, *rows]) + "\n").encode("utf-8")


def test_buy_and_sell_created_per_row(db):
    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)
    content = _csv(
        "2025-04-15,2025-04-19,BTC,0.00067626,57.95,57.88,-0.07,0.05,-0.12,USD",
    )
    batch = import_excel(
        db, connector_name="REVOLUT", taxpayer_id=taxpayer.id, account_id=acc.id,
        filename="revolut.csv", content=content,
    )
    assert batch.inserted_count == 2
    assert batch.errors_json is None

    txs = list(db.scalars(select(Transaction).order_by(Transaction.timestamp)))
    assert len(txs) == 2

    # BUY must chronologically precede SELL for FIFO correctness.
    buy = txs[0]
    sell = txs[1]
    assert buy.timestamp <= sell.timestamp

    assert buy.type == TransactionType.BUY
    assert buy.asset_in.symbol == "BTC"
    assert buy.amount_in == Decimal("0.00067626")
    # Cost basis 57.95 USD * default rate 0.92 = 53.314 -> quantize 0.01 -> 53.31
    assert buy.eur_value == Decimal("53.31")
    assert buy.timestamp.year == 2025
    assert buy.timestamp.month == 4
    assert buy.timestamp.day == 15

    assert sell.type == TransactionType.SELL
    assert sell.asset_out.symbol == "BTC"
    assert sell.amount_out == Decimal("0.00067626")
    # Gross proceeds 57.88 USD * 0.92 = 53.2496 -> 53.25
    assert sell.eur_value == Decimal("53.25")
    assert sell.fee_amount == Decimal("0.05")  # 0.046 USD -> 0.05 EUR quantizado
    assert sell.timestamp.day == 19


def test_zero_fee_skips_fee_asset(db):
    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)
    content = _csv(
        "2025-04-26,2025-04-27,BTC,0.00060618,57.51,57.03,-0.48,0.00,-0.48,USD",
    )
    batch = import_excel(
        db, connector_name="REVOLUT", taxpayer_id=taxpayer.id, account_id=acc.id,
        filename="revolut.csv", content=content,
    )
    assert batch.inserted_count == 2

    sell = db.scalar(
        select(Transaction).where(Transaction.type == TransactionType.SELL)
    )
    assert sell.fee_amount is None
    assert sell.fee_asset_id is None


def test_real_revolut_export_imports_cleanly():
    """The demo export must import without row errors and create disposals."""
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

    taxpayer = Taxpayer(name="Revolut Real", tax_id="55555555K")
    session.add(taxpayer)
    session.commit()
    session.refresh(taxpayer)

    acc = Account(
        name="Revolut", taxpayer_id=taxpayer.id,
        platform=AccountPlatform.REVOLUT, is_abroad=True,
    )
    session.add(acc)
    session.commit()
    session.refresh(acc)

    batch = import_excel(
        session, connector_name="REVOLUT", taxpayer_id=taxpayer.id, account_id=acc.id,
        filename=REAL_CSV.name, content=REAL_CSV.read_bytes(),
    )

    assert batch.errors_json is None, batch.errors_json
    # Count data rows (header + trailing newline tolerant) and verify we got
    # exactly two canonical transactions per data row.
    data_rows = [line for line in REAL_CSV.read_text(encoding="utf-8").splitlines() if line.strip()][1:]
    assert batch.inserted_count == len(data_rows) * 2

    # Every round-trip produces a taxable disposal.
    assert session.scalar(select(func.count()).select_from(Disposal)) > 0

    session.close()
