"""Default savings-base (base imponible del ahorro) tax brackets by year.

These are the IRPF *base del ahorro* marginal rates that apply to capital
gains from crypto. They are seeded into the ``tax_brackets`` table and can be
edited there (rates change, and regional nuances may apply). ``to`` of ``None``
means the open-ended top bracket.

Each entry: (from_eur, to_eur_or_None, rate).
"""
from __future__ import annotations

from decimal import Decimal

# Brackets in force 2021-2022 (top rate 26% over 200.000 €).
_2021_2022 = [
    (Decimal("0"), Decimal("6000"), Decimal("0.19")),
    (Decimal("6000"), Decimal("50000"), Decimal("0.21")),
    (Decimal("50000"), Decimal("200000"), Decimal("0.23")),
    (Decimal("200000"), None, Decimal("0.26")),
]

# Brackets from 2023 onwards (new 27% / 28% top brackets).
_2023_PLUS = [
    (Decimal("0"), Decimal("6000"), Decimal("0.19")),
    (Decimal("6000"), Decimal("50000"), Decimal("0.21")),
    (Decimal("50000"), Decimal("200000"), Decimal("0.23")),
    (Decimal("200000"), Decimal("300000"), Decimal("0.27")),
    (Decimal("300000"), None, Decimal("0.28")),
]

DEFAULT_BRACKETS: dict[int, list[tuple[Decimal, Decimal | None, Decimal]]] = {
    2021: _2021_2022,
    2022: _2021_2022,
    2023: _2023_PLUS,
    2024: _2023_PLUS,
    2025: _2023_PLUS,
    2026: _2023_PLUS,
}
