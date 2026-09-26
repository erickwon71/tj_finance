"""
`parser/xml/table_extractor.py::_header_rule_name` "단위표기" 규칙 부분일치 버그 회귀 테스트
(2026-09-26, R178, missing_row 캠페인 배치#12 조사 중 발견).

`re.search(r'단위\\s*[:\\(]', text)` 가 라벨 어디에든 "단위:"/"단위(" 가 있으면 헤더로
간주해, "자기주식 소각 (단위: 주)"처럼 **자기 라벨에 단위를 부기한 진짜 데이터 행**을
통째로 드롭했다(SCE·BS/IS/CF 본문은 `keep_header_rows=False`가 기본이라 header_hint 가
붙은 행을 버린다 — 주석만 hint 만 남기고 행을 보존한다).

실측(note_lines, header_hint='단위표기' 고유라벨 6,098개 표본): 진짜로 단위 선언
**뿐**인 라벨은 3개뿐이었고 나머지는 전부 데이터 행이었다. 카카오 20250318001297
con-SCE '자기주식 소각 (단위: 주)' 3개 회계연도·13셀이 실측 사례(자본금·자본잉여금·
자본조정·지분합계·자본합계 전부 유실).

실행: python -m fin2.tests.test_header_rule_name_r178_unit_suffix  또는  pytest fin2/tests/
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.xml.table_extractor import _header_rule_name  # noqa: E402

# 실측(note_lines, header_hint='단위표기') — 진짜 단위 선언뿐인 헤더 셀. 여전히
# "단위표기"로 잡혀야 한다.
_GENUINE_UNIT_HEADERS = [
    "단위 : 천USD,천원",
    "단위 : 천 USD, 천 EUR, 천 CNY, 천 MYR, 천원",
    "단위(일,주)",
    "(단위 : 원)",
    "단위:천원",
    "(단위: 주)",
    "단위 : %",
]

# 실측(카카오 20250318001297 con-SCE 및 note_lines 표본) — "단위:"를 포함해 예전엔
# "단위표기"로 오분류되던 진짜 데이터 행(자기 라벨에 단위를 부기한 계정명).
_RESCUED_DATA_ROWS = [
    "　자기주식 소각 (단위: 주)",
    "발행한 주식수 (단위 : 주)",
    "자본금(단위:천원)",
    "지분율(단위 : %)",
    "가중평균유통보통주식수(단위 : 천주)",
    "보통주분기순이익 (단위:원)",
    "기초 자기주식수(단위 : 주)",
    "희석주당이익(단위: 원/주)(주2)",
]


def test_genuine_unit_only_headers_still_classified_as_header():
    """진짜 단위 선언뿐인 헤더는 여전히 헤더로 분류된다(회귀 없음)."""
    for text in _GENUINE_UNIT_HEADERS:
        assert _header_rule_name(text) == "단위표기", f"헤더가 데이터 행으로 오분류됨: {text!r}"


def test_labeled_data_rows_no_longer_dropped_as_unit_header():
    """자기 라벨에 단위를 부기한 진짜 데이터 행은 더 이상 '단위표기' 헤더로 드롭되지 않는다(R178)."""
    for text in _RESCUED_DATA_ROWS:
        assert _header_rule_name(text) != "단위표기", f"여전히 '단위표기' 헤더로 드롭됨: {text!r}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
