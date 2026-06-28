"""Crypto.com Exchange journal connector.

The Crypto.com Exchange export is a double-entry journal where each matched
trade is split into two or more legs (``TRADING`` rows) plus optional
``TRADE_FEE`` rows. All rows of a single execution share the same ``Order ID``.

This connector therefore works in two passes:

1. Read every journal row into a small internal record.
2. Group rows by ``Order ID`` (or treat singleton journal types such as
   ``FIAT_OPENPAYD_DEPOSIT`` as a single transaction).
3. Aggregate the crypto leg, the settlement-currency leg (EUR or
   ``USD_Stable_Coin``) and the fees.
4. Convert USD stablecoin amounts to EUR using the official ECB reference rate
   for the trade date (Frankfurter API), falling back to the configured rate.
5. Emit one canonical ``BUY`` or ``SELL`` per order, with crypto fees netted
   into the crypto amount and fiat fees passed as ``fee_asset``/``fee_amount``.

This keeps the FIFO engine and the Spanish IRPF reporting simple: the user
never has to track an internal ``USD_Stable_Coin`` lot.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO

from app.connectors.base import BaseConnector, CanonicalTransaction, ParseResult
from app.connectors.registry import register
from app.core.money import to_decimal
from app.models.enums import AccountPlatform, TransactionType
from app.services.exchange_rate_provider import fetch_usd_eur_rate


@dataclass
class _JournalRow:
    journal_id: str
    timestamp: datetime
    journal_type: str
    instrument: str | None
    side: str | None
    quantity: Decimal
    cost: Decimal
    order_id: str | None
    trade_id: str | None
    raw: dict[str, Any]


@register
class CryptoExchangeConnector(BaseConnector):
    source = AccountPlatform.CRYPTO_EXCHANGE
    name = "CRYPTO_EXCHANGE"
    mapping_file = "crypto_exchange.yaml"

    def _begin_parse(self) -> None:
        """Reset per-file caches."""
        self._rows: list[_JournalRow] = []
        self._rate_cache: dict[date, Decimal] = {}
        self._fallback = to_decimal(
            str(self.mapping.get("fallback_usd_to_eur_rate", 1.0))
        )

    def normalize_row(self, raw: dict[str, Any], row_no: int) -> CanonicalTransaction | None:
        """Stage every journal row for grouping; no canonical tx emitted yet."""
        c = self.mapping["columns"]

        journal_type = str(self._cell(raw, c["journal_type"]) or "").strip()
        if not journal_type:
            return None

        instrument = self._sym(self._cell(raw, c["instrument"]))
        side = self._opt_str(self._cell(raw, c["side"]))
        quantity = self._signed_dec(self._cell(raw, c["quantity"]))
        cost = self._signed_dec(self._cell(raw, c["cost"]))
        if quantity is None:
            quantity = Decimal("0")
        if cost is None:
            cost = Decimal("0")

        ts = self._parse_dt(self._cell(raw, c["timestamp"]))
        journal_id = str(self._cell(raw, c["journal_id"]) or row_no)
        order_id = self._opt_str(self._cell(raw, c["order_id"]))
        trade_id = self._opt_str(self._cell(raw, c["trade_id"]))

        self._rows.append(
            _JournalRow(
                journal_id=journal_id,
                timestamp=ts,
                journal_type=journal_type,
                instrument=instrument,
                side=side,
                quantity=quantity,
                cost=cost,
                order_id=order_id,
                trade_id=trade_id,
                raw=raw,
            )
        )
        return None

    def parse(self, file: str | Path | BinaryIO) -> ParseResult:
        """Group staged rows by order and emit canonical transactions."""
        result = super().parse(file)

        # Singleton journal types (deposits, withdrawals, etc.) become one tx
        # per row. Group the rest by Order ID so a multi-fill order collapses
        # into a single BUY/SELL.
        singleton_map: dict[str, str] = self.mapping.get("singleton_types", {})
        by_order: dict[str, list[_JournalRow]] = defaultdict(list)
        singletons: list[_JournalRow] = []

        for row in self._rows:
            if row.journal_type in singleton_map:
                singletons.append(row)
            elif row.order_id:
                by_order[row.order_id].append(row)
            else:
                # Should not happen in a normal export; keep as singleton with
                # a synthetic order key so it is not lost.
                by_order[f"__none__{row.journal_id}"].append(row)

        for row in singletons:
            tx = self._build_singleton(row, singleton_map[row.journal_type])
            if tx is not None:
                result.transactions.append(tx)

        for order_rows in by_order.values():
            tx = self._build_trade(order_rows)
            if tx is not None:
                result.transactions.append(tx)

        # Chronological order, BUY before SELL on equal timestamps so FIFO does
        # not complain about an intra-second sell before the buy.
        result.transactions.sort(
            key=lambda t: (t.timestamp, 0 if t.type == TransactionType.BUY else 1)
        )
        return result

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #
    def _rate(self, on: date) -> Decimal:
        """USD/EUR rate for ``on``; cache per file and fall back if needed."""
        if on not in self._rate_cache:
            rate = fetch_usd_eur_rate(on)
            if rate is None:
                rate = self._fallback
            self._rate_cache[on] = rate
        return self._rate_cache[on]

    def _to_eur(self, value: Decimal | None, rate: Decimal) -> Decimal | None:
        if value is None:
            return None
        return (value * rate).quantize(Decimal("0.01"))

    def _build_singleton(self, row: _JournalRow, tx_type_name: str) -> CanonicalTransaction | None:
        tx_type = TransactionType(tx_type_name)

        if tx_type == TransactionType.DEPOSIT:
            # EUR deposit: no taxable event, but preserve the record.
            asset = row.instrument or "EUR"
            return self.make_tx(
                tx_type=TransactionType.DEPOSIT,
                timestamp=row.timestamp,
                external_id=row.journal_id,
                eur_value=abs(row.quantity) if asset == "EUR" else None,
                raw=row.raw,
                recv_asset=asset,
                recv_amount=abs(row.quantity),
            )
        return None

    def _build_trade(self, rows: list[_JournalRow]) -> CanonicalTransaction | None:
        if not rows:
            return None

        # Use the earliest timestamp of the order as the canonical timestamp.
        ts = min(r.timestamp for r in rows)
        fiat_map: dict[str, str] = self.mapping.get("fiat_instruments", {})

        trading = [r for r in rows if r.journal_type == "TRADING"]
        fees = [r for r in rows if r.journal_type == "TRADE_FEE"]

        if not trading:
            # Fee-only rows without a trade leg are not expected; ignore.
            return None

        # Aggregate trading legs by instrument.
        leg_qty: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for r in trading:
            if r.instrument:
                leg_qty[r.instrument] += r.quantity

        # Separate settlement currency legs from crypto legs.
        fiat_legs: list[tuple[str, Decimal]] = []
        crypto_legs: list[tuple[str, Decimal]] = []
        for instrument, qty in leg_qty.items():
            if instrument in fiat_map:
                fiat_legs.append((instrument, qty))
            else:
                crypto_legs.append((instrument, qty))

        if len(crypto_legs) != 1:
            # We expect exactly one crypto leg per order (possibly with many
            # fills). If there are none or several, flag for manual review.
            return self._fallback_trade(rows, ts, "Orden sin un único leg crypto")
        crypto_instr, crypto_qty = crypto_legs[0]

        if not fiat_legs:
            return self._fallback_trade(rows, ts, "Orden sin moneda de liquidación")

        # Aggregate all settlement legs into a single EUR value.  In practice
        # there is only one (EUR or USD_Stable_Coin), but we tolerate several.
        total_fiat_eur = Decimal("0")
        for instrument, qty in fiat_legs:
            abs_qty = abs(qty)
            if instrument == "EUR":
                total_fiat_eur += abs_qty
            elif fiat_map.get(instrument) == "USD":
                rate = self._rate(ts.date())
                total_fiat_eur += (abs_qty * rate)

        # Aggregate fees by instrument.
        fee_by_instr: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for r in fees:
            if r.instrument:
                fee_by_instr[r.instrument] += r.quantity

        crypto_fee = fee_by_instr.get(crypto_instr, Decimal("0"))
        fiat_fee_eur = Decimal("0")
        for instrument, fee_qty in fee_by_instr.items():
            if instrument == crypto_instr:
                continue
            abs_fee = abs(fee_qty)
            if instrument == "EUR":
                fiat_fee_eur += abs_fee
            elif fiat_map.get(instrument) == "USD":
                rate = self._rate(ts.date())
                fiat_fee_eur += (abs_fee * rate)

        # Determine direction from the signed crypto leg.
        if crypto_qty > 0:
            # BUY crypto: net received is gross minus crypto-denominated fee.
            recv_amount = crypto_qty - abs(crypto_fee)
            if recv_amount <= Decimal("0"):
                return self._fallback_trade(rows, ts, "Compra con comisión >= cantidad recibida")
            eur_cost = (total_fiat_eur + fiat_fee_eur).quantize(Decimal("0.01"))
            external_id = self.synth_id("BUY", rows[0].order_id, crypto_instr, recv_amount)
            return self.make_tx(
                tx_type=TransactionType.BUY,
                timestamp=ts,
                external_id=external_id,
                eur_value=eur_cost,
                raw=rows[0].raw,
                recv_asset=crypto_instr,
                recv_amount=recv_amount,
                give_asset="EUR",
                give_amount=eur_cost,
            )
        elif crypto_qty < 0:
            # SELL crypto: total disposed is gross plus crypto-denominated fee.
            give_amount = abs(crypto_qty) + abs(crypto_fee)
            eur_proceeds = (total_fiat_eur - fiat_fee_eur).quantize(Decimal("0.01"))
            if eur_proceeds < Decimal("0"):
                eur_proceeds = Decimal("0")
            external_id = self.synth_id("SELL", rows[0].order_id, crypto_instr, give_amount)
            return self.make_tx(
                tx_type=TransactionType.SELL,
                timestamp=ts,
                external_id=external_id,
                eur_value=eur_proceeds,
                raw=rows[0].raw,
                recv_asset="EUR",
                recv_amount=eur_proceeds,
                give_asset=crypto_instr,
                give_amount=give_amount,
            )

        return self._fallback_trade(rows, ts, "Leg crypto con cantidad cero")

    def _fallback_trade(
        self, rows: list[_JournalRow], ts: datetime, reason: str
    ) -> CanonicalTransaction:
        """Emit a generic transaction when the order shape is unexpected.

        This keeps the row visible in the import and creates a MANUAL_REVIEW
        item via ``Transaction.notes``.
        """
        order_id = rows[0].order_id or rows[0].journal_id
        journal_types = ",".join(sorted({r.journal_type for r in rows}))
        instruments = ",".join(sorted({r.instrument for r in rows if r.instrument}))
        return self.make_tx(
            tx_type=TransactionType.TRANSFER,
            timestamp=ts,
            external_id=self.synth_id("FALLBACK", order_id, ts, journal_types, instruments),
            eur_value=None,
            raw=rows[0].raw,
            notes=f"Revisar orden Exchange: {reason} (types={journal_types}, instruments={instruments})",
        )
