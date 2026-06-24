"""IRPF savings-base (base del ahorro) tax computation — pure functions.

Scope: capital gains/losses from crypto disposals plus crypto-derived income.
Income is classified per :class:`IncomeCategory`:

* ``GANANCIA`` -> ganancia patrimonial (joins the gains/losses group).
* ``RCM``      -> rendimiento del capital mobiliario (its own savings-base group).
* ``ACTIVIDAD``-> general base; reported separately, not part of the savings base.

Cross-compensation between the two savings-base groups is applied up to 25%
(current rule) when one group's balance is negative. Remaining negative
balances would carry forward up to 4 years — surfaced as a note for Phase 2,
not yet carried automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from app.core.money import ZERO, quantize_eur

CROSS_COMPENSATION_LIMIT = Decimal("0.25")


@dataclass
class BracketCharge:
    from_eur: Decimal
    to_eur: Decimal | None
    rate: Decimal
    taxable_in_bracket: Decimal
    tax: Decimal


@dataclass
class TaxResult:
    year: int
    total_gains: Decimal
    total_losses: Decimal
    net_capital_gain: Decimal  # gains/losses group (incl. GANANCIA income)
    rcm_income: Decimal
    actividad_income: Decimal
    savings_base: Decimal
    tax_due: Decimal
    effective_rate: Decimal
    bracket_breakdown: list[BracketCharge] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def apply_brackets(
    base: Decimal, brackets: list[tuple[Decimal, Decimal | None, Decimal]]
) -> tuple[Decimal, list[BracketCharge]]:
    """Apply progressive marginal brackets to ``base`` (>= 0)."""
    charges: list[BracketCharge] = []
    total = ZERO
    if base <= ZERO:
        return ZERO, charges
    for from_eur, to_eur, rate in sorted(brackets, key=lambda b: b[0]):
        if base <= from_eur:
            break
        upper = base if to_eur is None else min(base, to_eur)
        taxable = upper - from_eur
        if taxable <= ZERO:
            continue
        tax = quantize_eur(taxable * rate)
        charges.append(BracketCharge(from_eur, to_eur, rate, taxable, tax))
        total += tax
    return total, charges


def compute_tax(
    year: int,
    gain_loss_values: Iterable[Decimal],
    *,
    rcm_income: Decimal = ZERO,
    ganancia_income: Decimal = ZERO,
    actividad_income: Decimal = ZERO,
    brackets: list[tuple[Decimal, Decimal | None, Decimal]],
) -> TaxResult:
    values = list(gain_loss_values)
    total_gains = sum((v for v in values if v > ZERO), ZERO)
    total_losses = sum((v for v in values if v < ZERO), ZERO)  # negative

    # Gains/losses group also includes ganancias patrimoniales from income.
    group_pl = total_gains + total_losses + ganancia_income
    group_rcm = rcm_income

    notes: list[str] = []
    base_pl, base_rcm = group_pl, group_rcm

    # Cross compensation up to 25% when one group is negative.
    if base_pl < ZERO and base_rcm > ZERO:
        offset = min(-base_pl, quantize_eur(base_rcm * CROSS_COMPENSATION_LIMIT))
        base_rcm -= offset
        base_pl += offset
    elif base_rcm < ZERO and base_pl > ZERO:
        offset = min(-base_rcm, quantize_eur(base_pl * CROSS_COMPENSATION_LIMIT))
        base_pl -= offset
        base_rcm += offset

    if group_pl < ZERO:
        notes.append(
            f"Saldo negativo de ganancias/pérdidas de {quantize_eur(group_pl)} € "
            "compensable en los 4 ejercicios siguientes."
        )

    savings_base = max(ZERO, base_pl) + max(ZERO, base_rcm)
    tax_due, charges = apply_brackets(savings_base, brackets)
    effective = quantize_eur(tax_due / savings_base) if savings_base > ZERO else ZERO

    return TaxResult(
        year=year,
        total_gains=quantize_eur(total_gains),
        total_losses=quantize_eur(total_losses),
        net_capital_gain=quantize_eur(group_pl),
        rcm_income=quantize_eur(rcm_income),
        actividad_income=quantize_eur(actividad_income),
        savings_base=quantize_eur(savings_base),
        tax_due=quantize_eur(tax_due),
        effective_rate=effective,
        bracket_breakdown=charges,
        notes=notes,
    )
