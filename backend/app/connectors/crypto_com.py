"""Crypto.com App export connector.

PROVISIONAL layout based on the typical Crypto.com App CSV/XLSX export
(``Timestamp (UTC)``, ``Currency``/``Amount``, ``To Currency``/``To Amount``,
``Native Amount`` in the user's fiat, ``Transaction Kind``). Column names and
the ``type_map`` live in ``mappings/crypto_com.yaml`` — adjust them to a real
export and the rest of the system is unaffected.
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
class CryptoComConnector(BaseConnector):
    source = AccountPlatform.CRYPTO_COM
    name = "CRYPTO_COM"
    mapping_file = "crypto_com.yaml"

    FIAT = "EUR"

    def normalize_row(self, raw: dict[str, Any], row_no: int) -> CanonicalTransaction | None:
        c = self.mapping["columns"]
        kind = self._cell(raw, c["type"])
        tx_type = self.map_type(kind)
        if tx_type is None:
            raise ValueError(f"Transaction Kind no soportado: {kind!r}")

        ts = self._parse_dt(self._cell(raw, c["timestamp"]))
        currency = self._sym(self._cell(raw, c["currency"]))
        amount = self._dec(self._cell(raw, c["amount"]))
        to_currency = self._sym(self._cell(raw, c.get("to_currency")))
        to_amount = self._dec(self._cell(raw, c.get("to_amount")))
        native = self._dec(self._cell(raw, c.get("native_amount")))  # EUR value

        external_id = self._opt_str(self._cell(raw, c.get("external_id"))) or self.synth_id(
            ts, kind, currency, amount, to_currency, to_amount
        )

        common = dict(tx_type=tx_type, timestamp=ts, external_id=external_id, eur_value=native, raw=raw)

        if tx_type == TransactionType.BUY:
            return self.make_tx(**common, recv_asset=currency, recv_amount=amount,
                                give_asset=self.FIAT, give_amount=native)
        if tx_type in (TransactionType.SELL, TransactionType.SPEND):
            return self.make_tx(**common, give_asset=currency, give_amount=amount,
                                recv_asset=self.FIAT, recv_amount=native)
        if tx_type == TransactionType.SWAP:
            return self.make_tx(**common, give_asset=currency, give_amount=amount,
                                recv_asset=to_currency, recv_amount=to_amount)
        if tx_type in _ACQUIRE_ONLY:
            return self.make_tx(**common, recv_asset=currency, recv_amount=amount)
        if tx_type == TransactionType.WITHDRAWAL:
            return self.make_tx(**common, give_asset=currency, give_amount=amount)
        # Fallback: treat as a single-asset movement on the received side.
        return self.make_tx(**common, recv_asset=currency, recv_amount=amount)
