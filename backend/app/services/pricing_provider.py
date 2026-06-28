"""External price provider integration (CoinGecko public API).

Fetches historical EUR closing prices for crypto assets. Designed to be called
on demand from the dashboard/fiscal-year flows so the user can value year-end
holdings for Modelo 721 and portfolio tracking without manual price entry.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import requests

# Free public CoinGecko endpoint. Rate limit is roughly 10-30 calls/minute.
COINGECKO_HISTORY_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}/history"

# Common symbol -> CoinGecko id mapping. The user can extend this via settings
# in the future; for now it covers the assets most likely to appear in exports.
COIN_ID_MAP: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "XRP": "ripple",
    "CRO": "crypto-com-chain",
    "BNB": "binancecoin",
    "SOL": "solana",
    "ADA": "cardano",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "XLM": "stellar",
    "UNI": "uniswap",
    "AAVE": "aave",
    "ATOM": "cosmos",
    "ETC": "ethereum-classic",
    "FIL": "filecoin",
    "ALGO": "algorand",
    "XTZ": "tezos",
    "VET": "vechain",
    "TRX": "tron",
    "SHIB": "shiba-inu",
    "DOGE": "dogecoin",
    "USDT": "tether",
    "USDC": "usd-coin",
    "DAI": "dai",
    "BARA": "bara",  # not listed on CoinGecko; will be reported as unknown
    "XPL": "xpl",    # not listed; placeholder
}


def coin_id_for(symbol: str) -> str | None:
    """Return CoinGecko coin id for a symbol, or None if not mapped."""
    return COIN_ID_MAP.get(symbol.upper())


def _parse_price(data: dict[str, Any]) -> Decimal | None:
    """Extract EUR price from CoinGecko /coins/{id}/history response."""
    market_data = data.get("market_data")
    if not market_data:
        return None
    eur = market_data.get("current_price", {}).get("eur")
    if eur is None:
        return None
    try:
        return Decimal(str(eur))
    except InvalidOperation:
        return None


def fetch_history_eur(coin_id: str, on: date, timeout: int = 20) -> Decimal | None:
    """Fetch the EUR price for a CoinGecko coin id on a specific date.

    CoinGecko's /history endpoint takes a date string in DD-MM-YYYY format and
    returns the price as of that day (typically close to end-of-day).
    """
    date_param = on.strftime("%d-%m-%Y")
    url = COINGECKO_HISTORY_URL.format(coin_id=coin_id)
    try:
        response = requests.get(
            url,
            params={"date": date_param, "localization": "false"},
            timeout=timeout,
        )
        response.raise_for_status()
        return _parse_price(response.json())
    except requests.RequestException:
        return None
    except Exception:
        return None


def fetch_symbol_history_eur(symbol: str, on: date) -> Decimal | None:
    """Convenience: symbol -> CoinGecko id -> EUR price."""
    coin_id = coin_id_for(symbol)
    if not coin_id:
        return None
    return fetch_history_eur(coin_id, on)
