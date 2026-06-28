"""Pure, deterministic FIFO matching engine.

This module is intentionally free of any database or framework dependency: it
operates on in-memory :class:`LedgerMove` objects and returns plain result
objects. That keeps it reusable for the persistence flow *and* for Phase 2
"what-if" simulations (clone the lot state, apply hypothetical disposals).

FIFO is applied per asset (homogeneous values, DGT criterion). Acquisitions
push a lot; disposals consume the oldest lots first. Crypto-to-crypto swaps are
decomposed by the caller into a DISPOSE of the asset given plus an ACQUIRE of
the asset received, both at their EUR market value.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.core.money import ZERO, quantize_eur
from app.models.enums import DisposalKind


class MoveType(str, Enum):
    ACQUIRE = "ACQUIRE"
    DISPOSE = "DISPOSE"
    REMOVE = "REMOVE"  # take units off the books with no gain/loss (reward clawback)


@dataclass
class LedgerMove:
    """One asset-level effect of a transaction, already valued in EUR.

    For ACQUIRE, ``eur`` is the total cost basis (price paid + acquisition fees).
    For DISPOSE, ``eur`` is the proceeds net of disposal fees.
    """

    seq: int  # stable tiebreaker for equal timestamps
    timestamp: datetime
    asset_id: int
    move: MoveType
    quantity: Decimal
    eur: Decimal
    ref: int | None = None  # source transaction id
    disposal_kind: DisposalKind | None = None


@dataclass
class EngineLot:
    key: int
    asset_id: int
    acquired_at: datetime
    qty_original: Decimal
    qty_remaining: Decimal
    unit_cost_eur: Decimal  # high precision, not rounded to cents
    source_ref: int | None


@dataclass
class EngineConsumption:
    lot_key: int
    qty_consumed: Decimal
    cost_basis_eur: Decimal
    proceeds_eur: Decimal
    gain_loss_eur: Decimal
    holding_days: int
    acquired_at: datetime
    disposed_at: datetime


@dataclass
class EngineDisposal:
    ref: int | None
    asset_id: int
    disposed_at: datetime
    quantity: Decimal
    proceeds_eur: Decimal
    cost_basis_eur: Decimal
    gain_loss_eur: Decimal
    disposal_kind: DisposalKind
    consumptions: list[EngineConsumption] = field(default_factory=list)


@dataclass
class EngineWarning:
    category: str
    asset_id: int
    ref: int | None
    timestamp: datetime
    message: str
    severity: str = "WARNING"
    quantity: Decimal | None = None


@dataclass
class EngineResult:
    lots: list[EngineLot]
    disposals: list[EngineDisposal]
    warnings: list[EngineWarning]


def run_fifo(moves: list[LedgerMove]) -> EngineResult:
    """Process moves in strict chronological order and return FIFO results."""
    ordered = sorted(moves, key=lambda m: (m.timestamp, m.seq))

    queues: dict[int, deque[EngineLot]] = defaultdict(deque)
    lots: list[EngineLot] = []
    disposals: list[EngineDisposal] = []
    warnings: list[EngineWarning] = []
    next_key = 0

    for mv in ordered:
        if mv.move == MoveType.ACQUIRE:
            if mv.quantity <= ZERO:
                continue
            unit_cost = (mv.eur / mv.quantity) if mv.quantity else ZERO
            lot = EngineLot(
                key=next_key,
                asset_id=mv.asset_id,
                acquired_at=mv.timestamp,
                qty_original=mv.quantity,
                qty_remaining=mv.quantity,
                unit_cost_eur=unit_cost,
                source_ref=mv.ref,
            )
            next_key += 1
            queues[mv.asset_id].append(lot)
            lots.append(lot)
        elif mv.move == MoveType.REMOVE:
            _remove(mv, queues[mv.asset_id], warnings)
        else:  # DISPOSE
            disposals.append(
                _consume(mv, queues[mv.asset_id], warnings)
            )

    return EngineResult(lots=lots, disposals=disposals, warnings=warnings)


def _remove(mv: LedgerMove, queue: deque[EngineLot], warnings: list[EngineWarning]) -> None:
    """Drop ``mv.quantity`` units off the FIFO queue without a taxable disposal.

    Used to undo a previously credited reward (e.g. a card-cashback reversal):
    the units leave the books but generate no gain/loss. The matching income is
    reversed separately by the tax layer.
    """
    remaining = mv.quantity
    while remaining > ZERO and queue and queue[0].qty_remaining > ZERO:
        lot = queue[0]
        take = min(lot.qty_remaining, remaining)
        lot.qty_remaining -= take
        remaining -= take
        if lot.qty_remaining <= ZERO:
            queue.popleft()
    if remaining > ZERO:
        warnings.append(
            EngineWarning(
                category="REVERSAL_SHORTFALL",
                asset_id=mv.asset_id,
                ref=mv.ref,
                timestamp=mv.timestamp,
                message=(
                    f"Reversión sin saldo suficiente para asset_id={mv.asset_id} en "
                    f"{mv.timestamp:%Y-%m-%d}: faltan {remaining} unidades por retirar."
                ),
                quantity=remaining,
            )
        )


def _consume(
    mv: LedgerMove, queue: deque[EngineLot], warnings: list[EngineWarning]
) -> EngineDisposal:
    qty_to_dispose = mv.quantity
    total_proceeds = mv.eur
    disposal = EngineDisposal(
        ref=mv.ref,
        asset_id=mv.asset_id,
        disposed_at=mv.timestamp,
        quantity=qty_to_dispose,
        proceeds_eur=quantize_eur(total_proceeds),
        cost_basis_eur=ZERO,
        gain_loss_eur=ZERO,
        disposal_kind=mv.disposal_kind or DisposalKind.SALE,
    )

    remaining = qty_to_dispose
    allocated_proceeds = ZERO

    while remaining > ZERO and queue and queue[0].qty_remaining > ZERO:
        lot = queue[0]
        take = min(lot.qty_remaining, remaining)
        cost_basis = quantize_eur(take * lot.unit_cost_eur)
        # Allocate proceeds proportionally to the quantity consumed.
        proceeds_portion = quantize_eur(total_proceeds * (take / qty_to_dispose)) if qty_to_dispose else ZERO
        disposal.consumptions.append(
            EngineConsumption(
                lot_key=lot.key,
                qty_consumed=take,
                cost_basis_eur=cost_basis,
                proceeds_eur=proceeds_portion,
                gain_loss_eur=proceeds_portion - cost_basis,
                holding_days=max((mv.timestamp - lot.acquired_at).days, 0),
                acquired_at=lot.acquired_at,
                disposed_at=mv.timestamp,
            )
        )
        allocated_proceeds += proceeds_portion
        lot.qty_remaining -= take
        remaining -= take
        if lot.qty_remaining <= ZERO:
            queue.popleft()

    if remaining > ZERO:
        # Disposing more than we have a recorded basis for: treat the shortfall
        # as zero-cost (full proceeds taxed as gain), the conservative choice.
        proceeds_portion = quantize_eur(total_proceeds * (remaining / qty_to_dispose)) if qty_to_dispose else ZERO
        disposal.consumptions.append(
            EngineConsumption(
                lot_key=-1,
                qty_consumed=remaining,
                cost_basis_eur=ZERO,
                proceeds_eur=proceeds_portion,
                gain_loss_eur=proceeds_portion,
                holding_days=0,
                acquired_at=mv.timestamp,
                disposed_at=mv.timestamp,
            )
        )
        allocated_proceeds += proceeds_portion
        warnings.append(
            EngineWarning(
                category="INSUFFICIENT_BALANCE",
                asset_id=mv.asset_id,
                ref=mv.ref,
                timestamp=mv.timestamp,
                message=(
                    f"Saldo insuficiente para asset_id={mv.asset_id} en {mv.timestamp:%Y-%m-%d}: "
                    f"se enajenan {remaining} unidades sin coste de adquisición registrado (base=0)."
                ),
                quantity=remaining,
            )
        )

    # Absorb any cent-level rounding remainder into the last consumption so the
    # disposal's proceeds always sum exactly to the given total.
    drift = quantize_eur(total_proceeds) - allocated_proceeds
    if disposal.consumptions and drift != ZERO:
        last = disposal.consumptions[-1]
        last.proceeds_eur += drift
        last.gain_loss_eur += drift

    disposal.cost_basis_eur = sum((c.cost_basis_eur for c in disposal.consumptions), ZERO)
    disposal.gain_loss_eur = disposal.proceeds_eur - disposal.cost_basis_eur
    return disposal
