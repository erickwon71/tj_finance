"""R204 regression — a filer arc that re-places an expense concept inherits the base template's negation.

DART's IS base template negates deductions (R170-b drops that negation on base arcs). When the filer
re-places such a concept under its own arc with the same preferredLabel, the filer arc is the base placement
moved, so it must be de-negated too; otherwise the expense is stored negative while the printed 손익계산서
shows it positive (원익홀딩스 20180816000066 투자비용, 서울전자통신 20161114002549 관리비).

Income tax stays with R170-d and OCI reclassification adjustments keep their sign.

Run: pytest fin2/tests/test_r204_filer_replaced_expense_negation.py
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest                                                      # noqa: E402

from parser.xbrl_instance.taxonomy_linkbase import _R204_EXPENSE_LOCAL_RE as expense_re  # noqa: E402
from fin2.extract.report_lines_xbrl import extract_report_lines_xbrl  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_WONIK = _ROOT / "raw_report/KOSDAQ/00216647_원익홀딩스/half/2018/20180816000066.zip"
_SEOUL = _ROOT / "raw_report/KOSDAQ/00130587_서울전자통신/quarter/2016/20161114002549.zip"
_NEXT = _ROOT / "raw_report/KOSDAQ/00614593_넥스트아이/half/2018/20180816000176.zip"


@pytest.mark.parametrize("local,want", [
    ("AdministrativeExpense", True),
    ("DistributionCosts", True),
    ("LossesArisingFromDerecognitionOfFinancialAssetsMeasuredAtAmortisedCost", True),
    ("IncomeTaxExpenseContinuingOperations", False),          # R170-d owns the tax sign
    ("ReclassificationAdjustmentsOnExchangeDifferencesOnTranslationNetOfTax", False),
    ("OtherComprehensiveIncome", False),
])
def test_expense_local_filter(local, want):
    assert (expense_re.search(local) is not None) is want


def _is_values(path, rcept, corp, fy, fp, pe):
    lines = extract_report_lines_xbrl(
        path, rcept_no=rcept, corp_code=corp, report_fiscal_year=fy,
        report_fiscal_period=fp, period_end_date=pe)
    return {(l.basis, l.source_ref.split("/")[1]): l.value_won
            for l in lines if l.statement == "IS" and l.col_index == 0}


@pytest.mark.skipif(not _WONIK.exists(), reason="raw XBRL zip missing")
def test_wonik_investment_cost_is_positive():
    v = _is_values(_WONIK, "20180816000066", "00216647", 2018, "H1", datetime.date(2018, 6, 30))
    name = "LossesArisingFromDerecognitionOfFinancialAssetsMeasuredAtAmortisedCost"
    assert v[("consolidated", name)] == 3_176_117_802
    assert v[("separate", name)] == 908_418_000


@pytest.mark.skipif(not _SEOUL.exists(), reason="raw XBRL zip missing")
def test_seoul_admin_expense_is_positive_and_operating_identity_closes():
    v = _is_values(_SEOUL, "20161114002549", "00130587", 2016, "Q3", datetime.date(2016, 9, 30))
    assert v[("consolidated", "AdministrativeExpense")] == 2_790_502_820
    # 매출총이익 − 판매비 − 관리비 − 연구개발비 = 영업이익
    assert 6_732_336_960 - 480_711_972 - 2_790_502_820 - 540_762_371 == v[("consolidated", "OperatingIncomeLoss")]


@pytest.mark.skipif(not _NEXT.exists(), reason="raw XBRL zip missing")
def test_reclassification_adjustment_keeps_its_sign():
    v = _is_values(_NEXT, "20180816000176", "00614593", 2018, "H1", datetime.date(2018, 6, 30))
    assert v[("separate", "ReclassificationAdjustmentsOnFinancialAssetsMeasuredAtFairValueThroughOtherComprehensiveIncomeNetOfTax")] == 1_915_028
