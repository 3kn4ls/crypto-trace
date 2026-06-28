"""Tests for CoinGecko historical price fetching and bulk endpoint."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import meta
from app.services import pricing_provider as pp


def test_coin_id_for_known_symbols():
    assert pp.coin_id_for("BTC") == "bitcoin"
    assert pp.coin_id_for("eth") == "ethereum"
    assert pp.coin_id_for("UNKNOWN") is None


def test_discover_coin_id_falls_back_to_search():
    # Unknown symbol should be discovered from /coins/list.
    sample_list = [
        {"id": "tiny-token", "symbol": "ttk", "name": "Tiny Token"},
    ]
    with patch.object(pp.requests, "get", return_value=_mock_response(sample_list)):
        assert pp.discover_coin_id("TTK") == "tiny-token"
    # Clears cache for other tests.
    pp._DISCOVERED_IDS.pop("TTK", None)


def test_fetch_history_eur_parses_response():
    sample = {
        "market_data": {
            "current_price": {"eur": 45000.50}
        }
    }
    with patch.object(pp.requests, "get", return_value=_mock_response(sample)):
        price = pp.fetch_history_eur("bitcoin", date(2024, 12, 31))
    assert price == Decimal("45000.50")


def test_fetch_historical_prices_endpoint(client: TestClient):
    tp = client.post("/api/taxpayers", json={"name": "Price Fetch", "tax_id": "77777777G"}).json()
    acc = client.post("/api/accounts", json={
        "taxpayer_id": tp["id"], "name": "Crypto.com", "platform": "CRYPTO_COM_BANK",
        "type": "EXCHANGE", "is_abroad": True,
    }).json()
    content = b"""Timestamp (UTC),Transaction Kind,Currency,Amount,To Currency,To Amount,Native Amount,Native Currency
2024-06-01 10:00:00,viban_purchase,BTC,1,,,30000,EUR
2024-08-01 10:00:00,crypto_viban_exchange,BTC,0.5,,,20000,EUR
"""
    client.post(
        "/api/imports",
        data={"connector": "CRYPTO_COM_BANK", "taxpayer_id": tp["id"], "account_id": acc["id"]},
        files={"file": ("btc.csv", content, "text/csv")},
    )

    with patch.object(meta, "fetch_history_eur", return_value=Decimal("100000.00")):
        resp = client.post("/api/prices/fetch-historical", json={
            "taxpayer_id": tp["id"], "year": 2024,
        }).json()

    assert len(resp["fetched"]) == 1
    assert resp["fetched"][0]["asset"] == "BTC"
    assert resp["fetched"][0]["year"] == 2024
    assert resp["fetched"][0]["price_eur"] == "100000.00"
    assert resp["missing"] == []


def _mock_response(json_data):
    class MockResponse:
        def raise_for_status(self): pass
        def json(self): return json_data
    return MockResponse()
