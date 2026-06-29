"""Generate, list and resolve review items (warnings needing user attention).

Review items centralise three kinds of warnings:
- Connector hints stored in Transaction.notes (P2P transfers, reversals, etc.).
- FIFO engine warnings (insufficient balance, reversal shortfall).
- Missing price quotes surfaced by reports such as Modelo 721.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Asset,
    PriceQuote,
    ReviewCategory,
    ReviewItem,
    ReviewSeverity,
    ReviewStatus,
    Taxpayer,
    Transaction,
    TransactionType,
)
from app.services.fifo_engine import EngineWarning
from app.services.reversal_matching import REVERSABLE_REWARD_TYPES, match_reversals


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _note_category(note: str | None) -> ReviewCategory | None:
    if not note:
        return None
    low = note.lower()
    if "p2p" in low:
        return ReviewCategory.P2P_TRANSFER
    if "reversión" in low or "reversion" in low or "reverted" in low:
        return ReviewCategory.REVERSAL
    return ReviewCategory.MANUAL_REVIEW


def _severity_for(category: ReviewCategory) -> ReviewSeverity:
    if category == ReviewCategory.INSUFFICIENT_BALANCE:
        return ReviewSeverity.WARNING
    if category == ReviewCategory.MISSING_PRICE:
        return ReviewSeverity.WARNING
    return ReviewSeverity.INFO


def generate_manual_items(db: Session, *, taxpayer_id: int | None = None) -> int:
    """Scan Transaction.notes and upsert review items.

    If taxpayer_id is None, scans all transactions.
    Returns number of pending items ensured.
    """
    q = select(Transaction).where(Transaction.notes.isnot(None))
    if taxpayer_id is not None:
        q = q.where(Transaction.taxpayer_id == taxpayer_id)
    created = 0
    for tx in db.scalars(q):
        category = _note_category(tx.notes)
        if category is None:
            continue
        existing = db.scalar(
            select(ReviewItem).where(
                ReviewItem.transaction_id == tx.id,
                ReviewItem.category == category,
            )
        )
        if existing is not None:
            # Keep the message in sync if the note changed.
            if existing.status == ReviewStatus.PENDING and existing.message != tx.notes:
                existing.message = tx.notes
            continue
        db.add(
            ReviewItem(
                transaction_id=tx.id,
                taxpayer_id=tx.taxpayer_id,
                category=category,
                severity=_severity_for(category),
                message=tx.notes,
                status=ReviewStatus.PENDING,
            )
        )
        created += 1
    db.commit()
    return created


def auto_resolve_reversals(db: Session, *, taxpayer_id: int | None = None) -> int:
    """Auto-resolve reversal review items when they match a prior reward.

    Crypto.com (and similar platforms) sometimes claws back a reward (cashback,
    staking, airdrop) within the same fiscal year. When the reversal exactly
    matches a prior income-like transaction by asset, quantity, account and year,
    the net fiscal effect is zero, so no user review is needed.

    This function scans pending REVERSAL items, finds their paired reward and
    marks the item as RESOLVED with action ``AUTO_RESOLVED``. Unmatched reversals
    remain PENDING so the user can review them manually.

    Returns the number of items auto-resolved.
    """
    q = (
        select(ReviewItem)
        .where(ReviewItem.category == ReviewCategory.REVERSAL)
        .where(ReviewItem.status == ReviewStatus.PENDING)
    )
    if taxpayer_id is not None:
        q = q.where(ReviewItem.taxpayer_id == taxpayer_id)
    items = list(db.scalars(q))
    if not items:
        return 0

    # Fetch reward + reversal transactions in scope and pair them with the same
    # shared matcher the FIFO ledger uses, so the inbox and the tax computation
    # agree on which reversals are matched.
    q_tx = select(Transaction).where(
        Transaction.type.in_(REVERSABLE_REWARD_TYPES | {TransactionType.REVERSAL})
    )
    if taxpayer_id is not None:
        q_tx = q_tx.where(Transaction.taxpayer_id == taxpayer_id)
    txs = list(db.scalars(q_tx))
    reversal_map = match_reversals(txs)
    tx_by_id = {tx.id: tx for tx in txs}

    resolved = 0
    for item in items:
        if item.transaction_id is None:
            continue
        reward_id = reversal_map.get(item.transaction_id)
        if reward_id is None:
            continue
        match = tx_by_id.get(reward_id)
        item.status = ReviewStatus.RESOLVED
        item.resolution_action = "AUTO_RESOLVED"
        item.resolution_note = (
            f"Auto-resuelto: emparejado con recompensa previa "
            f"(tx {match.id}, {match.amount_in} {match.asset_in.symbol}, "
            f"{match.timestamp.date().isoformat()}). Ingreso deshecho con su misma categoría."
        )
        item.resolved_at = datetime.utcnow()
        resolved += 1
    db.commit()
    return resolved


def _engine_category(warn: EngineWarning) -> ReviewCategory:
    if warn.category == "INSUFFICIENT_BALANCE":
        return ReviewCategory.INSUFFICIENT_BALANCE
    if warn.category == "REVERSAL_SHORTFALL":
        return ReviewCategory.REVERSAL
    return ReviewCategory.MANUAL_REVIEW


def generate_fifo_items(
    db: Session,
    warnings: list[EngineWarning],
    *,
    taxpayer_ids: list[int] | None = None,
) -> int:
    """Create/update review items from FIFO engine warnings.

    The caller should pass the warnings returned by ``run_fifo``; each warning
    carries a ``ref`` (transaction id) so we can derive taxpayer_id.
    """
    if not warnings:
        return 0

    # Build lookup for warnings without a transaction ref.
    tx_lookup = {}
    refs = [w.ref for w in warnings if w.ref is not None]
    if refs:
        for tx in db.scalars(select(Transaction).where(Transaction.id.in_(refs))):
            tx_lookup[tx.id] = tx

    created = 0
    for warn in warnings:
        tx = tx_lookup.get(warn.ref) if warn.ref else None
        taxpayer_id = tx.taxpayer_id if tx else None
        if taxpayer_ids and taxpayer_id not in taxpayer_ids:
            continue
        category = _engine_category(warn)
        existing = None
        if tx:
            existing = db.scalar(
                select(ReviewItem).where(
                    ReviewItem.transaction_id == tx.id,
                    ReviewItem.category == category,
                )
            )
        if existing is not None:
            if existing.status == ReviewStatus.PENDING:
                existing.message = warn.message
            continue
        db.add(
            ReviewItem(
                transaction_id=tx.id if tx else None,
                taxpayer_id=taxpayer_id,
                category=category,
                severity=_severity_for(category),
                message=warn.message,
                status=ReviewStatus.PENDING,
            )
        )
        created += 1
    db.commit()
    return created


def generate_missing_price_items(
    db: Session,
    *,
    year: int,
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = None,
) -> int:
    """Create review items for assets held abroad at year-end without a price quote."""
    from app.services import model721_service

    ids = taxpayer_ids if taxpayer_ids else ([taxpayer_id] if taxpayer_id is not None else None)
    result = model721_service.compute(db, year, taxpayer_ids=ids)
    created = 0
    for h in result.get("holdings", []):
        if h.get("price_eur") is not None:
            continue
        asset = db.scalar(select(Asset).where(Asset.symbol == h["asset"].upper()))
        if asset is None:
            continue
        # Find an account for the taxpayer so we can attach the item.
        from app.models import Account
        account = db.scalar(select(Account).where(Account.id == h["account_id"]))
        target_taxpayer = account.taxpayer_id if account else (ids[0] if ids else None)
        if target_taxpayer is None:
            continue
        target_date = date(year, 12, 31)
        existing = db.scalar(
            select(ReviewItem).where(
                ReviewItem.transaction_id.is_(None),
                ReviewItem.category == ReviewCategory.MISSING_PRICE,
                ReviewItem.taxpayer_id == target_taxpayer,
                ReviewItem.message.ilike(f"%asset_id={asset.id}%"),
                ReviewItem.message.ilike(f"%{year}%"),
            )
        )
        if existing is not None:
            continue
        db.add(
            ReviewItem(
                transaction_id=None,
                taxpayer_id=target_taxpayer,
                category=ReviewCategory.MISSING_PRICE,
                severity=ReviewSeverity.WARNING,
                message=(
                    f"Falta cotización a 31/12/{year} para {asset.symbol} "
                    f"(asset_id={asset.id}); el valor del Modelo 721 no se calcula."
                ),
                status=ReviewStatus.PENDING,
            )
        )
        created += 1
    db.commit()
    return created


# ---------------------------------------------------------------------------
# Listing and summary
# ---------------------------------------------------------------------------

def list_items(
    db: Session,
    *,
    taxpayer_ids: list[int] | None = None,
    status: ReviewStatus | None = None,
    category: ReviewCategory | None = None,
    year: int | None = None,
    limit: int = 500,
) -> list[ReviewItem]:
    q = select(ReviewItem)
    if taxpayer_ids:
        q = q.where(ReviewItem.taxpayer_id.in_(taxpayer_ids))
    if status is not None:
        q = q.where(ReviewItem.status == status)
    if category is not None:
        q = q.where(ReviewItem.category == category)
    if year is not None:
        q = q.where(ReviewItem.message.ilike(f"%{year}%"))
    q = q.order_by(ReviewItem.created_at.desc()).limit(limit)
    return list(db.scalars(q))


def summary(db: Session, *, taxpayer_ids: list[int] | None = None) -> dict:
    q = select(ReviewItem)
    if taxpayer_ids:
        q = q.where(ReviewItem.taxpayer_id.in_(taxpayer_ids))
    rows = list(db.scalars(q))
    out = {
        "total": len(rows),
        "pending": 0,
        "resolved": 0,
        "ignored": 0,
        "by_category": {},
    }
    for r in rows:
        status_val = r.status.value if hasattr(r.status, "value") else r.status
        cat = r.category.value if hasattr(r.category, "value") else r.category
        out[status_val.lower()] += 1
        out["by_category"][cat] = out["by_category"].get(cat, 0) + 1
    return out


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

VALID_ACTIONS = {
    ReviewCategory.P2P_TRANSFER: {
        "MARK_OWN_ACCOUNT",
        "MARK_THIRD_PARTY_SEND",
        "MARK_PAYMENT",
        "IGNORE",
    },
    ReviewCategory.REVERSAL: {"REVIEWED_OK", "IGNORE", "AUTO_RESOLVED"},
    ReviewCategory.INSUFFICIENT_BALANCE: {"ACCEPT_ZERO_BASIS", "CREATE_OPENING_POSITION", "IGNORE"},
    ReviewCategory.MANUAL_REVIEW: {"REVIEWED_OK", "IGNORE"},
    ReviewCategory.MISSING_PRICE: {"ADD_PRICE_QUOTE", "IGNORE"},
}


def _category_value(cat) -> str:
    return cat.value if hasattr(cat, "value") else str(cat)


def resolve_item(
    db: Session,
    item_id: int,
    *,
    action: str,
    note: str | None = None,
    payload: dict | None = None,
) -> ReviewItem:
    item = db.get(ReviewItem, item_id)
    if item is None:
        raise ValueError(f"Review item {item_id} no encontrado")
    status_val = item.status.value if hasattr(item.status, "value") else item.status
    if status_val != ReviewStatus.PENDING.value:
        raise ValueError("El aviso ya ha sido resuelto o ignorado")


    cat_key = _category_value(item.category)
    valid = VALID_ACTIONS.get(cat_key, set())
    if action not in valid:
        raise ValueError(f"Acción {action!r} no válida para categoría {cat_key}")

    if action == "ADD_PRICE_QUOTE":
        _add_price_quote(db, payload or {})

    if action == "CREATE_OPENING_POSITION":
        _create_opening_position(db, item, payload or {})

    if action in {"MARK_OWN_ACCOUNT", "MARK_THIRD_PARTY_SEND", "MARK_PAYMENT"}:
        _apply_p2p_resolution(db, item, action)

    item.status = ReviewStatus.RESOLVED.value if action != "IGNORE" else ReviewStatus.IGNORED.value
    item.resolution_action = action
    item.resolution_note = note
    item.resolved_at = datetime.utcnow()
    db.commit()
    # Local import to avoid a circular dependency with the recompute module.
    from app.services.recompute import recompute_all
    recompute_all(db)
    return item


def revert_item(db: Session, item_id: int) -> ReviewItem:
    """Revert a resolved/ignored review item back to PENDING.

    This lets the user correct a mistaken resolution. Side effects created by
    the original action (e.g. a price quote or an opening position transaction)
    are intentionally left in place; removing them automatically is risky. The
    user can delete or adjust them separately if needed.
    """
    item = db.get(ReviewItem, item_id)
    if item is None:
        raise ValueError(f"Review item {item_id} no encontrado")
    status_val = item.status.value if hasattr(item.status, "value") else item.status
    if status_val == ReviewStatus.PENDING.value:
        raise ValueError("El aviso ya está pendiente")

    item.status = ReviewStatus.PENDING
    item.resolution_action = None
    item.resolution_note = None
    item.resolved_at = None
    db.commit()
    return item


def _apply_p2p_resolution(db: Session, item: ReviewItem, action: str) -> None:
    """Record the user's intent for a P2P transfer review item.

    - MARK_OWN_ACCOUNT: movement between the taxpayer's own wallets/exchanges;
      no fiscal effect (is_internal_transfer = True).
    - MARK_THIRD_PARTY_SEND / MARK_PAYMENT: asset left the taxpayer's control;
      treated as a taxable disposal when the transfer debits crypto.
    """
    if item.transaction_id is None:
        raise ValueError(f"{action} requiere una transacción asociada")
    tx = db.get(Transaction, item.transaction_id)
    if tx is None:
        raise ValueError("Transacción asociada no encontrada")
    if tx.type != TransactionType.TRANSFER:
        raise ValueError("Solo las transacciones de tipo TRANSFER pueden resolverse como P2P")
    # Local import avoids a circular dependency (fiscal_year_service -> recompute
    # -> review_service).
    from app.services.fiscal_year_service import is_year_closed

    if is_year_closed(db, tx.taxpayer_id, tx.fiscal_year):
        raise ValueError(
            f"El año {tx.fiscal_year} está cerrado; reábrelo para reclasificar esta transferencia."
        )
    tx.is_internal_transfer = action == "MARK_OWN_ACCOUNT"


def _add_price_quote(db: Session, payload: dict) -> None:
    asset_symbol = (payload.get("asset_symbol") or "").upper()
    price_eur = payload.get("price_eur")
    quote_date = payload.get("date")
    if not asset_symbol or price_eur is None or not quote_date:
        raise ValueError("ADD_PRICE_QUOTE requiere asset_symbol, price_eur y date")
    asset = db.scalar(select(Asset).where(Asset.symbol == asset_symbol))
    if asset is None:
        raise ValueError(f"Activo {asset_symbol} no encontrado")
    try:
        d = datetime.fromisoformat(quote_date).date()
    except Exception as exc:
        raise ValueError("date debe ser ISO (YYYY-MM-DD)") from exc
    existing = db.scalar(
        select(PriceQuote).where(
            PriceQuote.asset_id == asset.id,
            PriceQuote.date == d,
            PriceQuote.source == "manual",
        )
    )
    if existing is not None:
        existing.price_eur = Decimal(str(price_eur))
    else:
        db.add(
            PriceQuote(
                asset_id=asset.id,
                date=d,
                price_eur=Decimal(str(price_eur)),
                source="manual",
            )
        )


def _create_opening_position(db: Session, item: ReviewItem, payload: dict) -> None:
    """Create a DEPOSIT transaction representing the missing cost basis.

    This is a thin wrapper around fiscal_year_service.add_opening_position; it
    requires the user to supply quantity and cost_basis_eur for the missing units.
    """
    from app.services import fiscal_year_service

    if item.transaction_id is None:
        raise ValueError("CREATE_OPENING_POSITION requiere una transacción asociada")
    tx = db.get(Transaction, item.transaction_id)
    if tx is None:
        raise ValueError("Transacción asociada no encontrada")
    asset_symbol = payload.get("asset_symbol") or (tx.asset_in.symbol if tx.asset_in else None)
    quantity = payload.get("quantity")
    cost_basis = payload.get("cost_basis_eur")
    acquired_at = payload.get("acquired_at") or tx.timestamp.isoformat()
    if not asset_symbol or quantity is None or cost_basis is None:
        raise ValueError("CREATE_OPENING_POSITION requiere asset_symbol, quantity y cost_basis_eur")
    fiscal_year_service.add_opening_position(
        db,
        taxpayer_id=tx.taxpayer_id,
        asset_symbol=asset_symbol,
        quantity=Decimal(str(quantity)),
        cost_basis_eur=Decimal(str(cost_basis)),
        acquired_at=datetime.fromisoformat(acquired_at),
    )
