"""Orchestrate an Excel import: connector -> validate -> dedup -> persist -> recompute."""
from __future__ import annotations

import hashlib
import json
from io import BytesIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors import get_connector
from app.connectors.base import CanonicalTransaction
from app.models import (
    Asset,
    AssetKind,
    FiscalYear,
    FiscalYearStatus,
    ImportBatch,
    ImportStatus,
    Transaction,
)
from app.services.recompute import recompute_all


def _get_or_create_asset(db: Session, cache: dict[str, Asset], symbol: str | None) -> Asset | None:
    if not symbol:
        return None
    symbol = symbol.upper()
    if symbol in cache:
        return cache[symbol]
    asset = db.scalar(select(Asset).where(Asset.symbol == symbol))
    if asset is None:
        asset = Asset(symbol=symbol, name=symbol, kind=AssetKind.CRYPTO)
        db.add(asset)
        db.flush()
    cache[symbol] = asset
    return asset


def _ensure_fiscal_year(db: Session, cache: dict[tuple[int, int], FiscalYear], taxpayer_id: int, year: int) -> FiscalYear:
    key = (taxpayer_id, year)
    if key in cache:
        return cache[key]
    fy = db.scalar(select(FiscalYear).where(FiscalYear.taxpayer_id == taxpayer_id, FiscalYear.year == year))
    if fy is None:
        fy = FiscalYear(taxpayer_id=taxpayer_id, year=year, status=FiscalYearStatus.OPEN)
        db.add(fy)
        db.flush()
    cache[key] = fy
    return fy


def import_excel(
    db: Session, *, connector_name: str, taxpayer_id: int, account_id: int, filename: str, content: bytes
) -> ImportBatch:
    connector = get_connector(connector_name)
    file_hash = hashlib.sha256(content).hexdigest()
    parsed = connector.parse(BytesIO(content))

    batch = ImportBatch(
        taxpayer_id=taxpayer_id,
        connector=connector_name,
        filename=filename,
        file_hash=file_hash,
        account_id=account_id,
        row_count=len(parsed.transactions) + len(parsed.errors),
    )
    db.add(batch)
    db.flush()

    asset_cache: dict[str, Asset] = {}
    fy_cache: dict[int, FiscalYear] = {}
    # Existing external_ids for this account, to dedup across imports.
    seen: set[str] = {
        row[0]
        for row in db.execute(
            select(Transaction.external_id).where(Transaction.account_id == account_id)
        )
        if row[0]
    }

    errors = [{"row": e.row, "message": e.message} for e in parsed.errors]
    inserted = duplicate = 0

    for ct in parsed.transactions:
        try:
            year = ct.timestamp.year
            fy = _ensure_fiscal_year(db, fy_cache, taxpayer_id, year)
            if fy.status == FiscalYearStatus.CLOSED:
                errors.append({"row": 0, "message": f"Año {year} cerrado: {ct.external_id} omitida"})
                continue
            if ct.external_id and ct.external_id in seen:
                duplicate += 1
                continue
            db.add(_to_orm(db, asset_cache, ct, taxpayer_id, account_id, batch.id, connector_name, year))
            if ct.external_id:
                seen.add(ct.external_id)
            inserted += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({"row": 0, "message": str(exc)})

    batch.inserted_count = inserted
    batch.duplicate_count = duplicate
    batch.errors_json = json.dumps(errors, ensure_ascii=False) if errors else None
    if inserted == 0 and errors:
        batch.status = ImportStatus.FAILED
    elif errors:
        batch.status = ImportStatus.PARTIAL
    else:
        batch.status = ImportStatus.OK
    db.commit()

    if inserted:
        recompute_all(db)
    return batch


def _to_orm(
    db: Session,
    asset_cache: dict[str, Asset],
    ct: CanonicalTransaction,
    taxpayer_id: int,
    account_id: int,
    batch_id: int,
    source: str,
    year: int,
) -> Transaction:
    asset_in = _get_or_create_asset(db, asset_cache, ct.asset_in)
    asset_out = _get_or_create_asset(db, asset_cache, ct.asset_out)
    fee_asset = _get_or_create_asset(db, asset_cache, ct.fee_asset)
    return Transaction(
        taxpayer_id=taxpayer_id,
        account_id=account_id,
        timestamp=ct.timestamp,
        type=ct.type,
        asset_in_id=asset_in.id if asset_in else None,
        amount_in=ct.amount_in,
        asset_out_id=asset_out.id if asset_out else None,
        amount_out=ct.amount_out,
        fee_asset_id=fee_asset.id if fee_asset else None,
        fee_amount=ct.fee_amount,
        eur_value=ct.eur_value,
        price_source=ct.price_source,
        external_id=ct.external_id,
        import_batch_id=batch_id,
        source=source,
        raw_json=json.dumps(ct.raw, ensure_ascii=False, default=str) if ct.raw else None,
        fiscal_year=year,
        notes=ct.notes,
    )
