"""Manage per-taxpayer fiscal treatment of reward transactions.

This service centralises the default classifications and lets users override
how STAKING_REWARD, REFERRAL and AIRDROP are treated in the FIFO engine and tax
computation.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IncomeCategory, TaxpayerRewardPreference, TransactionType

_DEFAULTS: dict[TransactionType, tuple[IncomeCategory, bool]] = {
    TransactionType.STAKING_REWARD: (IncomeCategory.RCM, False),
    TransactionType.REFERRAL: (IncomeCategory.RCM, False),
    TransactionType.AIRDROP: (IncomeCategory.GANANCIA, False),
}

_REWARD_TYPES = frozenset(_DEFAULTS.keys())


def get_preferences(db: Session, taxpayer_id: int) -> dict[TransactionType, TaxpayerRewardPreference]:
    """Return effective preferences for the taxpayer, falling back to defaults."""
    rows = {
        p.transaction_type: p
        for p in db.scalars(
            select(TaxpayerRewardPreference)
            .where(TaxpayerRewardPreference.taxpayer_id == taxpayer_id)
            .where(TaxpayerRewardPreference.transaction_type.in_(_REWARD_TYPES))
        )
    }
    out: dict[TransactionType, TaxpayerRewardPreference] = {}
    for tx_type, (category, zero_cost) in _DEFAULTS.items():
        if tx_type in rows:
            out[tx_type] = rows[tx_type]
        else:
            out[tx_type] = TaxpayerRewardPreference(
                taxpayer_id=taxpayer_id,
                transaction_type=tx_type,
                income_category=category,
                zero_cost_basis=zero_cost,
            )
    return out


def category_for(db: Session, taxpayer_id: int, tx_type: TransactionType) -> IncomeCategory:
    """Effective income category for a reward transaction type."""
    prefs = get_preferences(db, taxpayer_id)
    pref = prefs.get(tx_type)
    return pref.income_category if pref else _DEFAULTS.get(tx_type, (IncomeCategory.RCM, False))[0]


def is_zero_cost_basis(db: Session, taxpayer_id: int, tx_type: TransactionType) -> bool:
    """Whether reward acquisitions should enter FIFO with cost basis 0."""
    prefs = get_preferences(db, taxpayer_id)
    pref = prefs.get(tx_type)
    return pref.zero_cost_basis if pref else _DEFAULTS.get(tx_type, (IncomeCategory.RCM, False))[1]


def save_preferences(
    db: Session,
    taxpayer_id: int,
    preferences: list[dict],
) -> list[TaxpayerRewardPreference]:
    """Persist preference overrides for a taxpayer.

    ``preferences`` is a list of dicts with keys:
      - transaction_type (str): STAKING_REWARD | REFERRAL | AIRDROP
      - income_category (str): RCM | GANANCIA | ACTIVIDAD
      - zero_cost_basis (bool)
    """
    existing = {
        p.transaction_type: p
        for p in db.scalars(
            select(TaxpayerRewardPreference)
            .where(TaxpayerRewardPreference.taxpayer_id == taxpayer_id)
        )
    }
    out = []
    for item in preferences:
        tx_type = TransactionType(item["transaction_type"])
        category = IncomeCategory(item["income_category"])
        zero_cost = bool(item.get("zero_cost_basis", False))
        pref = existing.get(tx_type)
        if pref is None:
            pref = TaxpayerRewardPreference(
                taxpayer_id=taxpayer_id,
                transaction_type=tx_type,
                income_category=category,
                zero_cost_basis=zero_cost,
            )
            db.add(pref)
        else:
            pref.income_category = category
            pref.zero_cost_basis = zero_cost
        out.append(pref)
    db.flush()
    return out
