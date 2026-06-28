"""Translate persisted (canonical) transactions into FIFO engine moves.

This is the bridge between the stored model and the pure engine. It decides,
per transaction type, what is an acquisition and what is a disposal, and values
each leg in EUR. Swaps become a DISPOSE of the asset given plus an ACQUIRE of
the asset received. Income (staking/airdrop/referral) becomes both an ACQUIRE
(new lot at fair market value) and an :class:`IncomeSpec` for the tax layer.

Internal movements (DEPOSIT without a cost basis, WITHDRAWAL, TRANSFER) are
ignored because FIFO is tracked globally across the taxpayer's accounts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.core.money import ZERO, to_decimal
from app.models import IncomeCategory, Transaction, TransactionType
from app.models.enums import DisposalKind
from app.services.fifo_engine import LedgerMove, MoveType

INCOME_CATEGORY_MAP: dict[TransactionType, IncomeCategory] = {
    TransactionType.STAKING_REWARD: IncomeCategory.RCM,
    TransactionType.REFERRAL: IncomeCategory.RCM,
    TransactionType.AIRDROP: IncomeCategory.GANANCIA,
}

_DISPOSAL_KIND_MAP = {
    TransactionType.SELL: DisposalKind.SALE,
    TransactionType.SWAP: DisposalKind.SWAP,
    TransactionType.SPEND: DisposalKind.SPEND,
}


@dataclass
class IncomeSpec:
    ref: int | None
    asset_id: int
    received_at: datetime
    quantity: Decimal
    eur_value: Decimal
    category: IncomeCategory
    fiscal_year: int


def _is_fiat(asset) -> bool:
    return asset is not None and asset.is_fiat


def _fee_eur(tx: Transaction) -> Decimal:
    if tx.fee_amount and _is_fiat(tx.fee_asset):
        return to_decimal(tx.fee_amount)
    return ZERO


def _acquisition_cost(tx: Transaction) -> Decimal:
    if tx.eur_value:
        cost = to_decimal(tx.eur_value)
    elif _is_fiat(tx.asset_out) and tx.amount_out:
        cost = to_decimal(tx.amount_out)
    else:
        cost = ZERO
    return cost + _fee_eur(tx)


def _disposal_proceeds(tx: Transaction) -> Decimal:
    if tx.eur_value:
        proceeds = to_decimal(tx.eur_value)
    elif _is_fiat(tx.asset_in) and tx.amount_in:
        proceeds = to_decimal(tx.amount_in)
    else:
        proceeds = ZERO
    return proceeds - _fee_eur(tx)


def build_ledger(transactions: list[Transaction]) -> tuple[list[LedgerMove], list[IncomeSpec]]:
    moves: list[LedgerMove] = []
    incomes: list[IncomeSpec] = []

    for seq, tx in enumerate(transactions):
        t = tx.type
        if t == TransactionType.BUY:
            if tx.asset_in_id and not _is_fiat(tx.asset_in):
                moves.append(LedgerMove(seq, tx.timestamp, tx.asset_in_id, MoveType.ACQUIRE,
                                        to_decimal(tx.amount_in), _acquisition_cost(tx), tx.id))
        elif t in (TransactionType.SELL, TransactionType.SPEND):
            if tx.asset_out_id and not _is_fiat(tx.asset_out):
                moves.append(LedgerMove(seq, tx.timestamp, tx.asset_out_id, MoveType.DISPOSE,
                                        to_decimal(tx.amount_out), _disposal_proceeds(tx), tx.id,
                                        _DISPOSAL_KIND_MAP[t]))
        elif t == TransactionType.SWAP:
            market = to_decimal(tx.eur_value)
            if tx.asset_out_id and not _is_fiat(tx.asset_out):
                moves.append(LedgerMove(seq, tx.timestamp, tx.asset_out_id, MoveType.DISPOSE,
                                        to_decimal(tx.amount_out), market - _fee_eur(tx), tx.id,
                                        DisposalKind.SWAP))
            if tx.asset_in_id and not _is_fiat(tx.asset_in):
                moves.append(LedgerMove(seq, tx.timestamp, tx.asset_in_id, MoveType.ACQUIRE,
                                        to_decimal(tx.amount_in), market, tx.id))
        elif t in INCOME_CATEGORY_MAP:
            fmv = to_decimal(tx.eur_value)
            if tx.asset_in_id and not _is_fiat(tx.asset_in):
                moves.append(LedgerMove(seq, tx.timestamp, tx.asset_in_id, MoveType.ACQUIRE,
                                        to_decimal(tx.amount_in), fmv, tx.id))
                incomes.append(IncomeSpec(tx.id, tx.asset_in_id, tx.timestamp,
                                          to_decimal(tx.amount_in), fmv,
                                          INCOME_CATEGORY_MAP[t], tx.fiscal_year))
        elif t == TransactionType.DEPOSIT:
            # Only an acquisition if a cost basis is known (opening/external buy).
            if tx.asset_in_id and not _is_fiat(tx.asset_in) and tx.eur_value:
                moves.append(LedgerMove(seq, tx.timestamp, tx.asset_in_id, MoveType.ACQUIRE,
                                        to_decimal(tx.amount_in), to_decimal(tx.eur_value), tx.id))
        elif t == TransactionType.REVERSAL:
            # Clawback of a previously credited reward: remove the units with no
            # gain/loss and back out the income it had generated (assumed RCM,
            # matching cashback/referral). See docs/SUGGESTIONS.md.
            if tx.asset_out_id and not _is_fiat(tx.asset_out) and tx.amount_out:
                qty = to_decimal(tx.amount_out)
                moves.append(LedgerMove(seq, tx.timestamp, tx.asset_out_id,
                                        MoveType.REMOVE, qty, ZERO, tx.id))
                fmv = to_decimal(tx.eur_value)
                incomes.append(IncomeSpec(tx.id, tx.asset_out_id, tx.timestamp,
                                          -qty, -fmv, IncomeCategory.RCM, tx.fiscal_year))
        # WITHDRAWAL / TRANSFER / FEE: internal or embedded -> no move.

    return moves, incomes
