"""R171 — 정정 체인에 추출 경로가 섞일 때(XML → XBRL → XML) 나중 XML 필링이 앞선 XBRL
셀을 대체한다 (순수, DB 비의존 — 가짜 세션).

실측: 00242378 2019Q3 연결. 원본 XML → 정정1 XBRL(20191206000533) → 정정2 XML
(20200721000363). _CELL_KEY 는 경로가 다르면 절대 맞지 않아 정정1 셀이 '추가'로만 남고
정정2 가 덮지 못했다 → 자산·자본은 정정2, 부채는 정정1 값이 골라져 BS 항등식이 깨졌다.
R172: XBRL 셀은 개념(source_ref)으로도 매핑되므로 방향 무관하게 대체한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.combine import build_merged_lines  # noqa: E402

_CHAIN = [("orig", False), ("xbrl1", True), ("xml2", True)]
_KIND = {"orig": (False, False), "xbrl1": (True, False), "xml2": (False, False)}
_ROWS = {
    "orig": [("BS", "consolidated", 0, "부채", "부채총계", 1_103_679_410_688, "S", 0, False, None),
             ("IS", "consolidated", 0, None, "매출액", 100, "F", 1, False, None)],
    "xbrl1": [("BS", "consolidated", 0, "재무상태표 [abstract]>부채 [abstract]", "부채총계",
               1_135_133_772_680, "S", 0, False, "Liabilities")],
    "xml2": [("BS", "consolidated", 0, "부채", "부채총계", 1_134_848_933_304, "S", 0, False, None)],
}


class _Result:
    def __init__(self, rows): self._rows = rows
    def fetchall(self): return self._rows
    def fetchone(self): return self._rows[0] if self._rows else None


class _FakeSession:
    def execute(self, stmt, params):
        sql = str(stmt)
        if "FROM filings f" in sql:
            return _Result(_CHAIN)
        if "bool_or(unit_source = 'xbrl')" in sql:
            return _Result([_KIND[params["r"]]])
        return _Result(_ROWS[params["r"]])


def _merged(chain):
    global _CHAIN
    _CHAIN = chain
    return {(c["statement"], c["label_raw"], c["section_path"]): c["value_won"]
            for c in build_merged_lines(_FakeSession(), "00242378", 2019, "Q3")}


def test_later_xml_replaces_earlier_xbrl_cells_in_covered_scope():
    m = _merged([("orig", False), ("xbrl1", True), ("xml2", True)])
    liab = {k: v for k, v in m.items() if k[1] == "부채총계"}
    assert liab == {("BS", "부채총계", "부채"): 1_134_848_933_304}
    assert m[("IS", "매출액", None)] == 100  # scope xml2 doesn't carry stays untouched


def test_final_xbrl_amendment_replaces_xml_cells_in_covered_scope():
    """R172 이후(계층3 가 XBRL 개념으로 매핑) XBRL 정정본이 마지막이어도 대체한다."""
    m = _merged([("orig", False), ("xbrl1", True)])
    assert {v for k, v in m.items() if k[1] == "부채총계"} == {1_135_133_772_680}
    assert m[("IS", "매출액", None)] == 100


def test_xbrl_concept_maps_labels_the_korean_mapper_misses():
    from fin2.layer3.combine import _map_xbrl_concept
    assert _map_xbrl_concept("IncomeTaxExpenseContinuingOperations", "is").account_code == "is.tax_expense"
    assert _map_xbrl_concept("ShortTermBorrowings", "bs").account_code == "bs.short_term_debt"
    assert _map_xbrl_concept("ProfitLoss", "cf") is None          # canonical of another statement
    assert _map_xbrl_concept("udf_IS_2014526162056278_IncomeStatementAbstract", "is") is None
    assert _map_xbrl_concept(None, "is") is None


def test_xbrl_ni_attribution_section_is_not_mistaken_for_oci():
    """R172 — XBRL section_path 는 루트 '포괄손익계산서 [abstract]' 부터 시작해 항상 '포괄'을
    포함한다. 직전 부모 구간만 봐야 NI 귀속 구조 복구가 동작한다(01046708 2018Q1 연결:
    확장개념 '지배기업소유주지분' 359,627,990 + 비지배 −254,821,918 = 순이익 104,806,072)."""
    from fin2.layer3.combine import _ni_attribution_structural_candidates

    def row(label, value, sp):
        return {"statement": "IS", "basis": "consolidated", "label_raw": label, "value_won": value,
                "section_path": sp, "table_seq": 0, "node_role": "F", "is_cumulative": False}
    ni = "포괄손익계산서 [abstract]>당기순이익(손실)"
    oci = "포괄손익계산서 [abstract]>당기총포괄손익"
    rows = [row("지배기업소유주지분", 359_627_990, ni), row("비지배지분", -254_821_918, ni),
            row("지배기업 소유주지분", 489_183_647, oci), row("비재배지분", -222_983_109, oci)]
    extra = _ni_attribution_structural_candidates(rows, "Q1", "consolidated")
    assert [c["value"] for c in extra["is.controlling_ni"]] == [359_627_990]


def test_concept_fallback_ranks_below_label_matches():
    from fin2.layer3.combine import _map_xbrl_concept, _STAGE_RANK
    m = _map_xbrl_concept("ProfitLoss", "is")
    assert _STAGE_RANK[m.stage] < _STAGE_RANK["exact"]
