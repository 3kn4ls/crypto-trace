"""Revolut "Gains / Losses" tax-export connector.

The Revolut CSV reports completed round-trip trades: each row has an
acquisition date, a disposal date, the crypto symbol/quantity, the USD cost
basis, the USD gross proceeds and the USD fees. This connector normalises each
row into two canonical transactions:

* a BUY on ``Date acquired`` (acquire the asset at cost basis)
* a SELL on ``Date sold`` (dispose the asset at gross proceeds, net of fees)

USD amounts are converted to EUR via the optional ``usd_to_eur_rate`` multiplier
in ``mappings/revolut.yaml`` (defaults to 1.0).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO

from app.connectors.base import BaseConnector, CanonicalTransaction, ParseResult
from app.connectors.registry import register
from app.core.money import to_decimal
from app.models.enums import AccountPlatform, TransactionType


@register
class RevolutConnector(BaseConnector):
    source = AccountPlatform.REVOLUT
    name = "REVOLUT"
    mapping_file = "revolut.yaml"

    FIAT = "USD"  # values in the export are denominated in USD

    def _begin_parse(self) -> None:
        """Reset the per-file BUY side-list."""
        self._row_counter = 0
        self._pending: list[CanonicalTransaction] = []

    def normalize_row(self, raw: dict[str, Any], row_no: int) -> CanonicalTransaction | None:
        c = self.mapping["columns"]
        rate = to_decimal(str(self.mapping.get("usd_to_eur_rate", 1.0)))

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

        self._row_counter += 1
        base_id = self.synth_id(
            row_no, self._row_counter, acquired, sold, symbol, quantity,
            cost_basis, proceeds, fees,
        )

        # The original currency and applied rate are preserved in raw_json.
        # We intentionally do not put them in Transaction.notes so the connector
        # does not generate one MANUAL_REVIEW item per imported row.

        # BUY: receive crypto, give fiat value = cost basis
        buy_tx = self.make_tx(
            tx_type=TransactionType.BUY,
            timestamp=acquired,
            external_id=f"{base_id}-buy",
            eur_value=self._to_eur(cost_basis, rate),
            raw=raw,
            recv_asset=symbol,
            recv_amount=quantity,
            give_asset="EUR",
            give_amount=self._to_eur(cost_basis, rate),
        )

        # SELL: give crypto, receive fiat value = gross proceeds
        sell_tx = self.make_tx(
            tx_type=TransactionType.SELL,
            timestamp=sold,
            external_id=f"{base_id}-sell",
            eur_value=self._to_eur(proceeds, rate),
            raw=raw,
            give_asset=symbol,
            give_amount=quantity,
            recv_asset="EUR",
            recv_amount=self._to_eur(proceeds, rate),
            fee_asset="EUR" if fees else None,
            fee_amount=self._to_eur(fees, rate) if fees else None,
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
