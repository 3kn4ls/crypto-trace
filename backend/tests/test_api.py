"""HTTP-level smoke test of the main flow via FastAPI TestClient."""
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

HEADERS = ["Timestamp (UTC)", "Transaction Kind", "Currency", "Amount",
           "To Currency", "To Amount", "Native Amount", "Transaction Hash"]
ROWS = [
    ["2024-01-10 10:00:00", "viban_purchase", "BTC", "0.5", "", "", "15000", "tx1"],
    ["2024-02-10 10:00:00", "crypto_purchase", "BTC", "0.5", "", "", "20000", "tx2"],
    ["2024-03-10 10:00:00", "crypto_exchange", "BTC", "0.5", "ETH", "5", "18000", "tx3"],
    ["2024-06-10 10:00:00", "crypto_viban_exchange", "BTC", "0.5", "", "", "25000", "tx4"],
    ["2024-07-01 10:00:00", "crypto_earn_interest_paid", "ETH", "0.1", "", "", "300", "tx5"],
]


def _xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(HEADERS)
    for r in ROWS:
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
    # No `with`: skip lifespan so we don't touch the on-disk database.
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_full_http_flow(client):
    taxpayer = client.post("/api/taxpayers", json={"name": "HTTP Test", "tax_id": "44444444A"}).json()
    tp_id = taxpayer["id"]

    acc = client.post("/api/accounts", json={
        "taxpayer_id": tp_id, "name": "Crypto.com", "platform": "CRYPTO_COM_BANK",
        "type": "EXCHANGE", "is_abroad": True,
    }).json()

    batch = client.post(
        "/api/imports",
        data={"connector": "CRYPTO_COM_BANK", "taxpayer_id": tp_id, "account_id": acc["id"]},
        files={"file": ("cdc.xlsx", _xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()
    assert batch["inserted_count"] == 5

    txs = client.get("/api/transactions", params={"taxpayer_id": tp_id}).json()
    assert len(txs) == 5
    assert all(t["source"] == "CRYPTO_COM_BANK" for t in txs)

    tax = client.get("/api/fiscal-years/2024/tax", params={"taxpayer_id": tp_id}).json()
    # gains 8000 + RCM income 300 => savings base 8300.
    assert tax["savings_base"] == "8300.00"
    # 6000*0.19 + 2300*0.21 = 1140 + 483
    assert tax["tax_due"] == "1623.00"

    # Price ETH at year end so Modelo 721 can value the holding.
    client.post("/api/prices", json={"asset_symbol": "ETH", "date": "2024-12-31T00:00:00", "price_eur": "12000"})

    pf = client.get("/api/reports/portfolio", params={"taxpayer_id": tp_id}).json()
    eth = next(r for r in pf if r["asset"] == "ETH")
    assert eth["quantity"] == "5.1"

    m721 = client.get("/api/reports/model721/2024", params={"taxpayer_id": tp_id}).json()
    assert m721["obligated"] is True  # 5.1 ETH * 12000 = 61200 > 50000

    closed = client.post(f"/api/fiscal-years/2024/close?taxpayer_id={tp_id}").json()
    assert closed["status"] == "CLOSED"
    years = client.get("/api/fiscal-years", params={"taxpayer_id": tp_id}).json()
    assert any(y["year"] == 2024 and y["status"] == "CLOSED" and y["taxpayer_id"] == tp_id for y in years)
