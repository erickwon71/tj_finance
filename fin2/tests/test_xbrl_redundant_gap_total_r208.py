"""
R208 — the A-5 missing-total fallback (`_emit_missing_totals`) duplicated totals the document already prints:
a BS `자본총계` tagged with the filer's own udf concept (KG파이낸셜 · TYM · 현대리바트, verification extra_row
#87034 · #87548~#87554 · #88034), and IS ComprehensiveIncome carried by the second IS role (R199).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fin2.extract.report_lines_xbrl as X  # noqa: E402

_RAW = Path(__file__).resolve().parents[2] / "raw_report"


def _row(statement, label, value, concept, gap=False, col=0, basis="separate"):
    ref = f"{statement}_{basis}/{concept}" + ("/xbrl_tree_gap_total" if gap else "")
    return NS(statement=statement, basis=basis, col_index=col, value_won=value, label_raw=label, source_ref=ref)


def test_bs_gap_equity_dropped_when_udf_total_printed():
    gap = _row("BS", "자본", 140200258034, "Equity", gap=True)
    udf = _row("BS", "자본총계", 140200258034, "udf_BS_2015322115628968_StatementOfFinancialPositionAbstract")
    assert X._drop_redundant_gap_totals([gap, udf], "t") == [udf]


def test_bs_gap_equity_kept_when_only_owners_share_matches():
    # 지배기업소유주지분 == Equity (no NCI) is not the total itself — keep the fallback (R6)
    gap = _row("BS", "자본", 100, "Equity", gap=True)
    parent = _row("BS", "지배기업소유주지분", 100, "EquityAttributableToOwnersOfParent")
    assert X._drop_redundant_gap_totals([gap, parent], "t") == [gap, parent]


def test_bs_gap_kept_for_other_column_or_value():
    gap = _row("BS", "자본", 100, "Equity", gap=True, col=1)
    udf = _row("BS", "자본총계", 100, "udf_X")
    other = _row("BS", "자본총계", 99, "udf_X", col=1)
    assert X._drop_redundant_gap_totals([gap, udf, other], "t") == [gap, udf, other]


def test_is_gap_dropped_when_same_concept_in_second_role():
    gap = _row("IS", "포괄손익", 10018082511, "ComprehensiveIncome", gap=True)
    extra = _row("IS", "총포괄손익", 10018082511, "ComprehensiveIncome")
    assert X._drop_redundant_gap_totals([gap, extra], "t") == [extra]


def test_is_gap_label_rule_not_applied():
    # the printed-label rule is BS only; an IS row printed '당기순이익' with an equal value is not proof
    gap = _row("IS", "포괄손익", 5, "ComprehensiveIncome", gap=True)
    ni = _row("IS", "당기순이익", 5, "ProfitLoss")
    assert X._drop_redundant_gap_totals([gap, ni], "t") == [gap, ni]


def _extract(rel, rcept, corp, fy, fp, ped):
    path = _RAW / rel
    if not path.exists():
        return None
    return X.extract_report_lines_xbrl(path, rcept_no=rcept, corp_code=corp, report_fiscal_year=fy,
                                       report_fiscal_period=fp, period_end_date=ped)


def test_kg_financial_2016q1_separate_bs_has_no_leading_equity_row():
    """이슈 #87553 — 별도 BS 순번1 '자본' 140,200,258,034(자본총계와 중복)."""
    lines = _extract("KOSDAQ/00405278_KG파이낸셜/quarter/2016/20170112000213.zip", "20170112000213", "00405278",
                     2016, "Q1", date(2016, 3, 31))
    if lines is None:
        return
    bs = [l for l in lines if l.statement == "BS" and l.basis == "separate" and l.value_won == 140200258034]
    assert [l.label_raw for l in bs] == ["자본총계"]


def test_tym_2016q1_consolidated_bs_has_no_leading_equity_row():
    """이슈 #87034 — 연결 BS 순번1 '자본' 133,421,763,333."""
    lines = _extract("KOSPI/00117230_TYM/quarter/2016/20170414000813.zip", "20170414000813", "00117230",
                     2016, "Q1", date(2016, 3, 31))
    if lines is None:
        return
    assert not [l for l in lines if l.statement == "BS" and (l.source_ref or "").endswith("/xbrl_tree_gap_total")
                and l.basis == "consolidated" and l.value_won == 133421763333]
    assert [l for l in lines if l.statement == "BS" and l.basis == "consolidated" and l.label_raw == "자본총계"
            and l.value_won == 133421763333]


def test_hyundai_corp_2014h1_comprehensive_income_once():
    lines = _extract("KOSPI/00164812_현대코퍼레이션/half/2014/20150331002727.zip", "20150331002727", "00164812",
                     2014, "H1", date(2014, 6, 30))
    if lines is None:
        return
    ci = [l for l in lines if l.statement == "IS" and l.basis == "consolidated" and l.col_index == 0
          and (l.source_ref or "").split("/")[1] == "ComprehensiveIncome"]
    assert [(l.label_raw, l.value_won) for l in ci] == [("총포괄손익", 10018082511)]
