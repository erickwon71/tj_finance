"""R171 — 정정 체인에 추출 경로가 섞일 때(XML → XBRL → XML) 나중 XML 필링이 앞선 XBRL
셀을 대체한다 (순수, DB 비의존 — 가짜 세션).

실측: 00242378 2019Q3 연결. 원본 XML → 정정1 XBRL(20191206000533) → 정정2 XML
(20200721000363). _CELL_KEY 는 경로가 다르면 절대 맞지 않아 정정1 셀이 '추가'로만 남고
정정2 가 덮지 못했다 → 자산·자본은 정정2, 부채는 정정1 값이 골라져 BS 항등식이 깨졌다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.combine import build_merged_lines  # noqa: E402

_CHAIN = [("orig", False), ("xbrl1", True), ("xml2", True)]
_KIND = {"orig": (False, False), "xbrl1": (True, False), "xml2": (False, False)}
_ROWS = {
    "orig": [("BS", "consolidated", 0, "부채", "부채총계", 1_103_679_410_688, "S", 0, False),
             ("IS", "consolidated", 0, None, "매출액", 100, "F", 1, False)],
    "xbrl1": [("BS", "consolidated", 0, "재무상태표 [abstract]>부채 [abstract]", "부채총계",
               1_135_133_772_680, "S", 0, False)],
    "xml2": [("BS", "consolidated", 0, "부채", "부채총계", 1_134_848_933_304, "S", 0, False)],
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


def test_final_xbrl_amendment_keeps_both_paths_as_before():
    """XBRL 이 마지막이면 R171 은 아무것도 지우지 않는다(계층3 이 XBRL 라벨을 다 못 읽어
    XML 셀을 지우면 법인세·지배순이익이 비는 것을 실측, 2,122·305셀)."""
    m = _merged([("orig", False), ("xbrl1", True)])
    assert {v for k, v in m.items() if k[1] == "부채총계"} == {1_103_679_410_688, 1_135_133_772_680}
