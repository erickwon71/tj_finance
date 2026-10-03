"""R217(2026-10-03) 회귀 테스트 — 계층3 XBRL EPS 공백 + 계속영업 EPS 헤드라인 대체.

XBRL EPS 행은 source_ref 가 'eps/…' 가 아니어서 R213 규칙을 타지 않았고, 회사 확장 개념(udf_…)은
개념 폴백에도 걸리지 않아 214기간 중 148기간에 is.eps_basic 이 없었다. 수정: XBRL IS '주당' 행도
eps_row 로 싣는다(_EPS_ROW_SQL). 동시에 계속영업 EPS 는 헤드라인 행이 없고 0 아닌 중단영업 EPS 도
없을 때만 헤드라인으로 쓴다(기존 개념 경로가 맞게 내던 55셀 보존).

실행: pytest fin2/tests/test_r217_layer3_xbrl_eps.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.combine import _EPS_ROW_SQL, _eps_canonicals, _eps_classify, _map_rows  # noqa: E402

B, D = "is.eps_basic", "is.eps_diluted"


def _row(label, won, *, section="포괄손익계산서 [abstract]>주당이익", cum=False):
    return {"statement": "IS", "basis": "consolidated", "label_raw": label, "value_won": won,
            "value_exact": None, "eps_row": True, "node_role": None,
            "section_path": section, "table_seq": 0, "is_cumulative": cum}


def test_xbrl_rows_are_flagged_by_the_sql():
    assert "rl.unit_source = 'xbrl'" in _EPS_ROW_SQL and "주식수|배당" in _EPS_ROW_SQL
    assert "1000000" in _EPS_ROW_SQL and "LIKE 'eps/%'" in _EPS_ROW_SQL


def test_classify_kinds():
    assert _eps_classify("계속영업기본주당이익(손실)", None) == ("continuing", (B,))
    assert _eps_classify("중단영업희석주당이익(손실)", None) == ("discontinued", (D,))
    assert _eps_classify("기본주당손익", "계속영업") == ("continuing", (B,))
    assert _eps_classify("우선주 기본주당이익", None) == (None, ())
    # a label naming both components is the total (R217)
    assert _eps_canonicals("기본 및 희석주당이익(계속영업과중단영업)", None) == (B, D)
    # the label wins over a total-naming ancestor
    assert _eps_classify("계속영업기본주당이익", "계속영업과 중단영업") == ("continuing", (B,))


def test_udf_concept_line_reaches_layer3():
    """송원산업 20160901000022 별도 '기본주당이익(단위:원)' udf 개념 → is.eps_basic 1317."""
    cands = _map_rows([_row("기본주당이익(단위:원)", 1317, cum=True)], "H1", "consolidated", ("IS",))
    assert [c["value"] for c in cands[B]] == [1317]


def test_continuing_line_is_never_headline_even_tagged_with_the_headline_concept():
    """00102353 2015Q3 연결: 계속 696 / 중단 −106 이 BasicEarningsLossPerShare 로 태깅돼 기존 개념 경로가
    696 을 is.eps_basic 으로 냈다. 중단영업 EPS 가 없을 때 계속영업을 헤드라인으로 쓰는 대체는 측정에서
    추가 셀의 43% 가 지배순이익/주식수와 어긋나 넣지 않았다(R213 규약 유지)."""
    cands = _map_rows([_row("계속사업기본주당이익(지배기업)", 696),
                       _row("중단사업기본주당이익(지배기업)", -106)], "FY", "consolidated", ("IS",))
    assert B not in cands
    cands = _map_rows([_row("계속영업기본주당이익(손실)", 124)], "FY", "consolidated", ("IS",))
    assert B not in cands


def test_headline_line_wins_over_continuing():
    """00152862 2016Q3 연결: 보통주 기본주당순이익 3516 이 계속영업 3684 대신."""
    cands = _map_rows([_row("보통주 기본주당계속영업이익(손실)", 3684),
                       _row("보통주 기본주당순이익(손실)", 3516),
                       _row("우선주 기본주당순이익(손실)", 3554)], "FY", "consolidated", ("IS",))
    assert [c["value"] for c in cands[B]] == [3516]


def test_explicit_total_line_is_a_peer_candidate_not_a_winner():
    """LS 00105952 2018H1: 합계 14,662 와 평이한 라벨 4,751 이 둘 다 후보 → _resolve 가 보류.
    합계 우선 규칙은 측정 28셀 중 10셀을 악화시켜 넣지 않았다(오리엔트정공 2012Q3 열 오적재)."""
    cands = _map_rows([_row("계속영업과중단영업기본및희석주당이익(손실) (단위 : 원)", 14662, cum=True),
                       _row("기본 및 희석주당이익(손실) (단위 : 원)", 4751, cum=True)],
                      "H1", "consolidated", ("IS",))
    assert sorted(c["value"] for c in cands[B]) == [4751, 14662]
    assert _eps_classify("계속영업과 중단영업 기본및희석주당순손실", None)[0] == "total"


def test_preferred_line_is_never_headline():
    """00117337 2018Q3: 구형우선주 85 가 아니라 보통주 47."""
    cands = _map_rows([_row("지배기업 보통주 기본및희석주당이익", 47),
                       _row("지배기업 구형우선주 기본및희석주당이익", 85)], "FY", "consolidated", ("IS",))
    assert [c["value"] for c in cands[D]] == [47]
