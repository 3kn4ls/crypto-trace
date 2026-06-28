"""Revolut "Gains / Losses" tax-export connector.

The Revolut CSV reports completed round-trip trades: each row has an
acquisition date, a disposal date, the crypto symbol/quantity, the USD cost
basis, the USD gross proceeds and the USD fees. This connector normalises each
row into two canonical transactions:

* a BUY on ``Date acquired`` (acquire the asset at cost basis)
* a SELL on ``Date sold`` (dispose the asset at gross proceeds, net of fees)

USD amounts are converted to EUR using the official ECB reference rate
(Frankfurter API) for the corresponding date. If the API is unavailable, the
``fallback_usd_to_eur_rate`` value from ``mappings/revolut.yaml`` is used.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO

from app.connectors.base import BaseConnector, CanonicalTransaction, ParseResult
from app.connectors.registry import register
from app.core.money import to_decimal
from app.models.enums import AccountPlatform, TransactionType
from app.services.exchange_rate_provider import fetch_usd_eur_rate


@register
class RevolutConnector(BaseConnector):
    source = AccountPlatform.REVOLUT
    name = "REVOLUT"
    mapping_file = "revolut.yaml"

    FIAT = "USD"  # values in the export are denominated in USD

    def _begin_parse(self) -> None:
        """Reset the per-file BUY side-list and rate cache."""
        self._row_counter = 0
        self._pending: list[CanonicalTransaction] = []
        self._rate_cache: dict[date, Decimal] = {}
        self._fallback = to_decimal(
            str(self.mapping.get("fallback_usd_to_eur_rate", 1.0))
        )

    def _rate(self, on: date) -> Decimal:
        """USD/EUR rate for ``on``; cache per file and fall back if needed."""
        if on not in self._rate_cache:
            rate = fetch_usd_eur_rate(on)
            if rate is None:
                rate = self._fallback
            self._rate_cache[on] = rate
        return self._rate_cache[on]

    def normalize_row(self, raw: dict[str, Any], row_no: int) -> CanonicalTransaction | None:
        c = self.mapping["columns"]

        symbol = self._sym(self._cell(raw, c["symbol"]))
        quantity = self._dec(self._cell(raw, c["quantity"]))
        cost_basis = self._dec(self._cell(raw, c["cost_basis"]))
        proceeds = self._dec(self._cell(raw, c["gross_proceeds"]))
        fees = self._dec(self._cell(raw, c["fees"]))
        currency = self._opt_str(self._cell(raw, c.get("currency"))) or self.FIAT

        if symbol is None or quantity is None:
            return None

        acquired = self._parse_dt(self._cell(raw, c["date_acquired"]))
        sold = self._parse_dt(self._cell(raw, c["date_sold"]))
        acquired_date = acquired.date()
        sold_date = sold.date()

        self._row_counter += 1
        base_id = self.synth_id(
            row_no, self._row_counter, acquired, sold, symbol, quantity,
            cost_basis, proceeds, fees,
        )

        # Preserve conversion metadata in raw_json; do not store it in
        # Transaction.notes to avoid generating one MANUAL_REVIEW item per row.

        # BUY: receive crypto, give fiat value = cost basis converted at the
        # acquisition date rate.
        buy_rate = self._rate(acquired_date)
        buy_cost_eur = self._to_eur(cost_basis, buy_rate)
        buy_tx = self.make_tx(
            tx_type=TransactionType.BUY,
            timestamp=acquired,
            external_id=f"{base_id}-buy",
            eur_value=buy_cost_eur,
            raw=raw,
            recv_asset=symbol,
            recv_amount=quantity,
            give_asset="EUR",
            give_amount=buy_cost_eur,
        )

        # SELL: give crypto, receive fiat value = gross proceeds converted at
        # the disposal date rate; fees use the disposal date rate too.
        sell_rate = self._rate(sold_date)
        sell_proceeds_eur = self._to_eur(proceeds, sell_rate)
        sell_fee_eur = self._to_eur(fees, sell_rate) if fees else None
        sell_tx = self.make_tx(
            tx_type=TransactionType.SELL,
            timestamp=sold,
            external_id=f"{base_id}-sell",
            eur_value=sell_proceeds_eur,
            raw=raw,
            give_asset=symbol,
            give_amount=quantity,
            recv_asset="EUR",
            recv_amount=sell_proceeds_eur,
            fee_asset="EUR" if fees else None,
            fee_amount=sell_fee_eur,
        )

        # BaseConnector.parse expects a single transaction per row. We queue the
        # BUY in a side-list and flush it once parsing finishes.
        self._pending.append(buy_tx)
        return sell_tx

    def parse(self, file: str | Path | BinaryIO) -> ParseResult:
        result = super().parse(file)
        result.transactions.extend(self._pending)
        # The SELL for each row is emitted immediately while its paired BUY is
        # queued. Re-sort so the BUY always precedes the SELL chronologically
        # (and for equal timestamps), which keeps FIFO and the import_service
        # dedup logic correct.
        result.transactions.sort(
            key=lambda t: (t.timestamp, 0 if t.type == TransactionType.BUY else 1)
        )
        return result

    @staticmethod
    def _to_eur(value: Decimal | None, rate: Decimal) -> Decimal | None:
        if value is None:
            return None
        return (value * rate).quantize(Decimal("0.01"))
