"""Custom SQLAlchemy column types.

SQLite has no native DECIMAL type and SQLAlchemy's ``Numeric`` round-trips
through ``float`` on SQLite (it even warns about it). For a fiscal tool that is
unacceptable, so we store decimals as TEXT and convert back to ``Decimal`` on
load. This preserves exact values. Range filtering in SQL would be lexicographic
on these columns, but all amount aggregation happens in Python, so that is fine.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.core.money import to_decimal


class DecimalText(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        # 'f' formatting avoids scientific notation so the string is canonical.
        return format(to_decimal(value), "f")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value)
