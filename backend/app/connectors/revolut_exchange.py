"""Revolut exchange export connector.

PROVISIONAL layout for a Revolut crypto/exchange statement with one row per
operation: ``Date``, ``Type`` (BUY/SELL/EXCHANGE/...), ``Currency``/``Amount``
(crypto leg), optional ``To Currency``/``To Amount`` for exchanges, and a fiat
value column. Column names and the ``type_map`` live in
``mappings/revolut_exchange.yaml``.
"""
from __future__ import annotations

from typing import Any

from app.connectors.base import BaseConnector, CanonicalTransaction
from app.connectors.registry import register
from app.models.enums import AccountPlatform, TransactionType

_ACQUIRE_ONLY = {
    TransactionType.STAKING_REWARD,
    TransactionType.AIRDROP,
    TransactionType.REFERRAL,
    TransactionType.DEPOSIT,
}


@register
class RevolutExchangeConnector(BaseConnector):
    source = AccountPlatform.REVOLUT
    name = "REVOLUT_EXCHANGE"
    mapping_file = "revolut_exchange.yaml"

    FIAT = "EUR"

    def normalize_row(self, raw: dict[str, Any], row_no: int) -> CanonicalTransaction | None:
        c = self.mapping["columns"]
        kind = self._cell(raw, c["type"])
        tx_type = self.map_type(kind)
        if tx_type is None:
            raise ValueError(f"Type no soportado: {kind!r}")

        ts = self._parse_dt(self._cell(raw, c["timestamp"]))
        currency = self._sym(self._cell(raw, c["currency"]))
        amount = self._dec(self._cell(raw, c["amount"]))
        to_currency = self._sym(self._cell(raw, c.get("to_currency")))
        to_amount = self._dec(self._cell(raw, c.get("to_amount")))
        fiat = self._dec(self._cell(raw, c.get("fiat_amount")))  # EUR value
        fee_amount = self._dec(self._cell(raw, c.get("fee_amount")))
        fee_asset = self._sym(self._cell(raw, c.get("fee_asset"))) or self.FIAT

        external_id = self._opt_str(self._cell(raw, c.get("external_id"))) or self.synth_id(
            ts, kind, currency, amount, to_currency, to_amount, fiat
        )

        common = dict(
            tx_type=tx_type, timestamp=ts, external_id=external_id, eur_value=fiat, raw=raw,
            fee_asset=fee_asset if fee_amount else None, fee_amount=fee_amount,
        )

        if tx_type == TransactionType.BUY:
            return self.make_tx(**common, recv_asset=currency, recv_amount=amount,
                                give_asset=self.FIAT, give_amount=fiat)
        if tx_type in (TransactionType.SELL, TransactionType.SPEND):
            return self.make_tx(**common, give_asset=currency, give_amount=amount,
                                recv_asset=self.FIAT, recv_amount=fiat)
        if tx_type == TransactionType.SWAP:
            return self.make_tx(**common, give_asset=currency, give_amount=amount,
                                recv_asset=to_currency, recv_amount=to_amount)
        if tx_type in _ACQUIRE_ONLY:
            return self.make_tx(**common, recv_asset=currency, recv_amount=amount)
        if tx_type == TransactionType.WITHDRAWAL:
            return self.make_tx(**common, give_asset=currency, give_amount=amount)
        return self.make_tx(**common, recv_asset=currency, recv_amount=amount)
