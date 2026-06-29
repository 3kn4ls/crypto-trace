"""Closing a fiscal year write-locks it (docs/ANALISIS.md §1.2).

A CLOSED year is read-only: edits/deletes of its transactions, opening positions
in it and P2P resolutions touching it are rejected until the year is reopened.
This keeps the frozen FiscalYearSummary and the live computation consistent.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _taxpayer_and_account(client: TestClient, name: str, tax_id: str):
    tp = client.post("/api/taxpayers", json={"name": name, "tax_id": tax_id}).json()
    acc = client.post("/api/accounts", json={
        "taxpayer_id": tp["id"], "name": "Acc", "platform": "MANUAL", "type": "EXCHANGE",
    }).json()
    return tp, acc


def _cashback_csv() -> bytes:
    return (
        b"Timestamp (UTC),Transaction Kind,Currency,Amount,To Currency,To Amount,Native Amount,Native Currency\n"
        b"2024-06-01 10:00:00,referral_card_cashback,CRO,10,,,1,EUR\n"
    )


def test_closed_year_blocks_transaction_edits(client: TestClient):
    tp, _ = _taxpayer_and_account(client, "Lock Edits", "44444444D")
    tx = client.post("/api/fiscal-years/opening-position", params={"taxpayer_id": tp["id"]}, json={
        "asset_symbol": "BTC", "quantity": "1", "cost_basis_eur": "30000",
        "acquired_at": "2023-06-01T00:00:00",
    }).json()

    close = client.post("/api/fiscal-years/2023/close", params={"taxpayer_id": tp["id"]})
    assert close.status_code == 200

    # PATCH a transaction in the closed year -> rejected.
    patched = client.patch(f"/api/transactions/{tx['transaction_id']}", json={"notes": "x"})
    assert patched.status_code == 409

    # A new opening position in the closed year -> rejected.
    op = client.post("/api/fiscal-years/opening-position", params={"taxpayer_id": tp["id"]}, json={
        "asset_symbol": "BTC", "quantity": "1", "cost_basis_eur": "100",
        "acquired_at": "2023-02-01T00:00:00",
    })
    assert op.status_code == 400

    # Reopen -> edits allowed again.
    assert client.post("/api/fiscal-years/2023/reopen", params={"taxpayer_id": tp["id"]}).status_code == 200
    again = client.patch(f"/api/transactions/{tx['transaction_id']}", json={"notes": "ok"})
    assert again.status_code == 200
    assert again.json()["notes"] == "ok"


def test_closed_year_blocks_import_deletion_and_clear(client: TestClient):
    tp, acc = _taxpayer_and_account(client, "Lock Imports", "55555555E")
    batch = client.post(
        "/api/imports",
        data={"connector": "CRYPTO_COM_BANK", "taxpayer_id": tp["id"], "account_id": acc["id"]},
        files={"file": ("cdc.csv", _cashback_csv(), "text/csv")},
    ).json()

    assert client.post("/api/fiscal-years/2024/close", params={"taxpayer_id": tp["id"]}).status_code == 200

    # Deleting a batch that contains closed-year transactions -> rejected.
    deleted = client.delete(f"/api/imports/{batch['id']}", params={"taxpayer_id": tp["id"]})
    assert deleted.status_code == 409

    # "Clear all" while a year is closed -> rejected.
    cleared = client.delete("/api/imports", params={"taxpayer_id": tp["id"]})
    assert cleared.status_code == 409

    # Reopen -> deletion allowed.
    assert client.post("/api/fiscal-years/2024/reopen", params={"taxpayer_id": tp["id"]}).status_code == 200
    assert client.delete(f"/api/imports/{batch['id']}", params={"taxpayer_id": tp["id"]}).status_code == 200
