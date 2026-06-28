"""Aggregations that feed the dashboards and charts."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import ZERO, quantize_eur, to_decimal
from app.models import Account, Asset, Disposal, IncomeEvent, Lot, LotConsumption, ReviewItem, Transaction, TransactionType
from app.services.pricing_service import get_price


def _filter_by_taxpayers(q, model, taxpayer_ids: list[int] | None):
    if taxpayer_ids:
        return q.where(model.taxpayer_id.in_(taxpayer_ids))
    return q


def account_balances(
    db: Session, *, taxpayer_ids: list[int] | None = None, as_of: date | None = None
) -> dict[tuple[int, int], Decimal]:
    """Net quantity per (account_id, asset_id) from raw transactions."""
    balances: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    q = select(Transaction)
    if taxpayer_ids:
        q = q.where(Transaction.taxpayer_id.in_(taxpayer_ids))
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


def portfolio(db: Session, taxpayer_ids: list[int] | None = None) -> list[dict]:
    """Current holdings per asset from remaining FIFO lots, valued at latest price."""
    by_asset: dict[int, dict[str, Decimal]] = defaultdict(lambda: {"qty": ZERO, "cost": ZERO})
    q = select(Lot)
    if taxpayer_ids:
        q = q.where(Lot.taxpayer_id.in_(taxpayer_ids))
    for lot in db.scalars(q):
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


def realized_by_asset(
    db: Session, year: int | None = None, taxpayer_ids: list[int] | None = None
) -> list[dict]:
    agg: dict[int, dict[str, Decimal]] = defaultdict(
        lambda: {"proceeds": ZERO, "cost": ZERO, "gain": ZERO}
    )
    q = select(Disposal)
    if year is not None:
        q = q.where(Disposal.fiscal_year == year)
    if taxpayer_ids:
        q = q.where(Disposal.taxpayer_id.in_(taxpayer_ids))
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


def yearly_summary(db: Session, taxpayer_ids: list[int] | None = None) -> list[dict]:
    """Per fiscal year: realized gains/losses and income totals (live, from detail)."""
    from app.services.fiscal_year_service import compute_year

    q_disposals = select(Disposal.fiscal_year)
    q_incomes = select(IncomeEvent.fiscal_year)
    if taxpayer_ids:
        q_disposals = q_disposals.where(Disposal.taxpayer_id.in_(taxpayer_ids))
        q_incomes = q_incomes.where(IncomeEvent.taxpayer_id.in_(taxpayer_ids))

    years = sorted(set(db.scalars(q_disposals)) | set(db.scalars(q_incomes)))
    out = []
    for y in years:
        r = compute_year(db, y, taxpayer_ids=taxpayer_ids)
        out.append({
            "year": y,
            "total_gains": str(r.total_gains),
            "total_losses": str(r.total_losses),
            "net_capital_gain": str(r.net_capital_gain),
            "income_rcm": str(r.rcm_income),
            "income_ganancia": str(r.ganancia_income),
            "income_actividad": str(r.actividad_income),
            "savings_base": str(r.savings_base),
            "tax_due_eur": str(r.tax_due),
            "effective_rate": str(r.effective_rate),
        })
    return out


# ---------------------------------------------------------------------------
# Dashboard aggregate
# ---------------------------------------------------------------------------

def _to_dec(value: str | Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return ZERO


def dashboard(db: Session, *, taxpayer_ids: list[int] | None = None, year: int | None = None) -> dict:
    """Aggregate dashboard data: fiscal, portfolio, activity, reviews and Modelo 721."""
    from app.services import review_service
    from app.services import model721_service

    today = date.today()

    # ---- fiscal years (live computation) -----------------------------------
    q_disposals = select(Disposal.fiscal_year)
    q_incomes = select(IncomeEvent.fiscal_year)
    if taxpayer_ids:
        q_disposals = q_disposals.where(Disposal.taxpayer_id.in_(taxpayer_ids))
        q_incomes = q_incomes.where(IncomeEvent.taxpayer_id.in_(taxpayer_ids))
    fiscal_years = sorted(set(db.scalars(q_disposals)) | set(db.scalars(q_incomes)))

    years_data = yearly_summary(db, taxpayer_ids=taxpayer_ids)
    selected_years = [y for y in years_data if year is None or y["year"] == year]

    fiscal_totals = {
        "total_gains": sum((_to_dec(y["total_gains"]) for y in selected_years), ZERO),
        "total_losses": sum((_to_dec(y["total_losses"]) for y in selected_years), ZERO),
        "net_capital_gain": sum((_to_dec(y["net_capital_gain"]) for y in selected_years), ZERO),
        "rcm_income": sum((_to_dec(y["income_rcm"]) for y in selected_years), ZERO),
        "ganancia_income": sum((_to_dec(y["income_ganancia"]) for y in selected_years), ZERO),
        "actividad_income": sum((_to_dec(y["income_actividad"]) for y in selected_years), ZERO),
        "savings_base": sum((_to_dec(y["savings_base"]) for y in selected_years), ZERO),
        "tax_due_eur": sum((_to_dec(y["tax_due_eur"]) for y in selected_years), ZERO),
    }

    # ---- portfolio (current, or year-end when filtered) ----------------------
    portfolio_as_of = date(year, 12, 31) if year else today
    portfolio_data = _portfolio_at_date(db, taxpayer_ids=taxpayer_ids, as_of=portfolio_as_of)

    portfolio_value = sum((_to_dec(p["value_eur"]) for p in portfolio_data if p["value_eur"] is not None), ZERO)
    portfolio_cost = sum((_to_dec(p["cost_basis_eur"]) for p in portfolio_data), ZERO)
    portfolio_unrealized = sum(
        (_to_dec(p["unrealized_eur"]) for p in portfolio_data if p["unrealized_eur"] is not None),
        ZERO,
    )
    assets_with_price = sum(1 for p in portfolio_data if p["price_eur"] is not None)
    assets_without_price = len(portfolio_data) - assets_with_price

    sorted_by_value = sorted(
        portfolio_data,
        key=lambda p: _to_dec(p["value_eur"]) if p["value_eur"] is not None else ZERO,
        reverse=True,
    )
    top_assets = []
    for p in sorted_by_value[:5]:
        value = _to_dec(p["value_eur"])
        pct = (value / portfolio_value * Decimal("100")) if portfolio_value > ZERO else ZERO
        top_assets.append({
            **p,
            "pct": str(quantize_eur(pct)),
        })

    # ---- portfolio evolution (year-end values) -------------------------------
    evolution = []
    for y in fiscal_years:
        y_end = date(y, 12, 31)
        holdings = _portfolio_at_date(db, taxpayer_ids=taxpayer_ids, as_of=y_end)
        value = sum((_to_dec(h["value_eur"]) for h in holdings if h["value_eur"] is not None), ZERO)
        cost = sum((_to_dec(h["cost_basis_eur"]) for h in holdings), ZERO)
        evolution.append({"year": y, "value_eur": str(value), "cost_basis_eur": str(cost)})

    # ---- activity ------------------------------------------------------------
    q_tx = select(Transaction)
    if taxpayer_ids:
        q_tx = q_tx.where(Transaction.taxpayer_id.in_(taxpayer_ids))
    if year is not None:
        q_tx = q_tx.where(Transaction.fiscal_year == year)
    transactions = list(db.scalars(q_tx))
    total_transactions = len(transactions)

    tx_by_type: dict[str, int] = defaultdict(int)
    for tx in transactions:
        key = tx.type.value if hasattr(tx.type, "value") else str(tx.type)
        tx_by_type[key] += 1

    # ---- contributions / total invested (cash inflow) per asset ------------
    # Tracks fiat spent to buy each asset, plus the EUR cost of income received.
    contributions_by_asset: dict[int, dict[str, Decimal]] = defaultdict(
        lambda: {"invested_eur": ZERO, "rewards_eur": ZERO, "cost_basis_eur": ZERO, "quantity": ZERO}
    )
    for tx in transactions:
        if tx.asset_in_id is None or tx.asset_in is None or tx.asset_in.is_fiat:
            continue
        asset_id = tx.asset_in_id
        qty = to_decimal(tx.amount_in)
        eur = to_decimal(tx.eur_value)
        contributions_by_asset[asset_id]["quantity"] += qty
        if tx.type == TransactionType.BUY:
            # Direct fiat purchase: the EUR value is cash contributed.
            contributions_by_asset[asset_id]["invested_eur"] += eur
            contributions_by_asset[asset_id]["cost_basis_eur"] += eur
        elif tx.type in (TransactionType.STAKING_REWARD, TransactionType.REFERRAL, TransactionType.AIRDROP):
            # Income-like acquisition: counted separately as "rewards", but also
            # adds to cost basis so totals reconcile with FIFO lots.
            contributions_by_asset[asset_id]["rewards_eur"] += eur
            contributions_by_asset[asset_id]["cost_basis_eur"] += eur
        elif tx.type == TransactionType.DEPOSIT and tx.eur_value:
            # Deposit with known cost basis (e.g. opening position or external transfer in).
            contributions_by_asset[asset_id]["invested_eur"] += eur
            contributions_by_asset[asset_id]["cost_basis_eur"] += eur
        elif tx.type == TransactionType.SWAP:
            # Crypto-to-crypto swap: cost basis is the EUR value provided by the connector.
            contributions_by_asset[asset_id]["cost_basis_eur"] += eur

    # Subtract disposals that happened in the selected period so "invested" and
    # "rewards" reflect what remains in the portfolio. We keep it simple:
    # for the dashboard we show cumulative totals (money put in vs value now).

    contributions = []
    for asset_id, agg in contributions_by_asset.items():
        if agg["quantity"] <= ZERO:
            continue
        asset = db.get(Asset, asset_id)
        if asset is None:
            continue
        contributions.append({
            "asset": asset.symbol,
            "quantity": str(agg["quantity"]),
            "invested_eur": str(quantize_eur(agg["invested_eur"])),
            "rewards_eur": str(quantize_eur(agg["rewards_eur"])),
            "cost_basis_eur": str(quantize_eur(agg["cost_basis_eur"])),
        })
    contributions.sort(key=lambda x: _to_dec(x["cost_basis_eur"]), reverse=True)

    q_income = select(IncomeEvent)
    if taxpayer_ids:
        q_income = q_income.where(IncomeEvent.taxpayer_id.in_(taxpayer_ids))
    if year is not None:
        q_income = q_income.where(IncomeEvent.fiscal_year == year)
    income_events = list(db.scalars(q_income))
    total_income_events = len(income_events)

    income_by_category: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"count": ZERO, "eur": ZERO})
    for ev in income_events:
        cat = ev.category.value if hasattr(ev.category, "value") else str(ev.category)
        income_by_category[cat]["count"] += 1
        income_by_category[cat]["eur"] += ev.eur_value

    last_transactions = []
    for tx in sorted(transactions, key=lambda t: t.timestamp, reverse=True)[:5]:
        last_transactions.append({
            "id": tx.id,
            "timestamp": tx.timestamp.isoformat(),
            "type": tx.type.value if hasattr(tx.type, "value") else str(tx.type),
            "asset_in": tx.asset_in.symbol if tx.asset_in else None,
            "amount_in": str(tx.amount_in) if tx.amount_in is not None else None,
            "asset_out": tx.asset_out.symbol if tx.asset_out else None,
            "amount_out": str(tx.amount_out) if tx.amount_out is not None else None,
            "eur_value": str(tx.eur_value) if tx.eur_value is not None else None,
        })

    # ---- reviews -------------------------------------------------------------
    review_summary = review_service.summary(db, taxpayer_ids=taxpayer_ids)
    q_reviews = select(ReviewItem)
    if taxpayer_ids:
        q_reviews = q_reviews.where(ReviewItem.taxpayer_id.in_(taxpayer_ids))
    if year is not None:
        q_reviews = q_reviews.where(ReviewItem.message.ilike(f"%{year}%"))
    all_reviews = list(db.scalars(q_reviews.order_by(ReviewItem.created_at.desc())))

    reviews_by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"pending": 0, "resolved": 0, "ignored": 0})
    for r in all_reviews:
        cat = r.category.value if hasattr(r.category, "value") else str(r.category)
        status = r.status.value if hasattr(r.status, "value") else str(r.status)
        reviews_by_category[cat][status.lower()] = reviews_by_category[cat].get(status.lower(), 0) + 1

    pending_reviews = []
    for r in all_reviews:
        if (r.status.value if hasattr(r.status, "value") else r.status) == "PENDING":
            pending_reviews.append({
                "id": r.id,
                "transaction_id": r.transaction_id,
                "category": r.category.value if hasattr(r.category, "value") else r.category,
                "severity": r.severity.value if hasattr(r.severity, "value") else r.severity,
                "message": r.message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        if len(pending_reviews) >= 5:
            break

    # ---- Modelo 721 ----------------------------------------------------------
    model721 = {"total_abroad_eur": "0", "obligated": False, "accounts_count": 0}
    if fiscal_years:
        m721_year = year if year else max(fiscal_years)
        m721 = model721_service.compute(db, m721_year, taxpayer_ids=taxpayer_ids)
        unique_accounts = {h["account_id"] for h in m721.get("holdings", []) if h.get("is_abroad") and h.get("value_eur")}
        model721 = {
            "total_abroad_eur": str(m721.get("total_abroad_eur", "0")),
            "obligated": bool(m721.get("obligated", False)),
            "accounts_count": len(unique_accounts),
            "threshold_eur": str(m721.get("threshold_eur", "50000")),
            "year": m721_year,
        }

    return {
        "year": year,
        "years": selected_years,
        "fiscal_totals": {k: str(v) for k, v in fiscal_totals.items()},
        "closed_years_count": 0,  # placeholder: fiscal year closure status not central here
        "open_years_count": len(fiscal_years),
        "portfolio": {
            "total_value_eur": str(portfolio_value),
            "total_cost_basis_eur": str(portfolio_cost),
            "unrealized_gain_eur": str(portfolio_unrealized),
            "assets_count": len(portfolio_data),
            "assets_with_price": assets_with_price,
            "assets_without_price": assets_without_price,
            "top_assets": top_assets,
        },
        "portfolio_evolution": evolution,
        "activity": {
            "total_transactions": total_transactions,
            "transactions_by_type": dict(tx_by_type),
            "total_income_events": total_income_events,
            "income_by_category": {
                k: {"count": int(v["count"]), "eur": str(quantize_eur(v["eur"]))}
                for k, v in income_by_category.items()
            },
            "last_transactions": last_transactions,
        },
        "contributions": contributions,
        "invested_totals": {
            "invested_eur": str(quantize_eur(sum((_to_dec(c["invested_eur"]) for c in contributions), ZERO))),
            "rewards_eur": str(quantize_eur(sum((_to_dec(c["rewards_eur"]) for c in contributions), ZERO))),
            "cost_basis_eur": str(quantize_eur(sum((_to_dec(c["cost_basis_eur"]) for c in contributions), ZERO))),
        },
        "reviews": {
            "summary": review_summary,
            "by_category": dict(reviews_by_category),
            "pending": pending_reviews,
        },
        "model721": model721,
    }


def _portfolio_at_date(db: Session, *, taxpayer_ids: list[int] | None, as_of: date) -> list[dict]:
    """Current-style portfolio valued as of a specific date.

    Uses remaining FIFO lots plus an adjustment for disposals/consumptions
    that happened after ``as_of``. Simpler path: value lots acquired on/before
    ``as_of`` and still remaining, then subtract the consumed portion of those
    lots by disposals after ``as_of``.
    """
    from app.services.pricing_service import get_price

    q = select(Lot)
    if taxpayer_ids:
        q = q.where(Lot.taxpayer_id.in_(taxpayer_ids))
    lots = list(db.scalars(q))

    # Pre-calculate total consumed per lot after as_of.
    q_cons = select(LotConsumption)
    q_cons = q_cons.where(LotConsumption.disposed_at > datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59))
    future_consumptions = list(db.scalars(q_cons))
    consumed_after: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for c in future_consumptions:
        if c.lot_id is not None:
            consumed_after[c.lot_id] += c.qty_consumed

    by_asset: dict[int, dict[str, Decimal]] = defaultdict(lambda: {"qty": ZERO, "cost": ZERO})
    for lot in lots:
        if lot.acquired_at.date() > as_of:
            continue
        qty = lot.qty_remaining
        # If this lot had future consumptions, its current qty_remaining already
        # reflects them because the engine runs on full history. For a historical
        # as_of we want qty at that moment: add back consumptions after as_of.
        qty_at_date = qty + consumed_after.get(lot.id, ZERO)
        if qty_at_date <= ZERO:
            continue
        by_asset[lot.asset_id]["qty"] += qty_at_date
        by_asset[lot.asset_id]["cost"] += qty_at_date * lot.unit_cost_eur

    out = []
    for asset_id, agg in by_asset.items():
        asset = db.get(Asset, asset_id)
        price = get_price(db, asset_id, as_of)
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
