"""Revolut crypto *account statement* connector (per-operation export, es-ES).

This handles Revolut's "crypto account statement", which lists one row per
movement (``Symbol, Type, Quantity, Price, Value, Fees, Date``). It is the
COMPLETE ledger — deposits, withdrawals, buys, sells and Learn rewards — and so,
unlike the "Gains / Losses" tax report handled by :mod:`revolut`, it preserves
open positions and lets the portfolio value be computed correctly.

Format quirks a flat YAML mapping cannot express, handled here:

* Monetary cells carry a currency suffix with Spanish number formatting, e.g.
  ``"1.681,46$"`` or ``"100,00€"`` (``.`` thousands, ``,`` decimals). The suffix
  also tells us the currency: ``$`` rows are converted to EUR at the official ECB
  reference rate for the row's date (Frankfurter API); ``€`` rows pass through.
* Dates are Spanish, e.g. ``"3 sept 2025, 21:40:50"`` (note ``sept``), which
  ``datetime.strptime`` / ``%b`` cannot parse portably across locales.
* Pure-fiat funding rows (Symbol ``EUR``/``USD``: Recepción/Envío/Otro) are
  dropped — they carry no crypto and have no fiscal effect (the FIFO engine
  ignores fiat in/out; the disposal proceeds are already captured by the SELL
  rows).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO

from app.connectors.base import BaseConnector, CanonicalTransaction, ParseResult
from app.connectors.registry import register
from app.core.money import to_decimal
from app.models.enums import AccountPlatform, TransactionType
from app.services.exchange_rate_provider import fetch_usd_eur_rate

# Spanish month abbreviations as exported by Revolut (note "sept" for September).
_MONTHS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dic": 12,
}

_DATE_RE = re.compile(
    r"^\s*(\d{1,2})\s+([A-Za-zÁÉÍÓÚáéíóú]+)\.?\s+(\d{4})\s*,?\s+"
    r"(\d{1,2}):(\d{2}):(\d{2})\s*$"
)

# Acquisition side (push a lot) vs disposal side (consume lots), for ordering.
_ACQUIRE = {TransactionType.BUY, TransactionType.AIRDROP}


@register
class RevolutCryptoConnector(BaseConnector):
    source = AccountPlatform.REVOLUT
    name = "REVOLUT_CRYPTO"
    mapping_file = "revolut_crypto.yaml"

    FIAT = "EUR"  # canonical settlement currency

    def _begin_parse(self) -> None:
        """Reset per-file state: row counter, rate cache and config."""
        self._row_counter = 0
        self._rate_cache: dict[date, Decimal] = {}
        self._fallback = to_decimal(
            str(self.mapping.get("fallback_usd_to_eur_rate", 1.0))
        )
        self._fiat_symbols = {
            str(s).strip().upper() for s in self.mapping.get("fiat_symbols", [])
        }

    def normalize_row(self, raw: dict[str, Any], row_no: int) -> CanonicalTransaction | None:
        c = self.mapping["columns"]

        symbol = self._sym(self._cell(raw, c["symbol"]))
        type_raw = self._opt_str(self._cell(raw, c["type"]))
        if symbol is None or type_raw is None:
            return None

        # Drop pure-fiat funding rows (EUR/USD deposits, withdrawals, "Otro").
        if symbol in self._fiat_symbols:
            return None

        tx_type = self._map_type(type_raw)
        if tx_type is None:
            raise ValueError(f"Tipo de operación Revolut no soportado: {type_raw!r}")

        ts = self._parse_dt(self._cell(raw, c["date"]))
        quantity = self._money(self._cell(raw, c["quantity"]))
        if quantity is None:
            raise ValueError(f"Cantidad vacía o no numérica para {symbol} ({type_raw})")

        value_cell = self._cell(raw, c["value"])
        fees_cell = self._cell(raw, c.get("fees"))
        currency = self._currency_of(value_cell, self._cell(raw, c.get("price")), fees_cell)

        on = ts.date()
        eur_value = self._fiat_eur(self._money(value_cell), currency, on)
        fee = self._money(fees_cell)
        # A zero (or absent) fee carries no fee leg, so it is not recorded.
        fee_eur = self._fiat_eur(fee, currency, on) if fee else None

        self._row_counter += 1
        external_id = self.synth_id(
            self._row_counter, ts, type_raw, symbol, quantity, value_cell, fees_cell,
        )

        if tx_type == TransactionType.BUY:
            return self.make_tx(
                tx_type=TransactionType.BUY, timestamp=ts, external_id=external_id,
                eur_value=eur_value, raw=raw,
                recv_asset=symbol, recv_amount=quantity,
                give_asset=self.FIAT, give_amount=eur_value,
                fee_asset=self.FIAT if fee_eur else None, fee_amount=fee_eur,
            )
        if tx_type == TransactionType.SELL:
            return self.make_tx(
                tx_type=TransactionType.SELL, timestamp=ts, external_id=external_id,
                eur_value=eur_value, raw=raw,
                give_asset=symbol, give_amount=quantity,
                recv_asset=self.FIAT, recv_amount=eur_value,
                fee_asset=self.FIAT if fee_eur else None, fee_amount=fee_eur,
            )
        # AIRDROP (Learn & Earn reward): crypto received with no fiat leg. The
        # reward-preference layer decides its fiscal category and cost basis.
        return self.make_tx(
            tx_type=TransactionType.AIRDROP, timestamp=ts, external_id=external_id,
            eur_value=eur_value, raw=raw,
            recv_asset=symbol, recv_amount=quantity,
        )

    def parse(self, file: str | Path | BinaryIO) -> ParseResult:
        result = super().parse(file)
        # The export is not strictly chronological (rewards are grouped at the
        # end). Sort so the ledger/FIFO sees acquisitions before disposals on
        # equal timestamps.
        result.transactions.sort(
            key=lambda t: (t.timestamp, 0 if t.type in _ACQUIRE else 1)
        )
        return result

    # --- helpers ------------------------------------------------------------
    def _map_type(self, raw_type: str) -> TransactionType | None:
        """Exact YAML mapping first, then a tolerant keyword fallback so future
        product-name suffixes (e.g. ``Comprar - …``) keep resolving."""
        mapped = self.map_type(raw_type)
        if mapped is not None:
            return mapped
        t = raw_type.strip().lower()
        if t.startswith(("comprar", "compra")):
            return TransactionType.BUY
        if t.startswith(("vender", "venta")):
            return TransactionType.SELL
        if t.startswith("recompensa"):
            return TransactionType.AIRDROP
        return None

    @staticmethod
    def _currency_of(*cells: Any) -> str:
        """Infer the row's currency from the symbol suffix of its money cells."""
        for cell in cells:
            if cell is None:
                continue
            s = str(cell)
            if "$" in s:
                return "USD"
            if "€" in s:
                return "EUR"
        return "EUR"

    @staticmethod
    def _money(value: Any) -> Decimal | None:
        """Parse a Spanish-formatted amount, stripping the currency suffix.

        Examples: ``"1.681,46$"`` -> 1681.46, ``"76.477.160"`` -> 76477160,
        ``"0,0493869"`` -> 0.0493869. ``.`` is the thousands separator and ``,``
        the decimal separator.
        """
        if value is None:
            return None
        text = str(value).replace("€", "").replace("$", "")
        text = re.sub(r"[\s ]", "", text)
        if not text:
            return None
        text = text.replace(".", "").replace(",", ".")
        if text in ("", "-", "+"):
            return None
        return to_decimal(text)

    def _rate(self, on: date) -> Decimal:
        """USD/EUR rate for ``on``; cache per file and fall back if needed."""
        if on not in self._rate_cache:
            rate = fetch_usd_eur_rate(on)
            if rate is None:
                rate = self._fallback
            self._rate_cache[on] = rate
        return self._rate_cache[on]

    def _fiat_eur(self, amount: Decimal | None, currency: str, on: date) -> Decimal | None:
        """Convert a fiat amount to EUR cents (USD via the ECB rate for ``on``)."""
        if amount is None:
            return None
        if currency == "USD":
            amount = amount * self._rate(on)
        return amount.quantize(Decimal("0.01"))

    def _parse_dt(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        text = self._opt_str(value)
        if not text:
            raise ValueError("Fecha vacía")
        m = _DATE_RE.match(text)
        if not m:
            raise ValueError(f"Formato de fecha no reconocido: {value!r}")
        day, month_txt, year, hh, mm, ss = m.groups()
        month = _MONTHS.get(month_txt.lower().rstrip("."))
        if month is None:
            raise ValueError(f"Mes no reconocido en fecha: {value!r}")
        return datetime(int(year), month, int(day), int(hh), int(mm), int(ss))
