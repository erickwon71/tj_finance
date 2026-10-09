"""R162-d2 — SCE 행 항등식: 그룹 합계 칸이 원문에서 공란이고 구성요소가 하나만 인쇄된 행.

남해화학 `20220317000080` 연결 2019 '연차배당': 이익잉여금 (2,397,434,750) 은 복원됐는데 자본 합계는
+2,397,434,750 으로 남았다. 지배기업 귀속 합계·비지배지분 칸이 공란이라 R162-d 는 항등식을 만들지 못했다.
"""
from __future__ import annotations

import fin2.extract.sce_sign_repair as ssr
from fin2.extract.sce_sign_repair import repair_sce_row_identity

import pytest


@pytest.fixture(autouse=True)
def _correction_rules_on():
    """R0-2: these rules no longer write layer 2 — they produce layer-3 corrections
    (fin2/extract/layer3_corrections.py). Test the rules themselves with them on."""
    from fin2.extract.as_printed import forced
    with forced("repaired"):
        yield


RE = "자본>지배기업의 소유주에게 귀속되는 자본>이익잉여금"
TOTAL = "자본>자본 합계"


class _Line:
    def __init__(self, statement, basis, label_raw, value_won, *, col_index=0, col_label=None,
                 row_order=0, table_seq=0):
        self.statement = statement
        self.basis = basis
        self.label_raw = label_raw
        self.value_won = value_won
        self.col_index = col_index
        self.col_label = col_label
        self.row_order = row_order
        self.table_seq = table_seq


def _table(div_total, *, div_re=-5, ni=10, open_=100, close_re=105, close_total=105):
    rows = [(0, "2019.01.01 (기초자본)", open_, open_), (1, "당기순이익(손실)", ni, ni),
            (2, "연차배당", div_re, div_total), (3, "2019.12.31 (기말자본)", close_re, close_total)]
    lines = []
    for ro, label, re_v, tot_v in rows:
        lines.append(_Line("SCE", "consolidated", label, re_v, col_index=4, col_label=RE, row_order=ro))
        lines.append(_Line("SCE", "consolidated", label, tot_v, col_index=7, col_label=TOTAL, row_order=ro))
    # a negative 5 elsewhere in the filing (the dividend note) is the second evidence R162-d needs
    lines.append(_Line("note", "consolidated", "배당금", -5, col_index=0, col_label=None, row_order=0))
    return lines


def _total(lines, ro):
    (l,) = [x for x in lines if x.row_order == ro and x.col_label == TOTAL]
    return l.value_won


def test_lone_member_closes_the_parent_total():
    lines = _table(div_total=5)                       # 자본 합계 sign lost, 이익잉여금 already -5
    fixes = repair_sce_row_identity(lines)
    assert _total(lines, 2) == -5
    assert [f.col_label for f in fixes] == [TOTAL]


def test_switch_off_keeps_old_behaviour():
    ssr._R162D_BLANK_GROUP_TOTAL = False
    try:
        lines = _table(div_total=5)
        assert repair_sce_row_identity(lines) == []
        assert _total(lines, 2) == 5
    finally:
        ssr._R162D_BLANK_GROUP_TOTAL = True


def test_flip_that_widens_the_column_residual_is_refused():
    """The 자본 합계 column closes exactly as printed (100 + 10 + 5 = 115); flipping the dividend
    would break it, so the row identity alone is not enough."""
    lines = _table(div_total=5, close_total=115)
    assert repair_sce_row_identity(lines) == []
    assert _total(lines, 2) == 5


def test_namhae_chemical_2019_annual_dividend_total_is_negative():
    """이슈 #86977 — 원문 연결 SCE 2019 '연차배당' 은 무괄호 2,397,434,750 이지만 롤포워드는 감소다."""
    from pathlib import Path

    from fin2.extract.report_lines import extract_report_lines

    path = (Path(__file__).resolve().parents[2]
            / "raw_report/KOSPI/00107987_남해화학/annual/2021/20220317000080.xml")
    if not path.exists():
        return
    lines = extract_report_lines(str(path), rcept_no="20220317000080", corp_code="00107987",
                                 report_fiscal_year=2021, report_fiscal_period="FY", include_notes=True)
    cells = {l.col_index: l.value_won for l in lines if l.statement == "SCE" and l.basis == "consolidated"
             and l.row_order == 5 and l.label_raw == "연차배당"}
    assert cells.get(4) == -2397434750 and cells.get(7) == -2397434750
