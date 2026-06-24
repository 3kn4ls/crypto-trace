"""Reporting & charts data, including Modelo 721."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services import model721_service, reporting_service

router = APIRouter()


@router.get("/portfolio")
def portfolio(db: Session = Depends(get_db)) -> list[dict]:
    return reporting_service.portfolio(db)


@router.get("/by-asset")
def by_asset(year: int | None = None, db: Session = Depends(get_db)) -> list[dict]:
    return reporting_service.realized_by_asset(db, year)


@router.get("/yearly")
def yearly(db: Session = Depends(get_db)) -> list[dict]:
    return reporting_service.yearly_summary(db)


@router.get("/model721/{year}")
def model721(year: int, db: Session = Depends(get_db)) -> dict:
    return model721_service.compute(db, year)
