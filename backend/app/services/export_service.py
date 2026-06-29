"""CSV/PDF export generators for fiscal summary, transactions and Modelo 721."""
from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Asset, Transaction
from app.services import model721_service, reporting_service


class PdfExportUnavailable(RuntimeError):
    """Raised when PDF export is requested but the optional ``fpdf2`` dependency
    is not installed. The API turns this into a 503 with a helpful message; CSV
    export never depends on ``fpdf2``."""


def _fmt_dec(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return str(v)
    return str(v)


def _csv_bytes(rows: list[list[str]], header: list[str]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def export_summary_csv(
    db: Session, *, taxpayer_ids: list[int] | None = None, year: int | None = None
) -> tuple[bytes, str]:
    data = reporting_service.yearly_summary(db, taxpayer_ids=taxpayer_ids)
    if year is not None:
        data = [d for d in data if d["year"] == year]
    header = [
        "Ejercicio",
        "Ganancias",
        "Pérdidas",
        "Ganancia neta",
        "RCM",
        "Ganancia patrimonial",
        "Actividad económica",
        "Base ahorro",
        "Impuesto estimado",
        "Tipo efectivo",
    ]
    rows = [
        [
            str(d["year"]),
            _fmt_dec(d.get("total_gains")),
            _fmt_dec(d.get("total_losses")),
            _fmt_dec(d.get("net_capital_gain")),
            _fmt_dec(d.get("income_rcm")),
            _fmt_dec(d.get("income_ganancia")),
            _fmt_dec(d.get("income_actividad")),
            _fmt_dec(d.get("savings_base")),
            _fmt_dec(d.get("tax_due_eur")),
            _fmt_dec(d.get("effective_rate")),
        ]
        for d in data
    ]
    filename = f"resumen_fiscal_{year or 'todos'}_{date.today().isoformat()}.csv"
    return _csv_bytes(rows, header), filename


def export_summary_pdf(
    db: Session, *, taxpayer_ids: list[int] | None = None, year: int | None = None
) -> tuple[bytes, str]:
    data = reporting_service.yearly_summary(db, taxpayer_ids=taxpayer_ids)
    if year is not None:
        data = [d for d in data if d["year"] == year]
    header = ["Ejercicio", "Ganancia neta", "RCM", "Base ahorro", "Impuesto", "Tipo efectivo"]
    rows = [
        [
            str(d["year"]),
            _fmt_dec(d.get("net_capital_gain")),
            _fmt_dec(d.get("income_rcm")),
            _fmt_dec(d.get("savings_base")),
            _fmt_dec(d.get("tax_due_eur")),
            _fmt_dec(d.get("effective_rate")),
        ]
        for d in data
    ]
    return _build_pdf(
        title=f"Resumen fiscal {'(' + str(year) + ')' if year else '(todos los años)'}",
        header=header,
        rows=rows,
        filename=f"resumen_fiscal_{year or 'todos'}_{date.today().isoformat()}.pdf",
        col_widths=[25, 35, 35, 35, 35, 35],
    )


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def export_transactions_csv(
    db: Session, *, taxpayer_ids: list[int] | None = None, year: int | None = None
) -> tuple[bytes, str]:
    txs = _fetch_transactions(db, taxpayer_ids=taxpayer_ids, year=year)
    header = [
        "ID",
        "Fecha",
        "Ejercicio",
        "Tipo",
        "Entrada",
        "Cantidad entrada",
        "Salida",
        "Cantidad salida",
        "EUR operación",
        "Coste base EUR",
        "Comisión",
        "Cuenta",
        "Origen",
        "Notas",
    ]
    rows = []
    for t in txs:
        rows.append(
            [
                str(t.id),
                t.timestamp.isoformat(),
                str(t.fiscal_year),
                t.type.value if hasattr(t.type, "value") else str(t.type),
                t.asset_in.symbol if t.asset_in else "",
                _fmt_dec(t.amount_in),
                t.asset_out.symbol if t.asset_out else "",
                _fmt_dec(t.amount_out),
                _fmt_dec(t.eur_value),
                _fmt_dec(t.cost_basis_eur),
                f"{_fmt_dec(t.fee_amount)} {t.fee_asset.symbol if t.fee_asset else ''}".strip(),
                t.account.name if t.account else "",
                t.source or "",
                t.notes or "",
            ]
        )
    filename = f"transacciones_{year or 'todos'}_{date.today().isoformat()}.csv"
    return _csv_bytes(rows, header), filename


def export_transactions_pdf(
    db: Session, *, taxpayer_ids: list[int] | None = None, year: int | None = None
) -> tuple[bytes, str]:
    txs = _fetch_transactions(db, taxpayer_ids=taxpayer_ids, year=year)
    header = ["Fecha", "Tipo", "Entrada", "Salida", "EUR", "Cuenta"]
    rows = []
    for t in txs:
        entrada = f"{_fmt_dec(t.amount_in)} {t.asset_in.symbol if t.asset_in else ''}".strip()
        salida = f"{_fmt_dec(t.amount_out)} {t.asset_out.symbol if t.asset_out else ''}".strip()
        rows.append(
            [
                t.timestamp.strftime("%Y-%m-%d"),
                t.type.value if hasattr(t.type, "value") else str(t.type),
                entrada,
                salida,
                _fmt_dec(t.eur_value),
                t.account.name if t.account else "",
            ]
        )
    return _build_pdf(
        title=f"Transacciones {'(' + str(year) + ')' if year else '(todos los años)'}",
        header=header,
        rows=rows,
        filename=f"transacciones_{year or 'todos'}_{date.today().isoformat()}.pdf",
        col_widths=[30, 35, 40, 40, 30, 35],
    )


def _fetch_transactions(
    db: Session, *, taxpayer_ids: list[int] | None = None, year: int | None = None
) -> list[Transaction]:
    q = select(Transaction).order_by(Transaction.timestamp.desc())
    if taxpayer_ids:
        q = q.where(Transaction.taxpayer_id.in_(taxpayer_ids))
    if year is not None:
        q = q.where(Transaction.fiscal_year == year)
    return list(db.scalars(q))


# ---------------------------------------------------------------------------
# Modelo 721
# ---------------------------------------------------------------------------

def export_model721_csv(
    db: Session, *, year: int, taxpayer_ids: list[int] | None = None
) -> tuple[bytes, str]:
    data = model721_service.compute(db, year, taxpayer_ids=taxpayer_ids)
    header = ["Cuenta", "Extranjero", "Activo", "Cantidad", "Precio EUR", "Valor EUR"]
    rows = []
    for h in data.get("holdings", []):
        rows.append(
            [
                h.get("account", ""),
                "Sí" if h.get("is_abroad") else "No",
                h.get("asset", ""),
                _fmt_dec(h.get("quantity")),
                _fmt_dec(h.get("price_eur")),
                _fmt_dec(h.get("value_eur")),
            ]
        )
    rows.append(["", "", "", "", "Total extranjero", _fmt_dec(data.get("total_abroad_eur"))])
    filename = f"modelo721_{year}_{date.today().isoformat()}.csv"
    return _csv_bytes(rows, header), filename


def export_model721_pdf(
    db: Session, *, year: int, taxpayer_ids: list[int] | None = None
) -> tuple[bytes, str]:
    data = model721_service.compute(db, year, taxpayer_ids=taxpayer_ids)
    header = ["Cuenta", "Extranjero", "Activo", "Cantidad", "Precio EUR", "Valor EUR"]
    rows = []
    for h in data.get("holdings", []):
        rows.append(
            [
                h.get("account", ""),
                "Sí" if h.get("is_abroad") else "No",
                h.get("asset", ""),
                _fmt_dec(h.get("quantity")),
                _fmt_dec(h.get("price_eur")),
                _fmt_dec(h.get("value_eur")),
            ]
        )
    rows.append(["", "", "", "", "Total extranjero", _fmt_dec(data.get("total_abroad_eur"))])
    return _build_pdf(
        title=f"Modelo 721 — {year}",
        subtitle=f"Obligado a declarar: {'Sí' if data.get('obligated') else 'No'} (umbral {_fmt_dec(data.get('threshold_eur'))} €)",
        header=header,
        rows=rows,
        filename=f"modelo721_{year}_{date.today().isoformat()}.pdf",
        col_widths=[45, 30, 30, 35, 35, 35],
    )


# ---------------------------------------------------------------------------
# PDF helper
# ---------------------------------------------------------------------------

def _build_pdf(
    *,
    title: str,
    header: list[str],
    rows: list[list[str]],
    filename: str,
    col_widths: list[float],
    subtitle: str | None = None,
) -> tuple[bytes, str]:
    try:
        from fpdf import FPDF
    except ImportError as exc:  # optional dependency
        raise PdfExportUnavailable(
            "La exportación a PDF requiere el paquete 'fpdf2'. "
            "Instálalo (pip install fpdf2) o exporta a CSV."
        ) from exc

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    font_name = _register_dejavu(pdf)
    pdf.add_page()
    pdf.set_font(font_name, "B", 14)
    pdf.cell(0, 10, title, ln=True)
    if subtitle:
        pdf.set_font(font_name, "", 10)
        pdf.cell(0, 8, subtitle, ln=True)
    pdf.ln(4)

    pdf.set_font(font_name, "B", 9)
    for text, width in zip(header, col_widths):
        pdf.cell(width, 8, text, border=1, align="C")
    pdf.ln()

    pdf.set_font(font_name, "", 9)
    for row in rows:
        for text, width in zip(row, col_widths):
            pdf.cell(width, 7, text, border=1, align="L")
        pdf.ln()

    pdf.set_font(font_name, "", 8)
    pdf.cell(0, 8, f"Generado el {date.today().isoformat()} por Crypto-Trace", align="R", ln=True)

    return bytes(pdf.output(dest="S")), filename


def _register_dejavu(pdf) -> str:
    """Try to load a Unicode font; fall back to core fonts otherwise."""
    import os

    from fpdf import FPDF

    def _try_load(regular_path: str, bold_path: str) -> bool:
        try:
            if os.path.exists(regular_path):
                pdf.add_font("DejaVu", "", regular_path, uni=True)
                if os.path.exists(bold_path):
                    pdf.add_font("DejaVu", "B", bold_path, uni=True)
                return True
        except Exception:
            pass
        return False

    # Current working directory.
    if _try_load("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        return "DejaVu"

    # System DejaVu (common on Linux after installing fonts-dejavu-core).
    sys_regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    sys_bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if _try_load(sys_regular, sys_bold):
        return "DejaVu"

    return "Arial"
