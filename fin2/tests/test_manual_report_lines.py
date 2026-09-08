"""`fin2/extract/manual_report_lines.py` 순수 로직 단위 테스트(DB 비의존).

★ `store_manual_report_lines()`(실제 session.execute)는 여기서 테스트하지 않는다 —
`fin2/tests/test_reconcile_store.py`와 동일 관례(DB 의존 write-path는 pytest 스위트가
아니라 수동 스모크로 1회 검증, 결과를 대화/문서에 남긴다).

실행: python -m fin2.tests.test_manual_report_lines
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from fin2.extract.manual_report_lines import (  # noqa: E402
    FilingMeta, ManualCsvError, build_manual_report_lines,
)

_META = {"20020814000872": FilingMeta(corp_code="00307222", fiscal_year=2002, fiscal_period="H1")}


def _row(**kw):
    base = {
        "rcept_no": "20020814000872", "statement": "BS", "basis": "separate",
        "label_raw": "1. 상품", "value_raw": "197,000,000",
    }
    base.update(kw)
    return base


def test_basic_row_uses_filing_meta_and_defaults():
    rows = build_manual_report_lines([_row()], _META)
    assert len(rows) == 1
    r = rows[0]
    assert r.corp_code == "00307222"
    assert r.report_fiscal_year == 2002
    assert r.report_fiscal_period == "H1"
    assert r.col_index == 0
    assert r.unit_source == "manual"
    assert r.value_won == 197_000_000
    assert r.value_raw is None  # 파싱 성공한 칸은 원문을 안 남긴다(F1 관례)
    assert r.period_kind == "instant"  # BS
    assert r.is_cumulative is False


def test_is_statement_duration_and_cumulative_for_non_fy_period():
    rows = build_manual_report_lines([_row(statement="현금흐름표", value_raw="1,000")], _META)
    assert rows[0].statement == "CF"
    assert rows[0].period_kind == "duration"
    assert rows[0].is_cumulative is True  # H1 != FY


def test_fy_period_is_not_cumulative():
    meta = {"r1": FilingMeta(corp_code="00000001", fiscal_year=2001, fiscal_period="FY")}
    rows = build_manual_report_lines([_row(rcept_no="r1", statement="IS", value_raw="1")], meta)
    assert rows[0].is_cumulative is False


def test_korean_basis_and_statement_aliases_normalize():
    rows = build_manual_report_lines([_row(statement="대차대조표", basis="별도")], _META)
    assert rows[0].statement == "BS"
    assert rows[0].basis == "separate"


def test_unit_thousand_won_multiplies_value():
    rows = build_manual_report_lines([_row(value_raw="197,000", unit="천원")], _META)
    assert rows[0].value_won == 197_000_000
    assert rows[0].adecimal == -3


def test_blank_value_raw_loads_as_missing_not_zero():
    rows = build_manual_report_lines([_row(value_raw="")], _META)
    assert rows[0].value_won is None
    assert rows[0].value_raw is None


def test_unparseable_value_keeps_missing_but_preserves_original_text():
    rows = build_manual_report_lines([_row(value_raw="확인불가")], _META)
    assert rows[0].value_won is None
    assert rows[0].value_raw == "확인불가"


def test_negative_parenthesized_value():
    rows = build_manual_report_lines([_row(value_raw="(1,234)")], _META)
    assert rows[0].value_won == -1234


def test_row_order_assigned_sequentially_per_scope():
    rows = build_manual_report_lines([_row(label_raw="A"), _row(label_raw="B")], _META)
    assert [r.row_order for r in rows] == [0, 1]


def test_row_order_resets_across_different_scopes():
    rows = build_manual_report_lines(
        [_row(label_raw="A"), _row(statement="IS", label_raw="B"), _row(label_raw="C")], _META,
    )
    bs_rows = [r for r in rows if r.statement == "BS"]
    assert [r.row_order for r in bs_rows] == [0, 1]


def test_excel_text_wrapped_rcept_no_is_unwrapped():
    """엑셀 지수표기(2.00208E+13) 함정을 피하려고 ="20020814000872" 로 감싼 값도 정상 인식."""
    rows = build_manual_report_lines([_row(rcept_no='="20020814000872"')], _META)
    assert rows[0].rcept_no == "20020814000872"


def test_unknown_rcept_no_raises_with_line_number():
    with pytest.raises(ManualCsvError, match="line 2.*20020814000872"):
        build_manual_report_lines([_row()], {})


def test_unknown_statement_raises():
    with pytest.raises(ManualCsvError, match="statement"):
        build_manual_report_lines([_row(statement="말도안되는표")], _META)


def test_missing_label_raw_raises():
    with pytest.raises(ManualCsvError, match="label_raw"):
        build_manual_report_lines([_row(label_raw="")], _META)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
