"""Connectors: translate exchange-specific exports into the canonical model.

A connector's ONLY job is format translation. Everything downstream (FIFO
engine, tax, reporting) works exclusively on :class:`CanonicalTransaction` and
never knows which exchange a row came from. Adding an exchange = adding a
connector, with zero changes to the fiscal logic.
"""
from app.connectors.base import (
    BaseConnector,
    CanonicalTransaction,
    ParseResult,
    RowError,
)
from app.connectors.registry import get_connector, list_connectors, register

__all__ = [
    "BaseConnector",
    "CanonicalTransaction",
    "ParseResult",
    "RowError",
    "get_connector",
    "list_connectors",
    "register",
]
