"""Tests for Phase 2 improvements:

- Manual transaction reclassification.
- Mass year-end price fetching.
- CSV/PDF exports.
- Import preview endpoint.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.connectors.base import BaseConnector
from app.models import (
    Account,
    AccountPlatform,
    Asset,
    Disposal,
    Transaction,
    TransactionType,
)
from app.services.recompute import recompute_all


def _btc(db):
    return db.scalar(select(Asset).where(Asset.symbol == "BTC"))


def _make_account(db, taxpayer_id: int, name: str = "Test") -> Account:
    acc = Account(
        taxpayer_id=taxpayer_id,
        name=name,
        platform=AccountPlatform.MANUAL,
        type="EXCHANGE",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def test_reclassify_transfer_to_sell_creates_disposal(db, taxpayer):
    acc = _make_account(db, taxpayer.id)
    btc = _btc(db)

    buy = Transaction(
        taxpayer_id=taxpayer.id,
        account_id=acc.id,
        timestamp=datetime(2024, 1, 1),
        type=TransactionType.BUY,
        asset_in_id=btc.id,
        amount_in=Decimal("1"),
        eur_value=Decimal("30000"),
        fiscal_year=2024,
        external_id="buy-reclass",
    )
    db.add(buy)

    transfer = Transaction(
        taxpayer_id=taxpayer.id,
        account_id=acc.id,
        timestamp=datetime(2024, 6, 1),
        type=TransactionType.TRANSFER,
        asset_out_id=btc.id,
        amount_out=Decimal("1"),
        eur_value=Decimal("0"),
        is_internal_transfer=True,
        fiscal_year=2024,
        external_id="transfer-reclass",
    )
    db.add(transfer)
    db.commit()
    recompute_all(db)

    assert db.scalar(select(Disposal)) is None

    transfer.type = TransactionType.SELL
    db.commit()
    recompute_all(db)

    disposal = db.scalar(select(Disposal))
    assert disposal is not None
    assert disposal.quantity == Decimal("1")
    assert disposal.gain_loss_eur == Decimal("-30000")


def test_api_reclassify_transaction(client: TestClient):
    taxpayer = client.post("/api/taxpayers", json={"name": "Reclass"}).json()
    tp_id = taxpayer["id"]
    client.post("/api/accounts", json={
        "taxpayer_id": tp_id, "name": "Reclass", "platform": "MANUAL", "type": "EXCHANGE",
    }).json()
    client.post("/api/fiscal-years/opening-position", params={"taxpayer_id": tp_id}, json={
        "asset_symbol": "BTC", "quantity": "1", "cost_basis_eur": "30000",
        "acquired_at": "2023-06-01T00:00:00",
    }).json()

    tx = client.get(f"/api/transactions?taxpayer_id={tp_id}").json()[0]
    patched = client.patch(f"/api/transactions/{tx['id']}", json={"type": "TRANSFER"}).json()
    assert patched["type"] == "TRANSFER"

    # The DEPOSIT is now a TRANSFER; the lot should have disappeared after recompute.
    portfolio = client.get(f"/api/reports/portfolio?taxpayer_id={tp_id}").json()
    assert not any(p["asset"] == "BTC" for p in portfolio)


def test_fetch_historical_includes_year_with_only_purchases(client: TestClient):
    taxpayer = client.post("/api/taxpayers", json={"name": "Prices"}).json()
    tp_id = taxpayer["id"]
    client.post("/api/accounts", json={
        "taxpayer_id": tp_id, "name": "Prices", "platform": "MANUAL", "type": "EXCHANGE",
    }).json()
    client.post("/api/fiscal-years/opening-position", params={"taxpayer_id": tp_id}, json={
        "asset_symbol": "BTC", "quantity": "1", "cost_basis_eur": "30000",
        "acquired_at": "2023-06-01T00:00:00",
    }).json()

    # No disposals or income for 2023, only the opening position (a DEPOSIT).
    # We still want a 31/12 price for 2023.
    with patch("app.api.meta.fetch_history_eur", return_value=Decimal("50000")):
        resp = client.post("/api/prices/fetch-historical", json={"taxpayer_id": tp_id})
    assert resp.status_code == 200
    data = resp.json()
    assert any(p["year"] == 2023 for p in data["fetched"] + data["skipped"])


def test_export_summary_csv(client: TestClient):
    taxpayer = client.post("/api/taxpayers", json={"name": "Export"}).json()
    tp_id = taxpayer["id"]
    resp = client.get(f"/api/exports/summary?taxpayer_id={tp_id}&format=csv")
    assert resp.status_code == 200
    assert "resumen_fiscal_" in resp.headers["content-disposition"]
    body = resp.content.decode("utf-8-sig")
    assert "Ejercicio" in body


def test_export_transactions_pdf(client: TestClient):
    taxpayer = client.post("/api/taxpayers", json={"name": "Export PDF"}).json()
    tp_id = taxpayer["id"]
    client.post("/api/accounts", json={
        "taxpayer_id": tp_id, "name": "Export", "platform": "MANUAL", "type": "EXCHANGE",
    }).json()
    client.post("/api/fiscal-years/opening-position", params={"taxpayer_id": tp_id}, json={
        "asset_symbol": "BTC", "quantity": "1", "cost_basis_eur": "30000",
        "acquired_at": "2023-06-01T00:00:00",
    }).json()

    resp = client.get(f"/api/exports/transactions?taxpayer_id={tp_id}&format=pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


def test_export_model721_requires_year(client: TestClient):
    taxpayer = client.post("/api/taxpayers", json={"name": "Export 721"}).json()
    tp_id = taxpayer["id"]
    resp = client.get(f"/api/exports/model721?taxpayer_id={tp_id}&format=csv")
    assert resp.status_code == 400


def test_import_preview_does_not_persist(client: TestClient):
    class DummyConnector(BaseConnector):
        source = AccountPlatform.MANUAL
        name = "DUMMY_PREVIEW"
        mapping_file = "dummy_preview.yaml"

        def __init__(self):
            self.mapping = {"header_row": 1}

        def normalize_row(self, raw, row_no):
            from app.connectors.base import CanonicalTransaction
            return CanonicalTransaction(
                external_id=f"prev-{row_no}",
                timestamp=datetime(2024, 1, 1),
                type=TransactionType.BUY,
                asset_in="BTC",
                amount_in=Decimal("0.1"),
                eur_value=Decimal("1000"),
                raw=raw,
            )

    from app.connectors import registry

    registry.register(DummyConnector)
    try:
        taxpayer = client.post("/api/taxpayers", json={"name": "Preview"}).json()
        tp_id = taxpayer["id"]
        acc = client.post("/api/accounts", json={
            "taxpayer_id": tp_id, "name": "Preview", "platform": "MANUAL", "type": "EXCHANGE",
        }).json()

        content = b"dummy\nrow1\n"
        resp = client.post(
            "/api/imports/preview",
            data={"connector": "DUMMY_PREVIEW", "taxpayer_id": tp_id, "account_id": acc["id"]},
            files={"file": ("dummy.csv", BytesIO(content), "text/csv")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["parsed_count"] == 1
        assert data["preview"][0]["type"] == "BUY"

        # No transactions persisted.
        txs = client.get(f"/api/transactions?taxpayer_id={tp_id}").json()
        assert len(txs) == 0
    finally:
        registry._REGISTRY.pop("DUMMY_PREVIEW", None)
