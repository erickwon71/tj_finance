"""R221 — layer-3 expense sign normalization (fin2/layer3/expense_sign.py)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.expense_sign import normalize_expense_signs


def _samyang_2024():
    # 삼양식품 연결 FY2024 as loaded from the source (expenses printed in parentheses).
    return {
        "revenue": 1728015003746, "cogs": -1004797694924,
        "gross_profit": 723217308822, "sga": -378648158379,
        "operating_income": 344569150443, "interest_expense": -28977708722,
        "ebt": 351640034115, "tax_expense": -80384368652, "net_income": 271255665463,
    }


def test_parenthesised_expenses_become_positive():
    col = _samyang_2024()
    flipped = normalize_expense_signs(col)
    assert set(flipped) == {"cogs", "sga", "interest_expense", "tax_expense"}
    assert col["cogs"] == 1004797694924
    assert col["sga"] == 378648158379
    assert col["interest_expense"] == 28977708722
    assert col["tax_expense"] == 80384368652


def test_positive_convention_untouched():
    col = {"revenue": 1192914607980, "cogs": 776182562968, "gross_profit": 416732045012,
           "ebt": 156325436987, "tax_expense": 29734237354, "net_income": 126591199633,
           "interest_expense": 12226591766}
    before = dict(col)
    assert normalize_expense_signs(col) == []
    assert col == before


def test_tax_benefit_printed_positive_under_negative_convention_becomes_negative():
    # Negative convention: a tax *benefit* is printed positive and adds to net income.
    col = {"ebt": -100_000_000, "tax_expense": 20_000_000, "net_income": -80_000_000}
    assert normalize_expense_signs(col) == ["tax_expense"]
    assert col["tax_expense"] == -20_000_000


def test_tax_benefit_under_positive_convention_stays_negative():
    col = {"ebt": -100_000_000, "tax_expense": -20_000_000, "net_income": -80_000_000}
    assert normalize_expense_signs(col) == []
    assert col["tax_expense"] == -20_000_000


def test_negative_nonneg_expense_flips_without_identity():
    # Interest expense can never be negative economically; no identity needed.
    col = {"interest_expense": -5_000_000}
    assert normalize_expense_signs(col) == ["interest_expense"]
    assert col["interest_expense"] == 5_000_000


def test_tax_without_proof_untouched():
    col = {"tax_expense": -5_000_000, "ebt": 10}
    assert normalize_expense_signs(col) == []


def test_mixed_convention_in_one_statement():
    # 00145260 consolidated FY2018: 매출원가 positive, 판관비·금융비용 negative, 법인세 positive.
    col = {"revenue": 489770531952, "cogs": 433385731007, "gross_profit": 56384800945,
           "sga": -38609448276, "operating_income": 17775352669,
           "interest_expense": -2375684240, "ebt": 17810597253,
           "tax_expense": 3085963416, "net_income": 14724633837}
    assert normalize_expense_signs(col) == ["sga", "interest_expense"]
    assert col["cogs"] == 433385731007 and col["tax_expense"] == 3085963416


def test_negative_cogs_kept_when_identity_proves_it():
    # gross_profit = revenue - cogs holds with the negative value → it is genuine.
    col = {"revenue": 1_000_000, "cogs": -50_000, "gross_profit": 1_050_000}
    assert normalize_expense_signs(col) == []
    assert col["cogs"] == -50_000


def test_rounding_tolerance_for_thousand_won_tables():
    col = {"revenue": 314631900000, "cogs": -237309271000, "gross_profit": 77322630000}
    assert normalize_expense_signs(col) == ["cogs"]
