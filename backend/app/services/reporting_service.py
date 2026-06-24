"""Aggregations that feed the dashboards and charts."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import ZERO, quantize_eur
from app.models import Account, Asset, Disposal, IncomeEvent, Lot, Transaction
from app.services.pricing_service import get_price


def account_balances(db: Session, as_of: date | None = None) -> dict[tuple[int, int], Decimal]:
    """Net quantity per (account_id, asset_id) from raw transactions."""
    balances: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    q = select(Transaction)
    if as_of is not None:
        q = q.where(Transaction.timestamp <= datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59))
    for tx in db.scalars(q):
        if tx.asset_in_id and tx.amount_in:
            balances[(tx.account_id, tx.asset_in_id)] += tx.amount_in
        if tx.asset_out_id and tx.amount_out:
            balances[(tx.account_id, tx.asset_out_id)] -= tx.amount_out
        if tx.fee_asset_id and tx.fee_amount:
            balances[(tx.account_id, tx.fee_asset_id)] -= tx.fee_amount
    return balances


def portfolio(db: Session) -> list[dict]:
    """Current holdings per asset from remaining FIFO lots, valued at latest price."""
    by_asset: dict[int, dict[str, Decimal]] = defaultdict(lambda: {"qty": ZERO, "cost": ZERO})
    for lot in db.scalars(select(Lot)):
        if lot.qty_remaining <= ZERO:
            continue
        by_asset[lot.asset_id]["qty"] += lot.qty_remaining
        by_asset[lot.asset_id]["cost"] += lot.qty_remaining * lot.unit_cost_eur

    today = date.today()
    out = []
    for asset_id, agg in by_asset.items():
        asset = db.get(Asset, asset_id)
        price = get_price(db, asset_id, today)
        value = quantize_eur(agg["qty"] * price) if price is not None else None
        cost = quantize_eur(agg["cost"])
        out.append({
            "asset": asset.symbol if asset else str(asset_id),
            "quantity": str(agg["qty"]),
            "cost_basis_eur": str(cost),
            "price_eur": str(price) if price is not None else None,
            "value_eur": str(value) if value is not None else None,
            "unrealized_eur": str(quantize_eur(value - cost)) if value is not None else None,
        })
    return sorted(out, key=lambda r: r["asset"])


def realized_by_asset(db: Session, year: int | None = None) -> list[dict]:
    agg: dict[int, dict[str, Decimal]] = defaultdict(
        lambda: {"proceeds": ZERO, "cost": ZERO, "gain": ZERO}
    )
    q = select(Disposal)
    if year is not None:
        q = q.where(Disposal.fiscal_year == year)
    for d in db.scalars(q):
        a = agg[d.asset_id]
        a["proceeds"] += d.proceeds_eur
        a["cost"] += d.cost_basis_eur
        a["gain"] += d.gain_loss_eur
    out = []
    for asset_id, a in agg.items():
        asset = db.get(Asset, asset_id)
        out.append({
            "asset": asset.symbol if asset else str(asset_id),
            "proceeds_eur": str(quantize_eur(a["proceeds"])),
            "cost_basis_eur": str(quantize_eur(a["cost"])),
            "gain_loss_eur": str(quantize_eur(a["gain"])),
        })
    return sorted(out, key=lambda r: r["asset"])


def yearly_summary(db: Session) -> list[dict]:
    """Per fiscal year: realized gains/losses and income totals (live, from detail)."""
    from app.services.fiscal_year_service import compute_year

    years = sorted(set(db.scalars(select(Disposal.fiscal_year))) |
                   set(db.scalars(select(IncomeEvent.fiscal_year))))
    out = []
    for y in years:
        r = compute_year(db, y)
        out.append({
            "year": y,
            "total_gains": str(r.total_gains),
            "total_losses": str(r.total_losses),
            "net_capital_gain": str(r.net_capital_gain),
            "income_rcm": str(r.rcm_income),
            "savings_base": str(r.savings_base),
            "tax_due_eur": str(r.tax_due),
            "effective_rate": str(r.effective_rate),
        })
    return out
