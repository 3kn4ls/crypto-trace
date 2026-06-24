"""Deterministic tests for the savings-base tax calculator."""
from __future__ import annotations

from decimal import Decimal

from app.services.tax_calculator import compute_tax
from app.tax.brackets import DEFAULT_BRACKETS


def brackets(year: int):
    return DEFAULT_BRACKETS[year]


def test_single_bracket():
    res = compute_tax(2024, [Decimal("5000")], brackets=brackets(2024))
    assert res.savings_base == Decimal("5000.00")
    assert res.tax_due == Decimal("950.00")  # 5000 * 19%


def test_multi_bracket():
    res = compute_tax(2024, [Decimal("60000")], brackets=brackets(2024))
    # 6000*0.19 + 44000*0.21 + 10000*0.23 = 1140 + 9240 + 2300
    assert res.tax_due == Decimal("12680.00")
    assert res.savings_base == Decimal("60000.00")


def test_gains_and_losses_net():
    res = compute_tax(2024, [Decimal("5000"), Decimal("-2000")], brackets=brackets(2024))
    assert res.net_capital_gain == Decimal("3000.00")
    assert res.tax_due == Decimal("570.00")  # 3000 * 19%


def test_negative_pl_carryforward_note_and_zero_tax():
    res = compute_tax(2024, [Decimal("-4000")], brackets=brackets(2024))
    assert res.savings_base == Decimal("0.00")
    assert res.tax_due == Decimal("0.00")
    assert any("compensable" in n for n in res.notes)


def test_cross_compensation_pl_loss_against_rcm():
    # group_pl = -1000, rcm = 10000. Offset limited to 25% of rcm = 2500, so all
    # 1000 offsets. base = 0 + 9000.
    res = compute_tax(
        2024, [Decimal("-1000")], rcm_income=Decimal("10000"), brackets=brackets(2024)
    )
    assert res.savings_base == Decimal("9000.00")
    # 6000*0.19 + 3000*0.21 = 1140 + 630
    assert res.tax_due == Decimal("1770.00")


def test_top_bracket_2024_vs_2022():
    # 2022 top bracket is 26% over 200k; 2023+ adds 27%/28%.
    assert any(b[2] == Decimal("0.26") for b in brackets(2022))
    assert any(b[2] == Decimal("0.28") for b in brackets(2024))
