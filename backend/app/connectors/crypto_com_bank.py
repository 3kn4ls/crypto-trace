"""Crypto.com App / Bank / Card export connector.

PROVISIONAL layout based on the typical Crypto.com App CSV/XLSX export
(``Timestamp (UTC)``, ``Currency``/``Amount``, ``To Currency``/``To Amount``,
``Native Amount`` in the user's fiat, ``Transaction Kind``). Column names and
the ``type_map`` live in ``mappings/crypto_com_bank.yaml`` — adjust them to a real
export and the rest of the system is unaffected.
"""
from __future__ import annotations

from collections import Counter
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
class CryptoComBankConnector(BaseConnector):
    source = AccountPlatform.CRYPTO_COM_BANK
    name = "CRYPTO_COM_BANK"
    mapping_file = "crypto_com_bank.yaml"

    FIAT = "EUR"

    def _begin_parse(self) -> None:
        # Counts otherwise-identical rows within a file so synthetic ids stay
        # unique. The Crypto.com export has no per-row id and can legitimately
        # contain several micro-rewards that share timestamp/amount.
        self._occurrence: Counter[tuple] = Counter()

    def normalize_row(self, raw: dict[str, Any], row_no: int) -> CanonicalTransaction | None:
        c = self.mapping["columns"]
        kind = self._cell(raw, c["type"])
        tx_type = self.map_type(kind)
        if tx_type is None:
            raise ValueError(f"Transaction Kind no soportado: {kind!r}")

        ts = self._parse_dt(self._cell(raw, c["timestamp"]))
        currency = self._sym(self._cell(raw, c["currency"]))
        amount = self._dec(self._cell(raw, c["amount"]))  # absolute value
        signed = self._signed_dec(self._cell(raw, c["amount"]))  # sign = direction
        to_currency = self._sym(self._cell(raw, c.get("to_currency")))
        to_amount = self._dec(self._cell(raw, c.get("to_amount")))
        native = self._dec(self._cell(raw, c.get("native_amount")))  # EUR value

        external_id = self._opt_str(self._cell(raw, c.get("external_id")))
        if external_id is None:
            # No Transaction Hash in this export: build a stable synthetic id.
            # ``native`` and an occurrence counter keep genuinely distinct rows
            # (e.g. two rewards in the same second with different EUR values)
            # from collapsing, while a re-import of the same file stays idempotent.
            base = (ts, kind, currency, amount, to_currency, to_amount, native)
            self._occurrence[base] += 1
            external_id = self.synth_id(*base, self._occurrence[base])

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
        if tx_type == TransactionType.REVERSAL:
            # Reward clawback (e.g. card cashback reverted): the units leave the
            # books on the "given" side; the tax layer backs out the income.
            return self.make_tx(**common, give_asset=currency, give_amount=amount,
                                 notes=self._note(kind))
        if tx_type == TransactionType.TRANSFER:
            # Internal moves (supercharger/staking lock) and P2P transfers carry
            # no fiscal effect here; sign decides the leg. P2P is flagged for
            # manual review (own account vs gift/payment). See SUGGESTIONS.md.
            note = self._note(kind)
            if signed is not None and signed < 0:
                return self.make_tx(**common, give_asset=currency, give_amount=amount, notes=note)
            return self.make_tx(**common, recv_asset=currency, recv_amount=amount, notes=note)
        if tx_type in _ACQUIRE_ONLY:
            return self.make_tx(**common, recv_asset=currency, recv_amount=amount)
        if tx_type == TransactionType.WITHDRAWAL:
            return self.make_tx(**common, give_asset=currency, give_amount=amount)
        # Fallback: treat as a single-asset movement on the received side.
        return self.make_tx(**common, recv_asset=currency, recv_amount=amount)

    @staticmethod
    def _note(kind: Any) -> str | None:
        """Human-readable review hint for movements that need attention."""
        k = str(kind or "")
        if "p2p" in k:
            return "P2P con tercero: revisar si es cuenta propia, donación o pago"
        if "reverted" in k or "reversal" in k:
            return "Reversión de recompensa (deshace ingreso previo)"
        return None
