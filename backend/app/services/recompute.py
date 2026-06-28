"""Rebuild all derived fiscal state (lots, disposals, income) from transactions.

Transactions are the single source of truth. Because FIFO depends on the full
history, the simplest correct strategy at single-user scale is a full recompute:
wipe the derived tables and replay every transaction through the engine. Opening
positions for past years are themselves transactions (a DEPOSIT carrying a cost
basis), so they participate naturally.
"""
from __future__ import annotations

from sqlalchemy import delete, select

from sqlalchemy.orm import Session

from app.models import Disposal, IncomeEvent, Lot, LotConsumption, Transaction
from app.services.fifo_engine import run_fifo
from app.services.ledger import build_ledger
from app.services.review_service import (
    auto_resolve_reversals,
    generate_fifo_items,
    generate_manual_items,
)



def recompute_all(db: Session) -> dict:
    # Wipe derived state (order respects FKs).
    db.execute(delete(LotConsumption))
    db.execute(delete(Disposal))
    db.execute(delete(IncomeEvent))
    db.execute(delete(Lot))
    db.flush()

    txs = list(
        db.scalars(select(Transaction).order_by(Transaction.timestamp, Transaction.id))
    )
    moves, incomes = build_ledger(db, txs)
    result = run_fifo(moves)

    # Build a lookup from transaction id to its taxpayer for derived rows.
    tx_taxpayer: dict[int | None, int] = {tx.id: tx.taxpayer_id for tx in txs}

    keymap: dict[int, int] = {}
    for el in result.lots:
        lot = Lot(
            taxpayer_id=tx_taxpayer.get(el.source_ref, 1),
            asset_id=el.asset_id,
            account_id=None,
            acquired_at=el.acquired_at,
            qty_original=el.qty_original,
            qty_remaining=el.qty_remaining,
            unit_cost_eur=el.unit_cost_eur,
            source_tx_id=el.source_ref,
            fiscal_year_acquired=el.acquired_at.year,
        )
        db.add(lot)
        db.flush()
        keymap[el.key] = lot.id

    for ed in result.disposals:
        disp = Disposal(
            taxpayer_id=tx_taxpayer.get(ed.ref, 1),
            tx_id=ed.ref,
            asset_id=ed.asset_id,
            disposed_at=ed.disposed_at,
            quantity=ed.quantity,
            proceeds_eur=ed.proceeds_eur,
            cost_basis_eur=ed.cost_basis_eur,
            gain_loss_eur=ed.gain_loss_eur,
            fiscal_year=ed.disposed_at.year,
            disposal_kind=ed.disposal_kind,
        )
        db.add(disp)
        db.flush()
        for ec in ed.consumptions:
            db.add(
                LotConsumption(
                    disposal_id=disp.id,
                    lot_id=keymap.get(ec.lot_key),
                    qty_consumed=ec.qty_consumed,
                    cost_basis_eur=ec.cost_basis_eur,
                    proceeds_eur=ec.proceeds_eur,
                    gain_loss_eur=ec.gain_loss_eur,
                    holding_days=ec.holding_days,
                    acquired_at=ec.acquired_at,
                    disposed_at=ec.disposed_at,
                )
            )

    for inc in incomes:
        db.add(
            IncomeEvent(
                taxpayer_id=tx_taxpayer.get(inc.ref, 1),
                tx_id=inc.ref,
                asset_id=inc.asset_id,
                received_at=inc.received_at,
                quantity=inc.quantity,
                eur_value=inc.eur_value,
                category=inc.category,
                fiscal_year=inc.fiscal_year,
            )
        )

    db.commit()

    # Ensure review items exist for manual connector notes and FIFO warnings.
    generate_manual_items(db)
    auto_resolve_reversals(db)
    generate_fifo_items(db, result.warnings)

    return {
        "lots": len(result.lots),
        "disposals": len(result.disposals),
        "income_events": len(incomes),
        "warnings": len(result.warnings),
    }
