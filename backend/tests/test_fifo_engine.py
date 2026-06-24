"""Deterministic tests for the pure FIFO engine."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.models.enums import DisposalKind
from app.services.fifo_engine import LedgerMove, MoveType, run_fifo


def _dt(day: int) -> datetime:
    return datetime(2024, 1, day)


def acquire(seq, day, asset_id, qty, eur, ref=None):
    return LedgerMove(seq, _dt(day), asset_id, MoveType.ACQUIRE, Decimal(qty), Decimal(eur), ref)


def dispose(seq, day, asset_id, qty, eur, kind=DisposalKind.SALE, ref=None):
    return LedgerMove(seq, _dt(day), asset_id, MoveType.DISPOSE, Decimal(qty), Decimal(eur), ref, kind)


def test_simple_buy_then_sell_gain():
    res = run_fifo([acquire(0, 1, 1, "1", "10000"), dispose(1, 5, 1, "1", "15000")])
    assert len(res.disposals) == 1
    d = res.disposals[0]
    assert d.cost_basis_eur == Decimal("10000.00")
    assert d.proceeds_eur == Decimal("15000.00")
    assert d.gain_loss_eur == Decimal("5000.00")
    assert res.warnings == []


def test_partial_multilot_fifo():
    moves = [
        acquire(0, 1, 1, "1", "10000"),
        acquire(1, 2, 1, "1", "20000"),
        dispose(2, 3, 1, "1.5", "30000"),
    ]
    res = run_fifo(moves)
    d = res.disposals[0]
    # 1 BTC @10000 + 0.5 BTC @20000 = 20000 cost basis.
    assert d.cost_basis_eur == Decimal("20000.00")
    assert d.gain_loss_eur == Decimal("10000.00")
    assert len(d.consumptions) == 2
    # Lot 2 should retain 0.5 remaining.
    lot2 = res.lots[1]
    assert lot2.qty_remaining == Decimal("0.5")


def test_loss_disposal():
    res = run_fifo([acquire(0, 1, 1, "2", "40000"), dispose(1, 9, 1, "1", "15000")])
    d = res.disposals[0]
    assert d.cost_basis_eur == Decimal("20000.00")
    assert d.gain_loss_eur == Decimal("-5000.00")


def test_insufficient_balance_zero_basis_warning():
    # Dispose 1 BTC with nothing acquired -> zero cost basis, full proceeds gain.
    res = run_fifo([dispose(0, 1, 1, "1", "12000")])
    d = res.disposals[0]
    assert d.cost_basis_eur == Decimal("0.00")
    assert d.gain_loss_eur == Decimal("12000.00")
    assert len(res.warnings) == 1


def test_chronological_ordering_independent_of_input_order():
    # Feed disposals before the acquisition; engine must sort by timestamp.
    moves = [dispose(5, 5, 1, "1", "15000"), acquire(0, 1, 1, "1", "10000")]
    res = run_fifo(moves)
    assert res.disposals[0].gain_loss_eur == Decimal("5000.00")
    assert res.warnings == []


def test_swap_decomposed_as_dispose_plus_acquire():
    # Swap ETH->BTC at t2: dispose 10 ETH (proceeds 30000) + acquire 1 BTC (cost 30000).
    moves = [
        acquire(0, 1, 2, "10", "20000"),  # buy 10 ETH for 20000
        dispose(1, 2, 2, "10", "30000", kind=DisposalKind.SWAP),  # give 10 ETH worth 30000
        acquire(2, 2, 1, "1", "30000"),  # receive 1 BTC worth 30000
        dispose(3, 9, 1, "1", "35000"),  # later sell the BTC
    ]
    res = run_fifo(moves)
    eth_disposal = res.disposals[0]
    assert eth_disposal.disposal_kind == DisposalKind.SWAP
    assert eth_disposal.gain_loss_eur == Decimal("10000.00")  # 30000 - 20000
    btc_disposal = res.disposals[1]
    assert btc_disposal.cost_basis_eur == Decimal("30000.00")
    assert btc_disposal.gain_loss_eur == Decimal("5000.00")  # 35000 - 30000
