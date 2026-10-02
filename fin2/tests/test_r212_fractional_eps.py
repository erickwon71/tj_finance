"""R212(2026-10-02) 회귀 테스트 — 소수 EPS 보존(value_exact / amount_exact).

`report_lines.value_won` 은 BIGINT 라 원문 EPS 13.42 가 13 으로 저장됐다(비투엔 2020FY
`20210317000884` 별도 기본·희석주당이익, 이슈 #88194·#88195). value_won 은 반올림 정수 그대로
두고, 반올림된 칸에만 정확값을 `value_exact` 로 함께 싣는다. 계층3 은 확장 캐노니컬
(is.eps_basic 등)의 정확값을 `extended_facts_v3.amount_exact` 로 옮긴다.

실행: pytest fin2/tests/test_r212_fractional_eps.py
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.common.amount_normalizer import (                      # noqa: E402
    fractional_or_none, parse_amount, parse_amount_decimal)
from parser.xbrl_instance.instance_parser import QName, XbrlFact   # noqa: E402
from fin2.extract.report_lines import (                            # noqa: E402
    ReportLineRow, _parse_eps_amount, extract_report_lines)
from fin2.extract.report_lines_xbrl import _exact_value, _negated  # noqa: E402
from fin2.layer3.combine import _extended_exact, _map_rows         # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_BITWIN_2020FY = _ROOT / "raw_report/KOSDAQ/01326792_비투엔/annual/2020/20210317000884.xml"


def test_parse_amount_decimal_keeps_the_fraction_and_parse_amount_is_unchanged():
    assert parse_amount_decimal("13.42") == Decimal("13.42")
    assert parse_amount_decimal("(399.53)") == Decimal("-399.53")
    assert parse_amount_decimal("1,234.5", 1_000_000) == Decimal("1234500000.0")
    assert parse_amount("13.42") == 13
    assert parse_amount("(13.5)") == -14              # ROUND_HALF_UP away from zero, as before
    assert parse_amount("1,234.5", 1_000_000) == 1_234_500_000
    assert parse_amount("1,457") == 1457
    assert parse_amount_decimal("-") is None and parse_amount("-") is None


def test_fractional_or_none():
    assert fractional_or_none(Decimal("13.42")) == Decimal("13.42")
    assert fractional_or_none(Decimal("69.0")) is None   # '69.0' is an integer — value_won is exact
    assert fractional_or_none(Decimal("1457")) is None
    assert fractional_or_none(None) is None


def test_eps_amount_is_an_int_that_carries_its_exact_value():
    a = _parse_eps_amount("13.42", 1)
    assert a == 13 and isinstance(a, int) and a.exact == Decimal("13.42")
    b = _parse_eps_amount("1,457", 1)
    assert b == 1457 and b.exact is None
    assert _parse_eps_amount("", 1) is None


def test_as_row_carries_value_exact():
    row = ReportLineRow(
        corp_code="01326792", rcept_no="20210317000884", report_fiscal_year=2020,
        report_fiscal_period="FY", statement="IS", basis="separate", label_raw="기본주당이익",
        col_index=0, context_fiscal_year=2020, period_kind="duration", is_cumulative=False,
        value_won=13, adecimal=0, unit_source="declared", source_ref=None, context_raw=None,
        value_exact=Decimal("13.42"))
    assert row.as_row()["value_exact"] == Decimal("13.42")
    assert row.as_row()["value_won"] == 13


def test_bitwin_2020fy_separate_eps_keeps_13_42():
    if not _BITWIN_2020FY.exists():
        return
    lines = extract_report_lines(
        _BITWIN_2020FY, rcept_no="20210317000884", corp_code="01326792",
        report_fiscal_year=2020, report_fiscal_period="FY")
    eps = {(l.label_raw, l.col_index): (l.value_won, l.value_exact) for l in lines
           if l.statement == "IS" and l.basis == "separate" and "주당" in l.label_raw}
    # 원문: 기본·희석주당이익 당기 13.42 / 전기 19.72
    assert eps[("기본주당이익", 0)] == (13, Decimal("13.42"))
    assert eps[("기본주당이익", 1)] == (20, Decimal("19.72"))
    assert eps[("희석주당이익", 0)] == (13, Decimal("13.42"))
    # value_exact 는 EPS 행에만 — 같은 표의 금액 행은 NULL
    assert all(l.value_exact is None for l in lines if "주당" not in (l.label_raw or ""))


def _fact(value: str) -> XbrlFact:
    return XbrlFact(qname=QName(ns="ifrs-full", local="BasicEarningsLossPerShare"),
                    context_ref="c", value_raw=value, unit_ref="KRWEPS")


def test_xbrl_exact_value_and_negation():
    assert _exact_value(_fact("13.42")) == Decimal("13.42")
    assert _exact_value(_fact("1457")) is None
    assert _exact_value(_fact("")) is None
    row = ReportLineRow(
        corp_code="x", rcept_no="r", report_fiscal_year=2020, report_fiscal_period="FY",
        statement="IS", basis="separate", label_raw="기본주당손실", col_index=0,
        context_fiscal_year=2020, period_kind="duration", is_cumulative=False, value_won=13,
        adecimal=0, unit_source="xbrl", source_ref=None, context_raw=None,
        value_exact=Decimal("13.42"))
    flipped = _negated(row)
    assert (flipped.value_won, flipped.value_exact) == (-13, Decimal("-13.42"))
    assert _negated(_negated(row)) == row


def _line(label: str, won: int, exact) -> dict:
    return {"statement": "IS", "basis": "separate", "label_raw": label, "value_won": won,
            "value_exact": exact, "node_role": None, "section_path": None, "table_seq": 0,
            "is_cumulative": False}


def test_layer3_carries_the_exact_eps_into_extended():
    cands = _map_rows([_line("기본주당이익", 13, Decimal("13.42")),
                       _line("매출액", 1_000, None)], "FY", "separate", ("IS",))
    eps = cands["is.eps_basic"]
    assert eps[0]["value"] == 13 and eps[0]["exact"] == Decimal("13.42")
    assert _extended_exact({"is.eps_basic": 13}, cands) == {"is.eps_basic": Decimal("13.42")}
    # the confirmed value is not the one that carries the exact → nothing is attached
    assert _extended_exact({"is.eps_basic": 14}, cands) == {}


def test_layer3_conflicting_exacts_attach_nothing():
    cands = {"is.eps_basic": [{"value": 13, "exact": Decimal("13.42")},
                              {"value": 13, "exact": Decimal("13.38")}]}
    assert _extended_exact({"is.eps_basic": 13}, cands) == {}
    cands = {"is.eps_basic": [{"value": 13, "exact": Decimal("13.42")},
                              {"value": 13, "exact": None}]}
    assert _extended_exact({"is.eps_basic": 13}, cands) == {"is.eps_basic": Decimal("13.42")}
