"""Canonical enumerations shared across the domain model.

These values are platform-agnostic: connectors translate each exchange's own
vocabulary into these. Nothing downstream (FIFO engine, tax, reporting) knows
about exchange-specific formats.
"""
from __future__ import annotations

from enum import Enum


class AssetKind(str, Enum):
    CRYPTO = "CRYPTO"
    STABLECOIN = "STABLECOIN"  # taxed as crypto (a swap to USDT is a permuta)
    FIAT = "FIAT"  # only EUR closes the cycle without creating a lot


class AccountPlatform(str, Enum):
    CRYPTO_COM = "CRYPTO_COM"
    REVOLUT = "REVOLUT"
    MANUAL = "MANUAL"
    WALLET = "WALLET"


class AccountType(str, Enum):
    EXCHANGE = "EXCHANGE"
    WALLET = "WALLET"


class TransactionType(str, Enum):
    BUY = "BUY"  # fiat -> crypto (acquisition)
    SELL = "SELL"  # crypto -> fiat (disposal)
    SWAP = "SWAP"  # crypto -> crypto (permuta: disposal + acquisition)
    DEPOSIT = "DEPOSIT"  # incoming transfer (may carry a known cost basis)
    WITHDRAWAL = "WITHDRAWAL"  # outgoing transfer (not a disposal by itself)
    STAKING_REWARD = "STAKING_REWARD"
    AIRDROP = "AIRDROP"
    REFERRAL = "REFERRAL"
    SPEND = "SPEND"  # paying for goods/services with crypto (disposal)
    FEE = "FEE"
    TRANSFER = "TRANSFER"  # internal move between own accounts (no fiscal effect)
    REVERSAL = "REVERSAL"  # clawback of a prior reward (e.g. cashback reverted)


class DisposalKind(str, Enum):
    SALE = "SALE"
    SWAP = "SWAP"
    SPEND = "SPEND"


class IncomeCategory(str, Enum):
    RCM = "RCM"  # rendimiento del capital mobiliario (base del ahorro)
    GANANCIA = "GANANCIA"  # ganancia patrimonial sin valor de adquisición
    ACTIVIDAD = "ACTIVIDAD"  # rendimiento de actividad económica


class FiscalYearStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SummarySource(str, Enum):
    COMPUTED = "COMPUTED"
    MANUAL_SUMMARY = "MANUAL_SUMMARY"


class ImportStatus(str, Enum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ReviewCategory(str, Enum):
    P2P_TRANSFER = "P2P_TRANSFER"  # P2P with third party: needs ownership classification
    REVERSAL = "REVERSAL"  # reward clawback, verify it matches prior income
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"  # FIFO disposed more than recorded basis
    MISSING_PRICE = "MISSING_PRICE"  # Modelo 721 / valuation missing price quote
    MANUAL_REVIEW = "MANUAL_REVIEW"  # generic connector hint


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


class ReviewSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
