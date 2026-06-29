"""Pair REVERSAL transactions with the reward they claw back.

A reversal (e.g. a card-cashback clawback when a purchase is refunded) must
inherit the fiscal treatment of the reward it reverses: the same income category
and zero-cost-basis flag, in the same fiscal year. Otherwise a reversal could
subtract from the wrong group (RCM vs ganancia) or back out income that a
zero-cost reward never generated.

We match a reversal to a reward in the same ``(taxpayer, account, asset,
fiscal_year)`` bucket, preferring an exact quantity match (a full clawback) and
otherwise the oldest reward with quantity still available. Remaining quantity is
tracked per reward so several partial reversals are attributed without double
counting (a partial refund reverts only part of a cashback).

This is a pure function over a list of transactions — no DB or framework
dependency — so the FIFO ledger (`services/ledger.py`) and the review service
(`services/review_service.py`) share the exact same pairing and never diverge.
"""
from __future__ import annotations

from decimal import Decimal

from app.core.money import ZERO, to_decimal
from app.models import Transaction, TransactionType

# Income-like reward types that a REVERSAL can claw back.
REVERSABLE_REWARD_TYPES = frozenset(
    {
        TransactionType.STAKING_REWARD,
        TransactionType.REFERRAL,
        TransactionType.AIRDROP,
    }
)


def match_reversals(transactions: list[Transaction]) -> dict[int, int]:
    """Return a mapping ``reversal_tx_id -> reward_tx_id`` for matched reversals.

    Reversals with no matching reward in their bucket are simply absent from the
    map; callers treat them as unmatched (units removed, no income reversed).
    """
    rewards_by_bucket: dict[tuple, list[Transaction]] = {}
    for tx in transactions:
        if tx.type in REVERSABLE_REWARD_TYPES and tx.asset_in_id is not None:
            key = (tx.taxpayer_id, tx.account_id, tx.asset_in_id, tx.fiscal_year)
            rewards_by_bucket.setdefault(key, []).append(tx)
    for bucket in rewards_by_bucket.values():
        bucket.sort(key=lambda t: (t.timestamp, t.id))

    # Unreversed quantity left on each reward, so partial reversals can be
    # attributed across rewards without one reward absorbing more than it gave.
    remaining: dict[int, Decimal] = {
        r.id: to_decimal(r.amount_in)
        for bucket in rewards_by_bucket.values()
        for r in bucket
    }

    out: dict[int, int] = {}
    reversals = [t for t in transactions if t.type == TransactionType.REVERSAL]
    for rev in sorted(reversals, key=lambda t: (t.timestamp, t.id)):
        if rev.asset_out_id is None or rev.amount_out is None:
            continue
        bucket = rewards_by_bucket.get(
            (rev.taxpayer_id, rev.account_id, rev.asset_out_id, rev.fiscal_year)
        )
        if not bucket:
            continue
        qty = to_decimal(rev.amount_out)
        candidates = [
            r for r in bucket
            if r.timestamp <= rev.timestamp and remaining.get(r.id, ZERO) > ZERO
        ]
        if not candidates:
            continue
        # Prefer an exact full clawback; otherwise the oldest available reward.
        match = next(
            (r for r in candidates if to_decimal(r.amount_in) == qty), candidates[0]
        )
        out[rev.id] = match.id
        remaining[match.id] = max(ZERO, remaining[match.id] - qty)
    return out
