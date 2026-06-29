"""Reversal pairing: a REVERSAL inherits the fiscal treatment of its reward.

Covers the fix for the bug where a reversal always backed out RCM regardless of
the matched reward's category or zero-cost setting (docs/ANALISIS.md §1.1):

* matched reversal of an RCM reward -> RCM backed out (net 0);
* matched reversal of a GANANCIA reward -> ganancia backed out, RCM untouched;
* matched reversal of a zero-cost reward -> nothing backed out (no phantom RCM);
* partial reversal -> only the reverted part is backed out;
* unmatched reversal -> units removed, no income reversed, review stays PENDING.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.models import (
    Account,
    AccountPlatform,
    Asset,
    IncomeEvent,
    Lot,
    ReviewCategory,
    ReviewItem,
    ReviewStatus,
    Transaction,
    TransactionType,
)
from app.services.fiscal_year_service import compute_year
from app.services.recompute import recompute_all
from app.services.reward_preference_service import save_preferences


def _btc(db) -> Asset:
    return db.scalar(select(Asset).where(Asset.symbol == "BTC"))


def _account(db, taxpayer_id: int) -> Account:
    acc = Account(
        taxpayer_id=taxpayer_id, name="Test", platform=AccountPlatform.MANUAL, type="EXCHANGE"
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def _reward(db, taxpayer_id, account_id, asset_id, *, kind, qty, eur, ts, ext):
    tx = Transaction(
        taxpayer_id=taxpayer_id, account_id=account_id, timestamp=ts, type=kind,
        asset_in_id=asset_id, amount_in=Decimal(qty), eur_value=Decimal(eur),
        fiscal_year=ts.year, external_id=ext,
    )
    db.add(tx)
    db.commit()
    return tx


def _reversal(db, taxpayer_id, account_id, asset_id, *, qty, eur, ts, ext):
    tx = Transaction(
        taxpayer_id=taxpayer_id, account_id=account_id, timestamp=ts,
        type=TransactionType.REVERSAL, asset_out_id=asset_id, amount_out=Decimal(qty),
        eur_value=Decimal(eur), fiscal_year=ts.year, external_id=ext,
        notes="Reversión de recompensa (deshace ingreso previo)",
    )
    db.add(tx)
    db.commit()
    return tx


def _review(db, tx_id):
    return db.scalar(
        select(ReviewItem).where(
            ReviewItem.transaction_id == tx_id,
            ReviewItem.category == ReviewCategory.REVERSAL,
        )
    )


def test_matched_rcm_reversal_nets_to_zero_and_auto_resolves(db, taxpayer):
    acc = _account(db, taxpayer.id)
    btc = _btc(db)
    _reward(db, taxpayer.id, acc.id, btc.id, kind=TransactionType.REFERRAL,
            qty="0.5", eur="3000", ts=datetime(2024, 6, 1), ext="rw-1")
    rev = _reversal(db, taxpayer.id, acc.id, btc.id,
                    qty="0.5", eur="3000", ts=datetime(2024, 6, 2), ext="rv-1")
    recompute_all(db)

    result = compute_year(db, 2024, taxpayer_ids=[taxpayer.id])
    assert result.rcm_income == Decimal("0.00")

    item = _review(db, rev.id)
    assert item is not None
    assert item.status == ReviewStatus.RESOLVED
    assert item.resolution_action == "AUTO_RESOLVED"


def test_matched_ganancia_reversal_backs_out_ganancia_not_rcm(db, taxpayer):
    acc = _account(db, taxpayer.id)
    btc = _btc(db)
    save_preferences(db, taxpayer.id, [
        {"transaction_type": "REFERRAL", "income_category": "GANANCIA", "zero_cost_basis": False},
    ])
    _reward(db, taxpayer.id, acc.id, btc.id, kind=TransactionType.REFERRAL,
            qty="0.5", eur="3000", ts=datetime(2024, 6, 1), ext="rw-1")
    _reversal(db, taxpayer.id, acc.id, btc.id,
              qty="0.5", eur="3000", ts=datetime(2024, 6, 2), ext="rv-1")
    recompute_all(db)

    result = compute_year(db, 2024, taxpayer_ids=[taxpayer.id])
    # The reversal is undone from ganancia (net 0), never turning RCM negative.
    assert result.ganancia_income == Decimal("0.00")
    assert result.rcm_income == Decimal("0.00")


def test_matched_zero_cost_reversal_creates_no_phantom_income(db, taxpayer):
    acc = _account(db, taxpayer.id)
    btc = _btc(db)
    save_preferences(db, taxpayer.id, [
        {"transaction_type": "REFERRAL", "income_category": "RCM", "zero_cost_basis": True},
    ])
    _reward(db, taxpayer.id, acc.id, btc.id, kind=TransactionType.REFERRAL,
            qty="0.5", eur="3000", ts=datetime(2024, 6, 1), ext="rw-1")
    _reversal(db, taxpayer.id, acc.id, btc.id,
              qty="0.5", eur="3000", ts=datetime(2024, 6, 2), ext="rv-1")
    recompute_all(db)

    # Zero-cost reward generated no income, so the reversal backs out nothing.
    assert db.scalar(select(func.count()).select_from(IncomeEvent)) == 0
    result = compute_year(db, 2024, taxpayer_ids=[taxpayer.id])
    assert result.rcm_income == Decimal("0.00")
    # Units still removed from FIFO (lot acquired at 0, fully reverted).
    lots = list(db.scalars(select(Lot)))
    assert all(lot.qty_remaining == Decimal("0") for lot in lots)


def test_partial_reversal_backs_out_reverted_part(db, taxpayer):
    acc = _account(db, taxpayer.id)
    btc = _btc(db)
    _reward(db, taxpayer.id, acc.id, btc.id, kind=TransactionType.REFERRAL,
            qty="1", eur="1000", ts=datetime(2024, 6, 1), ext="rw-1")
    _reversal(db, taxpayer.id, acc.id, btc.id,
              qty="0.4", eur="400", ts=datetime(2024, 6, 2), ext="rv-1")
    recompute_all(db)

    result = compute_year(db, 2024, taxpayer_ids=[taxpayer.id])
    assert result.rcm_income == Decimal("600.00")  # 1000 - 400
    lot = db.scalars(select(Lot)).first()
    assert lot.qty_remaining == Decimal("0.6")


def test_unmatched_reversal_reverses_no_income_and_stays_pending(db, taxpayer):
    acc = _account(db, taxpayer.id)
    btc = _btc(db)
    # A reversal with no prior reward in its bucket.
    rev = _reversal(db, taxpayer.id, acc.id, btc.id,
                    qty="0.5", eur="3000", ts=datetime(2024, 6, 2), ext="rv-1")
    recompute_all(db)

    # No income event is fabricated for an unmatched reversal.
    assert db.scalar(select(func.count()).select_from(IncomeEvent)) == 0
    result = compute_year(db, 2024, taxpayer_ids=[taxpayer.id])
    assert result.rcm_income == Decimal("0.00")

    item = _review(db, rev.id)
    assert item is not None
    assert item.status == ReviewStatus.PENDING
