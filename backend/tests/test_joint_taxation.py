"""Tests for multi-taxpayer aggregation (joint tax declaration)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.models import Account, AccountPlatform, Taxpayer, Transaction
from app.services.fiscal_year_service import compute_year
from app.services.import_service import import_excel


def _build_csv(rows: list[tuple[str, str, str, str]]) -> bytes:
    header = "Timestamp (UTC),Transaction Kind,Currency,Amount,To Currency,To Amount,Native Amount,Transaction Hash"
    lines = [header]
    for ts, kind, currency, native in rows:
        lines.append(f"{ts},{kind},{currency},1,,,{native},")
    return "\n".join(lines).encode("utf-8")


def _make_taxpayer_and_account(db, name: str, tax_id: str) -> tuple[Taxpayer, Account]:
    taxpayer = Taxpayer(name=name, tax_id=tax_id)
    db.add(taxpayer)
    db.commit()
    db.refresh(taxpayer)
    account = Account(
        taxpayer_id=taxpayer.id, name=f"Cuenta {tax_id}",
        platform=AccountPlatform.CRYPTO_COM, is_abroad=True,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return taxpayer, account


def test_joint_declaration_aggregates_bases(db):
    """Two taxpayers with gains; joint result uses combined base and brackets."""
    tp1, acc1 = _make_taxpayer_and_account(db, "Alice", "10000001A")
    tp2, acc2 = _make_taxpayer_and_account(db, "Bob", "20000002B")

    content1 = _build_csv([
        ("2024-01-01 10:00:00", "crypto_purchase", "BTC", "10000"),
        ("2024-06-01 10:00:00", "crypto_viban_exchange", "BTC", "20000"),  # gain 10000
    ])
    content2 = _build_csv([
        ("2024-01-01 10:00:00", "crypto_purchase", "ETH", "5000"),
        ("2024-06-01 10:00:00", "crypto_viban_exchange", "ETH", "15000"),  # gain 10000
    ])

    import_excel(
        db, connector_name="CRYPTO_COM", taxpayer_id=tp1.id, account_id=acc1.id,
        filename="alice.csv", content=content1,
    )
    import_excel(
        db, connector_name="CRYPTO_COM", taxpayer_id=tp2.id, account_id=acc2.id,
        filename="bob.csv", content=content2,
    )

    # Individual results.
    r1 = compute_year(db, 2024, taxpayer_ids=[tp1.id])
    r2 = compute_year(db, 2024, taxpayer_ids=[tp2.id])
    assert r1.net_capital_gain == Decimal("10000.00")
    assert r2.net_capital_gain == Decimal("10000.00")

    # Joint result: base = 20000.
    joint = compute_year(db, 2024, taxpayer_ids=[tp1.id, tp2.id])
    assert joint.net_capital_gain == Decimal("20000.00")
    # 6000*0.19 + 14000*0.21 = 1140 + 2940
    assert joint.tax_due == Decimal("4080.00")
