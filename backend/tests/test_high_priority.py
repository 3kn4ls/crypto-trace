"""Tests for the four high-priority fiscal improvements.

1. Reward fiscal treatment is configurable per taxpayer (category + zero-cost basis).
2. DEPOSIT transactions can carry an explicit cost_basis_eur.
3. P2P transfers to third parties can be marked as taxable disposals.
4. API endpoints expose these settings.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.models import (
    Account,
    AccountPlatform,
    Asset,
    Disposal,
    IncomeCategory,
    IncomeEvent,
    Lot,
    ReviewCategory,
    ReviewItem,
    ReviewStatus,
    Transaction,
    TransactionType,
)
from app.services.recompute import recompute_all
from app.services.reward_preference_service import save_preferences
from app.services.review_service import resolve_item


def _btc(db):
    return db.scalar(select(Asset).where(Asset.symbol == "BTC"))


def _make_account(db, taxpayer_id: int, name: str = "Test") -> Account:
    acc = Account(
        taxpayer_id=taxpayer_id,
        name=name,
        platform=AccountPlatform.MANUAL,
        type="EXCHANGE",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def test_reward_preference_zero_cost_basis_reduces_lot_cost(db, taxpayer):
    acc = _make_account(db, taxpayer.id)
    btc = _btc(db)

    tx = Transaction(
        taxpayer_id=taxpayer.id,
        account_id=acc.id,
        timestamp=datetime(2024, 6, 1),
        type=TransactionType.STAKING_REWARD,
        asset_in_id=btc.id,
        amount_in=Decimal("0.5"),
        eur_value=Decimal("3000"),
        fiscal_year=2024,
        external_id="reward-1",
    )
    db.add(tx)
    db.commit()

    # Default: RCM, full FMV basis.
    recompute_all(db)
    lot = db.scalars(select(Lot)).first()
    assert lot.unit_cost_eur == Decimal("6000")  # 3000 / 0.5
    income = db.scalar(select(IncomeEvent))
    assert income.category == IncomeCategory.RCM

    # Switch to zero-cost-basis discount.
    save_preferences(
        db,
        taxpayer.id,
        [{"transaction_type": "STAKING_REWARD", "income_category": "GANANCIA", "zero_cost_basis": True}],
    )
    recompute_all(db)
    lot = db.scalars(select(Lot)).first()
    assert lot.unit_cost_eur == Decimal("0")
    assert db.scalar(select(IncomeEvent)) is None  # no income event when zero-cost basis


def test_deposit_uses_explicit_cost_basis(db, taxpayer):
    acc = _make_account(db, taxpayer.id)
    btc = _btc(db)

    tx = Transaction(
        taxpayer_id=taxpayer.id,
        account_id=acc.id,
        timestamp=datetime(2023, 1, 1),
        type=TransactionType.DEPOSIT,
        asset_in_id=btc.id,
        amount_in=Decimal("1"),
        eur_value=Decimal("50000"),  # market value at deposit
        cost_basis_eur=Decimal("20000"),  # actual acquisition cost
        fiscal_year=2023,
        external_id="deposit-1",
    )
    db.add(tx)
    db.commit()

    recompute_all(db)
    lot = db.scalars(select(Lot)).first()
    assert lot.unit_cost_eur == Decimal("20000")

    sell = Transaction(
        taxpayer_id=taxpayer.id,
        account_id=acc.id,
        timestamp=datetime(2024, 1, 1),
        type=TransactionType.SELL,
        asset_out_id=btc.id,
        amount_out=Decimal("1"),
        eur_value=Decimal("60000"),
        fiscal_year=2024,
        external_id="sell-1",
    )
    db.add(sell)
    db.commit()
    recompute_all(db)
    disposal = db.scalar(select(Disposal))
    assert disposal.gain_loss_eur == Decimal("40000")


def test_p2p_third_party_send_is_taxable_disposal(db, taxpayer):
    acc = _make_account(db, taxpayer.id)
    btc = _btc(db)

    buy = Transaction(
        taxpayer_id=taxpayer.id,
        account_id=acc.id,
        timestamp=datetime(2024, 1, 1),
        type=TransactionType.BUY,
        asset_in_id=btc.id,
        amount_in=Decimal("1"),
        eur_value=Decimal("30000"),
        fiscal_year=2024,
        external_id="buy-p2p",
    )
    db.add(buy)
    db.commit()

    transfer = Transaction(
        taxpayer_id=taxpayer.id,
        account_id=acc.id,
        timestamp=datetime(2024, 6, 1),
        type=TransactionType.TRANSFER,
        asset_out_id=btc.id,
        amount_out=Decimal("0.5"),
        eur_value=Decimal("0"),
        notes="P2P send to external wallet",
        fiscal_year=2024,
        external_id="p2p-send",
        is_internal_transfer=True,
    )
    db.add(transfer)
    db.commit()
    recompute_all(db)

    # Without resolution, internal transfer -> no disposal.
    assert db.scalar(select(Disposal)) is None

    item = db.scalar(
        select(ReviewItem).where(
            ReviewItem.transaction_id == transfer.id,
            ReviewItem.category == ReviewCategory.P2P_TRANSFER,
        )
    )
    assert item is not None
    resolve_item(db, item.id, action="MARK_THIRD_PARTY_SEND")

    disposal = db.scalar(select(Disposal))
    assert disposal is not None
    assert disposal.quantity == Decimal("0.5")


def test_api_reward_preferences(client):
    taxpayer = client.post("/api/taxpayers", json={"name": "Prefs Test", "tax_id": "11111111A"}).json()
    tp_id = taxpayer["id"]

    prefs = client.get(f"/api/taxpayers/{tp_id}/reward-preferences").json()
    assert len(prefs) == 3
    by_type = {p["transaction_type"]: p for p in prefs}
    assert by_type["STAKING_REWARD"]["income_category"] == "RCM"

    updated = [
        {"transaction_type": "STAKING_REWARD", "income_category": "GANANCIA", "zero_cost_basis": True},
        {"transaction_type": "REFERRAL", "income_category": "RCM", "zero_cost_basis": False},
        {"transaction_type": "AIRDROP", "income_category": "GANANCIA", "zero_cost_basis": False},
    ]
    resp = client.put(f"/api/taxpayers/{tp_id}/reward-preferences", json=updated).json()
    by_type = {p["transaction_type"]: p for p in resp}
    assert by_type["STAKING_REWARD"]["income_category"] == "GANANCIA"
    assert by_type["STAKING_REWARD"]["zero_cost_basis"] is True


def test_api_transaction_patch(client):
    taxpayer = client.post("/api/taxpayers", json={"name": "Patch Test", "tax_id": "22222222B"}).json()
    tp_id = taxpayer["id"]
    client.post("/api/accounts", json={
        "taxpayer_id": tp_id, "name": "Patch", "platform": "MANUAL", "type": "EXCHANGE",
    }).json()

    tx = client.post("/api/fiscal-years/opening-position", params={"taxpayer_id": tp_id}, json={
        "asset_symbol": "BTC", "quantity": "1", "cost_basis_eur": "30000", "acquired_at": "2023-06-01T00:00:00",
    }).json()

    patched = client.patch(f"/api/transactions/{tx['transaction_id']}", json={
        "cost_basis_eur": "25000", "is_internal_transfer": False, "notes": "Ajustado",
    }).json()
    assert patched["cost_basis_eur"] == "25000"
    assert patched["is_internal_transfer"] is False
    assert patched["notes"] == "Ajustado"
