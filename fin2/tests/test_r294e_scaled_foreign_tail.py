"""R294-e — a won amount followed by a parenthesised foreign amount with a scale/remark word is read by its
first amount (docs/rules/10_layer2_parse.md R294-e). Anything else in the tail stays refused (R6)."""
from __future__ import annotations

import pytest

from fin2.extract.report_lines import split_amount_with_tail


@pytest.mark.parametrize("cell, first", [
    ("379,360&cr;(USD 325,000백만)", "379,360"),
    ("53,570&cr;(US$50,000천)", "53,570"),
    ("66,468&cr;(US$ 55,000천)", "66,468"),
    ("114,761&cr;(SGD 140백만)", "114,761"),
    ("35,248,889 &cr;(US D 29,389천)", "35,248,889"),
    ("12,000 (USD 300,000백만) (AUD 400,000백만)", "12,000"),
])
def test_scaled_foreign_tail_is_read_by_its_first_amount(cell, first):
    assert split_amount_with_tail(cell) == first


@pytest.mark.parametrize("cell", [
    "13,400,000 &cr;(중소기업은행)",          # Korean name, not a currency
    "21,312원&cr; 20,000원&cr; 2.03%",       # won suffix list
    "11,700,993 (US$ 5,717,069 포함)",        # '포함' remark stays refused (R294-d)
    "5,000 (USD 300,000 담보)",              # remark word other than 포함
])
def test_other_tails_stay_refused(cell):
    assert split_amount_with_tail(cell) is None
