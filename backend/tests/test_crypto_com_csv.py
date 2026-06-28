"""Crypto.com CSV connector: format support, cashback, reversals, transfers.

Covers the real-world export shape (a ``.csv`` file, not XLSX) and the tricky
Crypto.com "Transaction Kind" values: card cashback (income), cashback reversal
(negative income + unit removal, no taxable disposal), supercharger/staking
locks and P2P transfers (no fiscal effect).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from app.models import (
    Account,
    AccountPlatform,
    Disposal,
    IncomeEvent,
    Lot,
    Taxpayer,
    Transaction,
    TransactionType,
)
from app.services.fiscal_year_service import compute_year
from app.services.import_service import import_excel

REAL_CSV = (
    Path(__file__).resolve().parents[2]
    / "informes"
    / "crypto_transactions_record_24062026_120003-1.csv"
)

HEADER = (
    "Timestamp (UTC),Transaction Description,Currency,Amount,To Currency,To Amount,"
    "Native Currency,Native Amount,Native Amount (in USD),Transaction Kind,Transaction Hash"
)


def _taxpayer(db) -> Taxpayer:
    taxpayer = Taxpayer(name="CDC Test", tax_id="22222222J")
    db.add(taxpayer)
    db.commit()
    db.refresh(taxpayer)
    return taxpayer


def _account(db, taxpayer_id: int) -> Account:
    acc = Account(
        name="Crypto.com", taxpayer_id=taxpayer_id,
        platform=AccountPlatform.CRYPTO_COM, is_abroad=True,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def _csv(*rows: str) -> bytes:
    return ("\n".join([HEADER, *rows]) + "\n").encode("utf-8")


def test_cashback_then_reversal_nets_income_and_removes_units(db):
    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)
    content = _csv(
        # Card Cashback: +100 CRO worth 10 EUR -> RCM income + a lot.
        "2025-03-01 10:00:00,Card Cashback,CRO,100,,,EUR,10,11,referral_card_cashback,",
        # Reversal: -40 CRO worth 4 EUR -> remove 40 units, back out 4 EUR income.
        "2025-03-02 10:00:00,Card Cashback Reversal,CRO,-40,,,EUR,4,5,card_cashback_reverted,",
    )
    batch = import_excel(
        db, connector_name="CRYPTO_COM", taxpayer_id=taxpayer.id, account_id=acc.id,
        filename="cdc.csv", content=content,
    )
    assert batch.inserted_count == 2
    assert batch.errors_json is None  # both kinds mapped, no row errors

    # No taxable disposal from a reward clawback.
    assert db.scalar(select(func.count()).select_from(Disposal)) == 0

    # One lot from the cashback, reduced from 100 to 60 by the reversal.
    lots = list(db.scalars(select(Lot)))
    assert len(lots) == 1
    assert lots[0].qty_remaining == Decimal("60")
    assert lots[0].taxpayer_id == taxpayer.id

    # Net RCM income for the year = 10 - 4 = 6 EUR.
    result = compute_year(db, 2025, taxpayer_ids=[taxpayer.id])
    assert result.rcm_income == Decimal("6.00")


def test_internal_and_p2p_transfers_have_no_fiscal_effect(db):
    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)
    content = _csv(
        "2025-04-01 10:00:00,Bought CRO,CRO,1000,,,EUR,100,110,crypto_purchase,",
        # Lock CRO for the card (internal) -> no disposal, no income.
        "2025-04-02 10:00:00,Cardholder CRO Stake,CRO,-500,,,EUR,50,55,finance.lockup.dpos_lock.crypto_wallet,",
        # Supercharger deposit/withdrawal (internal round-trip).
        "2025-04-03 10:00:00,Supercharger Deposit (via app),CRO,-200,,,EUR,20,22,supercharger_deposit,",
        "2025-04-04 10:00:00,Supercharger Withdrawal (via app),CRO,200,,,EUR,20,22,supercharger_withdrawal,",
        # P2P with a third party -> flagged, no fiscal effect.
        "2025-04-05 10:00:00,Sent to Nancy,CRO,-100,CRO,100,EUR,-10,-11,transfer.p2p_transfer.crypto_wallet.crypto_wallet.debit,",
    )
    batch = import_excel(
        db, connector_name="CRYPTO_COM", taxpayer_id=taxpayer.id, account_id=acc.id,
        filename="cdc.csv", content=content,
    )
    assert batch.inserted_count == 5
    assert batch.errors_json is None
    assert db.scalar(select(func.count()).select_from(Disposal)) == 0
    assert db.scalar(select(func.count()).select_from(IncomeEvent)) == 0

    # Only the purchase creates a lot; transfers/locks do not touch FIFO.
    lots = list(db.scalars(select(Lot)))
    assert len(lots) == 1
    assert lots[0].qty_remaining == Decimal("1000")

    # P2P row is flagged for manual review.
    p2p = db.scalar(
        select(Transaction).where(Transaction.type == TransactionType.TRANSFER,
                                  Transaction.notes.is_not(None))
    )
    assert p2p is not None and "P2P" in p2p.notes


def test_real_crypto_com_export_imports_cleanly():
    """The actual export must import with zero unmapped-kind errors."""
    import pytest

    if not REAL_CSV.exists():
        pytest.skip(f"sample export not present: {REAL_CSV}")

    # Fresh in-memory DB (this test does not use the `db` fixture's lifecycle
    # because we want a clean engine seeded the same way).
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.db import Base
    from app.core.seed import seed_all
    import app.models  # noqa: F401

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True, expire_on_commit=False)()
    seed_all(session)

    taxpayer = Taxpayer(name="CDC Real", tax_id="33333333P")
    session.add(taxpayer)
    session.commit()
    session.refresh(taxpayer)

    acc = Account(name="Crypto.com", taxpayer_id=taxpayer.id,
                  platform=AccountPlatform.CRYPTO_COM, is_abroad=True)
    session.add(acc)
    session.commit()
    session.refresh(acc)

    batch = import_excel(
        session, connector_name="CRYPTO_COM", taxpayer_id=taxpayer.id, account_id=acc.id,
        filename=REAL_CSV.name, content=REAL_CSV.read_bytes(),
    )

    # Every data row parsed (no "Transaction Kind no soportado" errors).
    assert batch.errors_json is None, batch.errors_json
    assert batch.row_count == 436  # 437 physical lines: 1 header + 436 data rows
    assert batch.inserted_count + batch.duplicate_count == 436

    # No SELL/SWAP/SPEND rows in this export => no taxable disposals.
    assert session.scalar(select(func.count()).select_from(Disposal)) == 0

    # Reversals produce negative income events (cashback clawbacks).
    negative = list(session.scalars(select(IncomeEvent).where(IncomeEvent.eur_value < 0)))
    assert 0 < len(negative) <= 6

    # Net 2025 RCM income is positive (rewards far exceed reversals).
    result = compute_year(session, 2025, taxpayer_ids=[taxpayer.id])
    assert result.rcm_income > Decimal("0")

    session.close()
