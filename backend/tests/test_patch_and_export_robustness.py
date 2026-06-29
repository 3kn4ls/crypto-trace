"""Robustness fixes (docs/ANALISIS.md §1.3 and §1.4).

§1.3 — PATCH /transactions rejects reclassifications incoherent with the legs
       the transaction already carries.
§1.4 — PDF export degrades gracefully when the optional fpdf2 dependency is
       missing (a clear error instead of a 500 traceback).
"""
from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

from app.services import export_service


def _taxpayer_with_deposit(client: TestClient):
    """A taxpayer with one DEPOSIT (crypto in, no out leg) via opening position."""
    tp = client.post("/api/taxpayers", json={"name": "Patch Validate", "tax_id": "77777777G"}).json()
    client.post("/api/accounts", json={
        "taxpayer_id": tp["id"], "name": "Acc", "platform": "MANUAL", "type": "EXCHANGE",
    }).json()
    tx = client.post("/api/fiscal-years/opening-position", params={"taxpayer_id": tp["id"]}, json={
        "asset_symbol": "BTC", "quantity": "1", "cost_basis_eur": "30000",
        "acquired_at": "2024-06-01T00:00:00",
    }).json()
    return tp, tx["transaction_id"]


def test_patch_rejects_type_without_required_leg(client: TestClient):
    _, tx_id = _taxpayer_with_deposit(client)

    # DEPOSIT has no outgoing leg -> cannot become a SELL or a SWAP.
    assert client.patch(f"/api/transactions/{tx_id}", json={"type": "SELL"}).status_code == 400
    assert client.patch(f"/api/transactions/{tx_id}", json={"type": "SWAP"}).status_code == 400


def test_patch_allows_coherent_type_change(client: TestClient):
    _, tx_id = _taxpayer_with_deposit(client)

    # DEPOSIT has an incoming crypto leg -> reclassifying to AIRDROP is coherent.
    resp = client.patch(f"/api/transactions/{tx_id}", json={"type": "AIRDROP"})
    assert resp.status_code == 200
    assert resp.json()["type"] == "AIRDROP"


def test_pdf_export_unavailable_raises_clear_error(monkeypatch):
    # Simulate fpdf2 not being installed: `from fpdf import FPDF` then fails.
    monkeypatch.setitem(sys.modules, "fpdf", None)
    with pytest.raises(export_service.PdfExportUnavailable):
        export_service._build_pdf(
            title="t", header=["a"], rows=[["1"]], filename="x.pdf", col_widths=[10]
        )


def test_pdf_export_unavailable_returns_503(client: TestClient, monkeypatch):
    monkeypatch.setitem(sys.modules, "fpdf", None)
    tp = client.post("/api/taxpayers", json={"name": "Pdf 503"}).json()
    resp = client.get(f"/api/exports/summary?taxpayer_id={tp['id']}&format=pdf")
    assert resp.status_code == 503
    # CSV stays available regardless of fpdf2.
    assert client.get(f"/api/exports/summary?taxpayer_id={tp['id']}&format=csv").status_code == 200
