"""
`parser/xml/table_extractor.py::_header_rule_name` "기수" 규칙 부분일치 버그 회귀 테스트
(2026-08-16, R28 Phase 5-2 검증 중 발견).

`re.search(r'제\\s*\\d+\\s*기', text)` 가 라벨 어디에든 "제N기" 가 있으면 헤더로 간주해,
EPS/배당 데이터 행("XV.연결당기순이익 (...제54기: 1,713원...)", "배당금(율) 제36기:
80원(16%)")이 통째로 드롭됐다 — 진짜 헤더 셀은 "원"/"%" 를 포함하지 않는다는 신호로
가른다. 실제 `note_lines` DB 값(header_hint='기수')에서 두 부류를 그대로 가져왔다.

실행: python -m fin2.tests.test_header_rule_name_r28  또는  pytest fin2/tests/
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.xml.table_extractor import _header_rule_name  # noqa: E402

# 실측(note_lines, header_hint='기수') — 진짜 열 헤더. 여전히 "기수"(또는 다른 헤더 규칙)로
# 잡혀야 한다.
_GENUINE_HEADERS = [
    "제23기1분기", "제 21기(당기)", "제21기 1분기말", "제11기", "제18기3분기",
    "제21기 3분기", "제23기 3분기말", "제 51 기 1분기말", "제28기 1분기말",
    "제46기 배당", "제20기(전전기)", "제19기 반기말", "제18기1분기",
    "제20기 3분기말", "제 10 기", "기말(제21기말)", "제50기 3분기",
    "제59기 기초(2016.1.1)", "제42기 반기말", "제19기말", "제51기1분기",
    "제25기\n(당기말)", "제9기", "제 41기 기말", "제20기3분기말",
    "2019.1.1(제39기 당기초)",
]

# 실측(note_lines) — "제N기" 를 포함해 예전엔 "기수"로 오분류되던 진짜 배당/EPS 데이터 행.
_RESCUED_DATA_ROWS = [
    "현금배당제 7기  (주당 배당금(율) : 200원  (40%))제 6기  (주당 배당금(율) : 300원  (60%))",
    "배당금(율)  제36기 : 80원(16%)                    제35기 : 80원(16%)",
    "현금배당금      주당배당금(률)      제26기 - 보통주:    700원(140%)      제25기 - 보통주: 2,250원(450%)",
    "2. 현금배당     (주당배당금(률) 보통주       제50기:150 원(15%),제49기:130 원(13%)",
    "주당배당율  제39기 : 70원(14%)                     제38기 : 70원(14%)",
    "2. 배당금      주당배당금(률) :      제16기 : 50원(10%)                               제15기 : 50원(10%)",
    "1. 배당금     [현금배당주당배당금(률):      제73기: 500원(50%)      제72기: 500원(50%)]",
    # R28 curated key 실사례 (대동, rcept 20020329000386).
    "XV.연결당기순이익   (연결주당경상이익 :           제54기 : 1,713원        제53기 : 2,118원)"
    "   (연결주당순이익 :              제54기 : 1,709원         제53기 : 2,097원)",
]


def test_genuine_period_headers_still_classified_as_header():
    """진짜 열 헤더는 여전히 헤더로 분류된다(회귀 없음, "기수" 규칙 자체가 남아있는지 확인)."""
    for text in _GENUINE_HEADERS:
        assert _header_rule_name(text) is not None, f"헤더가 데이터 행으로 오분류됨: {text!r}"


def test_amount_bearing_labels_no_longer_dropped_as_header():
    """'원'/'%' 를 포함한 진짜 데이터 행은 '기수' 규칙에 더 이상 걸리지 않는다(R28 버그 수정)."""
    for text in _RESCUED_DATA_ROWS:
        assert _header_rule_name(text) != "기수", f"여전히 '기수' 헤더로 드롭됨: {text!r}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
