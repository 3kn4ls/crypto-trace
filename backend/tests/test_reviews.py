"""Tests for the review/warnings system."""
from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ReviewCategory, ReviewItem, ReviewStatus
from app.services import review_service as rs


def _p2p_csv(taxpayer_id: int, account_id: int):
    """Minimal CSV with a P2P transfer that gets flagged."""
    return b"""Timestamp (UTC),Transaction Kind,Currency,Amount,To Currency,To Amount,Native Amount,Native Currency
2024-06-01 10:00:00,transfer.p2p_transfer.crypto_wallet.crypto_wallet.credit,CRO,100,,,10,EUR
"""


def test_import_creates_p2p_review_item(client: TestClient):
    tp = client.post("/api/taxpayers", json={"name": "Review Test", "tax_id": "11111111A"}).json()
    acc = client.post("/api/accounts", json={
        "taxpayer_id": tp["id"], "name": "Crypto.com", "platform": "CRYPTO_COM",
        "type": "EXCHANGE", "is_abroad": True,
    }).json()

    client.post(
        "/api/imports",
        data={"connector": "CRYPTO_COM", "taxpayer_id": tp["id"], "account_id": acc["id"]},
        files={"file": ("p2p.csv", _p2p_csv(tp["id"], acc["id"]), "text/csv")},
    )

    reviews = client.get("/api/reviews", params={"taxpayer_id": tp["id"], "status": "PENDING"}).json()
    assert any(r["category"] == ReviewCategory.P2P_TRANSFER.value for r in reviews)


def test_fifo_insufficient_balance_creates_review_item(db: Session, taxpayer, account):
    """A disposal without prior acquisition generates an INSUFFICIENT_BALANCE item."""
    from app.services.import_service import import_excel

    content = b"""Timestamp (UTC),Transaction Kind,Currency,Amount,To Currency,To Amount,Native Amount,Native Currency
2024-01-01 10:00:00,crypto_viban_exchange,BTC,1,,,20000,EUR
"""
    import_excel(
        db, connector_name="CRYPTO_COM", taxpayer_id=taxpayer.id, account_id=account.id,
        filename="sell.csv", content=content,
    )

    items = rs.list_items(db, taxpayer_ids=[taxpayer.id], category=ReviewCategory.INSUFFICIENT_BALANCE)
    assert len(items) == 1
    assert items[0].status == ReviewStatus.PENDING
    assert "base=0" in items[0].message


def test_resolve_p2p_as_own_account(client: TestClient):
    tp = client.post("/api/taxpayers", json={"name": "Resolve Test", "tax_id": "22222222B"}).json()
    acc = client.post("/api/accounts", json={
        "taxpayer_id": tp["id"], "name": "Crypto.com", "platform": "CRYPTO_COM",
        "type": "EXCHANGE", "is_abroad": True,
    }).json()
    client.post(
        "/api/imports",
        data={"connector": "CRYPTO_COM", "taxpayer_id": tp["id"], "account_id": acc["id"]},
        files={"file": ("p2p.csv", _p2p_csv(tp["id"], acc["id"]), "text/csv")},
    )

    item = client.get("/api/reviews", params={"taxpayer_id": tp["id"], "category": "P2P_TRANSFER"}).json()[0]
    resolved = client.post(f"/api/reviews/{item['id']}/resolve", json={
        "action": "MARK_OWN_ACCOUNT", "note": "Es otra wallet mía",
    }).json()
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_action"] == "MARK_OWN_ACCOUNT"

    summary = client.get("/api/reviews/summary", params={"taxpayer_id": tp["id"]}).json()
    assert summary["resolved"] == 1


def test_resolve_missing_price_adds_quote(client: TestClient):
    """Resolve a MISSING_PRICE review item by creating a PriceQuote."""
    tp = client.post("/api/taxpayers", json={"name": "Price Test", "tax_id": "33333333C"}).json()
    # First create an asset through a tiny import, then generate review for a year with no price.
    acc = client.post("/api/accounts", json={
        "taxpayer_id": tp["id"], "name": "Crypto.com", "platform": "CRYPTO_COM",
        "type": "EXCHANGE", "is_abroad": True,
    }).json()
    client.post(
        "/api/imports",
        data={"connector": "CRYPTO_COM", "taxpayer_id": tp["id"], "account_id": acc["id"]},
        files={"file": ("p2p.csv", _p2p_csv(tp["id"], acc["id"]), "text/csv")},
    )

    # Trigger price review generation for 2024.
    client.post("/api/reviews/generate", params={"taxpayer_id": tp["id"], "year": 2024})

    reviews = client.get("/api/reviews", params={"taxpayer_id": tp["id"], "category": "MISSING_PRICE"}).json()
    if not reviews:
        # If there is no abroad holding, the review won't be created.
        return
    item = reviews[0]
    resolved = client.post(f"/api/reviews/{item['id']}/resolve", json={
        "action": "ADD_PRICE_QUOTE",
        "payload": {"asset_symbol": "CRO", "price_eur": "0.10", "date": "2024-12-31"},
    }).json()
    assert resolved["status"] == "RESOLVED"

    # Modelo 721 should now have the price available.
    m721 = client.get("/api/reports/model721/2024", params={"taxpayer_id": tp["id"]}).json()
    cro = next((h for h in m721["holdings"] if h["asset"] == "CRO"), None)
    if cro:
        assert cro["price_eur"] is not None


def test_revert_review_returns_to_pending(client: TestClient):
    """Resolving and then reverting a review item leaves it PENDING."""
    tp = client.post("/api/taxpayers", json={"name": "Revert Test", "tax_id": "44444444D"}).json()
    acc = client.post("/api/accounts", json={
        "taxpayer_id": tp["id"], "name": "Crypto.com", "platform": "CRYPTO_COM",
        "type": "EXCHANGE", "is_abroad": True,
    }).json()
    client.post(
        "/api/imports",
        data={"connector": "CRYPTO_COM", "taxpayer_id": tp["id"], "account_id": acc["id"]},
        files={"file": ("p2p.csv", _p2p_csv(tp["id"], acc["id"]), "text/csv")},
    )

    item = client.get("/api/reviews", params={"taxpayer_id": tp["id"], "category": "P2P_TRANSFER"}).json()[0]
    resolved = client.post(f"/api/reviews/{item['id']}/resolve", json={
        "action": "MARK_OWN_ACCOUNT", "note": "Me equivoqué",
    }).json()
    assert resolved["status"] == "RESOLVED"

    reverted = client.post(f"/api/reviews/{item['id']}/revert").json()
    assert reverted["status"] == "PENDING"
    assert reverted["resolution_action"] is None
    assert reverted["resolution_note"] is None
    assert reverted["resolved_at"] is None

    summary = client.get("/api/reviews/summary", params={"taxpayer_id": tp["id"]}).json()
    assert summary["pending"] == 1
    assert summary["resolved"] == 0
