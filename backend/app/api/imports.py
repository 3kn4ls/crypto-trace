"""Excel import endpoints."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Account, ImportBatch
from app.services.import_service import import_excel

router = APIRouter()


@router.post("")
async def upload(
    connector: str = Form(...),
    account_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    if db.get(Account, account_id) is None:
        raise HTTPException(404, f"Cuenta {account_id} no existe")
    content = await file.read()
    try:
        batch = import_excel(
            db, connector_name=connector, account_id=account_id,
            filename=file.filename or "upload.xlsx", content=content,
        )
    except KeyError as exc:
        raise HTTPException(400, str(exc))
    return _batch_dict(batch)


@router.get("")
def list_batches(db: Session = Depends(get_db)) -> list[dict]:
    return [_batch_dict(b) for b in db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc()))]


def _batch_dict(b: ImportBatch) -> dict:
    return {
        "id": b.id,
        "connector": b.connector,
        "filename": b.filename,
        "imported_at": b.imported_at.isoformat() if b.imported_at else None,
        "row_count": b.row_count,
        "inserted_count": b.inserted_count,
        "duplicate_count": b.duplicate_count,
        "status": b.status.value if hasattr(b.status, "value") else b.status,
        "errors": json.loads(b.errors_json) if b.errors_json else [],
    }
