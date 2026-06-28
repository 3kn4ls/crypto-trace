"""End-to-end import test: build a Crypto.com-style XLSX, import it, check FIFO."""
from __future__ import annotations

from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import func, select

from app.models import Account, AccountPlatform, Disposal, IncomeEvent, Lot, Taxpayer, Transaction
from app.services.import_service import import_excel

HEADERS = [
    "Timestamp (UTC)", "Transaction Kind", "Currency", "Amount",
    "To Currency", "To Amount", "Native Amount", "Transaction Hash",
]
ROWS = [
    ["2024-01-10 10:00:00", "viban_purchase", "BTC", "0.5", "", "", "15000", "tx1"],
    ["2024-02-10 10:00:00", "crypto_purchase", "BTC", "0.5", "", "", "20000", "tx2"],
    ["2024-03-10 10:00:00", "crypto_exchange", "BTC", "0.5", "ETH", "5", "18000", "tx3"],
    ["2024-06-10 10:00:00", "crypto_viban_exchange", "BTC", "0.5", "", "", "25000", "tx4"],
    ["2024-07-01 10:00:00", "crypto_earn_interest_paid", "ETH", "0.1", "", "", "300", "tx5"],
]


def _build_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for r in ROWS:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _account(db, taxpayer_id: int) -> Account:
    acc = Account(
        name="Crypto.com", taxpayer_id=taxpayer_id,
        platform=AccountPlatform.CRYPTO_COM, is_abroad=True,
    )
    db.add(acc)
    db.commit()
    return acc


def _taxpayer(db) -> Taxpayer:
    taxpayer = Taxpayer(name="Import Test", tax_id="11111111H")
    db.add(taxpayer)
    db.commit()
    db.refresh(taxpayer)
    return taxpayer


def test_import_creates_transactions_and_fifo(db):
    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)
    batch = import_excel(
        db, connector_name="CRYPTO_COM", taxpayer_id=taxpayer.id, account_id=acc.id,
        filename="cdc.xlsx", content=_build_xlsx(),
    )
    assert batch.inserted_count == 5
    assert db.scalar(select(func.count()).select_from(Transaction)) == 5

    # Two disposals: the BTC leg of the swap and the BTC sale.
    disposals = list(db.scalars(select(Disposal)))
    assert len(disposals) == 2
    total_gain = sum((d.gain_loss_eur for d in disposals), Decimal("0"))
    # swap: 18000 - 15000 = 3000 ; sale: 25000 - 20000 = 5000
    assert total_gain == Decimal("8000.00")

    # Lots: buy1, buy2, ETH from swap, ETH from staking = 4.
    assert db.scalar(select(func.count()).select_from(Lot)) == 4

    incomes = list(db.scalars(select(IncomeEvent)))
    assert len(incomes) == 1
    assert incomes[0].eur_value == Decimal("300")
    assert incomes[0].taxpayer_id == taxpayer.id


def test_reimport_is_idempotent(db):
    taxpayer = _taxpayer(db)
    acc = _account(db, taxpayer.id)
    content = _build_xlsx()
    import_excel(
        db, connector_name="CRYPTO_COM", taxpayer_id=taxpayer.id,
        account_id=acc.id, filename="cdc.xlsx", content=content,
    )
    batch2 = import_excel(
        db, connector_name="CRYPTO_COM", taxpayer_id=taxpayer.id,
        account_id=acc.id, filename="cdc.xlsx", content=content,
    )
    assert batch2.inserted_count == 0
    assert batch2.duplicate_count == 5
    assert db.scalar(select(func.count()).select_from(Transaction)) == 5
