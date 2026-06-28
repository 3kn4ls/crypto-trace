"""External price provider integration (CoinGecko public API).

Fetches historical EUR closing prices for crypto assets. Designed to be called
on demand from the dashboard/fiscal-year flows so the user can value year-end
holdings for Modelo 721 and portfolio tracking without manual price entry.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import requests

# Free public CoinGecko endpoint. Rate limit is roughly 10-30 calls/minute.
COINGECKO_HISTORY_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}/history"
COINGECKO_CURRENT_URL = "https://api.coingecko.com/api/v3/simple/price"

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
}

# Runtime cache for symbol -> CoinGecko id discovered via the search/list APIs.
_DISCOVERED_IDS: dict[str, str] = {}


def _load_coin_list(timeout: int = 30) -> dict[str, str]:
    """Fetch CoinGecko /coins/list and build a symbol -> id lookup.

    Many small-cap tokens share symbols; we return the first match, which is
    usually the highest market cap. The result is cached in memory.
    """
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/coins/list",
            timeout=timeout,
        )
        response.raise_for_status()
        mapping: dict[str, str] = {}
        for coin in response.json():
            sym = (coin.get("symbol") or "").upper()
            if sym and sym not in mapping:
                mapping[sym] = coin["id"]
        return mapping
    except Exception:
        return {}


def coin_id_for(symbol: str) -> str | None:
    """Return CoinGecko coin id for a symbol, discovering unknowns on demand."""
    sym = symbol.upper()
    if sym in COIN_ID_MAP:
        return COIN_ID_MAP[sym]
    if sym in _DISCOVERED_IDS:
        return _DISCOVERED_IDS[sym]
    return None


def discover_coin_id(symbol: str, timeout: int = 30) -> str | None:
    """Try to discover a CoinGecko id for an unmapped symbol.

    Uses /coins/list first; if no direct match, falls back to /search.
    """
    sym = symbol.upper()
    if sym in COIN_ID_MAP:
        return COIN_ID_MAP[sym]
    if sym in _DISCOVERED_IDS:
        return _DISCOVERED_IDS[sym]

    # First pass: bulk list (one call covers the whole search).
    coin_list = _load_coin_list(timeout=timeout)
    if sym in coin_list:
        _DISCOVERED_IDS[sym] = coin_list[sym]
        return coin_list[sym]

    # Second pass: search endpoint for tokens missed in the list.
    try:
        response = requests.get(
            "https://api.coingecko.com/api/v3/search",
            params={"query": sym.lower()},
            timeout=timeout,
        )
        response.raise_for_status()
        coins = response.json().get("coins", [])
        for coin in coins:
            if (coin.get("symbol") or "").upper() == sym:
                _DISCOVERED_IDS[sym] = coin["id"]
                return coin["id"]
    except Exception:
        pass
    return None


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


def fetch_symbol_history_eur(symbol: str, on: date, timeout: int = 20) -> Decimal | None:
    """Convenience: symbol -> CoinGecko id -> EUR price.

    Falls back to dynamic discovery for unmapped symbols.
    """
    coin_id = coin_id_for(symbol)
    if not coin_id:
        coin_id = discover_coin_id(symbol, timeout=timeout)
    if not coin_id:
        return None
    return fetch_history_eur(coin_id, on, timeout=timeout)


def fetch_current_eur(symbol: str, timeout: int = 20) -> Decimal | None:
    """Fetch the current EUR price for a single symbol from CoinGecko."""
    coin_id = coin_id_for(symbol)
    if not coin_id:
        coin_id = discover_coin_id(symbol, timeout=timeout)
    if not coin_id:
        return None
    try:
        response = requests.get(
            COINGECKO_CURRENT_URL,
            params={"ids": coin_id, "vs_currencies": "eur"},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        eur = data.get(coin_id, {}).get("eur")
        if eur is None:
            return None
        return Decimal(str(eur))
    except Exception:
        return None
