"""Deletion of imports: single batch and full taxpayer cleanup.

Because all derived state (lots, disposals, income, reviews) is rebuilt from
scratch after every change, deleting a batch only needs to remove its source
transactions and the batch itself, then invoke recompute_all.

These tests use the FastAPI TestClient with its own isolated in-memory database,
matching the style of test_api.py.
"""
from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.db import Base, get_db
from app.core.seed import seed_all
from app.main import app
from decimal import Decimal

HEADERS = [
    "Timestamp (UTC)", "Transaction Kind", "Currency", "Amount",
    "To Currency", "To Amount", "Native Amount", "Transaction Hash",
]
ROWS = [
    ["2024-01-10 10:00:00", "viban_purchase", "BTC", "0.5", "", "", "15000", "tx1"],
    ["2024-02-10 10:00:00", "crypto_purchase", "BTC", "0.5", "", "", "20000", "tx2"],
    ["2024-03-10 10:00:00", "crypto_exchange", "BTC", "0.5", "ETH", "5", "18000", "tx3"],
    ["2024-06-10 10:00:00", "crypto_viban_exchange", "BTC", "0.5", "", "", "25000", "tx4"],
    ["2024-07-01 10:00:00", "crypto_earn_interest_paid", "ETH", "0.1", "", "", "300", "tx5"],
]


def _xlsx(rows: list[list] | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for r in (rows or ROWS):
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool, future=True,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    seed_session = TestingSession()
    seed_all(seed_session)
    seed_session.close()

    def override():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _create_taxpayer(client: TestClient) -> int:
    resp = client.post("/api/taxpayers", json={"name": "Delete Test", "tax_id": "11111111H"})
    assert resp.status_code == 200
    return resp.json()["id"]


def _create_account(client: TestClient, taxpayer_id: int) -> int:
    resp = client.post("/api/accounts", json={
        "taxpayer_id": taxpayer_id, "name": "Crypto.com",
        "platform": "CRYPTO_COM_BANK", "type": "EXCHANGE", "is_abroad": True,
    })
    assert resp.status_code == 200
    return resp.json()["id"]


def _import_batch(client: TestClient, taxpayer_id: int, account_id: int, filename: str, content: bytes) -> int:
    resp = client.post(
        "/api/imports",
        data={"connector": "CRYPTO_COM_BANK", "taxpayer_id": str(taxpayer_id), "account_id": str(account_id)},
        files={"file": (filename, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["inserted_count"] > 0
    return data["id"]


def test_delete_single_batch_removes_transactions_and_recomputes(client: TestClient):
    tp_id = _create_taxpayer(client)
    acc_id = _create_account(client, tp_id)
    batch_id = _import_batch(client, tp_id, acc_id, "cdc.xlsx", _xlsx())

    assert len(client.get("/api/transactions", params={"taxpayer_id": tp_id}).json()) == 5
    dash_before = client.get("/api/reports/dashboard", params={"taxpayer_id": tp_id}).json()
    assert Decimal(dash_before["fiscal_totals"]["net_capital_gain"]) > Decimal("0")

    resp = client.delete(f"/api/imports/{batch_id}?taxpayer_id={tp_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted"] is True
    assert data["batch_id"] == batch_id
    assert data["recomputed"]["lots"] == 0
    assert data["recomputed"]["disposals"] == 0
    assert data["recomputed"]["income_events"] == 0

    assert len(client.get("/api/transactions", params={"taxpayer_id": tp_id}).json()) == 0
    dash = client.get("/api/reports/dashboard", params={"taxpayer_id": tp_id}).json()
    assert dash["activity"]["total_transactions"] == 0
    assert dash["activity"]["total_income_events"] == 0
    assert Decimal(dash["fiscal_totals"]["net_capital_gain"]) == Decimal("0")


def test_clear_all_imports_for_taxpayer(client: TestClient):
    tp_id = _create_taxpayer(client)
    acc_id = _create_account(client, tp_id)
    _import_batch(client, tp_id, acc_id, "batch1.xlsx", _xlsx())
    _import_batch(
        client, tp_id, acc_id, "batch2.xlsx",
        _xlsx([
            ["2024-01-15 10:00:00", "viban_purchase", "ETH", "1", "", "", "2000", "tx10"],
        ]),
    )

    assert len(client.get("/api/transactions", params={"taxpayer_id": tp_id}).json()) == 6

    resp = client.delete(f"/api/imports?taxpayer_id={tp_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted"] is True
    assert data["transactions_deleted"] == 6
    assert data["batches_deleted"] == 2

    assert len(client.get("/api/transactions", params={"taxpayer_id": tp_id}).json()) == 0


def test_delete_batch_of_other_taxpayer_is_forbidden(client: TestClient):
    tp_a = _create_taxpayer(client)
    tp_b = _create_taxpayer(client)
    acc_a = _create_account(client, tp_a)
    batch_id = _import_batch(client, tp_a, acc_a, "private.xlsx", _xlsx())

    resp = client.delete(f"/api/imports/{batch_id}?taxpayer_id={tp_b}")
    assert resp.status_code == 403

    assert len(client.get("/api/transactions", params={"taxpayer_id": tp_a}).json()) == 5


def test_delete_missing_batch_returns_404(client: TestClient):
    tp_id = _create_taxpayer(client)
    resp = client.delete(f"/api/imports/99999?taxpayer_id={tp_id}")
    assert resp.status_code == 404


def test_clear_imports_for_missing_taxpayer_returns_404(client: TestClient):
    resp = client.delete("/api/imports?taxpayer_id=99999")
    assert resp.status_code == 404


def test_reimport_after_delete_works(client: TestClient):
    """Deleting a batch must remove external_id records so the same file can be
    imported again afterwards."""
    tp_id = _create_taxpayer(client)
    acc_id = _create_account(client, tp_id)
    content = _xlsx()
    batch_id = _import_batch(client, tp_id, acc_id, "cdc.xlsx", content)

    resp = client.delete(f"/api/imports/{batch_id}?taxpayer_id={tp_id}")
    assert resp.status_code == 200

    # Re-importing the same content should insert the rows again.
    _import_batch(client, tp_id, acc_id, "cdc.xlsx", content)
    assert len(client.get("/api/transactions", params={"taxpayer_id": tp_id}).json()) == 5
