"""R209/R210 — XBRL SCE cells the statement never prints (fix queue extra_row).

R209: a tree-parent row whose fact contradicts Σ(its leaf children) in a block the leaves alone prove.
R210: a period block holding nothing but the 기말 row (balance-sheet comparative equity).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fin2.extract.report_lines_xbrl as X  # noqa: E402

_RAW = Path(__file__).resolve().parents[2] / "raw_report"


def _extract(rel, rcept, corp, fy, fp, ped):
    path = _RAW / rel
    if not path.exists():
        return None
    return X.extract_report_lines_xbrl(path, rcept_no=rcept, corp_code=corp, report_fiscal_year=fy,
                                       report_fiscal_period=fp, period_end_date=ped)


def _sce(lines, basis):
    return [l for l in lines if l.statement == "SCE" and l.basis == basis]


def test_chips_and_media_owner_transaction_subtotal_dropped():
    """이슈 #87229~#87236 — '자본에 직접 반영된 소유주와의 거래' 소계 fact 가 한 블록씩 밀린 값."""
    lines = _extract("KOSDAQ/00579971_칩스앤미디어/quarter/2015/20151127000627.zip", "20151127000627",
                     "00579971", 2015, "Q3", date(2015, 9, 30))
    if lines is None:
        return
    sep = _sce(lines, "separate")
    assert not [l for l in sep if l.label_raw == "자본에 직접 반영된 소유주와의 거래"]
    # the leaf rows stay, with the source values
    opt = {(l.row_order, l.col_index): l.value_won for l in sep if l.label_raw == "주식매수선택권"}
    assert opt[(7, 0)] == 285188 and opt[(17, 0)] == 10419623 and opt[(37, 3)] == -12545919


def test_shilla_trading_oci_total_dropped_and_lone_closing_block():
    """이슈 #87823~#87830 — '기타포괄손익' 합계 fact ≠ 하위 합, 2017-12-31 기말 단독 블록(R210)."""
    lines = _extract("KOSPI/00135962_신라교역/half/2018/20190201000248.zip", "20190201000248",
                     "00135962", 2018, "H1", date(2018, 6, 30))
    if lines is None:
        return
    for basis in ("separate", "consolidated"):
        sce = _sce(lines, basis)
        assert not [l for l in sce if l.label_raw == "기타포괄손익"]
        assert not [l for l in sce if "2017-12-31" in (l.label_raw or "")]
        assert [l for l in sce if l.label_raw.startswith("순확정급여부채의 재측정요소")]
    sep_end = {l.col_index: l.value_won for l in _sce(lines, "separate")
               if l.label_raw == "기말자본 (기말) (2018-06-30)"}
    assert sep_end[0] == 493670514968


def test_corestem_oci_row_copying_net_income_dropped():
    """이슈 #88060~#88065 — 2014H1 블록 '기타포괄손익' 행이 당기순이익 값을 복제."""
    lines = _extract("KOSDAQ/00989664_코아스템켐온/half/2015/20150902000296.zip", "20150902000296",
                     "00989664", 2015, "H1", date(2015, 6, 30))
    if lines is None:
        return
    con = _sce(lines, "consolidated")
    oci = [l for l in con if l.label_raw == "기타포괄손익"]
    assert oci and all(l.value_won != -1568271322 for l in oci)   # 2013 block (= child) survives
    assert [l.value_won for l in con if l.label_raw == "당기순이익(손실)" and l.col_index == 1].count(-1568271322) == 1


def test_muhak_lone_prior_year_end_block_dropped():
    """이슈 #87271/#87272 — 반기 정정본에 2014-12-31 기말 행만 있는 블록."""
    lines = _extract("KOSPI/00121543_무학/half/2015/20190225001238.zip", "20190225001238",
                     "00121543", 2015, "H1", date(2015, 6, 30))
    if lines is None:
        return
    for basis in ("separate", "consolidated"):
        sce = _sce(lines, basis)
        assert not [l for l in sce if "2014-12-31" in (l.label_raw or "")]
        assert [l for l in sce if l.label_raw == "기말자본 (기말) (2014-06-30)"]
