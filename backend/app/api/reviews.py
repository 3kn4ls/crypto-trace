"""Review items API: list, summarise and resolve warnings."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import ReviewCategory, ReviewItem, ReviewStatus, Taxpayer
from app.services import review_service as rs

router = APIRouter()


class ResolveIn(BaseModel):
    action: str
    note: str | None = None
    payload: dict | None = None


class PriceQuotePayload(BaseModel):
    asset_symbol: str
    price_eur: str
    date: str


def _active_taxpayer_ids(
    db: Session, taxpayer_id: int | None = None, taxpayer_ids: list[int] | None = None
) -> list[int] | None:
    ids = taxpayer_ids if taxpayer_ids else ([taxpayer_id] if taxpayer_id is not None else None)
    if ids:
        existing = {tp.id for tp in db.scalars(select(Taxpayer).where(Taxpayer.id.in_(ids)))}
        if any(i not in existing for i in ids):
            raise HTTPException(404, "Algún contribuyente no existe")
    return ids


@router.get("")
def list_reviews(
    transaction_id: int | None = None,
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = Query(default=None),
    status: ReviewStatus | None = None,
    category: ReviewCategory | None = None,
    year: int | None = None,
    limit: int = 500,
    db: Session = Depends(get_db),
) -> list[dict]:
    if transaction_id is not None:
        items = db.scalars(
            select(ReviewItem)
            .where(ReviewItem.transaction_id == transaction_id)
            .order_by(ReviewItem.created_at.desc())
            .limit(limit)
        )
        return [_item_dict(i) for i in items]
    ids = _active_taxpayer_ids(db, taxpayer_id, taxpayer_ids)
    items = rs.list_items(
        db,
        taxpayer_ids=ids,
        status=status,
        category=category,
        year=year,
        limit=limit,
    )
    return [_item_dict(i) for i in items]


@router.get("/summary")
def review_summary(
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    ids = _active_taxpayer_ids(db, taxpayer_id, taxpayer_ids)
    return rs.summary(db, taxpayer_ids=ids)


@router.post("/generate")
def generate_reviews(
    year: int | None = None,
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    ids = _active_taxpayer_ids(db, taxpayer_id, taxpayer_ids)
    manual = rs.generate_manual_items(db, taxpayer_id=ids[0] if ids and len(ids) == 1 else None)
    auto = rs.auto_resolve_reversals(db, taxpayer_id=ids[0] if ids and len(ids) == 1 else None)
    prices = 0
    if year:
        prices = rs.generate_missing_price_items(db, year=year, taxpayer_ids=ids)
    return {"manual_items_ensured": manual, "auto_resolved_reversals": auto, "missing_price_items_ensured": prices}


@router.post("/{item_id}/resolve")
def resolve_review(
    item_id: int,
    payload: ResolveIn,
    db: Session = Depends(get_db),
) -> dict:
    try:
        item = rs.resolve_item(
            db,
            item_id,
            action=payload.action,
            note=payload.note,
            payload=payload.payload,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _item_dict(item)


@router.post("/{item_id}/ignore")
def ignore_review(
    item_id: int,
    note: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    try:
        item = rs.resolve_item(db, item_id, action="IGNORE", note=note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _item_dict(item)


@router.post("/{item_id}/revert")
def revert_review(item_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        item = rs.revert_item(db, item_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _item_dict(item)


def _val(v):
    return v.value if hasattr(v, "value") else v


def _item_dict(i: ReviewItem) -> dict:
    return {
        "id": i.id,
        "transaction_id": i.transaction_id,
        "taxpayer_id": i.taxpayer_id,
        "category": _val(i.category),
        "severity": _val(i.severity),
        "message": i.message,
        "status": _val(i.status),
        "resolution_action": i.resolution_action,
        "resolution_note": i.resolution_note,
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
    }
