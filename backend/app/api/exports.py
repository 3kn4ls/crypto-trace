"""CSV/PDF export endpoints for summary, transactions and Modelo 721."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services.export_service import (
    export_model721_csv,
    export_model721_pdf,
    export_summary_csv,
    export_summary_pdf,
    export_transactions_csv,
    export_transactions_pdf,
)

router = APIRouter()


def _get_taxpayer_ids(
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = Query(default=None),
) -> list[int] | None:
    return taxpayer_ids if taxpayer_ids else ([taxpayer_id] if taxpayer_id is not None else None)


_MEDIA_TYPES = {
    "csv": "text/csv; charset=utf-8-sig",
    "pdf": "application/pdf",
}


@router.get("/{scope}")
def export_scope(
    scope: str,
    format: str = Query(default="csv", pattern="^(csv|pdf)$"),
    year: int | None = None,
    taxpayer_id: int | None = None,
    taxpayer_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    ids = _get_taxpayer_ids(taxpayer_id, taxpayer_ids)
    if scope == "summary":
        if format == "csv":
            data, filename = export_summary_csv(db, taxpayer_ids=ids, year=year)
        else:
            data, filename = export_summary_pdf(db, taxpayer_ids=ids, year=year)
    elif scope == "transactions":
        if format == "csv":
            data, filename = export_transactions_csv(db, taxpayer_ids=ids, year=year)
        else:
            data, filename = export_transactions_pdf(db, taxpayer_ids=ids, year=year)
    elif scope == "model721":
        if year is None:
            raise HTTPException(400, "Modelo 721 requiere el parámetro year")
        if format == "csv":
            data, filename = export_model721_csv(db, year=year, taxpayer_ids=ids)
        else:
            data, filename = export_model721_pdf(db, year=year, taxpayer_ids=ids)
    else:
        raise HTTPException(400, f"Ámbito de exportación no soportado: {scope}")

    media_type = _MEDIA_TYPES.get(format, "application/octet-stream")
    return StreamingResponse(
        content=iter([data]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
