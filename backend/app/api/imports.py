"""Excel import endpoints."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Account, ImportBatch, Taxpayer, Transaction
from app.services.import_service import import_excel
from app.services.recompute import recompute_all

router = APIRouter()


@router.post("")
async def upload(
    connector: str = Form(...),
    taxpayer_id: int = Form(...),
    account_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    if db.get(Taxpayer, taxpayer_id) is None:
        raise HTTPException(404, f"Contribuyente {taxpayer_id} no existe")
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(404, f"Cuenta {account_id} no existe")
    if account.taxpayer_id != taxpayer_id:
        raise HTTPException(400, "La cuenta no pertenece al contribuyente seleccionado")
    content = await file.read()
    try:
        batch = import_excel(
            db, connector_name=connector, taxpayer_id=taxpayer_id, account_id=account_id,
            filename=file.filename or "upload.xlsx", content=content,
        )
    except KeyError as exc:
        raise HTTPException(400, str(exc))
    return _batch_dict(batch)


@router.get("")
def list_batches(
    taxpayer_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    q = select(ImportBatch).order_by(ImportBatch.id.desc())
    if taxpayer_id is not None:
        q = q.where(ImportBatch.taxpayer_id == taxpayer_id)
    return [_batch_dict(b) for b in db.scalars(q)]


@router.delete("/{batch_id}")
def delete_batch(
    batch_id: int,
    taxpayer_id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise HTTPException(404, f"Importación {batch_id} no encontrada")
    if batch.taxpayer_id != taxpayer_id:
        raise HTTPException(403, "La importación no pertenece al contribuyente seleccionado")

    db.execute(
        delete(Transaction).where(
            Transaction.import_batch_id == batch_id,
            Transaction.taxpayer_id == taxpayer_id,
        )
    )
    db.delete(batch)
    db.flush()
    result = recompute_all(db)
    return {"deleted": True, "batch_id": batch_id, "recomputed": result}


@router.delete("")
def clear_imports(
    taxpayer_id: int = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    if db.get(Taxpayer, taxpayer_id) is None:
        raise HTTPException(404, f"Contribuyente {taxpayer_id} no existe")

    tx_count = db.execute(
        delete(Transaction).where(Transaction.taxpayer_id == taxpayer_id)
    ).rowcount
    batch_count = db.execute(
        delete(ImportBatch).where(ImportBatch.taxpayer_id == taxpayer_id)
    ).rowcount
    db.flush()
    result = recompute_all(db)
    return {
        "deleted": True,
        "transactions_deleted": tx_count,
        "batches_deleted": batch_count,
        "recomputed": result,
    }


def _batch_dict(b: ImportBatch) -> dict:
    return {
        "id": b.id,
        "taxpayer_id": b.taxpayer_id,
        "connector": b.connector,
        "filename": b.filename,
        "imported_at": b.imported_at.isoformat() if b.imported_at else None,
        "row_count": b.row_count,
        "inserted_count": b.inserted_count,
        "duplicate_count": b.duplicate_count,
        "status": b.status.value if hasattr(b.status, "value") else b.status,
        "errors": json.loads(b.errors_json) if b.errors_json else [],
    }
