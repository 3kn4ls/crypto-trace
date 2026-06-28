"""Tests for reporting aggregations including the dashboard endpoint."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _sample_csv() -> bytes:
    return b"""Timestamp (UTC),Transaction Kind,Currency,Amount,To Currency,To Amount,Native Amount,Native Currency
2024-06-01 10:00:00,viban_purchase,BTC,1,,,30000,EUR
2024-08-01 10:00:00,crypto_viban_exchange,BTC,0.5,,,20000,EUR
2024-09-01 10:00:00,finance.dpos.non_compound_interest.crypto_wallet,CRO,100,,,50,EUR
"""


def test_dashboard_returns_expected_keys(client: TestClient):
    tp = client.post("/api/taxpayers", json={"name": "Dash Test", "tax_id": "55555555E"}).json()
    acc = client.post("/api/accounts", json={
        "taxpayer_id": tp["id"], "name": "Crypto.com", "platform": "CRYPTO_COM",
        "type": "EXCHANGE", "is_abroad": True,
    }).json()
    client.post(
        "/api/imports",
        data={"connector": "CRYPTO_COM", "taxpayer_id": tp["id"], "account_id": acc["id"]},
        files={"file": ("dash.csv", _sample_csv(), "text/csv")},
    )

    dash = client.get("/api/reports/dashboard", params={"taxpayer_id": tp["id"]}).json()
    assert "fiscal_totals" in dash
    assert "portfolio" in dash
    assert "activity" in dash
    assert "reviews" in dash
    assert "model721" in dash
    assert "years" in dash
    assert "portfolio_evolution" in dash

    # We should have a 2024 fiscal year with a disposal and an income event.
    years = dash["years"]
    assert any(y["year"] == 2024 for y in years)

    # Portfolio contains the remaining BTC plus CRO income.
    portfolio = dash["portfolio"]
    assert portfolio["assets_count"] >= 2
    assert any(a["asset"] == "BTC" for a in portfolio["top_assets"])

    # Activity has 3 transactions.
    assert dash["activity"]["total_transactions"] == 3
    assert dash["activity"]["transactions_by_type"].get("BUY") == 1
    assert dash["activity"]["transactions_by_type"].get("SELL") == 1

    # Contributions section is present and shows invested/rewards per asset.
    assert "contributions" in dash
    assert "invested_totals" in dash
    btc_contrib = next((c for c in dash["contributions"] if c["asset"] == "BTC"), None)
    assert btc_contrib is not None
    assert btc_contrib["invested_eur"] == "30000.00"
    assert btc_contrib["cost_basis_eur"] == "30000.00"  # only the BUY adds to cost basis here
    cro_contrib = next((c for c in dash["contributions"] if c["asset"] == "CRO"), None)
    assert cro_contrib is not None
    assert cro_contrib["rewards_eur"] == "50.00"
    assert dash["invested_totals"]["invested_eur"] == "30000.00"
    assert dash["invested_totals"]["rewards_eur"] == "50.00"


def test_dashboard_filters_by_year(client: TestClient):
    tp = client.post("/api/taxpayers", json={"name": "Dash Year", "tax_id": "66666666F"}).json()
    acc = client.post("/api/accounts", json={
        "taxpayer_id": tp["id"], "name": "Crypto.com", "platform": "CRYPTO_COM",
        "type": "EXCHANGE", "is_abroad": True,
    }).json()
    client.post(
        "/api/imports",
        data={"connector": "CRYPTO_COM", "taxpayer_id": tp["id"], "account_id": acc["id"]},
        files={"file": ("dash.csv", _sample_csv(), "text/csv")},
    )

    dash_all = client.get("/api/reports/dashboard", params={"taxpayer_id": tp["id"]}).json()
    dash_2024 = client.get("/api/reports/dashboard", params={"taxpayer_id": tp["id"], "year": 2024}).json()

    assert dash_2024["year"] == 2024
    assert all(y["year"] == 2024 for y in dash_2024["years"])
    assert len(dash_2024["years"]) <= len(dash_all["years"])
    assert dash_2024["activity"]["total_transactions"] == 3
