"""USD/EUR exchange-rate lookup via Frankfurter (ECB reference rates).

Provides a per-date USD->EUR rate so connectors that receive USD-denominated
exports (e.g. Revolut tax reports) can convert each amount to EUR at the
official rate of the relevant day.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import requests

FRANKFURTER_BASE_URL = "https://api.frankfurter.dev/v1"

# In-memory cache: date.isoformat() -> Decimal rate.
_RATE_CACHE: dict[str, Decimal] = {}


def fetch_usd_eur_rate(on: date, timeout: int = 10) -> Decimal | None:
    """Return the ECB USD/EUR reference rate for ``on``.

    Uses the Frankfurter public API. Rates are cached in memory for the
    lifetime of the process. Weekends/holidays return the last published
    rate (Frankfurter already handles this). Returns ``None`` if the API
    is unreachable or the date has no rate.
    """
    key = on.isoformat()
    if key in _RATE_CACHE:
        return _RATE_CACHE[key]

    url = f"{FRANKFURTER_BASE_URL}/{key}"
    try:
        response = requests.get(
            url,
            params={"from": "USD", "to": "EUR"},
            timeout=timeout,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        rate = data.get("rates", {}).get("EUR")
        if rate is None:
            return None
        dec = Decimal(str(rate))
        _RATE_CACHE[key] = dec
        return dec
    except Exception:
        return None


def convert_usd_to_eur(usd_amount: Decimal | None, on: date, fallback_rate: Decimal | None = None) -> Decimal | None:
    """Convert a USD amount to EUR using the official rate for ``on``.

    If the API lookup fails and ``fallback_rate`` is provided, that rate is
    used instead. Returns ``None`` when the input is ``None`` and no conversion
    can be performed.
    """
    if usd_amount is None:
        return None
    rate = fetch_usd_eur_rate(on)
    if rate is None:
        if fallback_rate is None:
            return None
        rate = fallback_rate
    return (usd_amount * rate).quantize(Decimal("0.01"))
