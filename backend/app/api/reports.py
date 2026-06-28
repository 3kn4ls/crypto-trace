"""Reporting & charts data, including Modelo 721."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services import model721_service, reporting_service

router = APIRouter()


def _get_taxpayer_ids(
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = Query(default=None),
) -> list[int] | None:
    return taxpayer_ids if taxpayer_ids else ([taxpayer_id] if taxpayer_id is not None else None)


@router.get("/portfolio")
def portfolio(
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict]:
    return reporting_service.portfolio(db, taxpayer_ids=_get_taxpayer_ids(taxpayer_id, taxpayer_ids))


@router.get("/by-asset")
def by_asset(
    year: int | None = None,
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict]:
    return reporting_service.realized_by_asset(
        db, year=year, taxpayer_ids=_get_taxpayer_ids(taxpayer_id, taxpayer_ids)
    )


@router.get("/yearly")
def yearly(
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict]:
    return reporting_service.yearly_summary(db, taxpayer_ids=_get_taxpayer_ids(taxpayer_id, taxpayer_ids))


@router.get("/model721/{year}")
def model721(
    year: int,
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    return model721_service.compute(
        db, year, taxpayer_ids=_get_taxpayer_ids(taxpayer_id, taxpayer_ids)
    )


@router.get("/dashboard")
def dashboard(
    year: int | None = None,
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    ids = _get_taxpayer_ids(taxpayer_id, taxpayer_ids)
    return reporting_service.dashboard(db, taxpayer_ids=ids, year=year)
